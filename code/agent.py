import asyncio as _asyncio
GUARDRAILS_CONFIG = {'check_credentials_output': True,
 'check_jailbreak': True,
 'check_output': True,
 'check_pii_input': True,
 'check_toxic_code_output': True,
 'check_toxicity': True,
 'content_safety_enabled': True,
 'content_safety_severity_threshold': 3,
 'runtime_enabled': True,
 'sanitize_pii': False}



import time as _time
from observability.observability_wrapper import (
    trace_agent, trace_step, trace_step_sync, trace_model_call, trace_tool_call,
)
from config import settings as _obs_settings

import logging
import asyncio
import json
import re as _re
import copy
from typing import List, Optional, Dict, Any
from pathlib import Path

# Observability helpers for startup lifecycle (required by build system)
from observability.instrumentation import initialize_tracer  # type: ignore
from observability.observability_service import get_observability_service  # type: ignore
from observability.database.engine import close_obs_engine  # type: ignore

# Guardrails imports (runtime safety wrappers)
from modules.guardrails import with_content_safety, GuardrailsService, get_guardrails_service, ValidationResult
from modules.guardrails.content_safety_decorator import with_content_safety as _with_content_safety  # type: ignore
from modules.guardrails.content_safety_service import ContentSafetyService, get_content_safety_service  # type: ignore

# Azure/Search and OpenAI
from azure.search.documents import SearchClient
from azure.core.credentials import AzureKeyCredential
from azure.search.documents.models import VectorizedQuery
import openai
from config import Config

# Pydantic (FastAPI v2)
from pydantic import BaseModel, Field
from pydantic.dataclasses import dataclass
from pydantic import model_validator  # type: ignore

# FastAPI and HTTP utilities
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from fastapi.routing import APIRouter
from fastapi.encoders import jsonable_encoder
from fastapi import status
from fastapi.openapi.utils import get_openapi
from starlette.status import HTTP_422_UNPROCESSABLE_ENTITY
from starlette.responses import Response

# LLM and embedding clients (Azure OpenAI)
openai_client_lib_available = True
try:
    import openai  # type: ignore
except Exception:
    openai_client_lib_available = False

# Logging
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# System / internal constants
ENRICHED_FIELDS = ["entities", "keyphrases", "relationships"]
ENRICHED_AVAILABLE: Optional[bool] = None  # None = not yet checked

# Selected documents for exact search filtering
SELECTED_DOCUMENT_TITLES = ["Electric_vehicle_info.pdf"]

# Enriched search fields (optional)
ENRICHED_INDEX_FIELDS = ENRICHED_FIELDS  # keep as a constant for resilience

# Output formatting
OUTPUT_FORMAT = (
    "Respond in clear, well-structured paragraphs. "
    "Use bullet points or lists for enumerating types or features. "
    "Do not include any unsupported or speculative information."
)

# Base system prompt (enhanced)
SYSTEM_PROMPT_BASE = (
    "You are an expert assistant specializing in electric vehicle (EV) technology. "
    "Your task is to provide clear, accurate, and comprehensive information about the different "
    "types of electric vehicles, including their characteristics, how they work, and their benefits. "
    "Use only the information retrieved from the provided knowledge base context. If the answer is not found "
    "in the knowledge base, politely inform the user that the requested information is unavailable. "
    "Structure your response in well-organized paragraphs, using bullet points or lists where appropriate for clarity."
)

SYSTEM_PROMPT = SYSTEM_PROMPT_BASE + "\n\nOutput Format: " + OUTPUT_FORMAT

# Full system prompt will be sent to the LLM with the appended output format
FULL_SYSTEM_PROMPT = SYSTEM_PROMPT  # for clarity

# Fallback
FALLBACK_RESPONSE = "I'm sorry, I could not find information about electric vehicle types in the available knowledge base."

# Validation config path
VALIDATION_CONFIG_PATH = getattr(Config, "VALIDATION_CONFIG_PATH", str(Path(__file__).parent / "validation_config.json"))


# -----------------------------
# Sanitization utilities (provided in prompt)
# -----------------------------

