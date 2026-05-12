#!/usr/bin/env python3
# Generated Configuration Management Module for Electric Vehicle Types Information Agent

import os
import json
import logging
from dotenv import load_dotenv
from typing import Dict, Any, List, Tuple, Optional

# Load .env FIRST
load_dotenv()

logger = logging.getLogger(__name__)

class Config:
    # Internal KV cache
    _kv_secrets: Dict[str, Any] = {}

    # Map of (config_attr, secret_ref) for Key Vault secrets
    # This must reflect platform reference entries relevant to the agent
    KEY_VAULT_SECRET_MAP: List[Tuple[str, str]] = [
        # LLM Keys
        ("AZURE_OPENAI_API_KEY", "openai-secrets.gpt-4.1"),
        ("AZURE_OPENAI_API_KEY", "openai-secrets.azure-key"),
        ("OPENAI_API_KEY", "aba-openai-secret.openai_api_key"),

        # Azure Content Safety
        ("AZURE_CONTENT_SAFETY_ENDPOINT", "azure-content-safety-secrets.azure_content_safety_endpoint"),
        ("AZURE_CONTENT_SAFETY_KEY", "azure-content-safety-secrets.azure_content_safety_key"),

        # Azure AI Search
        ("AZURE_SEARCH_API_KEY", "azure-search-secret.azure_search_api_key"),
        ("AZURE_SEARCH_SERVICE_ENDPOINT", "azure-search-secret.azure_search_service_endpoint"),
        ("AZURE_SEARCH_INDEX_NAME", "azure-search-secret.azure_search_index_name"),

        # Observability Azure SQL (AgentOps)
        ("OBS_AZURE_SQL_SERVER", "agentops-secrets.obs_sql_endpoint"),
        ("OBS_AZURE_SQL_DATABASE", "agentops-secrets.obs_azure_sql_database"),
        ("OBS_AZURE_SQL_PORT", "agentops-secrets.obs_port"),
        ("OBS_AZURE_SQL_USERNAME", "agentops-secrets.obs_sql_username"),
        ("OBS_AZURE_SQL_PASSWORD", "agentops-secrets.obs_sql_password"),
        ("OBS_AZURE_SQL_SCHEMA", "agentops-secrets.obs_azure_sql_schema"),
        ("OBS_AZURE_SQL_TRUST_SERVER_CERTIFICATE", "agentops-secrets.obs_sql_trust_server_certificate"),
        
        # Agent identity
        # These may be provided via Key Vault as well; if not, fall back to .env
        ("AGENT_NAME", "agent-secrets.agent_name"),
        ("AGENT_ID", "agent-secrets.agent_id"),
        ("PROJECT_NAME", "agent-secrets.project_name"),
        ("PROJECT_ID", "agent-secrets.project_id"),
        ("SERVICE_NAME", "agent-secrets.service_name"),
        ("SERVICE_VERSION", "agent-secrets.service_version"),
    ]

    # Placeholder for constants used by agent observability and LLM logic
    _ORM_DEFAULTS = {
        "ENVIRONMENT": "",  # To be loaded from KV /.env
        "AGENT_NAME": "",
        "AGENT_ID": "",
        "PROJECT_NAME": "",
        "PROJECT_ID": "",
        "SERVICE_NAME": "",
        "SERVICE_VERSION": "",
    }

    # Basic LLM configuration
    LLM_MODEL: str = ""
    LLM_TEMPERATURE: Any = ""
    LLM_MAX_TOKENS: Any = ""

    MODEL_PROVIDER: str = ""  # e.g., "openai", "azure", "anthropic", "google"
    AZURE_OPENAI_ENDPOINT: str = ""
    AZURE_OPENAI_EMBEDDING_DEPLOYMENT: str = "text-embedding-ada-002"

    # API Keys (fallbacks if Key Vault not used)
    OPENAI_API_KEY: str = ""
    AZURE_OPENAI_API_KEY: str = ""
    ANTHROPIC_API_KEY: str = ""
    GOOGLE_API_KEY: str = ""
    GITHUB_API_KEY: str = ""
    DOCUMENT_KB_SUBSCRIPTION: str = ""
    DOCUMENT_KB_STORAGE_ACCOUNT: str = ""
    DOCUMENT_KB_CONTAINER_NAME: str = ""

    # Azure Content Safety (redundant keys; kept for completeness)
    AZURE_CONTENT_SAFETY_ENDPOINT: str = ""
    AZURE_CONTENT_SAFETY_KEY: str = ""

    # Azure Search (for knowledge retrieval)
    AZURE_SEARCH_ENDPOINT: str = ""
    AZURE_SEARCH_API_KEY: str = ""
    AZURE_SEARCH_INDEX_NAME: str = ""

    # Environment and identity / observability DB
    ENVIRONMENT: str = ""
    AGENT_NAME: str = ""
    AGENT_ID: str = ""
    PROJECT_NAME: str = ""
    PROJECT_ID: str = ""
    OBS_DATABASE_TYPE: str = "azure_sql"
    OBS_AZURE_SQL_SERVER: str = ""
    OBS_AZURE_SQL_DATABASE: str = ""
    OBS_AZURE_SQL_PORT: str = "1433"
    OBS_AZURE_SQL_USERNAME: str = ""
    OBS_AZURE_SQL_PASSWORD: str = ""
    OBS_AZURE_SQL_SCHEMA: str = "dbo"
    OBS_AZURE_SQL_TRUST_SERVER_CERTIFICATE: str = "yes"

    # Azure Key Vault related settings
    USE_KEY_VAULT: bool = False
    KEY_VAULT_URI: str = ""
    AZURE_USE_DEFAULT_CREDENTIAL: bool = True

    # Local environment configuration
    ENV_FILE_VARIABLES_LOADED: bool = False

    # Tooling / validation
    VALIDATION_CONFIG_PATH: str = ""

    # Runtime guardrails (defaults can be overridden by Key Vault / env)
    # (kept minimal here; actual guardrails are in separate modules)
    # Optional: expose a SHORTSET of commonly used env values
    PRIMARY_ADMIN_KEY: str = ""

    # IMPORTANT: expose a settings-like instance at module level for backward compatibility
    pass

    @classmethod
    def _load_keyvault_secrets(cls) -> None:
        """Populate cls._kv_secrets by talking to Azure Key Vault secrets.

        This function is intentionally resilient: failures do not
        crash startup; missing secrets are left as absent in the map.
        """
        if not cls.USE_KEY_VAULT:
            return
        if not cls.KEY_VAULT_URI:
            logger.warning("Key Vault URI not configured; skipping Key Vault secret load.")
            return

        try:
            # Lazy import to avoid hard dependency at import time
            from azure.identity import DefaultAzureCredential
            from azure.keyvault.secrets import SecretClient
            if cls.AZURE_USE_DEFAULT_CREDENTIAL:
                credential = DefaultAzureCredential()
            else:
                # Service principal flow
                tenant_id = os.getenv("AZURE_TENANT_ID", "")
                client_id = os.getenv("AZURE_CLIENT_ID", "")
                client_secret = os.getenv("AZURE_CLIENT_SECRET", "")
                if not (tenant_id and client_id and client_secret):
                    logger.warning("Azure SP credentials incomplete; cannot access Key Vault.")
                    return
                from azure.identity import ClientSecretCredential
                credential = ClientSecretCredential(
                    tenant_id=tenant_id,
                    client_id=client_id,
                    client_secret=client_secret,
                )
            client = SecretClient(vault_url=cls.KEY_VAULT_URI, credential=credential)

            # Group secrets by secret name to minimize trips
            grouped: Dict[str, List[Tuple[str, Optional[str]]]] = {}
            for var_name, secret_ref in cls.KEY_VAULT_SECRET_MAP:
                grouped.setdefault(secret_ref, []).append((var_name, None))

            for secret_name, refs in grouped.items():
                try:
                    secret = client.get_secret(secret_name)
                    if not secret or secret.value is None:
                        logger.debug("Key Vault secret '%s' is missing or empty.", secret_name)
                        continue
                    raw = secret.value
                    # BOM-stripping
                    if raw and raw[0] in ("\ufeff", "\ufeff"):
                        raw = raw.lstrip("\ufeff")
                    # Try JSON parsing if multiple refs exist for this secret
                    try:
                        payload = json.loads(raw)
                        if isinstance(payload, dict):
                            for (field, _), in_keys in zip(refs, refs):
                                if field in payload:
                                    cls._kv_secrets[field] = str(payload[field])
                            continue
                    except Exception:
                        pass
                    # Plain string value – assign to all refs that point to this secret
                    for field_name, _ in refs:
                        cls._kv_secrets[field_name] = str(raw)
                        logger.debug("Key Vault: loaded %s from secret '%s' (plain value)", field_name, secret_name)
                except Exception as ex:
                    logger.debug("Key Vault: failed to fetch secret '%s': %s", secret_name, ex)

        except Exception as e:
            logger.debug("Key Vault: failed to initialise client: %s", e)

    @classmethod
    def _initialize_config(cls) -> None:
        """Module-level config initialisation with priority KV > .env.

        - Load USE_KEY_VAULT and KEY_VAULT_URI from environment
        - If USE_KEY_VAULT: load KV secrets
        - For each variable: KV > .env; if missing: log warning and set to ""
        - Special-case: numeric port values
        - Convert numeric values where appropriate
        - Expose attributes on the Config class
        """
        # 1) Key Vault controls
        USE_KEY_VAULT = os.getenv("USE_KEY_VAULT", "").lower() in ("true", "1", "yes")
        KEY_VAULT_URI = os.getenv("KEY_VAULT_URI", "")
        AZURE_USE_DEFAULT_CREDENTIAL = os.getenv("AZURE_USE_DEFAULT_CREDENTIAL", "").lower() in ("true", "1", "yes")

        cls = Config
        cls.USE_KEY_VAULT = USE_KEY_VAULT
        cls.KEY_VAULT_URI = KEY_VAULT_URI
        cls.AZURE_USE_DEFAULT_CREDENTIAL = AZURE_USE_DEFAULT_CREDENTIAL

        if USE_KEY_VAULT:
            cls._load_keyvault_secrets()

        # 2) Variables to load (subset relevant to agent)
        CONFIG_VARS: List[str] = [
            # Environment / identity
            "ENVIRONMENT",
            "AGENT_NAME",
            "AGENT_ID",
            "PROJECT_NAME",
            "PROJECT_ID",
            "SERVICE_NAME",
            "SERVICE_VERSION",
            # LLM / Model
            "MODEL_PROVIDER",  # provider label (openai/azure/anthropic/google)
            "LLM_MODEL",
            "LLM_TEMPERATURE",
            "LLM_MAX_TOKENS",
            "AZURE_OPENAI_ENDPOINT",
            "AZURE_OPENAI_EMBEDDING_DEPLOYMENT",
            "AZURE_OPENAI_API_KEY",
            "OPENAI_API_KEY",
            "ANTHROPIC_API_KEY",
            "GOOGLE_API_KEY",
            "GITHUB_API_KEY",
            # Azure Search
            "AZURE_SEARCH_ENDPOINT",
            "AZURE_SEARCH_API_KEY",
            "AZURE_SEARCH_INDEX_NAME",
            # Azure Content Safety
            "AZURE_CONTENT_SAFETY_ENDPOINT",
            "AZURE_CONTENT_SAFETY_KEY",
            # Observability / Azure SQL (AgentOps)
            "OBS_AZURE_SQL_SERVER",
            "OBS_AZURE_SQL_DATABASE",
            "OBS_AZURE_SQL_PORT",
            "OBS_AZURE_SQL_USERNAME",
            "OBS_AZURE_SQL_PASSWORD",
            "OBS_AZURE_SQL_SCHEMA",
            "OBS_AZURE_SQL_TRUST_SERVER_CERTIFICATE",
        ]

        # 3) Load each var with priority KV > .env; special-case Azure Search vars
        AZURE_SEARCH_VARS = {"AZURE_SEARCH_ENDPOINT", "AZURE_SEARCH_API_KEY", "AZURE_SEARCH_INDEX_NAME"}
        AZURE_SP_VARS = {"AZURE_TENANT_ID", "AZURE_CLIENT_ID", "AZURE_CLIENT_SECRET"}

        for var in CONFIG_VARS:
            # Special: skip Service Principal vars if using DefaultAzureCredential
            if var in AZURE_SP_VARS and AZURE_USE_DEFAULT_CREDENTIAL:
                setattr(cls, var, "")
                continue

            value = None
            # Azure AI Search vars ALWAYS from .env (not Key Vault)
            if var in AZURE_SEARCH_VARS:
                value = os.getenv(var, "")
            else:
                # KV first if enabled
                if USE_KEY_VAULT:
                    value = cls._kv_secrets.get(var, "")
                if not value:
                    value = os.getenv(var, "")

            if var == "OBS_AZURE_SQL_PORT" and value != "":
                try:
                    value = int(value)
                except ValueError:
                    logger.warning("Invalid integer for %s: %s", var, value)
                    value = ""

            if not value:
                # Critical — warn about missing but do not inject defaults
                logger.warning(f"Configuration variable {var} not found in .env file")
                value = ""

            setattr(cls, var, value)

        # 4) Normalise some defaults / backward compatibility
        if not getattr(cls, "ENVIRONMENT", ""):
            setattr(cls, "ENVIRONMENT", "")

        # 5) Expose a settings-like instance at module level for observability
        # (module-level assignment occurs at bottom)

    @classmethod
    def _validate_api_keys(cls) -> None:
        """Validate required API keys based on the chosen MODEL_PROVIDER.

        Raises ValueError if a required key is missing for the selected provider.
        """
        provider = (cls.MODEL_PROVIDER or "").lower()
        if provider == "openai":
            if not cls.OPENAI_API_KEY and not cls.AZURE_OPENAI_API_KEY:
                raise ValueError("Missing API key for OpenAI provider (OPENAI_API_KEY or AZURE_OPENAI_API_KEY).")
        elif provider == "azure":
            if not cls.AZURE_OPENAI_API_KEY:
                raise ValueError("Missing AZURE_OPENAI_API_KEY for Azure OpenAI provider.")
        elif provider == "anthropic":
            if not cls.ANTHROPIC_API_KEY:
                raise ValueError("Missing ANTHROPIC_API_KEY for Anthropic provider.")
        elif provider == "google":
            if not cls.GOOGLE_API_KEY:
                raise ValueError("Missing GOOGLE_API_KEY for Google provider.")
        else:
            # Unknown provider; do not fail startup quietly
            if provider:
                raise ValueError(f"Unsupported LLM provider: {provider}")

    @classmethod
    def validate(cls) -> None:
        """Public validation entrypoint. Raises if config invalid."""
        cls._initialize_config()  # ensure latest values
        cls._validate_api_keys()

    @classmethod
    def get_llm_kwargs(cls) -> Dict[str, Any]:
        """Return LLM keyword args compatible with chat.completions.create().

        - If model is in UNSUPPORTED lists, omit temperature/max_tokens accordingly.
        - Otherwise provide both temperature and max_tokens.
        """
        kwargs: Dict[str, Any] = {}

        model_lower = (cls.LLM_MODEL or "").lower()

        _MAX_TOKENS_UNSUPPORTED = {
            "gpt-5", "gpt-5-mini", "gpt-5-nano", "gpt-5.1-chat",
            "o1", "o1-mini", "o1-preview", "o3", "o3-mini", "o3-pro", "o4-mini",
        }
        _TEMPERATURE_UNSUPPORTED = {
            "gpt-5", "gpt-5-mini", "gpt-5-nano", "gpt-5.1-chat",
            "o1", "o1-mini", "o1-preview", "o3", "o3-mini", "o3-pro", "o4-mini",
        }

        if cls.LLM_TEMPERATURE != "" and not any(model_lower.startswith(m) for m in _TEMPERATURE_UNSUPPORTED):
            try:
                kwargs["temperature"] = float(cls.LLM_TEMPERATURE)
            except Exception:
                logger.warning("Invalid LLM_TEMPERATURE value: %r", cls.LLM_TEMPERATURE)

        # Choose max tokens field based on model support
        if cls.LLM_MAX_TOKENS != "" and any(model_lower.startswith(m) for m in _MAX_TOKENS_UNSUPPORTED):
            try:
                kwargs["max_completion_tokens"] = int(cls.LLM_MAX_TOKENS)
            except Exception:
                logger.warning("Invalid LLM_MAX_TOKENS value: %r", cls.LLM_MAX_TOKENS)
        else:
            if cls.LLM_MAX_TOKENS != "":
                try:
                    kwargs["max_tokens"] = int(cls.LLM_MAX_TOKENS)
                except Exception:
                    logger.warning("Invalid LLM_MAX_TOKENS value: %r", cls.LLM_MAX_TOKENS)

        return kwargs

