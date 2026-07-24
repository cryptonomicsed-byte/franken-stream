"""Async content scraper using aiohttp for maximum throughput."""

import asyncio
import json
import os
import re
import time
from pathlib import Path
from typing import AsyncIterator, Dict, List, Optional, Tuple
from urllib.parse import quote_plus, urlparse

import aiohttp
from aiohttp import ClientTimeout, TCPConnector
from bs4 import BeautifulSoup

from franken_stream.circuit_breaker import CircuitBreaker

try:
    import _scraper
    HAS_NATIVE_SCRAPER = True
except ImportError:
    HAS_NATIVE_SCRAPER = False

# Many streaming-mirror providers gate their real content behind a
# JS-executed fingerprint/consent redirect (confirmed live: 2flix.com
# serves nothing but a FingerprintJS redirect shell to a plain HTTP
# client -- aiohttp gets zero real bytes no matter the retry count or
# selector quality). crawl4ai runs a real headless browser so that
# redirect actually executes before we read the page. Optional: falls
# back to the plain aiohttp fetch below if crawl4ai isn't installed or
# a given fetch fails, so this never hard-breaks environments without it.
try:
    from crawl4ai import AsyncWebCrawler, BrowserConfig, CacheMode, CrawlerRunConfig
    HAS_CRAWL4AI = True
except ImportError:
    HAS_CRAWL4AI = False

_shared_crawler: Optional["AsyncWebCrawler"] = None
_crawler_lock = asyncio.Lock()


async def _get_shared_crawler() -> Optional["AsyncWebCrawler"]:
    """Lazily starts one persistent headless-browser crawler, reused across
    every fetch -- spinning up a fresh browser per request would be far too
    slow for interactive search."""
    global _shared_crawler
    if not HAS_CRAWL4AI:
        return None
    async with _crawler_lock:
        if _shared_crawler is None:
            # Route the scraping browser's traffic through Tor if configured
            # (FRANKEN_STREAM_TOR_PROXY, e.g. socks5://127.0.0.1:9050 -- the
            # already-running system tor.service's SOCKS port) so provider
            # requests get a rotating exit IP against per-IP rate-limiting.
            # Deliberately NOT oniux/network-namespace isolation for this --
            # that isolates the whole process's loopback too, which would
            # make this web server unreachable from Vantage on localhost.
            tor_proxy = os.environ.get("FRANKEN_STREAM_TOR_PROXY")
            browser_config = BrowserConfig(headless=True, proxy=tor_proxy) if tor_proxy else BrowserConfig(headless=True)
            crawler = AsyncWebCrawler(config=browser_config)
            await crawler.start()
            _shared_crawler = crawler
    return _shared_crawler


# ── page-agent fallback: last resort when structured extraction finds
# nothing (a provider's markup changes too often for hand-written
# selectors/regex to keep up). alibaba/page-agent is a client-side,
# natural-language, LLM-driven GUI agent -- it runs INSIDE the rendered
# page (injected via crawl4ai's js_code) and is told in plain English what
# to find, rather than relying on a CSS selector that can go stale. Needs
# its own LLM credentials (BYO, same idea as the existing llm.py selector
# healer, just a different, more capable tool) -- disabled by default
# unless PAGE_AGENT_API_KEY is set, since it costs a real LLM call per
# resolution and should never fire silently on every request.
_PAGE_AGENT_BUNDLE_PATH = Path(__file__).resolve().parent / "vendor" / "page-agent-bundle.js"
_page_agent_bundle_cache: Optional[str] = None


def _get_page_agent_config() -> Optional[dict]:
    api_key = os.environ.get("PAGE_AGENT_API_KEY")
    if not api_key:
        return None
    return {
        "model": os.environ.get("PAGE_AGENT_MODEL", "deepseek-chat"),
        "baseURL": os.environ.get("PAGE_AGENT_BASE_URL", "https://api.deepseek.com"),
        "apiKey": api_key,
    }


def _load_page_agent_bundle() -> Optional[str]:
    global _page_agent_bundle_cache
    if _page_agent_bundle_cache is None and _PAGE_AGENT_BUNDLE_PATH.exists():
        _page_agent_bundle_cache = _PAGE_AGENT_BUNDLE_PATH.read_text()
    return _page_agent_bundle_cache


_URL_IN_TEXT_RE = re.compile(r'https?://[^\s"\'<>]+')


