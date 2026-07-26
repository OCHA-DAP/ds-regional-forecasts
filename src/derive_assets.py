"""Turn the raw grab into display assets + a site catalog.

- classify every file (product family, kind, year, season, language)
- PDFs -> page-1 thumbnail PNG in docs/thumbs/
- map images (jpg/png) -> resized copies in docs/img/
- geojson -> copied to docs/geo/ (small, future map layer)
- everything else (shp, nc) -> listed with source link only
- writes docs/catalog.json consumed by the gallery
"""

import json
import logging
import re
import unicodedata
from pathlib import Path

import fitz  # pymupdf
from PIL import Image

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)

ROOT = Path(__file__).parents[1]
DATA_RAW = ROOT / "data" / "raw"
DOCS = ROOT / "docs"

SEASONS = [
    "JFM", "FMA", "MAM", "AMJ", "MJJ", "JJA", "JAS", "ASO", "SON", "OND", "NDJ", "DJF",
    "JJAS", "MAMJ", "ONDJ", "ASON", "MJJA",
]
SEASON_RE = re.compile(r"(?<![A-Za-z])(" + "|".join(SEASONS) + r")(?![A-Za-z])", re.I)
YEAR_RE = re.compile(r"(?<!\d)(20[0-3]\d)(?!\d)")
# observation/climatology graphics that sit at folder roots beside the forecasts
JUNK_NAME_RE = re.compile(
    r"(?i)(rfe|percent_normal|annual-temp|last-30-days|sst_anom|_obs_|climatolog)"
)


def classify(rec: dict) -> dict:
    text = f"{rec['path']} {rec['name']}"
    norm = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().lower()

    product = rec.get("product")
    if not product:
        if "presass" in norm or re.search(r"presas\b", norm):
            product = "presass"
        elif "presagg" in norm:
            product = "presagg"
        elif "presac" in norm or "preac" in norm:
            product = "presac"
        elif "medcof" in norm or "presanord" in norm:
            product = "medcof"
        elif "swiocof" in norm:
            product = "swiocof"
        elif "sarcof" in norm:
            product = "sarcof"
        elif "accof" in norm:
            product = "accof"
        elif "brief" in norm or "breif" in norm:
            product = "lrf-policy-brief"
        elif "technical" in norm or "_tn" in norm:
            product = "lrf-technical-note"
        else:
            product = "lrf"

    suffix = Path(rec["name"]).suffix.lower()
    if suffix in (".jpg", ".jpeg", ".png", ".gif"):
        kind = "map-image"
    elif suffix == ".pdf":
        kind = (
            "communique" if "communique" in norm or "comm_" in norm
            else "statement" if "statement" in norm
            else "bulletin"
        )
    elif suffix in (".shp", ".dbf", ".shx", ".prj", ".cpg", ".qmd", ".sbn", ".sbx", ".xml"):
        kind = "shapefile"
    elif suffix == ".geojson":
        kind = "geojson"
    elif suffix == ".nc":
        kind = "netcdf"
    elif suffix in (".doc", ".docx", ".ppt", ".pptx"):
        kind = "document"
    else:
        kind = "other"

    season = None
    m = SEASON_RE.search(rec["name"]) or SEASON_RE.search(norm)
    if m:
        season = m.group(1).upper()

    years = YEAR_RE.findall(text)
    year = None
    if rec.get("issued"):
        year = int(str(rec["issued"])[:4])
    elif years:
        year = int(years[0])
    else:
        m = re.search(r"/(20[0-3]\d)/", rec["path"])
        if m:
            year = int(m.group(1))

    lang = None
    if re.search(r"(_|-)?(en|eng|engl)(_|-|\.|\b)", norm.replace(rec["path"].lower(), "")):
        lang = "en"
    if re.search(r"_en(g|gl)?[._-]|_en\b|-en[._-]|english", norm):
        lang = "en"
    elif re.search(r"_fr[._-]|_fra[._-]|_vf|francais|_fr\b", norm):
        lang = "fr"

    return {**rec, "product": product, "kind": kind, "season": season, "year": year, "lang": lang}


def slug(path: str) -> str:
    s = unicodedata.normalize("NFKD", path).encode("ascii", "ignore").decode()
    return re.sub(r"[^A-Za-z0-9._-]+", "_", s)


def pdf_thumb(src: Path, dest: Path, width: int = 700) -> bool:
    try:
        with fitz.open(src) as doc:
            page = doc[0]
            zoom = width / page.rect.width
            pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom))
            dest.parent.mkdir(parents=True, exist_ok=True)
            pix.save(dest)
        return True
    except Exception as e:
        logger.warning(f"thumb failed {src.name}: {e}")
        return False


def img_copy(src: Path, dest: Path, max_px: int = 1400) -> bool:
    try:
        with Image.open(src) as im:
            im = im.convert("RGB")
            im.thumbnail((max_px, max_px))
            dest.parent.mkdir(parents=True, exist_ok=True)
            im.save(dest, "JPEG", quality=82)
        return True
    except Exception as e:
        logger.warning(f"img failed {src.name}: {e}")
        return False


if __name__ == "__main__":
    records = json.loads((ROOT / "data" / "catalog_raw.json").read_text())
    out = []
    for rec in records:
        if JUNK_NAME_RE.search(rec["name"]):
            continue
        rec = classify(rec)
        src = DATA_RAW / rec["path"]
        if not src.exists():
            continue
        rec["size_kb"] = src.stat().st_size // 1024
        stem = slug(rec["path"])
        if rec["kind"] in ("communique", "bulletin", "statement") or (
            rec["kind"] == "document" and False
        ):
            thumb = DOCS / "thumbs" / (stem + ".png")
            if pdf_thumb(src, thumb):
                rec["thumb"] = str(thumb.relative_to(DOCS))
        elif rec["kind"] == "map-image":
            img = DOCS / "img" / (Path(stem).stem + ".jpg")
            if img_copy(src, img):
                rec["image"] = str(img.relative_to(DOCS))
        elif rec["kind"] == "geojson" and rec["size_kb"] < 5000:
            dest = DOCS / "geo" / (Path(stem).stem + ".geojson")
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(src.read_bytes())
            rec["geo"] = str(dest.relative_to(DOCS))
        out.append(rec)

    # collapse shapefile sidecars into one record per layer
    (DOCS / "catalog.json").write_text(json.dumps(out, indent=1))
    kinds = {}
    for r in out:
        kinds[r["kind"]] = kinds.get(r["kind"], 0) + 1
    logger.info(f"{len(out)} records -> docs/catalog.json | kinds: {kinds}")
