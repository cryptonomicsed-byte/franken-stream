"""Jamendo -- real, legal, full-length music streaming (Creative Commons
licensed catalog). The music equivalent of archive.org for movies: a
genuine first-party service, not a mirror, with full tracks streamable
by design (artists opt in to CC licensing specifically to be shared).

Requires JAMENDO_CLIENT_ID env var (free, instant signup at
devportal.jamendo.com -- requires a human to create a developer account,
same as TMDB/YouTube; this module degrades to empty results rather than
raising if it's unset).
"""
import os
from typing import List, Optional

import httpx

JAMENDO_CLIENT_ID = os.environ.get("JAMENDO_CLIENT_ID", "")
JAMENDO_API_BASE = "https://api.jamendo.com/v3.0"


def jamendo_configured() -> bool:
    return bool(JAMENDO_CLIENT_ID)


async def jamendo_search(term: str, limit: int = 20) -> List[dict]:
    """Real, full-length, legally-licensed tracks. audio field is a
    directly-streamable full-track URL, not a preview."""
    if not JAMENDO_CLIENT_ID:
        return []
    params = {
        "client_id": JAMENDO_CLIENT_ID, "format": "json", "limit": limit,
        "search": term, "include": "musicinfo",
    }
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.get(f"{JAMENDO_API_BASE}/tracks/", params=params)
        if r.status_code != 200:
            return []
        data = r.json()

    results = []
    for t in data.get("results", []):
        results.append({
            "title": t.get("name", "Untitled"),
            "artist": t.get("artist_name", ""),
            "artwork": t.get("album_image") or t.get("image"),
            "audio_url": t.get("audio"),
            "duration": t.get("duration"),
            "license": t.get("license_ccurl"),
        })
    return results
