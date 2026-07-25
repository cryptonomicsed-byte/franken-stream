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
SOUNDCLOUD_OEMBED_URL = "https://soundcloud.com/oembed"
YOUTUBE_API_KEY = os.environ.get("YOUTUBE_API_KEY", "")
YOUTUBE_SEARCH_URL = "https://www.googleapis.com/youtube/v3/search"


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
        results.append({
            "kind": item.get("kind") or item.get("wrapperType"),
            "title": item.get("trackName") or item.get("collectionName", "Untitled"),
            "artist": item.get("artistName", ""),
            "collection": item.get("collectionName", ""),
            "artwork": _upgrade_artwork(item.get("artworkUrl100")),
            "preview_url": item.get("previewUrl"),
            "feed_url": item.get("feedUrl"),
            "track_count": item.get("trackCount"),
            "genre": item.get("primaryGenreName"),
            "view_url": item.get("trackViewUrl") or item.get("collectionViewUrl"),
        })
    return results


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
