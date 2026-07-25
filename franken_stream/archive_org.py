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