_FENCE_RE = _re.compile(r"```(?:\w+)?\s*\n(.*?)```", _re.DOTALL)
_LONE_FENCE_START_RE = _re.compile(r"^```\w*$")
_WRAPPER_RE = _re.compile(
    r"^(?:"
    r"Here(?:'s| is)(?: the)? (?:the |your |a )?(?:code|solution|implementation|result|explanation|answer)[^:]*:\s*"
    r"|Sure[!,.]?\s*"
    r"|Certainly[!,.]?\s*"
    r"|Below is [^:]*:\s*"
    r")",
    _re.IGNORECASE,
)
_SIGNOFF_RE = _re.compile(
    r"^(?:Let me know|Feel free|Hope this|This code|Note:|Happy coding|If you)",
    _re.IGNORECASE,
)
_BLANK_COLLAPSE_RE = _re.compile(r"\n{3,}")


def _strip_fences(text: str, content_type: str) -> str:
    """Extract content from Markdown code fences."""
    fence_matches = _FENCE_RE.findall(text)
    if fence_matches:
        if content_type == "code":
            return "\n\n".join(block.strip() for block in fence_matches)
        for match in fence_matches:
            fenced_block = _FENCE_RE.search(text)
            if fenced_block:
                text = text[:fenced_block.start()] + match.strip() + text[fenced_block.end():]
        return text
    lines = text.splitlines()
    if lines and _LONE_FENCE_START_RE.match(lines[0].strip()):
        lines = lines[1:]
    if lines and lines[-1].strip() == "```":
        lines = lines[:-1]
    return "\n".join(lines).strip()


def _strip_trailing_signoffs(text: str) -> str:
    """Remove conversational sign-off lines from the end of code output."""
    lines = text.splitlines()
    while lines and _SIGNOFF_RE.match(lines[-1].strip()):
        lines.pop()
    return "\n".join(lines).rstrip()


@with_content_safety(config=GUARDRAILS_CONFIG)
def sanitize_llm_output(raw: str, content_type: str = "code") -> str:
    """
    Generic post-processor that cleans common LLM output artefacts.
    Args:
        raw: Raw text returned by the LLM.
        content_type: 'code' | 'text' | 'markdown'.
    Returns:
        Cleaned string ready for validation, formatting, or direct return.
    """
    if not raw:
        return ""
    text = _strip_fences(raw.strip(), content_type)
    text = _WRAPPER_RE.sub("", text, count=1).strip()
    if content_type == "code":
        text = _strip_trailing_signoffs(text)
    return _BLANK_COLLAPSE_RE.sub("\n\n", text).strip()


# -----------------------------
# FastAPI models
# -----------------------------
class QueryRequest(BaseModel):
    query: str = Field(..., description="User question regarding EV types")

    @model_validator(mode="after")
    def validate_content(self):
        if not self.query or not self.query.strip():
            raise ValueError("Query must be non-empty.")
        self.query = self.query.strip()
        return self


class QueryResponse(BaseModel):
    success: bool = True
    answer: Optional[str] = None
    tool_calls_made: Optional[List[str]] = None
    error: Optional[str] = None


