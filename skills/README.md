# Clawbie Skills

These skills are for use with OpenClaw agents.

## Available Skills

### clawbie-memory

Memory engine for Clawbie AI assistant. Provides:
- `recent` — fetch recent memories from the database
- `text-search` — search memories by content
- `promise-scan` — detect follow-up/commitment patterns
- `since-id` — fetch memories after a known ID

**Prerequisites:** PostgreSQL database with Clawbie schema. Set `DATABASE_URL` in `.env`.

### minimax-tts

MiniMax TTS for voice output. Provides:
- `synthesize` — short text → audio file (use `--use-proxy` for OpenAI-compatible endpoint)
- `async` — long text → async audio generation
- `voices` — list available voices
- `models` — list available models

**Prerequisites:** MiniMax API key. Set `MINIMAX_API_KEY` in `.env`.

**For OpenClaw TTS integration:** Use the local proxy (recommended):
```bash
# Start proxy
python minixtts_proxy/simple_proxy.py
# Or via systemd: systemctl --user start minixtts-proxy
# Configure OpenClaw: provider=openai, baseUrl=http://127.0.0.1:18793
```

### nightly-reverie

Daily memory synthesis — generates coherent summaries of the previous day's memories, identifies themes/decisions/blockers, and emails the result to the user.

- `get-latest` — fetch the most recent nightly reverie
- `generate` — run reverie generation for a specific date

**Prerequisites:** Clawbie memory engine running. Requires `DATABASE_URL` in `.env`.

**Full documentation:** `docs/REVERIE_README.md`

## Setup

1. Copy `.env.example` to `.env`
2. Fill in your values
3. Configure the skill paths in your OpenClaw workspace
