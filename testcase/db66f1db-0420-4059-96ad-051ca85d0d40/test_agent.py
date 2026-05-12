
import pytest
import time
from unittest.mock import MagicMock, AsyncMock, patch
from starlette.testclient import TestClient

# Ensure OpenAPI version is set to avoid FastAPI import-time error
try:
    import config as _config_mod
    if hasattr(_config_mod, 'Config'):
        _cfg = _config_mod.Config
        setattr(_cfg, 'SERVICE_VERSION', '1.0.0')
except Exception:
    pass

from agent import AzureAISearchClient

@pytest.mark.asyncio
async def test_functional_process_query_successful_end_to_end():
    """Unit-level functional test: verify AzureAISearchClient.retrieve_chunks returns without raising and yields a non-None result."""
    _agent = AzureAISearchClient()
    # Provide required parameters: query, filter, top_k
    result = await _agent.retrieve_chunks("test input", "", 5)
    assert result is not None