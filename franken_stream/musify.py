"""musify.club -- full-length unlicensed music streaming mirror.

DISCLOSED, NOT HIDDEN (same policy as the movie-mirror providers in
tmdb_embed.py): this serves real commercial songs in full, without a
license, from a public mp3-mirror catalog site. This is a meaningfully
higher legal-risk category than the movie-embed mirrors -- music labels
pursue takedowns far more aggressively -- and was only built after the
owner explicitly asked for it, having already been told the legal-first
alternatives (iTunes previews, podcasts, SoundCloud, YouTube) exist and
chose full-catalog streaming anyway.

Mechanics (verified live, 2026-07-25/26): musify.club/search returns real
HTML search results; each track page embeds a `data-url="/track/pl/{id}/
{slug}.mp3"` link. Fetching that (with the track page as Referer) 302s to
a signed, time-limited CDN URL (`...musify.club/get/...?expires=...&sig=...`)
that streams the FULL track directly -- confirmed via file size/bitrate
math (14.3MB @ 320kbps = ~357s, matching "Thriller"'s real 5:57 runtime,
not a 30s preview) -- and that final URL plays with no special headers
from any origin (confirmed: a plain unauthenticated GET streamed real
audio bytes). No anti-bot/JS-rendering gate observed, unlike the movie
scraper sites -- plain httpx works.

Signed URLs expire ~1hr after issuance -- resolve on-demand right before
playback, don't cache them long-term.
"""
import re
from typing import List, Optional
from urllib.parse import urljoin

import httpx

MUSIFY_BASE = "https://musify.club"
_UA = "Mozilla/5.0 (compatible; VantageAudioBot/1.0)"


async def musify_search(term: str, limit: int = 15) -> List[dict]:
    """Returns [{title, track_url}] -- track_url is musify.club's own
    track page, passed to musify_resolve() to get the actual playable URL."""
    async with httpx.AsyncClient(timeout=15, headers={"User-Agent": _UA}, follow_redirects=True) as client:
        r = await client.get(f"{MUSIFY_BASE}/search", params={"searchText": term})
        if r.status_code != 200:
            return []
        html = r.text

    # Track links look like /track/artist-title-12345 ; titles come from
    # the link's own text/title attribute in the search results markup.
    results = []
    seen = set()
    for m in re.finditer(r'<a[^>]+href="(/track/[a-z0-9-]+-(\d+))"[^>]*title="([^"]+)"', html, re.I):
        path, track_id, title = m.group(1), m.group(2), m.group(3)
        if track_id in seen:
            continue
        seen.add(track_id)
        results.append({"title": title, "track_url": urljoin(MUSIFY_BASE, path)})
        if len(results) >= limit:
            break
    return results


async def musify_resolve(track_url: str) -> Optional[str]:
    """Resolves a musify.club track page to its actual, time-limited,
    directly-streamable full-track URL. Returns None if not found."""
    async with httpx.AsyncClient(timeout=15, headers={"User-Agent": _UA}) as client:
        r = await client.get(track_url)
        if r.status_code != 200:
            return None
        m = re.search(r'data-url="(/track/pl/\d+/[^"]+\.mp3)"', r.text)
        if not m:
            return None
        mp3_path = urljoin(MUSIFY_BASE, m.group(1))

        resolve_resp = await client.get(mp3_path, headers={"Referer": track_url}, follow_redirects=False)
        if resolve_resp.status_code in (301, 302, 303, 307, 308):
            return resolve_resp.headers.get("location")
        if resolve_resp.status_code == 200:
            return str(resolve_resp.url)
    return None
