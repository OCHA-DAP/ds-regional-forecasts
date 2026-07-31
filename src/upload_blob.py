"""Upload the raw grabbed archive to Azure blob (dev) via ocha-stratus.

Layout: {PROJECT_PREFIX}/raw/{acmad|agrhymet|zenodo}/... mirroring data/raw/.
"""

import logging
from pathlib import Path

import ocha_stratus as stratus

from src.constants import PROJECT_PREFIX

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)

ROOT = Path(__file__).parents[1]
# (local dir, blob prefix under PROJECT_PREFIX)
UPLOADS = [
    (ROOT / "data" / "raw", "raw"),
    # derived site assets, served to the Pages site via the token issuer
    (ROOT / "docs" / "img", "processed/site-assets/img"),
    (ROOT / "docs" / "maps", "processed/site-assets/maps"),
    (ROOT / "docs" / "thumbs", "processed/site-assets/thumbs"),
    (ROOT / "docs" / "geo", "processed/site-assets/geo"),
    (ROOT / "docs" / "data", "processed/site-assets/data"),
]

if __name__ == "__main__":
    container = stratus.get_container_client(write=True)
    existing = {b.name for b in container.list_blobs(name_starts_with=f"{PROJECT_PREFIX}/")}
    n_up, n_skip = 0, 0
    for local_dir, prefix in UPLOADS:
        if not local_dir.exists():
            continue
        for f in sorted(local_dir.rglob("*")):
            if not f.is_file() or f.suffix == ".part":
                continue
            blob_name = f"{PROJECT_PREFIX}/{prefix}/{f.relative_to(local_dir)}"
            if blob_name in existing:
                n_skip += 1
                continue
            with open(f, "rb") as fh:
                container.upload_blob(blob_name, fh, overwrite=True)
            n_up += 1
            if n_up % 100 == 0:
                logger.info(f"{n_up} uploaded...")
    logger.info(f"UPLOAD DONE: {n_up} uploaded, {n_skip} already present")