async def resolve_embed_with_page_agent(page_url: str) -> Optional[str]:
    """Ask page-agent (running inside the live rendered page) to find the
    video player / embed and report its URL. Returns None on any failure,
    missing config, or if the agent's answer doesn't contain a URL --
    never raises, this is a best-effort last resort."""
    config = _get_page_agent_config()
    bundle = _load_page_agent_bundle()
    if not config or not bundle or not HAS_CRAWL4AI:
        return None

    crawler = await _get_shared_crawler()
    if crawler is None:
        return None

    instruction = (
        "Find the main video player on this page (an iframe, a <video> "
        "element, or a 'play' button that reveals one) and report ONLY "
        "the resulting video/embed URL as plain text, nothing else. If "
        "there's a play button, click it first and wait for the player "
        "to load before reporting the URL."
    )
    js = bundle + f"""
    return (async () => {{
        return await window.__pageAgentResolve({json.dumps(instruction)}, {json.dumps(config)});
    }})();
    """
    try:
        result = await crawler.arun(
            url=page_url,
            config=CrawlerRunConfig(cache_mode=CacheMode.BYPASS, js_code=[js], page_timeout=30000),
        )
        exec_result = result.js_execution_result or {}
        inner = (exec_result.get("results") or [{}])[0]
        if not inner.get("ok"):
            return None
        answer = str((inner.get("result") or {}).get("data") or "")
        match = _URL_IN_TEXT_RE.search(answer)
        return match.group(0) if match else None
    except Exception:
        return None

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/119.0.0.0 Safari/537.36"
)

EMBED_PATTERNS = [
    (r'iframe[^>]*src=["\']([^"\']+)["\']', "iframe src"),
    (r'<a[^>]*href=["\']([^"\']*(?:embed|player)[^"\']*)["\']', "embed link"),
    (r'src=["\']([^"\']*\.m3u8[^"\']*)["\']', "HLS stream"),
    (r'src=["\']([^"\']*\.mp4[^"\']*)["\']', "MP4 video"),
    (r'data-url=["\']([^"\']+)["\']', "data-url attribute"),
]

# Multiple CSS selector fallbacks per extraction type
RESULT_SELECTORS = [
    ("a.ml-mask",       lambda el: (el.get("title", el.get_text(strip=True)), el.get("href", ""))),
    ("a[href]",         lambda el: (el.get_text(strip=True), el.get("href", ""))),
    ("h2 a",            lambda el: (el.get_text(strip=True), el.get("href", ""))),
    (".item a",         lambda el: (el.get_text(strip=True), el.get("href", ""))),
    (".movie-card a",   lambda el: (el.get_text(strip=True), el.get("href", ""))),
]


