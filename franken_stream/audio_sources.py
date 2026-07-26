"""Legal-first audio sources for Vantage's Audio "Stream" tab.

Deliberately built around real, licensed/open sources rather than any
scraping of full commercial music -- music labels enforce takedowns far
more aggressively than the movie-embed-mirror space, so this module
avoids that risk entirely:

- iTunes Search API (itunes.apple.com/search): free, no key, official
  Apple endpoint. Real album/track metadata, high-res cover art (bump
  artworkUrl100 -> 600x600bb), and a legal 30-second preview clip per
  track (previewUrl) -- not a full-song stream, by Apple's own design.
- Podcasts: also via iTunes Search (media=podcast), which returns a
  real feedUrl (public RSS) directly -- no separate Podcast Index API
  key needed. Episodes come straight from the RSS <enclosure> tag: a
  direct, legal, full-length audio file URL (podcasts are distributed
  as open RSS by design, no scraping involved at all).
- SoundCloud oEmbed (soundcloud.com/oembed): real, key-free, official.
  Only works for a track URL the caller already has (SoundCloud doesn't
  expose a key-free full-catalog *search* API -- that needs a
  registered client_id, which isn't available here yet).
- YouTube: gated behind YOUTUBE_API_KEY (Google Cloud Console, free
  tier) -- not configured yet, degrades to empty results like TMDB does
  when its key is unset, rather than breaking.
"""
import os
import re
import xml.etree.ElementTree as ET
from typing import List, Optional

import httpx

ITUNES_SEARCH_URL = "https://itunes.apple.com/search"
ITUNES_LOOKUP_URL = "https://itunes.apple.com/lookup"
ITUNES_CHARTS_URL = "https://itunes.apple.com/us/rss/topsongs/limit={limit}/json"
ITUNES_CHARTS_GENRE_URL = "https://itunes.apple.com/us/rss/topsongs/limit={limit}/genre={genre_id}/json"
SOUNDCLOUD_OEMBED_URL = "https://soundcloud.com/oembed"
YOUTUBE_API_KEY = os.environ.get("YOUTUBE_API_KEY", "")
YOUTUBE_SEARCH_URL = "https://www.googleapis.com/youtube/v3/search"

# Apple's own documented, stable genre IDs (classic iTunes RSS charts API).
MUSIC_GENRES = [
    {"id": 20, "name": "Alternative"}, {"id": 21, "name": "Rock"},
    {"id": 14, "name": "Pop"}, {"id": 15, "name": "R&B/Soul"},
    {"id": 18, "name": "Hip-Hop/Rap"}, {"id": 17, "name": "Dance"},
    {"id": 24, "name": "Reggae"}, {"id": 6, "name": "Country"},
    {"id": 11, "name": "Jazz"}, {"id": 12, "name": "Classical"},
]


def _upgrade_artwork(url: Optional[str]) -> Optional[str]:
    """iTunes' documented trick: swap the trailing NxNbb size segment for
    a much larger one. Works on any artworkUrlNN value."""
    if not url:
        return None
    return re.sub(r"/\d+x\d+bb\.(jpg|png)$", r"/600x600bb.\1", url)


async def itunes_search(term: str, media: str = "music", entity: Optional[str] = None, limit: int = 20) -> List[dict]:
    """media: 'music' | 'podcast'. entity (optional): 'album' | 'song' |
    'podcast'. Returns real Apple metadata, artwork upgraded to 600x600,
    plus previewUrl for songs (a real, legal 30s clip) and feedUrl for
    podcasts (a real, public RSS feed -- see podcast_episodes below)."""
    params = {"term": term, "media": media, "limit": limit}
    if entity:
        params["entity"] = entity
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.get(ITUNES_SEARCH_URL, params=params)
        if r.status_code != 200:
            return []
        data = r.json()

    results = []
    for item in data.get("results", []):
        # entity=musicArtist results are a different shape entirely --
        # no trackName/collectionName, only artistName/artistId -- handle
        # them explicitly rather than falling through to "Untitled".
        results.append({
            "kind": item.get("kind") or item.get("wrapperType"),
            "title": item.get("trackName") or item.get("collectionName") or item.get("artistName", "Untitled"),
            "artist": item.get("artistName", ""),
            "artist_id": item.get("artistId"),
            "collection": item.get("collectionName", ""),
            "collection_id": item.get("collectionId"),
            "artwork": _upgrade_artwork(item.get("artworkUrl100")),
            # entity=album results NEVER carry a real preview_url -- iTunes
            # only attaches previews at the individual-track level (confirmed
            # live: entity=album for an album returns null, the same album's
            # entity=song tracks return real .m4a preview URLs). Use
            # itunes_album_tracks(collection_id) to get real, playable
            # per-track previews for an album result.
            "preview_url": item.get("previewUrl"),
            "feed_url": item.get("feedUrl"),
            "track_count": item.get("trackCount"),
            "genre": item.get("primaryGenreName"),
            "view_url": item.get("trackViewUrl") or item.get("collectionViewUrl") or item.get("artistLinkUrl"),
        })
    return results


