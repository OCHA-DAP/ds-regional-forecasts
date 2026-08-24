"""SADC CSC objective seasonal forecast maps (the region's WASS2S analogue).

csc.sadc.int/climate-prediction renders maps fully client-side: a custom
Drupal module embeds the whole valid product space (issued dates, systems,
products) as drupalSettings JSON and builds image URLs as
    {folder}/{variable}_{product}_{system}[_{predictor}]_{YYYY-Mon}_{PER}.jpg
so we re-read that JSON each run (self-updating as new months appear) and
probe the constructible URLs. Not every combination exists — a target season
is typically published out to ~4 months lead — so 404s are expected and cheap.

Kept to core products per the repo's scope decision: seasonal only (no
monthly/subseasonal), tercile probabilities only (no anomaly/skill maps);
the MME across all variables, single models for rainfall only.
"""

import json
import logging
import re

from src.constants import CSC_OSF_PAGE
from src.utils.download import DATA_RAW, download, fetch

logger = logging.getLogger(__name__)

MONTH_NUM = {
    m: f"{i + 1:02d}"
    for i, m in enumerate(
        ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
    )
}
MAX_LEAD = 4  # months from issue to target-season start; probes past this all 404

MME_PRODUCTS = ["prob-tercile-m", "prob-tercile"]
SINGLE_SYSTEMS = ["SEAS51", "CFSv2", "GEOSS2S", "CCSM4"]  # these require a predictor


def load_cfg() -> dict:
    html = fetch(CSC_OSF_PAGE).text
    m = re.search(
        r'<script type="application/json" data-drupal-selector="drupal-settings-json">(.*?)</script>',
        html,
        re.S,
    )
    return json.loads(m.group(1))["climatePrediction"]


def candidate_files(cfg: dict) -> list[tuple[str, str, str]]:
    """(filename, issued YYYY-MM, target period) for every combination worth probing."""
    periods = cfg["forecastPeriods"]["seasonal"]
    # the rolling-window list starts at MJJ, so period i starts in month i+5
    period_start = {p: (i + 4) % 12 + 1 for i, p in enumerate(periods)}

    out = []
    for issued in cfg["issuedDates"]["seasonal"]:
        year, mon = issued.split("-")
        issue_m = int(MONTH_NUM[mon])
        issued_num = f"{year}-{MONTH_NUM[mon]}"
        targets = [p for p in periods if (period_start[p] - issue_m) % 12 <= MAX_LEAD]
        for per in targets:
            for var in cfg["variables"]["seasonal"]:
                for prod in MME_PRODUCTS:
                    out.append((f"{var}_{prod}_MME01_{issued}_{per}.jpg", issued_num, per))
            for system in SINGLE_SYSTEMS:
                for pred in cfg["predictors"]:
                    out.append(
                        (f"PRCP_prob-tercile-m_{system}_{pred}_{issued}_{per}.jpg", issued_num, per)
                    )
    return out


def run() -> list[dict]:
    cfg = load_cfg()
    base = cfg["imageFolderUrls"]["seasonal"]
    candidates = candidate_files(cfg)
    logger.info(f"SADC OSF: probing {len(candidates)} candidate images")
    records, misses = [], 0
    for fname, issued_num, per in candidates:
        dest = DATA_RAW / "sadc" / "osf-seasonal" / issued_num / fname
        if download(base + fname, dest):
            records.append(
                {
                    "org": "sadc",
                    "product": "osf-seasonal",
                    "issued": issued_num,
                    "season": per,
                    "source_url": base + fname,
                    "path": str(dest.relative_to(DATA_RAW)),
                    "name": fname,
                }
            )
        else:
            misses += 1
    logger.info(f"SADC OSF: {len(records)} images, {misses} combinations not published")
    return records
