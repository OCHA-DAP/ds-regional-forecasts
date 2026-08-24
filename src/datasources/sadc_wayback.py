"""Rescue historical SARCOF statements that survive only in the Wayback Machine.

Three generations of dead hosting, all verified in the CDX index during the
2026-08 survey:
- www.dmc.co.zw — the SADC Drought Monitoring Centre (Harare), captured only
  around 2004-2006; source of the oldest surviving statements (SARCOF-6 on).
- www.sadc.int old CMS (/files/<hash>/ paths) — killed by the Drupal migration.
- csc.sadc.int Joomla (/images/... paths) — killed by the ~2025 relaunch.

Known-lost despite the hunt: SARCOF-11/12/13 (2007-2009; the DMC site was
barely archived in those years) and the SARCOF-22 and -26 main statements
(only their mid-season review/update statements survive).
"""

import logging

from src.datasources.wayback import resolve_snapshot
from src.utils.download import DATA_RAW, download

logger = logging.getLogger(__name__)

# (year, original URL, optional rename for opaque filenames)
HISTORICAL = [
    (2002, "http://www.dmc.co.zw/SeasonalForecasts/SARCOF6FinalEdition.pdf", None),
    (2003, "http://www.dmc.co.zw/SeasonalForecasts/MidSeasonJFM2003.pdf", None),
    (2003, "http://www.dmc.co.zw/SARCOF/SarcofStatementSep2003Lusaka.pdf", None),
    (2004, "http://www.dmc.co.zw/SeasonalForecasts/MidSeasonJFM2004Update.pdf", None),
    (2004, "http://www.dmc.co.zw/SARCOF/SarcofStatementSep2004Harare.pdf", None),
    (2004, "http://www.dmc.co.zw/SeasonalForecasts/SARCOF_2004_STATEMENT.pdf", None),
    (2005, "http://www.dmc.co.zw/SeasonalForecasts/March_May2005_Outlook.pdf", None),
    (2005, "http://www.dmc.co.zw/SARCOF/SarcofStatementSep2005Harare.pdf", None),
    (2006, "http://www.dmc.co.zw/SARCOF/SarcofStatementSep2006Gaborone.pdf", None),
    # filename says nothing, XMP title says SARCOF-14
    (2010, "http://www.sadc.int/files/9015/1314/8484/STATEMENT_SARCOF.pdf", "SARCOF-14_STATEMENT.pdf"),
    # NOT listed: fanr/aims/rews SARCOF15_Statement_290811.pdf and the three
    # sadc.int SARCOF-25_STATEMENT-_<LANG>.pdf — their only captures are
    # truncated (unreadable PDFs); readable alternates below/in sadc_web cover them
    (2011, "http://www.sadc.int/files/4213/1555/4365/SADC_CSC_SARCOF15_Final_Statement_020911_fa.pdf", None),
    (2012, "http://www.sadc.int/files/1713/4789/5375/SARCOF_16_Statement_Bjg2308122300hrs.pdf", None),
    (2015, "http://www.sadc.int/files/3614/4196/5349/SARCOF_19_Statement-_31august_2015_2.pdf", None),
    (2017, "http://csc.sadc.int/images/documents/SARCOF%2021_Statement.pdf", None),
    (2019, "http://csc.sadc.int/images/data/documents/sarcof23/SARCOF-23%20STATEMENT.pdf", None),
    (2019, "http://csc.sadc.int/images/data/documents/sarcof23/SADC%20Regional%20Early%20Warning%20for%202019_20%20season.pdf", None),
    (2020, "http://csc.sadc.int/images/documents/FINAL%20SARCOF-24%20STATEMENT.pdf", None),
    (2020, "http://csc.sadc.int/images/documents/FR%20-%20FINAL%20SARCOF-24%20STATEMENT.pdf", None),
    (2021, "http://csc.sadc.int/images/documents/EN_FINAL-SARCOF-25-STATEMENT-for-2021-22-rainfall-season.pdf", None),
    (2021, "https://sadc.int/files/9316/3092/4033/SARCOF-25_STATEMENT-_ENGLISH.pdf", None),
    (2021, "https://sadc.int/files/1716/3092/4040/SARCOF-25_STATEMENT-_FRENCH.pdf", None),
    (2021, "https://sadc.int/files/3116/3092/4045/SARCOF-25_STATEMENT-_PORTUGUESE.pdf", None),
    (2021, "https://sadc.int/files/3916/3092/4056/SUMMARY_SARCOF_25_-_ENGLISH.pdf", None),
    (2021, "https://sadc.int/files/3816/3092/4064/SUMMARY_SARCOF_25_-_FRENCH.pdf", None),
    (2021, "https://sadc.int/files/3816/3092/4071/SUMMARY_SARCOF_25_-_PORTUGUESE.pdf", None),
    (2024, "http://csc.sadc.int/images/documents/ENGLISH_SARCOF-28_STATEMENT.pdf", None),
    (2024, "http://csc.sadc.int/images/documents/FRENCH_SARCOF-28_STATEMENT.pdf", None),
    (2024, "http://csc.sadc.int/images/documents/PORTUGUESE_SARCOF-28_STATEMENT.pdf", None),
    (2024, "http://csc.sadc.int/images/data/bulletins/EN_FINAL_SARCOF-29_STATEMENT.pdf", None),
]


def run() -> list[dict]:
    records = []
    for year, orig, rename in HISTORICAL:
        fname = rename or orig.rsplit("/", 1)[-1].replace("%20", "_")
        dest = DATA_RAW / "sadc" / "sarcof" / str(year) / fname
        if dest.exists() and dest.stat().st_size > 0:
            wb_url = f"https://web.archive.org/web/2id_/{orig}"
        else:
            wb_url = resolve_snapshot(orig)
            if not wb_url:
                logger.error(f"no snapshot found: {orig}")
                continue
        if download(wb_url, dest):
            records.append(
                {
                    "org": "sadc",
                    "product": "sarcof",
                    "issued": str(year),
                    "source_url": wb_url,
                    "original_url": orig,
                    "path": str(dest.relative_to(DATA_RAW)),
                    "name": fname,
                    "via": "wayback",
                }
            )
    return records
