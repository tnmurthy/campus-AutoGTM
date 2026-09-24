"""Polite, cached fetching of college websites.

These are third-party sites belonging to institutions this business wants as
customers, so the crawl behaves accordingly: it reads robots.txt, honours
Crawl-delay (GRIET publishes 10 seconds), identifies itself, caps what it
downloads, and caches so a re-run does not hit anyone twice.

Every failure returns None. A college whose site is slow, blocked or missing
must degrade to the unenriched lead, never break the campaign.
"""

import hashlib
import logging
import re
import time
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urljoin, urlparse
from urllib.robotparser import RobotFileParser

import requests

logger = logging.getLogger(__name__)

USER_AGENT = "CampusAutoGTM/0.1 (+college outreach research; contact via website)"
DEFAULT_CRAWL_DELAY = 2.0
MAX_BYTES = 1_500_000
CACHE_TTL_SECONDS = 7 * 24 * 3600


def _decode(body: bytes, content_type: str) -> str:
    """Decode HTML without scattering replacement characters through the text.

    Many college sites serve cp1252 punctuation with no charset, or declare one
    only in a meta tag. Decoding everything as utf-8 with errors="replace"
    turned curly quotes and bullets into U+FFFD, which then appeared verbatim in
    the excerpts sent to the model.
    """
    # utf-8 is tried first, ahead of any declared charset. It is
    # self-validating: cp1252 bytes rarely form valid utf-8, but utf-8 bytes
    # always decode as cp1252 -- wrongly. Several college sites declare cp1252
    # while serving utf-8, which turned a curly quote into "Roboticsa€™".
    candidates: list[str] = ["utf-8"]
    match = re.search(r"charset=([\w-]+)", content_type, re.I)
    if match:
        candidates.append(match.group(1))
    meta = re.search(rb"charset=[\"']?([\w-]+)", body[:4096], re.I)
    if meta:
        candidates.append(meta.group(1).decode("ascii", "ignore"))
    candidates += ["cp1252", "latin-1"]

    for encoding in candidates:
        try:
            return body.decode(encoding)
        except (UnicodeDecodeError, LookupError):
            continue
    return body.decode("utf-8", errors="replace")


@dataclass
class Page:
    url: str
    html: str


class Fetcher:
    def __init__(self, cache_dir: Path, timeout: float = 15.0):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.timeout = timeout
        self._robots: dict[str, tuple[RobotFileParser | None, float]] = {}
        self._last_hit: dict[str, float] = {}

    # -- robots -------------------------------------------------------------

    def _robots_for(self, url: str) -> tuple[RobotFileParser | None, float]:
        host = urlparse(url).netloc
        if host in self._robots:
            return self._robots[host]

        parser: RobotFileParser | None = RobotFileParser()
        delay = DEFAULT_CRAWL_DELAY
        robots_url = urljoin(f"{urlparse(url).scheme}://{host}", "/robots.txt")
        try:
            resp = requests.get(
                robots_url, headers={"User-Agent": USER_AGENT}, timeout=self.timeout
            )
            if resp.status_code == 200 and resp.text.strip():
                parser.parse(resp.text.splitlines())
                published = parser.crawl_delay(USER_AGENT)
                if published:
                    delay = float(published)
            else:
                # No robots.txt is permission by omission, not a reason to stop.
                parser = None
        except requests.RequestException:
            parser = None

        self._robots[host] = (parser, delay)
        return parser, delay

    def allowed(self, url: str) -> bool:
        parser, _ = self._robots_for(url)
        return True if parser is None else parser.can_fetch(USER_AGENT, url)

    # -- cache --------------------------------------------------------------

    def _cache_path(self, url: str) -> Path:
        return self.cache_dir / f"{hashlib.sha256(url.encode()).hexdigest()[:24]}.html"

    def _cached(self, url: str) -> str | None:
        path = self._cache_path(url)
        if not path.is_file():
            return None
        if time.time() - path.stat().st_mtime > CACHE_TTL_SECONDS:
            return None
        try:
            return path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return None

    # -- fetch --------------------------------------------------------------

    def get(self, url: str) -> Page | None:
        cached = self._cached(url)
        if cached is not None:
            return Page(url=url, html=cached)

        if not self.allowed(url):
            logger.info("robots.txt disallows %s", url)
            return None

        self._wait_for_host(url)

        try:
            resp = requests.get(
                url,
                headers={"User-Agent": USER_AGENT, "Accept": "text/html"},
                timeout=self.timeout,
                stream=True,
            )
            if resp.status_code != 200:
                logger.info("%s returned %s", url, resp.status_code)
                return None
            if "html" not in resp.headers.get("Content-Type", "").lower():
                return None

            body = resp.raw.read(MAX_BYTES, decode_content=True) or b""
            html = _decode(body, resp.headers.get("Content-Type", ""))
        except requests.RequestException as exc:
            logger.info("could not fetch %s: %s", url, exc)
            return None

        try:
            self._cache_path(url).write_text(html, encoding="utf-8")
        except OSError:
            pass

        return Page(url=url, html=html)

    def _wait_for_host(self, url: str) -> None:
        host = urlparse(url).netloc
        _, delay = self._robots_for(url)
        elapsed = time.time() - self._last_hit.get(host, 0.0)
        if elapsed < delay:
            time.sleep(delay - elapsed)
        self._last_hit[host] = time.time()
