"""musify.club -- full-length unlicensed music streaming mirror.

DISCLOSED, NOT HIDDEN (same policy as the movie-mirror providers in
tmdb_embed.py): this serves real commercial songs in full, without a
license, from a public mp3-mirror catalog site. This is a meaningfully
higher legal-risk category than the movie-embed mirrors -- music labels
pursue takedowns far more aggressively -- and was only built after the
owner explicitly asked for it, having already been told the legal-first
alternatives (iTunes previews, podcasts, SoundCloud, YouTube) exist and
chose full-catalog streaming anyway.

Search quality fix (2026-07-26): the original version regex-scraped the
search page and only ever caught ~2 of the real ~10-17 candidates per
query -- it was matching a `title="..."` HTML attribute pattern that only
a handful of result rows actually use. Real inspection (BeautifulSoup,
not regex) found every genuine result row is a `.tracklist__row` element
carrying clean `data-artist`/`data-name` attributes, and its
`.tracklist__cover-wrap` child carries `data-url` -- the direct mp3 path
-- right there in the search results HTML, no second page fetch needed
at all. Confirmed live: querying "Queen Bohemian Rhapsody" (artist+title
together, exactly how resolve_full_track calls this) surfaces the real
Queen original among ~10 real candidates (covers, karaoke versions, the
original) with clean, correctly-attributed metadata.

Mechanics: musify.club/search returns real HTML; each `.tracklist__row`
carries the mp3 path directly. Fetching that mp3 path (with a Referer
header from the same domain) 302s to a signed, time-limited CDN URL that
streams the FULL track -- confirmed via file size/bitrate math (14.3MB @
320kbps = ~357s, matching "Thriller"'s real 5:57 runtime, not a preview)
-- and that final URL plays with no special headers from any origin
EXCEPT it 403s if a browser's cross-origin Origin header is present
(confirmed separately; see web.py's proxy-stream endpoint for the fix --
this module only resolves the URL, doesn't serve it to browsers
directly).

Signed URLs expire ~1hr after issuance -- resolve on-demand right before
playback, don't cache them long-term.
"""
import re
from typing import List, Optional
from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup

MUSIFY_BASE = "https://musify.club"
_UA = "Mozilla/5.0 (compatible; VantageAudioBot/1.0)"


def _normalize(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", s.lower())


async def musify_search(term: str, limit: int = 20) -> List[dict]:
    """Returns [{title, artist, track_url, mp3_path}] -- mp3_path is
    already the direct /track/pl/{id}/{slug}.mp3 path (extracted from
    the search page itself), passed to musify_resolve() to get the
    actual playable signed CDN URL."""
    async with httpx.AsyncClient(timeout=15, headers={"User-Agent": _UA}, follow_redirects=True) as client:
        r = await client.get(f"{MUSIFY_BASE}/search", params={"searchText": term})
        if r.status_code != 200:
            return []
        html = r.text

    soup = BeautifulSoup(html, "html.parser")
    results = []
    seen = set()
    for row in soup.select(".tracklist__row"):
        artist = row.get("data-artist", "").strip()
        name = row.get("data-name", "").strip()
        cover = row.select_one(".tracklist__cover-wrap")
        mp3_path = cover.get("data-url") if cover else None
        if not name or not mp3_path:
            continue
        key = mp3_path
        if key in seen:
            continue
        seen.add(key)
        results.append({
            "title": name,
            "artist": artist,
            # Display/reference only -- resolution uses mp3_path directly,
            # doesn't need to revisit a track page.
            "track_url": f"{MUSIFY_BASE}/search?searchText={term}",
            "mp3_path": urljoin(MUSIFY_BASE, mp3_path),
        })
        if len(results) >= limit:
            break
    return results


async def musify_resolve_path(mp3_path: str) -> Optional[str]:
    """Resolves an already-known mp3_path (from musify_search) directly
    to its signed, time-limited CDN URL -- no second page fetch needed."""
    async with httpx.AsyncClient(timeout=15, headers={"User-Agent": _UA}) as client:
        resp = await client.get(mp3_path, headers={"Referer": f"{MUSIFY_BASE}/"}, follow_redirects=False)
        if resp.status_code in (301, 302, 303, 307, 308):
            return resp.headers.get("location")
        if resp.status_code == 200:
            return str(resp.url)
    return None


async def musify_resolve(track_url: str) -> Optional[str]:
    """Back-compat path: resolves a musify.club TRACK PAGE (not a direct
    mp3_path) by fetching it and extracting its data-url. Prefer
    musify_search() + musify_resolve_path() for new code -- this refetches
    a page unnecessarily when the mp3_path is already known from search."""
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


async def musify_best_match(title: str, artist: str = "") -> Optional[dict]:
    """Searches for artist+title together (matches real candidates far
    better than title alone -- confirmed live) and returns the single
    best match by real (artist, title) equality, not just a loose
    substring check on title alone. Returns {title, artist, mp3_path} or
    None."""
    query = f"{artist} {title}".strip()
    candidates = await musify_search(query, limit=20)
    if not candidates:
        return None

    target_title = _normalize(title)
    target_artist = _normalize(artist)

    # Real catalog quirk found live: for some songs (e.g. "Billie Jean")
    # musify has ZERO plain unadorned matches -- every result carries a
    # parenthetical qualifier (Extended/Instrumental/Demo/Acapella/1983).
    # A non-original marker is actively wrong for "play me the song", so
    # it's penalized hard rather than left to arbitrary list-order
    # tie-breaking (the previous version of this fix still picked
    # "(Extended)" over "(1983)" by accident of search-result order).
    NON_ORIGINAL_MARKERS = (
        "instrumental", "acapella", "extended", "remix", "cover",
        "karaoke", "tribute", "live", "demo", "edit", "mix", "version",
        "reprise", "intro", "outro", "medley",
    )

    def score(c: dict) -> tuple:
        c_title_norm = _normalize(c["title"])
        c_artist = _normalize(c["artist"])
        artist_match = bool(target_artist) and c_artist == target_artist
        has_marker = any(m in c["title"].lower() for m in NON_ORIGINAL_MARKERS)

        if c_title_norm == target_title and artist_match:
            base = 4  # exact title, correct artist -- the real original
        elif c_title_norm == target_title:
            base = 3  # exact title, artist unknown/different (cover, but the full song)
        elif artist_match and (target_title in c_title_norm or c_title_norm in target_title):
            base = 2  # right artist, extra words in title
        elif target_title in c_title_norm or c_title_norm in target_title:
            base = 1  # loose title overlap only
        else:
            base = 0
        # Tiebreak within a score tier: prefer no non-original marker,
        # then prefer the title closest in length to the target (a
        # bare year suffix like "(1983)" is much closer to the real
        # thing than "(Extended)" or "(Instrumental)").
        return (base, 0 if has_marker else 1, -abs(len(c_title_norm) - len(target_title)))

    ranked = sorted(candidates, key=score, reverse=True)
    if score(ranked[0])[0] == 0:
        return None
    return ranked[0]
