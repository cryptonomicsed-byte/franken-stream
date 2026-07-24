"""Internet Archive (archive.org) provider — 25k+ public-domain films."""

import re
from typing import List, Optional

import aiohttp

from .base import MediaItem, ProviderPlugin


class InternetArchiveProvider(ProviderPlugin):
    name = "internet_archive"
    base_url = "https://archive.org"
    legal = True
    requires_js = False

    # Public search API — no key required
    SEARCH_URL = (
        "https://archive.org/advancedsearch.php"
        "?q={query}+AND+mediatype:(movies)&fl[]=identifier,title,year,description"
        "&rows=20&page=1&output=json"
    )
    DETAILS_URL = "https://archive.org/details/{identifier}"
    EMBED_URL = "https://archive.org/embed/{identifier}"

    async def search(self, query: str, media_type: str = "any") -> List[MediaItem]:
        if media_type == "tv":
            return []  # IA is mostly movies/documentaries

        url = self.SEARCH_URL.format(query=query.replace(" ", "+"))
        try:
            async with aiohttp.ClientSession() as s:
                async with s.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                    if resp.status != 200:
                        return []
                    data = await resp.json(content_type=None)

            docs = data.get("response", {}).get("docs", [])
            results = []
            query_words: List[str] = [w.lower() for w in query.split()]
            
            for doc in docs:
                ident = doc.get("identifier", "")
                title = doc.get("title", ident)
                title_lower = title.lower()
                
                # Relevance filter: title must contain all significant query words
                if not all(w in title_lower for w in query_words if len(w) > 3):
                    continue
                    
                year = self._parse_year(str(doc.get("year", "")))
                if not ident:
                    continue
                results.append(
                    MediaItem(
                        id=f"archive:{ident}",
                        title=title,
                        url=self.DETAILS_URL.format(identifier=ident),
                        provider=self.name,
                        year=year,
                        media_type="movie",
                        quality="varies",
                    )
                )
            return results
        except Exception:
            return []

    async def extract_embed(self, page_url: str) -> Optional[str]:
        """Return the archive.org embed player URL."""
        m = re.search(r"archive\.org/details/([^/?#]+)", page_url)
        if m:
            return self.EMBED_URL.format(identifier=m.group(1))
        return None

    @staticmethod
    def _parse_year(s: str) -> Optional[int]:
        m = re.search(r"\b(19|20)\d{2}\b", s)
        return int(m.group(0)) if m else None
