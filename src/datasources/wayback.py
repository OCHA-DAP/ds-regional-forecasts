"""Rescue historical PRESASS/PRESAGG PDFs that survive only in the Wayback Machine.

URLs verified present in the CDX index during the 2026-07 survey; the live
originals 404 after successive AGRHYMET site redesigns. `id_` suffix returns
the original bytes without archive rewriting.
"""

import logging

from src.utils.download import DATA_RAW, download, fetch

logger = logging.getLogger(__name__)


def resolve_snapshot(orig: str) -> str | None:
    """Look up a working snapshot timestamp in the CDX index (flaky — retry)."""
    cdx = (
        "https://web.archive.org/cdx/search/cdx?url="
        + orig.replace("https://", "").replace("http://", "")
        + "&output=json&filter=statuscode:200&collapse=digest&limit=5"
    )
    for _ in range(3):
        try:
            rows = fetch(cdx).json()
        except Exception as e:
            logger.warning(f"CDX lookup failed for {orig}: {e}")
            continue
        if len(rows) > 1:
            ts = rows[-1][1]  # newest 200 capture
            return f"https://web.archive.org/web/{ts}id_/{orig}"
    return None

# (product, year, original URL)
HISTORICAL = [
    ("presass", 2016, "http://agrhymet.cilss.int/wp-content/uploads/2019/05/COMMUNIQUE-FINAL-PRESASS-03_Ouaga2016-VF.pdf"),
    ("presass", 2017, "http://www.agrhymet.ne/PDF/COMMUNIQUE%20FINAL%20PRESASS%20ACCRA%202017%20VF.pdf"),
    ("presass", 2018, "http://agrhymet.cilss.int/wp-content/uploads/2018/05/COMMUNIQUE-FINAL_-PRESASS_Abidjan_2018.pdf"),
    ("presass", 2018, "http://agrhymet.cilss.int/wp-content/uploads/2018/05/Bulletin_PRESASS-2018.pdf"),
    ("presass", 2019, "http://agrhymet.cilss.int/wp-content/uploads/2019/05/Communiqu%C3%A9-final_PRESASS_2019.pdf"),
    ("presass", 2020, "http://agrhymet.cilss.int/wp-content/uploads/2020/04/COMMUNIQUE_FINAL_PRESASS_2020_FRA.pdf"),
    ("presass", 2020, "http://agrhymet.cilss.int/wp-content/uploads/2020/04/COMMUNIQUE_FINAL_PRESASS_2020_ENG.pdf"),
    ("presass", 2020, "http://agrhymet.cilss.int/wp-content/uploads/2020/04/Bulletin-mensuel_PRESASS2020.pdf"),
    ("presass", 2021, "http://agrhymet.cilss.int/wp-content/uploads/2021/04/Communique_final_PRESASS_2021_FR.pdf"),
    ("presass", 2021, "http://agrhymet.cilss.int/wp-content/uploads/2021/04/Communique_final_PRESASS_2021_EN.pdf"),
    ("presass", 2021, "http://agrhymet.cilss.int/wp-content/uploads/2021/05/Bulletin_PRESASS21_news.pdf"),
    ("presass", 2021, "http://agrhymet.cilss.int/wp-content/uploads/2021/06/Bulletin_PRESASS21_MAJ-Juin.pdf"),
    ("presass", 2022, "http://agrhymet.cilss.int/wp-content/uploads/2022/04/COMMUNIQUE_FINAL_FORUM-PRESAS_2022.pdf"),
    ("presass", 2022, "http://agrhymet.cilss.int/wp-content/uploads/2022/05/Bulletin_PRESASS22.pdf"),
    ("presass", 2022, "http://agrhymet.cilss.int/wp-content/uploads/2022/05/Bulletin_PRESASS22_eng.pdf"),
    ("presagg", 2022, "http://agrhymet.cilss.int/wp-content/uploads/2022/03/PRESAGG-2022__communique_final_FR.pdf"),
    ("presagg", 2023, "https://agrhymet.cilss.int/doss/tocharg/2023/02/COMMUNIQUE-FINAL_PRESAGG_2023_VF_Engl.pdf"),
]


def run() -> list[dict]:
    records = []
    for product, year, orig in HISTORICAL:
        fname = orig.rsplit("/", 1)[-1].replace("%20", "_").replace("%C3%A9", "e")
        dest = DATA_RAW / "agrhymet" / product / str(year) / fname
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
                    "org": "agrhymet",
                    "product": product,
                    "issued": str(year),
                    "source_url": wb_url,
                    "original_url": orig,
                    "path": str(dest.relative_to(DATA_RAW)),
                    "name": fname,
                    "via": "wayback",
                }
            )
    return records
