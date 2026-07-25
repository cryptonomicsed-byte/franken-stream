"""iptv-org Live TV: real, zero-scraping HLS channel source.

Static, community-maintained M3U playlists at iptv-org.github.io -- no
anti-bot, no auth, no scraping, just fetch+parse. Per-country playlists
(iptv-org/iptv/countries/{code}.m3u) keep responses small; the country
list itself comes from iptv-org's own countries.json API.
"""
import re
import time
from typing import Dict, List, Optional

import httpx

COUNTRIES_URL = "https://iptv-org.github.io/api/countries.json"
COUNTRY_M3U_URL = "https://iptv-org.github.io/iptv/countries/{code}.m3u"

_CACHE_TTL = 3600  # 1h -- these playlists don't change minute-to-minute
_countries_cache: Optional[List[dict]] = None
_countries_cache_at: float = 0.0
_channels_cache: Dict[str, tuple] = {}  # code -> (channels, fetched_at)

_EXTINF_RE = re.compile(
    r'#EXTINF:-?\d+\s*(?P<attrs>(?:[a-zA-Z-]+="[^"]*"\s*)*),(?P<title>.+)'
)
_ATTR_RE = re.compile(r'([a-zA-Z-]+)="([^"]*)"')


async def list_countries() -> List[dict]:
    """[{name, code, flag}] -- cached 1h."""
    global _countries_cache, _countries_cache_at
    if _countries_cache and (time.time() - _countries_cache_at) < _CACHE_TTL:
        return _countries_cache
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.get(COUNTRIES_URL)
        r.raise_for_status()
        data = r.json()
    _countries_cache = [{"name": c["name"], "code": c["code"], "flag": c.get("flag", "")} for c in data]
    _countries_cache_at = time.time()
    return _countries_cache


def _parse_m3u(text: str) -> List[dict]:
    lines = text.splitlines()
    channels = []
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        if line.startswith("#EXTINF"):
            m = _EXTINF_RE.match(line)
            title = m.group("title").strip() if m else "Unknown"
            attrs = dict(_ATTR_RE.findall(m.group("attrs"))) if m else {}
            # Next non-comment line is the stream URL
            j = i + 1
            while j < len(lines) and lines[j].strip().startswith("#"):
                j += 1
            stream_url = lines[j].strip() if j < len(lines) else None
            if stream_url:
                channels.append({
                    "title": title,
                    "url": stream_url,
                    "group": attrs.get("group-title", ""),
                    "logo": attrs.get("tvg-logo", ""),
                })
            i = j + 1
        else:
            i += 1
    return channels


async def list_channels(country_code: str) -> List[dict]:
    """[{title, url, group, logo}] for a country. url is a real .m3u8 HLS
    stream, not a synthetic identifier -- playable directly by hls.js or a
    native-HLS <video> element. Cached 1h per country."""
    code = country_code.lower()
    cached = _channels_cache.get(code)
    if cached and (time.time() - cached[1]) < _CACHE_TTL:
        return cached[0]
    async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
        r = await client.get(COUNTRY_M3U_URL.format(code=code))
        if r.status_code != 200:
            return []
        channels = _parse_m3u(r.text)
    _channels_cache[code] = (channels, time.time())
    return channels