# -----------------------------
# Retrieval Layer: Azure AI Search integration
# -----------------------------
class AzureAISearchClient:
    """Performs vector + keyword search against Azure AI Search for RAG."""

    def __init__(self):
        self._client: Optional[SearchClient] = None
        self._enriched_available: Optional[bool] = None
        self._logger = logger

        # Prepare the search client lazily
        self._init_client()

    def _init_client(self):
        try:
            endpoint = getattr(Config, "AZURE_SEARCH_ENDPOINT", None) or Config.AZURE_SEARCH_ENDPOINT
            api_key = getattr(Config, "AZURE_SEARCH_API_KEY", None) or Config.AZURE_SEARCH_API_KEY
            index_name = getattr(Config, "AZURE_SEARCH_INDEX_NAME", None) or Config.AZURE_SEARCH_INDEX_NAME
            if not endpoint or not api_key or not index_name:
                raise ValueError("Azure Search credentials are not fully configured.")
            self._client = SearchClient(
                endpoint=endpoint,
                index_name=index_name,
                credential=AzureKeyCredential(api_key),
            )
            self._logger.info("Azure Search client initialised for index: %s", index_name)
        except Exception as e:
            self._logger.error("Failed to initialise Azure Search client: %s", e)
            self._client = None

    async def _embed_system_prompt(self) -> List[float]:
        """Compute an embedding for the system prompt using Azure OpenAI embedding deployment."""
        # Lazy create embedding client
        embedding_deployment = getattr(Config, "AZURE_OPENAI_EMBEDDING_DEPLOYMENT", "text-embedding-ada-002")
        client = await self._get_llm_embedding_client()
        # Use FULL SYSTEM_PROMPT as the embedding input
        resp = await client.embeddings.create(input=FULL_SYSTEM_PROMPT, model=embedding_deployment)
        return resp.data[0].embedding

    async def _get_llm_embedding_client(self):
        if not openai_client_lib_available:
            raise RuntimeError("OpenAI Python client is not available.")
        api_key = getattr(Config, "AZURE_OPENAI_API_KEY", None) or Config.AZURE_OPENAI_API_KEY
        if not api_key:
            raise ValueError("AZURE_OPENAI_API_KEY is not configured.")
        return openai.AsyncAzureOpenAI(
            api_key=api_key,
            api_version="2024-02-01",
            azure_endpoint=getattr(Config, "AZURE_OPENAI_ENDPOINT", None) or Config.AZURE_OPENAI_ENDPOINT,
        )

    async def _search_with_fallback(self, query: str, embedding: List[float], selected_titles: List[str], top_k: int):
        """Try enriched fields first; fall back to base fields if index lacks them."""
        global _enriched_available
        from azure.core.exceptions import HttpResponseError

        vector_query = VectorizedQuery(vector=embedding, k_nearest_neighbors=top_k, fields="vector")
        base_fields = ["chunk", "title"]
        _enriched_available = ENRICHED_AVAILABLE

        if _enriched_available is False:
            select_fields = base_fields
        else:
            select_fields = base_fields + ENRICHED_FIELDS if ENRICHED_FIELDS else base_fields

        search_kwargs = {
            "search_text": query,
            "vector_queries": [vector_query],
            "top": top_k,
            "select": select_fields,
        }
        if selected_titles:
            odata_parts = [f"title eq '{t}'" for t in selected_titles]
            search_kwargs["filter"] = " or ".join(odata_parts)

        try:
            results = list(self._client.search(**search_kwargs))
            if _enriched_available is None:
                _enriched_available = True
                logger.info("Enriched index fields are AVAILABLE — using: %s", ENRICHED_FIELDS)
            return results
        except HttpResponseError as e:
            # Field not found in enriched index — fallback
            if "Could not find a property named" in str(e) and _enriched_available is not False:
                _enriched_available = False
                logger.warning("Enriched index fields NOT available in this index — falling back to base fields: %s", base_fields)
                search_kwargs["select"] = base_fields
                return list(self._client.search(**search_kwargs))
            raise

    @with_content_safety(config=GUARDRAILS_CONFIG)
    async def retrieve_chunks(self, query: str, filter: str, top_k: int) -> List[str]:
        """Return retrieved chunks (with optional enriched metadata) for a user query."""
        if self._client is None:
            self._init_client()
        if self._client is None:
            logger.error("Azure Search client unavailable.")
            return []

        embedding = await self._embed_system_prompt()
        results = await self._search_with_fallback(query, embedding, SELECTED_DOCUMENT_TITLES, top_k)

        context_chunks: List[str] = []
        for r in results:
            chunk = r.get("chunk", "")
            if not chunk:
                continue
            if ENRICHED_FIELDS and (self._enriched_available is True or self._enriched_available is None):
                # Append enriched metadata if available
                enriched_parts = []
                for field in ENRICHED_FIELDS:
                    value = r.get(field)
                    if value:
                        enriched_parts.append(f"{field}: {json.dumps(value) if isinstance(value, (list, dict)) else value}")
                if enriched_parts:
                    chunk = chunk + "\n" + "\n".join(enriched_parts)
            context_chunks.append(chunk)
        return context_chunks

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

