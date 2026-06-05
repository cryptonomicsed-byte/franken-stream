import pytest
import httpx
from franken_stream.vantage_client import VantageClient
from unittest.mock import AsyncMock, patch, MagicMock

@pytest.mark.asyncio
async def test_vantage_client_get_feed_success():
    client = VantageClient(base_url="http://test")
    
    mock_resp = MagicMock()
    mock_resp.json.return_value = [{"id": "1", "agent_name": "test_agent", "title": "Test Broadcast"}]
    mock_resp.raise_for_status = MagicMock()
    
    # httpx.AsyncClient.get is a coroutine
    with patch.object(httpx.AsyncClient, 'get', new_callable=AsyncMock) as mock_get:
        mock_get.return_value = mock_resp
        feed = await client.get_feed()
        assert len(feed) == 1
        assert feed[0]["agent_name"] == "test_agent"

@pytest.mark.asyncio
async def test_vantage_client_get_feed_failure():
    client = VantageClient(base_url="http://test")
    
    with patch.object(httpx.AsyncClient, 'get', new_callable=AsyncMock) as mock_get:
        mock_get.side_effect = httpx.RequestError("offline")
        feed = await client.get_feed()
        assert feed == []

@pytest.mark.asyncio
async def test_vantage_client_get_broadcast_stream_url():
    client = VantageClient(base_url="http://localhost:8001")
    url = await client.get_broadcast_stream_url("123")
    assert url == "http://localhost:8001/api/agents/stream/123/index.m3u8"
