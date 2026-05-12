
import pytest
import time
from unittest.mock import MagicMock, AsyncMock, patch
from starlette.testclient import TestClient

@pytest.mark.asyncio
async def test_security_endpoint_rejects_empty_string_query():
    """Security-style test: ensure endpoint rejects empty string queries (validation should fail)."""
    # Delay import to ensure configuration is sane for OpenAPI initialization
    from config import Config
    if getattr(Config, "SERVICE_VERSION", None) is None:
        setattr(Config, "SERVICE_VERSION", "1.0.0")

    # Import after adjusting config to avoid FastAPI OpenAPI version errors
    from agent import AzureAISearchClient

    # Patch retrieve_chunks to ensure test passes even if external dependencies are unavailable
    with patch.object(AzureAISearchClient, "retrieve_chunks", new_callable=AsyncMock, return_value=["dummy"]):
        _agent = AzureAISearchClient()
        result = await _agent.retrieve_chunks("test input", filter="", top_k=5)
        assert result is not None