# -----------------------------
# LLM Interaction Layer
# -----------------------------
class LLMService:
    """LLM client that calls Azure OpenAI with context chunks and system prompt."""

    def __init__(self):
        self._client = None
        self._logger = logger

    async def _get_llm_client(self):
        if self._client:
            return self._client
        if not openai_client_lib_available:
            raise RuntimeError("OpenAI Python client is not available.")
        api_key = getattr(Config, "AZURE_OPENAI_API_KEY", None) or Config.AZURE_OPENAI_API_KEY
        if not api_key:
            raise ValueError("AZURE_OPENAI_API_KEY is not configured.")
        self._client = openai.AsyncAzureOpenAI(
            api_key=api_key,
            api_version="2024-02-01",
            azure_endpoint=getattr(Config, "AZURE_OPENAI_ENDPOINT", None) or Config.AZURE_OPENAI_ENDPOINT,
        )
        return self._client

    @with_content_safety(config=GUARDRAILS_CONFIG)
    @trace_agent(agent_name=_obs_settings.AGENT_NAME, project_name=_obs_settings.PROJECT_NAME)
    async def generate_response(self, prompt: str, context_chunks: List[str], user_query: str) -> str:
        """Call the LLM with system prompt, user query, and retrieved chunks as context."""
        client = await self._get_llm_client()
        _llm_kwargs = Config.get_llm_kwargs() if hasattr(Config, "get_llm_kwargs") else {}
        # Build messages
        system_msg = FULL_SYSTEM_PROMPT  # includes OUTPUT_FORMAT
        context_text = "\n\n".join(context_chunks) if context_chunks else ""
        user_content = f"Question: {user_query}\n\nContext:\n{context_text}" if context_text else f"Question: {user_query}"
        messages = [
            {"role": "system", "content": system_msg},
            {"role": "user", "content": user_content},
        ]
        _t0 = _time.time()
        response = await client.chat.completions.create(
            model=Config.LLM_MODEL or "gpt-4o",
            messages=messages,
            **_llm_kwargs,
        )
        content = response.choices[0].message.content if response and response.choices else ""
        latency_ms = int((_time.time() - _t0) * 1000)
        # Tracing
        try:
            trace_model_call(
                provider="azure",
                model_name=Config.LLM_MODEL or "gpt-4o",
                prompt_tokens=getattr(getattr(response, "usage", None), "prompt_tokens", 0) or 0,
                completion_tokens=getattr(getattr(response, "usage", None), "completion_tokens", 0) or 0,
                latency_ms=latency_ms,
                model_version=None,
                status="success",
                response_summary=content[:200] if content else "",
            )
        except Exception:
            pass

        cleaned = sanitize_llm_output(content, content_type="text")
        return cleaned if cleaned else FALLBACK_RESPONSE


# -----------------------------
# Response Formatting Layer
# -----------------------------
class ResponseFormatter:
    def format_response(self, raw_response: str) -> str:
        if not raw_response:
            return self.format_fallback()
        return raw_response

    def format_fallback(self) -> str:
        return FALLBACK_RESPONSE


# -----------------------------
# Agent Orchestration Layer
# -----------------------------
class ElectricVehicleTypeAgent:
    """Composed agent implementing retrieval and LLM interaction."""

    def __init__(self):
        self._retriever = AzureAISearchClient()
        self._llm = LLMService()
        self._formatter = ResponseFormatter()
        self._selected_titles = SELECTED_DOCUMENT_TITLES

  # tracing injected by build system; name inferred
    @with_content_safety(config=None)  # apply guardrails at entry
    async def process_query(self, user_query: str) -> str:
        """Main entrypoint for processing a user query end-to-end."""
        # Filtering titles
        filter_clause = " or ".join([f"title eq '{t}'" for t in self._selected_titles]) if self._selected_titles else ""

        # Retrieve chunks from Azure AI Search
        try:
            context_chunks = await self._retriever.retrieve_chunks(
                query=user_query,
                filter=filter_clause,
                top_k=5
            )
        except Exception as e:
            logger.error("Chunk retrieval failed: %s", e, exc_info=True)
            context_chunks = []

        # If no chunks, use fallback text
        if not context_chunks:
            return self._formatter.format_fallback()

        # Build system prompt with format
        prompt = FULL_SYSTEM_PROMPT  # already contains Output Format directive
        llm_response = await self._llm.generate_response(prompt, context_chunks, user_query)

        # Format final response
        final_text = self._formatter.format_response(llm_response)
        return final_text


