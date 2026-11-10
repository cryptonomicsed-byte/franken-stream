"""iptv-org Live TV: real, zero-scraping HLS channel source.

2026-07-27: switched from the simple per-country .m3u playlists (US: 1,596
entries, group/logo only) to iptv-org's richer, joined API dataset (US:
3,286 real streams with working URLs, once joined to channels.json for
names/categories and logos.json for real logo images) -- nearly double
the US catalog with proper category metadata instead of a raw M3U
group-title string.

Static JSON files at iptv-org.github.io -- no anti-bot, no auth, no
scraping, just fetch+join:
  streams.json    -- {channel, feed, title, url, quality} per stream
  channels.json   -- {id, name, categories[], country} per channel
  categories.json -- {id, name} readable category labels
  logos.json      -- {channel, url} real logo images (channels.json has
                      no logo field itself)
  countries.json  -- country picker list (unchanged)
"""
import time
from typing import Dict, List, Optional

import httpx

COUNTRIES_URL = "https://iptv-org.github.io/api/countries.json"
STREAMS_URL = "https://iptv-org.github.io/api/streams.json"
CHANNELS_URL = "https://iptv-org.github.io/api/channels.json"
CATEGORIES_URL = "https://iptv-org.github.io/api/categories.json"
LOGOS_URL = "https://iptv-org.github.io/api/logos.json"

_CACHE_TTL = 3600  # 1h -- these datasets don't change minute-to-minute

_countries_cache: Optional[List[dict]] = None
_countries_cache_at: float = 0.0

# The four joined datasets are global (not per-country), so cache them
# once and slice per country_code on read -- avoids re-downloading ~19MB
# of streams.json on every country switch.
_dataset_cache: Optional[tuple] = None  # (streams, channels_by_id, categories_by_id, logos_by_channel)
_dataset_cache_at: float = 0.0

_channels_cache: Dict[str, tuple] = {}  # country_code -> (channels, fetched_at)


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


async def _load_dataset() -> tuple:
    global _dataset_cache, _dataset_cache_at
    if _dataset_cache and (time.time() - _dataset_cache_at) < _CACHE_TTL:
        return _dataset_cache

    async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
        streams_r, channels_r, categories_r, logos_r = [
            await client.get(u) for u in (STREAMS_URL, CHANNELS_URL, CATEGORIES_URL, LOGOS_URL)
        ]
    streams_r.raise_for_status()
    channels_r.raise_for_status()
    categories_r.raise_for_status()
    logos_r.raise_for_status()

    channels_by_id = {c["id"]: c for c in channels_r.json()}
    categories_by_id = {c["id"]: c["name"] for c in categories_r.json()}
    logos_by_channel: Dict[str, str] = {}
    for logo in logos_r.json():
        ch = logo.get("channel")
        if ch and ch not in logos_by_channel and logo.get("url"):
            logos_by_channel[ch] = logo["url"]

    _dataset_cache = (streams_r.json(), channels_by_id, categories_by_id, logos_by_channel)
    _dataset_cache_at = time.time()
    return _dataset_cache


async def list_channels(country_code: str) -> List[dict]:
    """[{title, url, group, logo}] for a country, joined from
    streams+channels+categories+logos. `group` is now a real, readable
    category name (or semicolon-joined list, same compound-category shape
    the frontend already splits on) instead of a raw M3U group-title.
    Cached 1h."""
    code = country_code.lower()
    cached = _channels_cache.get(code)
    if cached and (time.time() - cached[1]) < _CACHE_TTL:
        return cached[0]

    streams, channels_by_id, categories_by_id, logos_by_channel = await _load_dataset()

    suffix = f".{code}"
    result = []
    seen_urls = set()
    for s in streams:
        ch_id = s.get("channel")
        url = s.get("url")
        if not ch_id or not url or not ch_id.lower().endswith(suffix):
            continue
        if url in seen_urls:
            continue  # same stream URL sometimes listed under multiple feed rows
        seen_urls.add(url)

        channel = channels_by_id.get(ch_id, {})
        cat_ids = channel.get("categories") or []
        group = ";".join(categories_by_id.get(cid, cid) for cid in cat_ids) or "General"
        title = channel.get("name") or s.get("title") or ch_id

        result.append({
            "title": title,
            "url": url,
            "group": group,
            "logo": logos_by_channel.get(ch_id, ""),
        })

    _channels_cache[code] = (result, time.time())
    return result
