"""WAS-NextGen digitized PRESASS consensus forecasts (Houngnibo et al., CC-BY 4.0).

The only public machine-readable record of the pre-WASS2S consensus maps:
tercile probabilities for JAS, digitized from the forum maps, 2016-2024.
"""

import logging

from src.constants import ZENODO_FILES, ZENODO_RECORD
from src.utils.download import DATA_RAW, download, fetch

logger = logging.getLogger(__name__)


def run() -> list[dict]:
    meta = fetch(f"https://zenodo.org/api/records/{ZENODO_RECORD}").json()
    by_name = {f["key"]: f for f in meta.get("files", [])}
    records = []
    for name in ZENODO_FILES:
        entry = by_name.get(name)
        if not entry:
            logger.warning(f"not in record: {name}")
            continue
        url = entry["links"]["self"]
        dest = DATA_RAW / "zenodo" / name
        if download(url, dest):
            records.append(
                {
                    "org": "agrhymet",
                    "product": "presass-digitized",
                    "source_url": url,
                    "path": str(dest.relative_to(DATA_RAW)),
                    "name": name,
                    "license": "CC-BY-4.0",
                    "doi": meta.get("doi"),
                }
            )
    return records
