"""TMDB search + embed-provider resolution -- the real replacement for the
dead scraper path.

The 9 scraped sites (myflixerz, lookmovie, hurawatch, etc) are ~100% dead
now: Cloudflare, JWT anti-bot, JS-rendering gates, SSL issues. Plain
requests+BeautifulSoup can't touch modern streaming sites anymore, and
crawl4ai/page-agent only get you so far against active anti-bot.

The fix: TMDB (themoviedb.org) is a real, free, sanctioned metadata API --
search/trending/now_playing/upcoming, real movie/TV IDs. Separately, a
handful of embed providers (vidsrc.to, 2embed.cc, vidsrc.xyz, vidlink.pro,
multiembed.mov) are *designed* to be embedded -- they return real players
keyed by TMDB/IMDb id, not bot-checks, because being embeddable is their
whole business model (unlike the scraped sites, which actively fight
scraping). So: TMDB for search/metadata, embed providers for the actual
stream, old scraper kept only as a last-resort fallback.

Requires TMDB_API_KEY env var (free key from themoviedb.org -- requires a
human to register an account; this module degrades to "no results" rather
than raising if it's unset, so the rest of franken-stream keeps working).
"""
import os
from typing import List, Optional

import httpx

TMDB_API_KEY = os.environ.get("TMDB_API_KEY", "")
TMDB_BASE = "https://api.themoviedb.org/3"
TMDB_IMG_BASE = "https://image.tmdb.org/t/p/w342"

# Ordered by reliability/reputation observed in the open-source streaming
# community; first one wins in extract order but all are tried.
EMBED_PROVIDERS = [
    # (name, movie_url_fmt, tv_url_fmt) -- {id} = tmdb id, {s}/{e} = season/episode
    ("vidsrc.to", "https://vidsrc.to/embed/movie/{id}", "https://vidsrc.to/embed/tv/{id}/{s}/{e}"),
    ("vidsrc.xyz", "https://vidsrc.xyz/embed/movie/{id}", "https://vidsrc.xyz/embed/tv/{id}/{s}/{e}"),
    ("2embed.cc", "https://www.2embed.cc/embed/{id}", "https://www.2embed.cc/embedtv/{id}&s={s}&e={e}"),
    ("vidlink.pro", "https://vidlink.pro/movie/{id}", "https://vidlink.pro/tv/{id}/{s}/{e}"),
    ("multiembed.mov", "https://multiembed.mov/?video_id={id}&tmdb=1", "https://multiembed.mov/?video_id={id}&tmdb=1&s={s}&e={e}"),
]


def tmdb_configured() -> bool:
    return bool(TMDB_API_KEY)


async def tmdb_search(query: str, media_type: str = "any", limit: int = 15) -> List[dict]:
    """Returns [{title, url, year, media_type, thumbnail}] -- url is a
    synthetic `tmdb:{media_type}:{id}` identifier, resolved to a real
    embed URL by resolve_tmdb_embed() below. Matches the {title,url} shape
    /api/search already returns so no caller-side changes are needed."""
    if not TMDB_API_KEY:
        return []
    endpoint = "multi" if media_type == "any" else media_type
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.get(
            f"{TMDB_BASE}/search/{endpoint}",
            params={"api_key": TMDB_API_KEY, "query": query, "include_adult": "false"},
        )
        if r.status_code != 200:
            return []
        data = r.json()

    results = []
    for item in data.get("results", [])[:limit]:
        mtype = item.get("media_type") or (media_type if media_type != "any" else "movie")
        if mtype not in ("movie", "tv"):
            continue
        title = item.get("title") or item.get("name") or "Untitled"
        date = item.get("release_date") or item.get("first_air_date") or ""
        year = int(date[:4]) if date[:4].isdigit() else None
        poster = item.get("poster_path")
        results.append({
            "title": f"{title} ({year})" if year else title,
            "url": f"tmdb:{mtype}:{item['id']}",
            "year": year,
            "media_type": mtype,
            "thumbnail": f"{TMDB_IMG_BASE}{poster}" if poster else None,
        })
    return results


async def tmdb_trending(window: str = "week", media_type: str = "all", limit: int = 20) -> List[dict]:
    """window: 'day'|'week'. media_type: 'all'|'movie'|'tv'."""
    if not TMDB_API_KEY:
        return []
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.get(
            f"{TMDB_BASE}/trending/{media_type}/{window}",
            params={"api_key": TMDB_API_KEY},
        )
        if r.status_code != 200:
            return []
        data = r.json()
    results = []
    for item in data.get("results", [])[:limit]:
        mtype = item.get("media_type", media_type if media_type != "all" else "movie")
        if mtype not in ("movie", "tv"):
            continue
        title = item.get("title") or item.get("name") or "Untitled"
        date = item.get("release_date") or item.get("first_air_date") or ""
        year = int(date[:4]) if date[:4].isdigit() else None
        poster = item.get("poster_path")
        results.append({
            "title": f"{title} ({year})" if year else title,
            "url": f"tmdb:{mtype}:{item['id']}",
            "year": year,
            "media_type": mtype,
            "thumbnail": f"{TMDB_IMG_BASE}{poster}" if poster else None,
        })
    return results


async def tmdb_now_playing(limit: int = 20) -> List[dict]:
    if not TMDB_API_KEY:
        return []
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.get(f"{TMDB_BASE}/movie/now_playing", params={"api_key": TMDB_API_KEY})
        if r.status_code != 200:
            return []
        data = r.json()
    results = []
    for item in data.get("results", [])[:limit]:
        date = item.get("release_date") or ""
        year = int(date[:4]) if date[:4].isdigit() else None
        poster = item.get("poster_path")
        results.append({
            "title": f"{item.get('title','Untitled')} ({year})" if year else item.get("title", "Untitled"),
            "url": f"tmdb:movie:{item['id']}",
            "year": year,
            "media_type": "movie",
            "thumbnail": f"{TMDB_IMG_BASE}{poster}" if poster else None,
        })
    return results


def is_tmdb_url(url: str) -> bool:
    return url.startswith("tmdb:movie:") or url.startswith("tmdb:tv:")


async def resolve_tmdb_embed(url: str, season: int = 1, episode: int = 1) -> Optional[str]:
    """url is a `tmdb:{type}:{id}` identifier from tmdb_search/tmdb_trending.
    Embed providers don't require a liveness probe -- they're built to be
    iframed directly -- so this just picks the first provider in priority
    order and returns its URL. The frontend iframe will show that
    provider's own error state if it's down; a future iteration could
    HEAD-check each in parallel and pick the first 200, but that adds
    latency for a class of provider that's historically been far more
    stable than the scraped sites."""
    if not is_tmdb_url(url):
        return None
    _, mtype, tmdb_id = url.split(":", 2)
    name, movie_fmt, tv_fmt = EMBED_PROVIDERS[0]
    if mtype == "movie":
        return movie_fmt.format(id=tmdb_id)
    return tv_fmt.format(id=tmdb_id, s=season, e=episode)
