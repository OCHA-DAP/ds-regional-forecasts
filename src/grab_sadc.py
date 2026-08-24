"""One-off: run only the SADC datasources and merge into data/catalog_raw.json.

Used for the 2026-08 SADC addition — a full run_grab re-crawls ACMAD THREDDS
(hours). Safe to re-run: downloads resume, merge is keyed on path.
"""

import json
import logging
from pathlib import Path

from src.datasources import sadc_osf, sadc_wayback, sadc_web

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
logger = logging.getLogger("grab_sadc")

OUT = Path(__file__).parents[1] / "data" / "catalog_raw.json"

if __name__ == "__main__":
    existing = json.loads(OUT.read_text()) if OUT.exists() else []
    merged = {r["path"]: r for r in existing}
    for mod in (sadc_web, sadc_wayback, sadc_osf):
        name = mod.__name__.rsplit(".", 1)[-1]
        logger.info(f"=== {name} ===")
        try:
            recs = mod.run()
        except Exception:
            logger.exception(f"{name} failed")
            recs = []
        logger.info(f"{name}: {len(recs)} files")
        for r in recs:
            merged[r["path"]] = r
        OUT.write_text(json.dumps(list(merged.values()), indent=1))
    logger.info(f"TOTAL {len(merged)} records -> {OUT}")
