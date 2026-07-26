"""Resumable, sequential downloading with a shared session."""

import logging
import time
from pathlib import Path
from urllib.parse import quote, urlsplit, urlunsplit

import requests

logger = logging.getLogger(__name__)

DATA_RAW = Path(__file__).parents[2] / "data" / "raw"

_session = requests.Session()
_session.headers["User-Agent"] = (
    "ds-regional-forecasts (OCHA Centre for Humanitarian Data; "
    "seasonal forecast archive; contact: centrehumdata@un.org)"
)


def encode_url(url: str) -> str:
    """Percent-encode the path of a URL with raw spaces/%/accents in it."""
    parts = urlsplit(url)
    return urlunsplit(
        parts._replace(path=quote(parts.path, safe="/%") if "%" not in parts.path else parts.path)
    )


def fetch(url: str, retries: int = 3, timeout: int = 120) -> requests.Response:
    for attempt in range(retries):
        try:
            resp = _session.get(url, timeout=timeout)
            if resp.status_code == 200:
                return resp
            if resp.status_code in (404, 410):
                resp.raise_for_status()
        except requests.RequestException:
            if attempt == retries - 1:
                raise
        time.sleep(2**attempt)
    resp.raise_for_status()
    return resp


def download(url: str, dest: Path, retries: int = 3) -> Path | None:
    """Stream url to dest. Skips if dest exists and is non-empty. Returns None on failure."""
    if dest.exists() and dest.stat().st_size > 0:
        logger.debug(f"skip (exists): {dest.name}")
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    for attempt in range(retries):
        try:
            with _session.get(encode_url(url), stream=True, timeout=300) as resp:
                if resp.status_code != 200:
                    logger.warning(f"HTTP {resp.status_code}: {url}")
                    if resp.status_code in (404, 410):
                        return None
                    continue
                with open(tmp, "wb") as f:
                    for chunk in resp.iter_content(chunk_size=1 << 16):
                        f.write(chunk)
            tmp.rename(dest)
            logger.info(f"got {dest.relative_to(DATA_RAW)} ({dest.stat().st_size // 1024} KB)")
            return dest
        except requests.RequestException as e:
            logger.warning(f"attempt {attempt + 1} failed for {url}: {e}")
            time.sleep(2**attempt)
    tmp.unlink(missing_ok=True)
    logger.error(f"giving up: {url}")
    return None