class AsyncContentScraper:
    """
    Async scraper with connection pooling, circuit breakers, and streaming results.
    """

    def __init__(
        self,
        proxy: Optional[str] = None,
        user_agent: Optional[str] = None,
        provider_manager=None,
        max_connections: int = 100,
        max_per_host: int = 20,
    ):
        self.proxy = proxy
        self.user_agent = user_agent or DEFAULT_USER_AGENT
        self.provider_manager = provider_manager
        self.circuit_breaker = CircuitBreaker(
            failure_threshold=5,
            recovery_timeout=300.0,
        )
        self._connector: Optional[TCPConnector] = None
        self._session: Optional[aiohttp.ClientSession] = None
        self._max_connections = max_connections
        self._max_per_host = max_per_host

    async def _ensure_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._connector = TCPConnector(
                limit=self._max_connections,
                limit_per_host=self._max_per_host,
                ttl_dns_cache=300,
                enable_cleanup_closed=True,
                force_close=False,
            )
            self._session = aiohttp.ClientSession(
                connector=self._connector,
                timeout=ClientTimeout(total=15, connect=5),
                headers={
                    "User-Agent": self.user_agent,
                    "Accept": "text/html,application/xhtml+xml",
                    "Accept-Language": "en-US,en;q=0.9",
                },
            )
        return self._session

    async def close(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()

    async def _get_page_crawl4ai(self, url: str) -> Optional[str]:
        """Real headless-browser fetch -- executes JS (fingerprint/consent
        redirects, client-rendered listings) that a plain HTTP client can
        never get past. Returns None on any failure so the caller falls
        back to the plain aiohttp path rather than raising."""
        crawler = await _get_shared_crawler()
        if crawler is None:
            return None
        try:
            config = CrawlerRunConfig(
                cache_mode=CacheMode.BYPASS,
                page_timeout=20000,
                delay_before_return_html=2.0,
            )
            result = await crawler.arun(url=url, config=config)
            return result.html if result and result.success else None
        except Exception:
            return None

    async def _get_page(self, url: str, retries: int = 3) -> Optional[str]:
        """Fetch a URL with exponential backoff retry."""
        import random

        html = await self._get_page_crawl4ai(url)
        if html:
            return html

        session = await self._ensure_session()
        for attempt in range(retries):
            try:
                kwargs: Dict = {}
                if self.proxy:
                    kwargs["proxy"] = self.proxy
                async with session.get(url, **kwargs) as resp:
                    if resp.status == 200:
                        return await resp.text()
                    return None
            except (aiohttp.ClientError, asyncio.TimeoutError):
                if attempt == retries - 1:
                    return None
                wait = (2 ** attempt) + random.uniform(0, 0.5)
                await asyncio.sleep(wait)
        return None

    def _extract_results(self, html: str, base_url: str) -> List[Tuple[str, str]]:
        """Try multiple CSS selectors in order, return first non-empty set."""
        if not html:
            return []
        soup = BeautifulSoup(html, "html.parser")
        host = urlparse(base_url).scheme + "://" + urlparse(base_url).netloc

        for selector, extractor in RESULT_SELECTORS:
            found = []
            for el in soup.select(selector):
                try:
                    title, href = extractor(el)
                    title = title.strip()
                    if not title or len(title) < 2:
                        continue
                    if href and href.startswith("/"):
                        href = host + href
                    if href and href.startswith("http") and title:
                        found.append((title, href))
                except Exception:
                    continue
            if found:
                return found[:15]
        return []

    async def _search_provider(
        self, base_url: str, query: str
    ) -> List[Tuple[str, str]]:
        """Search one provider, returning (title, url) pairs."""
        provider_name = urlparse(base_url).netloc
        if self.circuit_breaker.is_open(provider_name):
            return []

        search_url = base_url + quote_plus(query)
        start = time.monotonic()
        try:
            html = await self._get_page(search_url)
            elapsed_ms = (time.monotonic() - start) * 1000

            if html is None:
                self.circuit_breaker.record_failure(provider_name)
                if self.provider_manager:
                    self.provider_manager.record_result(base_url, False, elapsed_ms)
                return []

            results = self._extract_results(html, base_url)
            self.circuit_breaker.record_success(provider_name)
            if self.provider_manager:
                self.provider_manager.record_result(base_url, True, elapsed_ms)
            return results

        except Exception:
            self.circuit_breaker.record_failure(provider_name)
            elapsed_ms = (time.monotonic() - start) * 1000
            if self.provider_manager:
                self.provider_manager.record_result(base_url, False, elapsed_ms)
            return []

    async def search_streaming(
        self, query: str, bases: List[str]
    ) -> AsyncIterator[Tuple[str, str]]:
        """
        Yield (title, url) pairs as each provider responds.
        Results arrive within 1-2s instead of waiting for the slowest provider.
        """
        tasks = {
            asyncio.create_task(self._search_provider(base, query)): base
            for base in bases
        }
        seen_urls: set = set()

        for coro in asyncio.as_completed(list(tasks)):
            try:
                results = await coro
                for title, url in results:
                    if url not in seen_urls:
                        seen_urls.add(url)
                        yield title, url
            except Exception:
                continue

    async def search(
        self, query: str, bases: List[str]
    ) -> List[Tuple[str, str]]:
        """Collect all streaming results into a list."""
        if HAS_NATIVE_SCRAPER:
            try:
                config = _scraper.ScraperConfig(
                    user_agent=self.user_agent,
                    proxy=self.proxy or ""
                )
                # Route search through the native Rust implementation
                results = await _scraper.search(query, bases, config)
                if results:
                    return [(r[0], r[1]) for r in results]
            except Exception:
                # Fallback to Python if Rust fails at runtime
                pass

        # Python implementation (original or fallback)
        results: List[Tuple[str, str]] = []
        async for item in self.search_streaming(query, bases):
            results.append(item)
        return results

    async def fetch_embed_from_page(
        self, page_url: str, base_url: Optional[str] = None
    ) -> Optional[str]:
        """Extract a playable embed URL from a detail page."""
        html = await self._get_page(page_url)
        if not html:
            return None

        host = base_url or (
            urlparse(page_url).scheme + "://" + urlparse(page_url).netloc
        )

        for pattern, _ in EMBED_PATTERNS:
            m = re.search(pattern, html, re.IGNORECASE)
            if m:
                url = m.group(1)
                if url.startswith("/"):
                    url = host + url
                if url.startswith(("http://", "https://", "//")):
                    return url

        # Structured extraction found nothing -- last resort, only if the
        # operator opted in (PAGE_AGENT_API_KEY set): ask page-agent to
        # find the player visually/semantically instead of via selector.
        return await resolve_embed_with_page_agent(page_url)

    async def validate_proxy(self, proxy_url: str) -> bool:
        """Return True if the proxy is reachable."""
        try:
            timeout = ClientTimeout(total=6)
            conn = TCPConnector()
            async with aiohttp.ClientSession(connector=conn, timeout=timeout) as s:
                async with s.get("https://www.example.com", proxy=proxy_url) as r:
                    return r.status < 500
        except Exception:
            return False