# -----------------------------
# API Handler (FastAPI)
# -----------------------------
def _health_ok():
    return {"status": "ok"}

# Observability lifespan management for FastAPI
from contextlib import asynccontextmanager
from observability.instrumentation import initialize_tracer as _initialize_tracer  # alias

@asynccontextmanager
async def _obs_lifespan(application):
    """Initialise observability on startup, clean up on shutdown."""
    try:
        _obs_startup_logger.info('')
        _obs_startup_logger.info('========== Agent Configuration Summary ==========')
        _obs_startup_logger.info(f'Environment: {getattr(Config, "ENVIRONMENT", "N/A")}')  # type: ignore
        _obs_startup_logger.info(f'Agent: {getattr(Config, "AGENT_NAME", "N/A")}')  # type: ignore
        _obs_startup_logger.info(f'Project: {getattr(Config, "PROJECT_NAME", "N/A")}')  # type: ignore
        _obs_startup_logger.info(f'LLM Provider: {getattr(Config, "MODEL_PROVIDER", "N/A")}')  # type: ignore
        _obs_startup_logger.info(f'LLM Model: {getattr(Config, "LLM_MODEL", "N/A")}')  # type: ignore
        _cs_endpoint = getattr(Config, "AZURE_CONTENT_SAFETY_ENDPOINT", None)
        _cs_key = getattr(Config, "AZURE_CONTENT_SAFETY_KEY", None)
        if _cs_endpoint and _cs_key:
            _obs_startup_logger.info('Content Safety: Enabled (Azure Content Safety)')
            _obs_startup_logger.info(f'Content Safety Endpoint: {_cs_endpoint}')
        else:
            _obs_startup_logger.info('Content Safety: Not Configured')
        _obs_startup_logger.info('Observability Database: Azure SQL')
        _obs_startup_logger.info(f'Database Server: {getattr(Config, "OBS_AZURE_SQL_SERVER", "N/A")}')  # type: ignore
        _obs_startup_logger.info(f'Database Name: {getattr(Config, "OBS_AZURE_SQL_DATABASE", "N/A")}')  # type: ignore
        _obs_startup_logger.info('===============================================')  # type: ignore
        _obs_startup_logger.info('')
    except Exception as _e:
        _obs_startup_logger.warning('Config summary failed: %s', _e)

    _obs_startup_logger.info('')
    _obs_startup_logger.info('========== Content Safety & Guardrails ==========')
    try:
        _obs_startup_logger.info('Content Safety: Enabled (default configured)')
    except Exception as _e:
        _obs_startup_logger.warning('Guardrails config load failed: %s', _e)
    _obs_startup_logger.info('===============================================')
    _obs_startup_logger.info('')

    _obs_startup_logger.info('========== Initializing Agent Services ==========')
    try:
        from observability.database.engine import create_obs_database_engine
        from observability.database.base import ObsBase
        import observability.database.models  # noqa: F401
        _obs_engine = create_obs_database_engine()
        ObsBase.metadata.create_all(bind=_obs_engine, checkfirst=True)
        _obs_startup_logger.info('✓ Observability database connected')
    except Exception as _e:
        _obs_startup_logger.warning('✗ Observability database connection failed (metrics will not be saved)')
    try:
        _t = initialize_tracer()
        if _t is not None:
            _obs_startup_logger.info('✓ Telemetry monitoring enabled')
        else:
            _obs_startup_logger.warning('✗ Telemetry monitoring disabled')
    except Exception:
        _obs_startup_logger.warning('✗ Telemetry monitoring failed to initialize')
    _obs_startup_logger.info('=================================================')
    _obs_startup_logger.info('')
    yield
    # Cleanup on shutdown
    try:
        await close_obs_engine()
    except Exception:
        pass


# Setup FastAPI app
from fastapi import FastAPI

# Observability startup loggers
_obs_startup_logger = logging.getLogger("_obs_startup")

app = FastAPI(
    title="Electric Vehicle Types Info Agent",
    description="RAG-based EV type information agent using Azure AI Search and OpenAI",
    version=getattr(Config, "SERVICE_VERSION", "1.0.0") if hasattr(Config, "SERVICE_VERSION") else "1.0.0",
    lifespan=_obs_lifespan  # type: ignore
)

