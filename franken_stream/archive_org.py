"""Internet Archive (archive.org) as a real, legal, first-party movie
source -- not a mirror/ad-supported embed site. Best fit specifically for
older/public-domain films: archive.org's advancedsearch.php is a real,
free, key-free metadata API, and archive.org/embed/{identifier} is their
own official embed pattern.

Verified live with Playwright (2026-07-25): real <video> element, zero
popups (sandboxed or not), tolerates the iframe `sandbox` attribute fine
-- the best-behaved source found in this whole integration, because it's
an actual archive, not an ad-monetized mirror.

Only attempted for older films (year <= ARCHIVE_YEAR_CUTOFF) -- archive.org
has real public-domain coverage there, but searching it for recent
copyrighted titles would mostly return noise (fan uploads, unrelated
content) or, worse, an actual unauthorized copy of a still-copyrighted
film. Gating by year is a deliberate legal/quality choice, not just a
performance optimization.
"""
import re
from typing import Optional

import httpx

ARCHIVE_SEARCH_URL = "https://archive.org/advancedsearch.php"
ARCHIVE_EMBED_BASE = "https://archive.org/embed/"

# Practical public-domain proxy cutoff, not a legal bright line. Owner's own
# framing: "especially pre-1970s". Real US public-domain status depends on
# publication date/renewal, which advancedsearch.php doesn't expose -- this
# cutoff just decides whether it's worth *trying* archive.org at all.
ARCHIVE_YEAR_CUTOFF = 1970


def _normalize(title: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", title.lower())


async def find_archive_org_match(title: str, year: Optional[int]) -> Optional[dict]:
    """Returns {"identifier": ..., "title": ..., "downloads": ...} for the
    best real match, or None. Only called for year <= ARCHIVE_YEAR_CUTOFF
    by the caller (tmdb_embed.py) -- see module docstring for why."""
    if not year or year > ARCHIVE_YEAR_CUTOFF:
        return None

    query = f'title:"{title}" AND year:{year} AND mediatype:movies'
    params = {
        "q": query,
        "fl[]": ["identifier", "title", "year", "downloads"],
        "sort[]": "downloads desc",
        "rows": 5,
        "output": "json",
    }
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.get(ARCHIVE_SEARCH_URL, params=params)
        if r.status_code != 200:
            return None
        data = r.json()

    docs = data.get("response", {}).get("docs", [])
    if not docs:
        return None

    # advancedsearch's title:"..." match is a phrase match, not exact --
    # confirm the normalized title actually overlaps before trusting it,
    # sorted by downloads so the most-referenced (usually best-quality/
    # most-authoritative) print wins among real matches.
    target = _normalize(title)
    for doc in docs:
        if target in _normalize(doc.get("title", "")) or _normalize(doc.get("title", "")) in target:
            return {"identifier": doc["identifier"], "title": doc.get("title", title), "downloads": doc.get("downloads", 0)}
    return None


def archive_org_embed_url(identifier: str) -> str:
    return f"{ARCHIVE_EMBED_BASE}{identifier}"


# --- Mixtapes (hiphopmixtapes collection) ------------------------------------
#
# Real find: DatPiff (the classic mixtape site) shut down its live site and
# officially partnered with archive.org, redirecting to
# archive.org/details/hiphopmixtapes as the new canonical home (confirmed
# live, 2026-07-26 -- datpiff.com's homepage itself says so and links
# there). So this isn't scraping a mixtape mirror; it's the same
# archive.org API already used for movies, pointed at DatPiff's own
# archived collection. No year gate here (unlike movies) -- mixtapes are a
# contemporary genre, not a public-domain-era one; the collection itself
# is the legitimacy signal, not the release date.
ARCHIVE_MIXTAPE_COLLECTION = "hiphopmixtapes"
ARCHIVE_METADATA_URL = "https://archive.org/metadata/{identifier}"
_AUDIO_FORMATS = {"vbr mp3", "mp3", "mpeg-4 audio", "128kbps mp3", "64kbps mp3"}


async def find_archive_org_mixtapes(artist: str, limit: int = 15) -> list:
    """Real mixtape search scoped to the hiphopmixtapes collection.
    Returns [{identifier, title, creator, downloads}]."""
    query = f'collection:{ARCHIVE_MIXTAPE_COLLECTION} AND creator:"{artist}"'
    params = {
        "q": query,
        "fl[]": ["identifier", "title", "creator", "downloads"],
        "sort[]": "downloads desc",
        "rows": limit,
        "output": "json",
    }
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.get(ARCHIVE_SEARCH_URL, params=params)
        if r.status_code != 200:
            return []
        data = r.json()
    return [
        {
            "identifier": d["identifier"],
            "title": d.get("title", d["identifier"]),
            "creator": d.get("creator", artist),
            "downloads": d.get("downloads", 0),
        }
        for d in data.get("response", {}).get("docs", [])
    ]


async def archive_org_track_list(identifier: str) -> list:
    """Real per-track direct audio URLs for a mixtape (or any archive.org
    audio item) via the metadata API -- confirmed CORS-open
    (access-control-allow-origin: *), so these play directly via a plain
    <audio src> for MP3-format files -- BUT confirmed live (2026-07-26)
    that archive.org's per-file CORS behavior is inconsistent by format:
    .mp3 files (VBR MP3) get access-control-allow-origin: *, .m4a files
    (MPEG-4 Audio) get NO CORS header at all on the same item/server.
    Most tracks on a typical mixtape are m4a, so relying on direct
    playback would silently fail for most of the tracklist. The 'url'
    field returned here is a RELATIVE PROXY URL (this server's own
    /api/audio/archive/stream) for every track regardless of format --
    consistent, doesn't depend on archive.org's per-format quirks, same
    proxy pattern already used for musify.club. Returns [{title, url,
    duration}] sorted by track number."""
    from urllib.parse import quote

    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.get(ARCHIVE_METADATA_URL.format(identifier=identifier))
        if r.status_code != 200:
            return []
        data = r.json()

    server = data.get("server")
    d = data.get("dir")
    if not server or not d:
        return []

    def track_num(f: dict) -> int:
        raw = str(f.get("track", "0"))
        # formats seen live: "12 of 25", "11/25", or a bare number
        digits = "".join(ch for ch in raw.split(" ")[0].split("/")[0] if ch.isdigit())
        return int(digits) if digits else 0

    tracks = []
    for f in data.get("files", []):
        if (f.get("format") or "").lower() not in _AUDIO_FORMATS:
            continue
        name = f.get("name")
        if not name:
            continue
        direct_url = f"https://{server}{d}/{quote(name)}"
        tracks.append({
            "title": f.get("title") or name.rsplit(".", 1)[0],
            "url": f"/api/audio/archive/stream?url={quote(direct_url, safe='')}",
            "duration": float(f["length"]) if f.get("length") else None,
            "_track_num": track_num(f),
        })
    tracks.sort(key=lambda t: t["_track_num"])
    for t in tracks:
        del t["_track_num"]
    return tracks
