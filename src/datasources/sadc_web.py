"""SARCOF statements + seasonal forecast bulletins from the live SADC sites.

Two Drupals: www.sadc.int (Secretariat — document library, statements back to
SARCOF-16) and csc.sadc.int (Climate Services Centre, relaunched ~2025 — only
recent forums survive there; HTTP only). Neither exposes an open media API, so
we crawl the listing/node pages. Pre-relaunch CSC files are rescued in
sadc_wayback.py.

Since 2024 SADC holds two forums per year (Jan/Feb mid-season + Aug/Sep main),
so session number no longer maps 1:1 to year — see session_year().
"""

import logging
import re
from urllib.parse import unquote, urljoin

from src.constants import CSC_BASE, SADC_BASE
from src.utils.download import DATA_RAW, download, fetch

logger = logging.getLogger(__name__)

DOC_SEARCH_TERMS = ["SARCOF", "climate outlook"]

# Forum core products only: statements, outlook updates, forecast bulletins,
# press releases carrying the headline outlook. Not conference logistics.
EXCLUDE_RE = re.compile(
    r"(?i)(announce|concept[ _-]?note|programme|draft[ _-]?program|opening|remark|speech"
    r"|participant|invitation|accreditation|information[ _-]?note|poverty)"
)
KEEP_RE = re.compile(r"(?i)(sarcof|climate[ _-]?outlook|rainfall_seasonal_forecast)")

PDF_HREF_RE = re.compile(r'href="([^"]+\.pdf)\s*"|href="([^"]+\.pdf)"', re.I)

# Individually verified live URLs that no listing page reaches.
EXTRA_LIVE = [
    f"{SADC_BASE}/sites/default/files/2021-06/24th_SARCOF_Statement_on_Climate-_English.pdf",
    f"{SADC_BASE}/sites/default/files/2021-06/24th_SARCOF_Statement_on_Climate-_FRENCH.pdf",
    f"{SADC_BASE}/sites/default/files/2021-06/24th_SARCOF_Statement_on_Climate-_Portuguese.pdf",
    f"{SADC_BASE}/sites/default/files/2025-02/SARCOF-30%20STATEMENT-EN.pdf",
    # statement missing from both SADC sites; Anticipation Hub mirrors it
    "https://www.anticipation-hub.org/Documents/Seasonal_forecasts/FINAL_SARCOF-31_STATEMENT.pdf",
]


def session_year(name: str) -> tuple[int | None, int | None]:
    """(session, forum year) from a filename. SARCOF-1 was 1997 and the forum
    was annual through SARCOF-27 (2023); from SARCOF-28 there are two per year
    (Jan/Feb mid-season + Aug/Sep main)."""
    m = re.search(r"(?i)sarcof[ _-]{0,2}(\d{1,2})|(\d{1,2})(?:th|st|nd|rd)[ _-]?sarcof", name)
    if not m:
        return None, None
    session = int(m.group(1) or m.group(2))
    if not 1 <= session <= 60:
        return None, None
    year = 1996 + session if session <= 27 else 2024 + (session - 28) // 2
    return session, year


def page_pdf_urls(page_url: str) -> list[str]:
    """All .pdf hrefs on a page, absolutized (csc's /index.php/ prefix is a
    routing artifact — the files live under /sites/...)."""
    try:
        html = fetch(page_url).text
    except Exception as e:
        logger.warning(f"page fetch failed {page_url}: {e}")
        return []
    urls = []
    for m in PDF_HREF_RE.finditer(html):
        href = (m.group(1) or m.group(2)).replace("/index.php/sites/", "/sites/")
        urls.append(urljoin(page_url, href))
    return list(dict.fromkeys(urls))


def collect_sadc_int() -> list[str]:
    """Document-library listings (embed direct file links) + /document/ nodes."""
    urls, doc_pages = [], []
    for term in DOC_SEARCH_TERMS:
        listing = f"{SADC_BASE}/documents?title={term.replace(' ', '+')}"
        try:
            html = fetch(listing).text
        except Exception as e:
            logger.warning(f"listing failed {listing}: {e}")
            continue
        urls += [
            urljoin(SADC_BASE, m.group(1))
            for m in re.finditer(r'href="(/sites/default/files/[^"]+\.pdf)"', html, re.I)
        ]
        doc_pages += [
            urljoin(SADC_BASE, m.group(1))
            for m in re.finditer(r'href="(/document/[^"]+)"', html)
        ]
    for page in dict.fromkeys(doc_pages):
        urls += [u for u in page_pdf_urls(page) if "/sites/default/files/" in u]
    return urls


def collect_csc() -> list[str]:
    """SARCOF event nodes (event type 6) + the bulletins page."""
    urls = []
    try:
        html = fetch(f"{CSC_BASE}/events?title=&field_event_type_target_id=6").text
        nodes = {
            m.group(1)
            for m in re.finditer(r'href="(/index\.php/[^"]*sarcof[^"]*)"', html, re.I)
            if "events" not in m.group(1)
        }
    except Exception as e:
        logger.warning(f"csc events listing failed: {e}")
        nodes = set()
    for node in sorted(nodes):
        urls += page_pdf_urls(urljoin(CSC_BASE, node))
    # bulletins page mixes monthly climate/fire bulletins (excluded by KEEP_RE)
    # with SARCOF-era seasonal forecast bulletins
    urls += page_pdf_urls(f"{CSC_BASE}/bulletins")
    return urls


def run() -> list[dict]:
    urls = collect_sadc_int() + collect_csc() + EXTRA_LIVE
    records = []
    for url in dict.fromkeys(urls):
        fname = unquote(url.rsplit("/", 1)[-1]).replace(" ", "_")
        if not KEEP_RE.search(fname) or EXCLUDE_RE.search(fname):
            continue
        session, year = session_year(fname)
        if year is None:
            m = re.search(r"(?<!\d)(19|20)(\d{2})(?!\d)", fname)
            year = int(m.group(0)) if m else None
        dest = DATA_RAW / "sadc" / "sarcof" / (str(year) if year else "undated") / fname
        if download(url, dest):
            rec = {
                "org": "sadc",
                "product": "sarcof",
                "issued": str(year) if year else None,
                "source_url": url,
                "path": str(dest.relative_to(DATA_RAW)),
                "name": fname,
            }
            if session:
                rec["session"] = session
            records.append(rec)
    return records
