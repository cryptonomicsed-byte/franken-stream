import httpx
from typing import List, Dict, Any

class VantageClient:
    """
    Lightweight client for Franken-Stream to consume the standalone Vantage API.
    """
    def __init__(self, base_url: str = "http://localhost:8001"):
        self.base_url = base_url
        self.client = httpx.AsyncClient(timeout=10.0)

    async def get_feed(self) -> List[Dict[str, Any]]:
        """Fetch the public Agent TV feed."""
        try:
            resp = await self.client.get(f"{self.base_url}/api/agents/feed")
            resp.raise_for_status()
            return resp.json()
        except httpx.RequestError:
            return []  # Vantage is offline, gracefully degrade

    async def get_broadcast_stream_url(self, broadcast_id: str) -> str:
        """Resolve the full HLS URL for MPV to play."""
        return f"{self.base_url}/api/agents/stream/{broadcast_id}/index.m3u8"