# Initialize config on import
Config._initialize_config()

# Public backward-compatible settings object
class _SettingsWrapper(Config):  # pragma: no cover - tiny helper for compat
    pass

settings = _SettingsWrapper()
# Ensure the settings instance mirrors the initial class attributes
for _k, _v in Config.__dict__.items():
    if not _k.startswith("_") and not callable(_v):
        setattr(settings, _k, _v)

# Ensure required attributes exist for agent code paths
for required_attr in [
    "ENVIRONMENT",
    "AGENT_NAME",
    "PROJECT_NAME",
    "MODEL_PROVIDER",
    "LLM_MODEL",
    "LLM_TEMPERATURE",
    "LLM_MAX_TOKENS",
    "AZURE_OPENAI_API_KEY",
    "OPENAI_API_KEY",
    "AZURE_SEARCH_ENDPOINT",
    "AZURE_SEARCH_API_KEY",
    "AZURE_SEARCH_INDEX_NAME",
    "AZURE_CONTENT_SAFETY_ENDPOINT",
    "AZURE_CONTENT_SAFETY_KEY",
    "OBS_AZURE_SQL_SERVER",
    "OBS_AZURE_SQL_DATABASE",
    "OBS_AZURE_SQL_PORT",
    "OBS_AZURE_SQL_USERNAME",
    "OBS_AZURE_SQL_PASSWORD",
    "OBS_AZURE_SQL_SCHEMA",
    "OBS_AZURE_SQL_TRUST_SERVER_CERTIFICATE",
]:
    if not hasattr(settings, required_attr):
        setattr(settings, required_attr, "")

# END OF CONFIG