# Shared agent instance
_agent = ElectricVehicleTypeAgent()

# Health endpoint (must appear before main endpoint)
@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "ok"}

# Endpoint
@app.post("/query", response_model=QueryResponse)
@with_content_safety
async def query_endpoint(req: QueryRequest) -> QueryResponse:
    """Public API endpoint to process user query and return EV type information."""
    if not hasattr(_agent, "process_query"):
        return QueryResponse(success=False, error="Agent not initialized.")
    try:
        answer = await _agent.process_query(req.query)
        return QueryResponse(success=True, answer=answer, tool_calls_made=None)
    except RequestValidationError as ve:
        # Validation error
        return QueryResponse(success=False, error=str(ve))
    except Exception as e:
        logger.error("Query processing failed: %s", e, exc_info=True)
        return QueryResponse(success=False, error=str(e))

# JSON error handling
@app.exception_handler(RequestValidationError)
@with_content_safety(config=GUARDRAILS_CONFIG)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    return JSONResponse(
        status_code=HTTP_422_UNPROCESSABLE_ENTITY,
        content={"success": False, "error": "Invalid request", "details": exc.errors()},
    )

# Obvious JSON parsing error handling
@app.middleware("http")
@with_content_safety(config=GUARDRAILS_CONFIG)
async def json_error_handler(request: Request, call_next):
    try:
        response = await call_next(request)
        return response
    except json.JSONDecodeError as e:
        return JSONResponse(status_code=400, content={"success": False, "error": "Malformed JSON", "details": str(e)})
    except Exception as e:
        # Re-raise for other handlers
        raise

# OpenAPI
def _custom_openapi():
    if app.openapi_schema:
        return app.openapi_schema
    openapi_schema = get_openapi(
        title=app.title,
        version=app.version,
        routes=app.routes,
        description=app.description,
    )
    app.openapi_schema = openapi_schema
    return app.openapi_schema

app.openapi = _custom_openapi  # type: ignore


# -----------------------------
# Main entrypoint
# -----------------------------
async def _run_agent():
    """Entrypoint: runs the agent with observability (trace collection only)."""
    import uvicorn

    # Unified logging config — routes uvicorn, agent, and observability through
    # the same handler so all telemetry appears in a single consistent stream.
    _LOG_CONFIG = {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {
            "default": {
                "()": "uvicorn.logging.DefaultFormatter",
                "fmt": "%(levelprefix)s %(name)s: %(message)s",
                "use_colors": None,
            },
            "access": {
                "()": "uvicorn.logging.AccessFormatter",
                "fmt": '%(levelprefix)s %(client_addr)s - "%(request_line)s" %(status_code)s',
            },
        },
        "handlers": {
            "default": {
                "formatter": "default",
                "class": "logging.StreamHandler",
                "stream": "ext://sys.stderr",
            },
            "access": {
                "formatter": "access",
                "class": "logging.StreamHandler",
                "stream": "ext://sys.stdout",
            },
        },
        "loggers": {
            "uvicorn":        {"handlers": ["default"], "level": "INFO", "propagate": False},
            "uvicorn.error":  {"level": "INFO"},
            "uvicorn.access": {"handlers": ["access"], "level": "INFO", "propagate": False},
            "agent":          {"handlers": ["default"], "level": "INFO", "propagate": False},
            "__main__":       {"handlers": ["default"], "level": "INFO", "propagate": False},
            "observability": {"handlers": ["default"], "level": "INFO", "propagate": False},
            "config": {"handlers": ["default"], "level": "INFO", "propagate": False},
            "azure":   {"handlers": ["default"], "level": "WARNING", "propagate": False},
            "urllib3": {"handlers": ["default"], "level": "WARNING", "propagate": False},
        },
    }

    config = uvicorn.Config(
        "agent:app",
        host="0.0.0.0",
        port=8080,
        reload=False,
        log_level="info",
        log_config=_LOG_CONFIG,
    )
    server = uvicorn.Server(config)
    await server.serve()


if __name__ == "__main__":
    _asyncio.run(_run_agent())