async def itunes_artist_albums(artist_id: int, limit: int = 25) -> List[dict]:
    """Real discography for a specific artist (lookup by artistId,
    entity=album) -- powers 'search an artist -> see their albums'.
    Same dict shape as itunes_search's album results, so the frontend's
    existing expand-to-tracks album card works unchanged."""
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.get(ITUNES_LOOKUP_URL, params={"id": artist_id, "entity": "album", "limit": limit})
        if r.status_code != 200:
            return []
        data = r.json()

    results = []
    for item in data.get("results", []):
        if item.get("wrapperType") != "collection":
            continue
        results.append({
            "kind": "album",
            "title": item.get("collectionName", "Untitled"),
            "artist": item.get("artistName", ""),
            "artist_id": item.get("artistId"),
            "collection": item.get("collectionName", ""),
            "collection_id": item.get("collectionId"),
            "artwork": _upgrade_artwork(item.get("artworkUrl100")),
            "preview_url": None,
            "feed_url": None,
            "track_count": item.get("trackCount"),
            "genre": item.get("primaryGenreName"),
            "view_url": item.get("collectionViewUrl"),
        })
    return results


async def itunes_album_tracks(collection_id: int) -> List[dict]:
    """Real per-track preview_urls for a specific album, via iTunes'
    lookup endpoint (id=collectionId, entity=song) -- precise (exact
    collection match), unlike re-searching by title/artist which can
    land on the wrong reissue/edition. First result is always the
    collection record itself (wrapperType='collection'), filtered out."""
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.get(ITUNES_LOOKUP_URL, params={"id": collection_id, "entity": "song"})
        if r.status_code != 200:
            return []
        data = r.json()

    tracks = []
    for item in data.get("results", []):
        if item.get("wrapperType") != "track":
            continue
        tracks.append({
            "title": item.get("trackName", "Untitled"),
            "track_number": item.get("trackNumber"),
            "preview_url": item.get("previewUrl"),
            "duration_ms": item.get("trackTimeMillis"),
        })
    tracks.sort(key=lambda t: t.get("track_number") or 0)
    return tracks


async def podcast_episodes(feed_url: str, limit: int = 30) -> List[dict]:
    """Parses a podcast's public RSS feed directly for real, direct,
    full-length episode audio URLs -- no scraping, no auth, this is
    exactly what RSS is for."""
    async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
        r = await client.get(feed_url)
        if r.status_code != 200:
            return []
        xml_text = r.text

    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return []

    channel_title = root.findtext(".//channel/title", default="")
    episodes = []
    for item in root.findall(".//channel/item")[:limit]:
        enclosure = item.find("enclosure")
        if enclosure is None or not enclosure.get("url"):
            continue
        episodes.append({
            "podcast": channel_title,
            "title": item.findtext("title", default="Untitled episode"),
            "audio_url": enclosure.get("url"),
            "audio_type": enclosure.get("type", "audio/mpeg"),
            "pub_date": item.findtext("pubDate", default=""),
            "duration": item.findtext("{http://www.itunes.com/dtds/podcast-1.0.dtd}duration", default=""),
        })
    return episodes


async def soundcloud_embed(track_url: str) -> Optional[dict]:
    """Real oEmbed lookup for a SoundCloud track/playlist URL the caller
    already has -- SoundCloud's key-free API only covers oEmbed, not
    full-catalog search (that needs a registered client_id)."""
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.get(SOUNDCLOUD_OEMBED_URL, params={"url": track_url, "format": "json"})
        if r.status_code != 200:
            return None
        data = r.json()
    return {
        "title": data.get("title"),
        "author": data.get("author_name"),
        "thumbnail": data.get("thumbnail_url"),
        "embed_html": data.get("html"),
    }


