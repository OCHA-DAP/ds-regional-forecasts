"""Run the full grab: all four sources, sequentially, then write data/catalog_raw.json."""

import json
import logging
from pathlib import Path

from src.datasources import (
    acmad_accof,
    acmad_thredds,
    agrhymet_wp,
    sadc_osf,
    sadc_wayback,
    sadc_web,
    wayback,
    zenodo,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
logger = logging.getLogger("run_grab")

OUT = Path(__file__).parents[1] / "data" / "catalog_raw.json"

if __name__ == "__main__":
    records = []
    for mod in (zenodo, agrhymet_wp, wayback, sadc_web, sadc_wayback, sadc_osf, acmad_accof, acmad_thredds):
        name = mod.__name__.rsplit(".", 1)[-1]
        logger.info(f"=== {name} ===")
        try:
            recs = mod.run()
        except Exception:
            logger.exception(f"{name} failed")
            recs = []
        logger.info(f"{name}: {len(recs)} files")
        records.extend(recs)
        # write incrementally so a killed run still leaves a usable catalog
        OUT.write_text(json.dumps(records, indent=1))
    logger.info(f"TOTAL {len(records)} files -> {OUT}")
