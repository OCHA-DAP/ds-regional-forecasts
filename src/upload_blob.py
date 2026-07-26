"""Upload the raw grabbed archive to Azure blob (dev) via ocha-stratus.

Layout: {PROJECT_PREFIX}/raw/{acmad|agrhymet|zenodo}/... mirroring data/raw/.
"""

import logging
from pathlib import Path

import ocha_stratus as stratus

from src.constants import PROJECT_PREFIX

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)

DATA_RAW = Path(__file__).parents[1] / "data" / "raw"

if __name__ == "__main__":
    container = stratus.get_container_client(write=True)
    existing = {b.name for b in container.list_blobs(name_starts_with=f"{PROJECT_PREFIX}/raw/")}
    n_up, n_skip = 0, 0
    for f in sorted(DATA_RAW.rglob("*")):
        if not f.is_file() or f.suffix == ".part":
            continue
        blob_name = f"{PROJECT_PREFIX}/raw/{f.relative_to(DATA_RAW)}"
        if blob_name in existing:
            n_skip += 1
            continue
        with open(f, "rb") as fh:
            container.upload_blob(blob_name, fh, overwrite=True)
        n_up += 1
        if n_up % 50 == 0:
            logger.info(f"{n_up} uploaded...")
    logger.info(f"done: {n_up} uploaded, {n_skip} already present")
