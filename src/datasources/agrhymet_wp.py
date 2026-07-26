"""Harvest PRESASS / PRESAGG PDFs from agrhymet.cilss.int via its open WP REST API.

Filenames are hand-authored each year (host cities embedded, double .pdf, stray
-1 suffixes) so we enumerate the media library rather than templating URLs.
"""

import logging
import re

from src.constants import AGRHYMET_WP_API
from src.utils.download import DATA_RAW, download, fetch

logger = logging.getLogger(__name__)

SEARCHES = ["PRESASS", "PRESAGG", "COMMUNIQUE", "Bulletin"]
# Keep only seasonal-forecast material (drop monthly campaign bulletins, fire
# bulletins, generic communiqués)
KEEP_RE = re.compile(r"presass|presagg", re.I)


def media_search(term: str) -> list[dict]:
    items, page = [], 1
    while True:
        url = f"{AGRHYMET_WP_API}/media?search={term}&per_page=100&page={page}"
        try:
            resp = fetch(url)
        except Exception as e:
            logger.warning(f"media search '{term}' page {page} failed: {e}")
            break
        batch = resp.json()
        if not isinstance(batch, list) or not batch:
            break
        items.extend(batch)
        if len(batch) < 100:
            break
        page += 1
    return items


def run() -> list[dict]:
    seen: dict[str, dict] = {}
    for term in SEARCHES:
        for item in media_search(term):
            url = item.get("source_url", "")
            if not url.lower().endswith(".pdf"):
                continue
            if not KEEP_RE.search(url) and not KEEP_RE.search(item.get("title", {}).get("rendered", "")):
                continue
            seen[url] = item
    logger.info(f"AGRHYMET WP: {len(seen)} seasonal PDFs enumerated")
    records = []
    for url, item in seen.items():
        product = "presass" if re.search(r"presass", url + str(item.get("title")), re.I) else "presagg"
        fname = url.rsplit("/", 1)[-1]
        # wp upload dir yyyy/mm gives us the publication date
        m = re.search(r"/uploads/(\d{4})/(\d{2})/", url)
        issued = f"{m.group(1)}-{m.group(2)}" if m else None
        dest = DATA_RAW / "agrhymet" / product / (m.group(1) if m else "undated") / fname
        if download(url, dest):
            records.append(
                {
                    "org": "agrhymet",
                    "product": product,
                    "issued": issued,
                    "source_url": url,
                    "path": str(dest.relative_to(DATA_RAW)),
                    "name": fname,
                }
            )
    return records
