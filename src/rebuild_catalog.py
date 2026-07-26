"""Rebuild data/catalog_raw.json from whatever is on disk.

Lets us derive/publish mid-grab, and repairs the catalog after killed runs.
Merges records from the existing catalog (which carry richer metadata like
issued dates and DOIs) with disk-only files whose source URLs are
reconstructed from the storage layout.
"""

import json
import logging
from pathlib import Path

from src.constants import THREDDS_BASE

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)

ROOT = Path(__file__).parents[1]
DATA_RAW = ROOT / "data" / "raw"
OUT = ROOT / "data" / "catalog_raw.json"


def reconstruct(relpath: str) -> dict | None:
    parts = Path(relpath).parts
    name = parts[-1]
    rec = {"path": relpath, "name": name}
    if parts[0] == "acmad":
        rec["org"] = "acmad"
        if parts[1] == "ACCOF":
            rec["product"] = "accof"
            rec["source_url"] = f"https://acmad.org/wp-content/uploads/2019/03/{name}"
        else:
            rec["source_url"] = f"{THREDDS_BASE}/fileServer/ACMAD/{'/'.join(parts[1:])}"
    elif parts[0] == "agrhymet":
        rec["org"] = "agrhymet"
        rec["product"] = parts[1]
        if len(parts) > 2 and parts[2].isdigit():
            rec["issued"] = parts[2]
        rec["source_url"] = f"https://agrhymet.cilss.int/?s={name}"
    elif parts[0] == "zenodo":
        rec["org"] = "agrhymet"
        rec["product"] = "presass-digitized"
        rec["license"] = "CC-BY-4.0"
        rec["source_url"] = "https://doi.org/10.5281/zenodo.18936657"
    else:
        return None
    return rec


if __name__ == "__main__":
    existing: dict[str, dict] = {}
    if OUT.exists():
        for rec in json.loads(OUT.read_text()):
            existing[rec["path"]] = rec
    records = []
    for f in sorted(DATA_RAW.rglob("*")):
        if not f.is_file() or f.suffix == ".part":
            continue
        rel = str(f.relative_to(DATA_RAW))
        rec = existing.get(rel) or reconstruct(rel)
        if rec:
            records.append(rec)
    OUT.write_text(json.dumps(records, indent=1))
    logger.info(f"{len(records)} records ({len(existing)} carried metadata) -> {OUT}")
