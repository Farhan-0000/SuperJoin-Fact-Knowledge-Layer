# Fact Knowledge Layer

A system that extracts, normalizes, and reconciles facts from PDF documents with full provenance tracking. Every factual claim is traceable to **document → page → chunk → exact source quote**.

## Architecture

```
fact-knowledge-layer/
├── app/
│   ├── api/              # FastAPI route handlers
│   │   ├── health.py     # /health endpoint
│   │   ├── documents.py  # Document upload & management
│   │   └── facts.py      # Fact query & relationships
│   ├── core/             # Shared utilities
│   ├── db/               # SQLite database schema & connection
│   ├── models/           # Pydantic schemas
│   ├── services/         # Processing pipeline
│   │   ├── ingestion/    # PDF text extraction & chunking
│   │   ├── extraction/   # LLM-based fact extraction
│   │   ├── normalization/# Deterministic value normalization
│   │   ├── matching/     # Candidate retrieval & deduplication
│   │   └── reasoning/    # Corroboration / contradiction analysis
│   └── workers/          # Async task execution
├── tests/                # pytest test suite
├── data/                 # Starter datasets (not committed)
├── storage/              # Runtime data (auto-created, gitignored)
├── ui/                   # Streamlit frontend
└── scripts/              # Utility scripts
```

## Quick Start

### Prerequisites

- Python 3.11+
- An OpenAI API key (for extraction phases)

### Setup

```bash
# Clone and enter the project
cd fact-knowledge-layer

# Create a virtual environment
python -m venv .venv

# Activate it
# Windows:
.venv\Scripts\activate
# macOS/Linux:
source .venv/bin/activate

# Install dependencies
pip install -e ".[dev]"

# Copy environment template
cp .env.example .env
# Edit .env and set your OPENAI_API_KEY
```

### Run the Server

```bash
# Development server with auto-reload
uvicorn app.main:create_app --factory --reload

# Or directly
python -m app
```

The API will be available at `http://localhost:8000`.

### Verify

```bash
# Health check
curl http://localhost:8000/health

# Interactive API docs
# Open http://localhost:8000/docs in your browser
```

### Run Tests

```bash
pytest
pytest --cov=app
```

## Configuration

All configuration is through environment variables (see `.env.example`):

| Variable | Default | Description |
|---|---|---|
| `OPENAI_API_KEY` | — | OpenAI API key (required for extraction) |
| `EXTRACTION_MODEL` | `gpt-4o` | Model for fact extraction |
| `RELATIONSHIP_MODEL` | `gpt-4o` | Model for relationship reasoning |
| `EMBEDDING_MODEL` | `text-embedding-3-small` | Embedding model |
| `STORAGE_DIR` | `./storage` | Upload & data directory |
| `DATABASE_URL` | `sqlite+aiosqlite:///./storage/facts.db` | SQLite URL |
| `MAX_LLM_CONCURRENCY` | `4` | Max concurrent LLM calls |
| `MAX_FILE_SIZE_MB` | `50` | Max upload file size |
| `LOG_LEVEL` | `INFO` | Logging level |

## Development

```bash
# Lint
ruff check app/ tests/

# Format
ruff format app/ tests/
```

## License

MIT
