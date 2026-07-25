"""TMDB search + embed-provider resolution -- the real replacement for the
dead scraper path.

The 9 scraped sites (myflixerz, lookmovie, hurawatch, etc) are ~100% dead
now: Cloudflare, JWT anti-bot, JS-rendering gates, SSL issues. Plain
requests+BeautifulSoup can't touch modern streaming sites anymore, and
crawl4ai/page-agent only get you so far against active anti-bot.

The fix: TMDB (themoviedb.org) is a real, free, sanctioned metadata API --
search/trending/now_playing/upcoming/discover-by-genre, real movie/TV IDs
and posters. Separately, a handful of embed providers (vidsrc.to, 2embed.cc,
vidsrc.xyz, vidlink.pro, multiembed.mov) are *designed* to be embedded --
they return real players keyed by TMDB/IMDb id, not bot-checks, because
being embeddable is their whole business model (unlike the scraped sites,
which actively fight scraping). So: TMDB for search/metadata/browse, embed
providers for the actual stream, old scraper kept only as a last-resort
fallback.

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

# Ordered by ACTUAL rendered reliability, verified live with Playwright
# (2026-07-25/26) against "Inception" (tmdb id 27205) and a brand-new 2026
# release (tmdb id 1368337), not assumption:
#   vidcore.org   -- real <video> element (MSE blob: src, readyState=4),
#                    plays on click, confirmed on BOTH test titles, ZERO
#                    popups fired (tested with real force-clicks on the
#                    <video> element, twice), AND tolerates the `sandbox`
#                    iframe attribute without breaking (still plays
#                    sandboxed). Best provider found so far on every axis
#                    -- promoted to first priority. TV url format is an
#                    educated guess (only movie tested); revisit if TV
#                    playback is reported broken.
#   vidlink.pro   -- real <video> element, playing, timestamps advancing,
#                    on BOTH test titles. WORKS, but fires a popunder ad
#                    (s.pemsrv.com) on ANY click inside the iframe -- and
#                    uniquely refuses to initialize at all if a `sandbox`
#                    attribute is present in ANY combination (tested
#                    every token). Kept as the fallback-after-vidcore
#                    since it's still a real working player, left
#                    unsandboxed (see frontend SANDBOXED_EXCEPTIONS).
#   multiembed.mov -- ALSO fires a popup on click (new finding), never
#                    renders video either way -- sandboxed for free.
#   2embed.cc     -- loads but lands on 2embed's own wrapper/landing page, not
#                    the direct player (this URL format doesn't reach the
#                    video) -- kept as fallback pending a corrected URL format.
#   vidsrc.to     -- loads (200) but renders an empty body, no video found.
#   vidsrc.xyz    -- domain does not even resolve (net::ERR_NAME_NOT_RESOLVED,
#                    confirmed dead), kept last only in case it comes back.
# Investigated and confirmed dead ends (not added): vidsrc.mov (loads blank,
# no video after 10s), superembed.stream (404 on every URL pattern tried),
# smashystream (ad-gate "session verification failed" page, not a real embed).
EMBED_PROVIDERS = [
    # (name, movie_url_fmt, tv_url_fmt) -- {id} = tmdb id, {s}/{e} = season/episode
    ("vidcore.org", "https://vidcore.org/embed/movie/{id}", "https://vidcore.org/embed/tv/{id}/{s}/{e}"),
    ("vidlink.pro", "https://vidlink.pro/movie/{id}", "https://vidlink.pro/tv/{id}/{s}/{e}"),
    ("2embed.cc", "https://www.2embed.cc/embed/{id}", "https://www.2embed.cc/embedtv/{id}&s={s}&e={e}"),
    ("multiembed.mov", "https://multiembed.mov/?video_id={id}&tmdb=1", "https://multiembed.mov/?video_id={id}&tmdb=1&s={s}&e={e}"),
    ("vidsrc.to", "https://vidsrc.to/embed/movie/{id}", "https://vidsrc.to/embed/tv/{id}/{s}/{e}"),
    ("vidsrc.xyz", "https://vidsrc.xyz/embed/movie/{id}", "https://vidsrc.xyz/embed/tv/{id}/{s}/{e}"),
]


def tmdb_configured() -> bool:
    return bool(TMDB_API_KEY)


def _parse_items(data: dict, default_media_type: str, limit: int) -> List[dict]:
    """Shared row->dict mapping for search/trending/now_playing/upcoming/
    discover -- all of TMDB's list endpoints share this result shape.
    Returns [{title, url, year, media_type, thumbnail, rating}]."""
    results = []
    for item in data.get("results", [])[:limit]:
        mtype = item.get("media_type") or default_media_type
        if mtype not in ("movie", "tv"):
            continue
        title = item.get("title") or item.get("name") or "Untitled"
        date = item.get("release_date") or item.get("first_air_date") or ""
        year = int(date[:4]) if date[:4].isdigit() else None
        poster = item.get("poster_path")
        rating = item.get("vote_average")
        results.append({
            "title": title,
            "url": f"tmdb:{mtype}:{item['id']}",
            "year": year,
            "media_type": mtype,
            "thumbnail": f"{TMDB_IMG_BASE}{poster}" if poster else None,
            "rating": round(rating, 1) if isinstance(rating, (int, float)) else None,
        })
    return results


async def _tmdb_get(path: str, params: Optional[dict] = None) -> Optional[dict]:
    if not TMDB_API_KEY:
        return None
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.get(f"{TMDB_BASE}{path}", params={"api_key": TMDB_API_KEY, **(params or {})})
        if r.status_code != 200:
            return None
        return r.json()


async def tmdb_search(query: str, media_type: str = "any", limit: int = 15) -> List[dict]:
    """url is a synthetic `tmdb:{media_type}:{id}` identifier, resolved to a
    real embed URL by resolve_tmdb_embed() below. Matches the {title,url}
    shape /api/search already returns so no caller-side changes are needed."""
    endpoint = "multi" if media_type == "any" else media_type
    data = await _tmdb_get(f"/search/{endpoint}", {"query": query, "include_adult": "false"})
    if not data:
        return []
    return _parse_items(data, media_type if media_type != "any" else "movie", limit)


async def tmdb_trending(window: str = "week", media_type: str = "all", limit: int = 20) -> List[dict]:
    """window: 'day'|'week'. media_type: 'all'|'movie'|'tv'."""
    data = await _tmdb_get(f"/trending/{media_type}/{window}")
    if not data:
        return []
    return _parse_items(data, media_type if media_type != "all" else "movie", limit)


async def tmdb_now_playing(limit: int = 20) -> List[dict]:
    data = await _tmdb_get("/movie/now_playing")
    if not data:
        return []
    return _parse_items(data, "movie", limit)


async def tmdb_upcoming(limit: int = 20) -> List[dict]:
    data = await _tmdb_get("/movie/upcoming")
    if not data:
        return []
    return _parse_items(data, "movie", limit)


async def tmdb_genres(media_type: str = "movie") -> List[dict]:
    """[{id, name}] -- for a genre picker."""
    data = await _tmdb_get(f"/genre/{media_type}/list")
    if not data:
        return []
    return data.get("genres", [])


async def tmdb_discover_by_genre(genre_id: int, media_type: str = "movie", limit: int = 20) -> List[dict]:
    data = await _tmdb_get(f"/discover/{media_type}", {"with_genres": genre_id, "sort_by": "popularity.desc"})
    if not data:
        return []
    return _parse_items(data, media_type, limit)


def is_tmdb_url(url: str) -> bool:
    return url.startswith("tmdb:movie:") or url.startswith("tmdb:tv:")


def resolve_tmdb_embed_all(url: str, season: int = 1, episode: int = 1) -> List[dict]:
    """Returns ALL candidate embed URLs, in provider-priority order:
    [{"provider": name, "url": embed_url}, ...].

    Correction (2026-07-25, live investigation): a prior version of this
    function returned only EMBED_PROVIDERS[0] on the assumption that these
    embed sites "don't require a liveness probe." That assumption was
    wrong -- rendered vidsrc.to's actual embed chain with Playwright and
    found its nested player (vsembed.ru) runs anti-automation/devtool
    detection that redirects to a fake 404 trap page
    (theajack.github.io/disable-devtool/404.html), plus loads sketchy
    ad-redirect domains (cloudorchestranova.com, cloudnestra.com). A
    plain HTTP 200 from the outer page (what a server-side liveness probe
    would see) does NOT mean the video actually plays -- the failure
    happens client-side, after JS runs, which a HEAD-check can't detect
    either. So: no amount of server-side probing reliably predicts which
    provider will actually render for a given user. The honest fix is
    exposing all candidates and letting the frontend offer "try another
    source" when the first one doesn't play, not pretending the backend
    can guarantee liveness."""
    if not is_tmdb_url(url):
        return []
    _, mtype, tmdb_id = url.split(":", 2)
    candidates = []
    for name, movie_fmt, tv_fmt in EMBED_PROVIDERS:
        if mtype == "movie":
            candidates.append({"provider": name, "url": movie_fmt.format(id=tmdb_id)})
        else:
            candidates.append({"provider": name, "url": tv_fmt.format(id=tmdb_id, s=season, e=episode)})
    return candidates


async def resolve_tmdb_embed(url: str, season: int = 1, episode: int = 1) -> Optional[str]:
    """Back-compat: first candidate only. Prefer resolve_tmdb_embed_all()
    for real usage -- see its docstring for why a single "the" embed URL
    isn't a reliable concept for this class of provider."""
    all_candidates = resolve_tmdb_embed_all(url, season, episode)
    return all_candidates[0]["url"] if all_candidates else None
