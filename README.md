# Clawbie

A long-term memory engine for AI assistants, built with PostgreSQL and pgvector.

Clawbie gives your AI assistant persistent memory by storing, retrieving, and summarizing conversational memories over time. It supports semantic search via vector embeddings, tracks sub-agent activity, and generates nightly memory summaries ("reveries") delivered by email.

## Features

- **Semantic memory storage** — Store memories with pgvector embeddings for semantic similarity search
- **Dual embeddings** — Separate vectors for raw memory and reflection content
- **Sub-agent tracking** — Track Codex/ACP sub-agent runs for follow-up detection
- **Nightly reveries** — Automated daily memory summaries delivered by email
- **OpenAI-compatible TTS proxy** — Local proxy for MiniMax TTS with OpenAI-compatible API

## Quick Start

```bash
# Clone the repo
git clone git@github.com:larkins/clawbie.git
cd clawbie

# Create and activate virtual environment
python3 -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Copy and configure .env
cp .env.example .env
# Edit .env with your values

# Create database and apply schema
psql "$DATABASE_URL" -f migrations/CLAWBIE_SCHEMA.sql

# Install systemd services (optional)
cd systemd && ./install.sh && cd ..

# Run the chat-memory bridge
python -m memory_engine.openclaw_bridge --config config.yaml
```

## Requirements

- Python 3.10+
- PostgreSQL 15+ with pgvector extension
- OpenClaw agent framework
- MiniMax API key (for TTS)
- Ollama or similar inference endpoint (for embeddings)

See `TECH_REQUIREMENTS.md` for full details.

## Project Structure

```
clawbie/
├── src/
│   ├── clawbie_memory/    # Memory engine core
│   └── minimax_tts/       # MiniMax TTS client
├── memory_engine/         # OpenClaw bridge and jobs
├── minixtts_proxy/        # OpenAI-compatible TTS proxy
├── migrations/            # Database schema
├── skills/                # OpenClaw skills
│   ├── clawbie-memory/    # Memory query skill
│   ├── minimax-tts/      # TTS skill
│   └── nightly-reverie/   # Reverie generation
├── systemd/               # Systemd service files
├── tests/                # Test suite
├── docs/                 # Documentation
└── scripts/               # Utility scripts
```

## Skills

Three OpenClaw skills are included:

- **`clawbie-memory`** — Query and manage memories (recent, text-search, promise-scan)
- **`minimax-tts`** — Text-to-speech via MiniMax API
- **`nightly-reverie`** — Daily memory synthesis and email delivery

See `skills/README.md` for full skill documentation.

## License

MIT License — see [LICENSE](LICENSE).
