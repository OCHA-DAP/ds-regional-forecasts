"""ACCOF (African Continental Climate Outlook Forum) statements from acmad.org.

Sessions live at https://acmad.org/index.php/accof-<NN>/ (one known exception,
accof-12-2); PDFs sit under wp-content/uploads. No WP REST API confirmed on
this site, so we parse the session pages for PDF links.
"""

import logging
import re

from src.utils.download import DATA_RAW, download, fetch

logger = logging.getLogger(__name__)

SESSION_URLS = ["https://acmad.org/index.php/accof-12-2/"] + [
    f"https://acmad.org/index.php/accof-{n}/" for n in range(9, 30) if n != 12
]

PDF_RE = re.compile(r'href="(https?://acmad\.org/wp-content/uploads/[^"]+\.pdf)"', re.I)


def run() -> list[dict]:
    records = []
    for page in SESSION_URLS:
        session = re.search(r"accof-(\d+)", page).group(1)
        try:
            html = fetch(page).text
        except Exception:
            logger.info(f"no page: {page}")
            continue
        for url in dict.fromkeys(PDF_RE.findall(html)):
            fname = url.rsplit("/", 1)[-1]
            dest = DATA_RAW / "acmad" / "ACCOF" / f"accof-{session}" / fname
            if download(url, dest):
                records.append(
                    {
                        "org": "acmad",
                        "product": "accof",
                        "session": int(session),
                        "source_url": url,
                        "path": str(dest.relative_to(DATA_RAW)),
                        "name": fname,
                    }
                )
    return records
