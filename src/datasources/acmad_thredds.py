"""Crawl ACMAD's THREDDS server for seasonal forecast products.

Every folder exposes a machine-readable catalog.xml; files download via
/thredds/fileServer/<urlPath>. This is the enumeration mechanism — filenames
are hand-authored (spaces, typos, inconsistent month codes) so we never guess.
"""

import logging
import re
import xml.etree.ElementTree as ET
from pathlib import Path

from src.constants import ACMAD_SEASONAL_TREES, THREDDS_BASE
from src.utils.download import DATA_RAW, download, encode_url, fetch

logger = logging.getLogger(__name__)

NS = {"t": "http://www.unidata.ucar.edu/namespaces/thredds/InvCatalog/v1.0"}

# The 2018-19-era issue folders are working directories: published products
# (FCST_MAP, briefs, bulletins) sit beside model-run debris whose folder names
# vary per issue (TREND_BOB, profile_FMAM, ANALOG YEAR, ...). Skip by pattern.
SKIP_DIR_RE = re.compile(
    r"(?i)^(analog|predictor|trend|profile|annual|obs|observ|verif|cpt|model|"
    r"hindcast|training|data.?prep|rain.?review|composite|txt|grads|script|"
    r"lrf_products_package|shp_afrique|percentile|graphs|development|documentation|"
    r"data$|"  # every folder literally named "Data" has been model inputs, not products
    r"cpc.?fcst|sst_vs|nmme|season\d|x-trop|.*_profiles?$)",
)
SKIP_SUFFIXES = {
    ".ctl", ".gs", ".dat", ".bin", ".exe", ".rar", ".grd", ".gra", ".csv", ".txt",
    ".tmp", ".filepart", ".db", ".ini",
}
MAX_FILE_MB = 200


def crawl_catalog(path: str, files: list[dict], depth: int = 0) -> None:
    """Recursively walk catalog.xml under `path`, appending file records."""
    if depth > 12:
        return
    url = f"{THREDDS_BASE}/catalog/{path}/catalog.xml"
    try:
        resp = fetch(encode_url(url))
        root = ET.fromstring(resp.content)
    except Exception as e:
        logger.warning(f"catalog failed {path}: {e}")
        return
    for ds in root.iter(f"{{{NS['t']}}}dataset"):
        url_path = ds.get("urlPath")
        if not url_path:
            continue
        name = ds.get("name", "")
        suffix = Path(name).suffix.lower()
        if suffix in SKIP_SUFFIXES:
            continue
        size_el = ds.find(f"{{{NS['t']}}}dataSize")
        size_mb = None
        if size_el is not None:
            units = size_el.get("units", "bytes")
            val = float(size_el.text or 0)
            size_mb = val / 1e6 if units == "bytes" else val if units == "Mbytes" else val * 1e3 if units == "Gbytes" else val / 1e3
        if size_mb and size_mb > MAX_FILE_MB:
            logger.info(f"skip (too big, {size_mb:.0f} MB): {url_path}")
            continue
        files.append({"url_path": url_path, "name": name})
    for ref in root.iter(f"{{{NS['t']}}}catalogRef"):
        href = ref.get("{http://www.w3.org/1999/xlink}href", "")
        title = ref.get("{http://www.w3.org/1999/xlink}title", "")
        if SKIP_DIR_RE.match(title):
            logger.info(f"skip subtree: {path}/{title}")
            continue
        if href.endswith("catalog.xml"):
            sub = href.rsplit("/catalog.xml", 1)[0]
            # hrefs are relative to the current catalog dir
            sub_path = f"{path}/{sub}" if not sub.startswith("/") else sub.strip("/").removeprefix("thredds/catalog/")
            crawl_catalog(sub_path, files, depth + 1)


def run() -> list[dict]:
    records = []
    for tree in ACMAD_SEASONAL_TREES:
        files: list[dict] = []
        crawl_catalog(tree, files)
        logger.info(f"{tree}: {len(files)} files enumerated")
        for f in files:
            url = f"{THREDDS_BASE}/fileServer/{f['url_path']}"
            dest = DATA_RAW / "acmad" / f["url_path"].removeprefix("ACMAD/")
            if download(url, dest):
                records.append(
                    {
                        "org": "acmad",
                        "source_url": url,
                        "path": str(dest.relative_to(DATA_RAW)),
                        "name": f["name"],
                    }
                )
    return records