def youtube_configured() -> bool:
    return bool(YOUTUBE_API_KEY)


async def youtube_search(term: str, limit: int = 15) -> List[dict]:
    """Official YouTube Data API v3 search -- gated behind YOUTUBE_API_KEY
    (free tier, Google Cloud Console). Degrades to [] if unset, same
    pattern as TMDB_API_KEY in tmdb_embed.py."""
    if not YOUTUBE_API_KEY:
        return []
    params = {
        "part": "snippet", "q": term, "type": "video", "maxResults": limit,
        "key": YOUTUBE_API_KEY, "videoCategoryId": "10",  # Music category
    }
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.get(YOUTUBE_SEARCH_URL, params=params)
        if r.status_code != 200:
            return []
        data = r.json()
    results = []
    for item in data.get("items", []):
        vid = item.get("id", {}).get("videoId")
        if not vid:
            continue
        sn = item.get("snippet", {})
        results.append({
            "video_id": vid,
            "title": sn.get("title"),
            "channel": sn.get("channelTitle"),
            "thumbnail": (sn.get("thumbnails", {}).get("high") or sn.get("thumbnails", {}).get("default") or {}).get("url"),
            "embed_url": f"https://www.youtube.com/embed/{vid}",
        })
    return results


async def itunes_charts(genre_id: Optional[int] = None, limit: int = 25) -> List[dict]:
    """Real Apple Top Songs chart -- classic iTunes RSS API (free, no
    key), optionally scoped to a genre. Powers the no-search-needed
    Trending/genre browse rows, same role TMDB's /trending plays for
    movies."""
    url = (ITUNES_CHARTS_GENRE_URL.format(limit=limit, genre_id=genre_id)
           if genre_id else ITUNES_CHARTS_URL.format(limit=limit))
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.get(url)
        if r.status_code != 200:
            return []
        data = r.json()

    results = []
    for e in data.get("feed", {}).get("entry", []):
        images = e.get("im:image", [])
        artwork = images[-1]["label"] if images else None
        # 170x170 is the biggest the RSS feed itself offers; upgrade it
        # the same way search results are upgraded.
        artwork = _upgrade_artwork(artwork) if artwork else None
        results.append({
            "title": e.get("im:name", {}).get("label", "Untitled"),
            "artist": e.get("im:artist", {}).get("label", ""),
            "collection": e.get("im:collection", {}).get("im:name", {}).get("label", ""),
            "artwork": artwork,
        })
    return results


async def itunes_search_grouped(term: str, limit: int = 12) -> dict:
    """Real categorization: parallel iTunes searches by entity, grouped
    into {songs, albums, artists} instead of one flat list."""
    import asyncio as _asyncio
    songs, albums, artists = await _asyncio.gather(
        itunes_search(term, media="music", entity="song", limit=limit),
        itunes_search(term, media="music", entity="album", limit=limit),
        itunes_search(term, media="music", entity="musicArtist", limit=limit),
    )
    return {"songs": songs, "albums": albums, "artists": artists}


async def resolve_full_track(title: str, artist: str = "") -> Optional[dict]:
    """Unified 'smart play': tries real full-length sources (musify.club,
    then Jamendo) before the caller falls back to a 30s iTunes preview.
    Returns {"source": ..., "stream_url": ...} or None if nothing found.
    This is what makes clicking a search result play the actual track
    instead of a preview whenever a real match exists."""
    from .musify import musify_best_match, musify_resolve_path
    from .jamendo import jamendo_configured, jamendo_search

    match = await musify_best_match(title, artist)
    if match:
        stream_url = await musify_resolve_path(match["mp3_path"])
        if stream_url:
            return {"source": "musify.club", "stream_url": stream_url}

    if jamendo_configured():
        query = f"{artist} {title}".strip()
        target = re.sub(r"[^a-z0-9]", "", title.lower())
        jam_results = await jamendo_search(query, limit=3)
        for j in jam_results:
            if j.get("audio_url") and target in re.sub(r"[^a-z0-9]", "", j["title"].lower()):
                return {"source": "jamendo", "stream_url": j["audio_url"]}

    return None
