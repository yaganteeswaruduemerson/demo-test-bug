# Electric Vehicle Types Information Agent

A retrieval-augmented agent that uses Azure AI Search to fetch EV type knowledge and an OpenAI model to generate clear, sourced responses. The agent processes user questions about EV types, enriches results with document context, and formats output in well-structured paragraphs and lists.

---

## Quick Start

### 1. Create a virtual environment
```bash
python -m venv .venv
```

---

### 2. Activate the virtual environment
- **Windows:** 
  ```bash
  .venv\Scripts\activate
  ```
- **macOS/Linux:** 
  ```bash
  source .venv/bin/activate
  ```

---

### 3. Install dependencies
```bash
pip install -r requirements.txt
```

---

### 4. Environment setup
```bash
cp .env.example .env
```

---

### 5. Running the agent

- Direct execution (code lives in code/):
  ```
  python code/agent.py
  ```
- FastAPI server (if applicable):
  ```
  uvicorn code.agent:app --reload --host 0.0.0.0 --port 8000
  ```

---

## Environment Variables

- Agent identity and project
  - ENVIRONMENT
  - AGENT_NAME
  - AGENT_ID
  - PROJECT_NAME
  - PROJECT_ID
  - SERVICE_NAME
  - SERVICE_VERSION

- LLM / model configuration
  - MODEL_PROVIDER
  - LLM_MODEL
  - LLM_TEMPERATURE
  - LLM_MAX_TOKENS
  - AZURE_OPENAI_ENDPOINT
  - AZURE_OPENAI_EMBEDDING_DEPLOYMENT
  - AZURE_OPENAI_API_KEY
  - OPENAI_API_KEY
  - ANTHROPIC_API_KEY
  - GOOGLE_API_KEY
  - GITHUB_API_KEY

- Azure Cognitive search
  - AZURE_SEARCH_ENDPOINT
  - AZURE_SEARCH_API_KEY
  - AZURE_SEARCH_INDEX_NAME
  - AZURE_SEARCH_SERVICE_ENDPOINT

- Azure Content Safety
  - AZURE_CONTENT_SAFETY_ENDPOINT
  - AZURE_CONTENT_SAFETY_KEY

- Observability / Azure SQL (AgentOps)
  - OBS_AZURE_SQL_SERVER
  - OBS_AZURE_SQL_DATABASE
  - OBS_AZURE_SQL_PORT
  - OBS_AZURE_SQL_USERNAME
  - OBS_AZURE_SQL_PASSWORD
  - OBS_AZURE_SQL_SCHEMA
  - OBS_AZURE_SQL_TRUST_SERVER_CERTIFICATE

- Key Vault / security (if used)
  - USE_KEY_VAULT
  - KEY_VAULT_URI
  - AZURE_USE_DEFAULT_CREDENTIAL
  - AZURE_TENANT_ID
  - AZURE_CLIENT_ID
  - AZURE_CLIENT_SECRET

- Validation and environment
  - VALIDATION_CONFIG_PATH
  - ENV_FILE_VARIABLES_LOADED
  - PRIMARY_ADMIN_KEY

- Misc
  - HOST
  - PORT
  - API keys and URLs as required by the deployment

Note: See the .env.example for your exact environment variable names and defaults.

---

## API Endpoints

- **GET** /health
  - Description: Health check endpoint.
  - Response:
    ```
    {
      "status": "ok"
    }
    ```

- **POST** /query
  - Description: Process a user query about EV types and return a formatted answer sourced from the knowledge base.
  - Request body
    ```
    {
      "query": "string (required)"
    }
    ```
  - Response
    ```
    {
      "success": true,
      "answer": "string",
      "tool_calls_made": ["string", ...] | null,
      "error": null | "string"
    }
    ```
  - Notes:
    - All responses are produced by the agent orchestration pipeline: API -> Agent -> Retrieval (Azure AI Search) -> LLM -> Formatting.

---

## Running Tests

### 1. Install test dependencies
```bash
pip install pytest pytest-asyncio
```

---

### 2. Run all tests
```bash
pytest tests/
```

---

### 3. Run a specific test file
```bash
pytest tests/test_<module_name>.py
```

---

### 4. Run tests with verbose output
```bash
pytest tests/ -v
```

---

### 5. Run tests with coverage report
```bash
pip install pytest-cov
pytest tests/ --cov=code --cov-report=term-missing
```

---

## Deployment with Docker

### 1. Prerequisites
- Ensure Docker is installed and running.

### 2. Environment setup
```bash
cp .env.example .env
```

### 3. Build the Docker image
```bash
docker build -t Electric Vehicle Types Information Agent -f deploy/Dockerfile .
```

### 4. Run the Docker container
```bash
docker run -d --env-file .env -p 8000:8000 --name Electric Vehicle Types Information Agent Electric Vehicle Types Information Agent
```

### 5. Verify the container is running
```bash
docker ps
```

### 6. View container logs
```bash
docker logs Electric Vehicle Types Information Agent
```

### 7. Stop the container
```bash
docker stop Electric Vehicle Types Information Agent
```

---

## Notes

- All run commands must use the code/ prefix (e.g., python code/agent.py, uvicorn code.agent:app ...).
- See .env.example for all required and optional environment variables.
- The agent requires access to LLM API keys and (optionally) Azure SQL for observability.
- For production, configure Key Vault and secure credentials as needed.

---

## Footer

**Electric Vehicle Types Information Agent** — A retrieval-augmented assistant delivering sourced, organized EV type information.