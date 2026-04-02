---
name: minimax-tts
description: Convert text to speech using MiniMax TTS API (speech-2.8-hd, speech-2.8-turbo, speech-2.6-hd, etc.). Use when you need to generate audio from text, create voice messages for Telegram/WhatsApp, or synthesize speech for any purpose. Supports multiple voices, models, and output formats.
---

# MiniMax TTS

Generate speech from text using the MiniMax TTS service via an OpenAI-compatible local proxy.

## Two Usage Modes

### Option 1: Local OpenAI-Compatible Proxy (Recommended)

The proxy runs at `http://127.0.0.1:18793` and provides an OpenAI-compatible TTS endpoint.

```bash
# Start the proxy (if not running via systemd)
cd ~/git/clawbie
python minixtts_proxy/simple_proxy.py

# Use the skill with the proxy
python skills/minimax-tts/scripts/tts.py synthesize --text "Hello world" --use-proxy
```

The proxy maps OpenAI voice names → MiniMax voice IDs:
- `alloy` → `English_expressive_narrator`
- `nova` → `English_Friendly_Guide`
- `onyx` → `English_Professional`
- `fable` → `English_Storyteller`

**Setup for persistent proxy:**
```bash
cp ~/git/clawbie/systemd/minixtts-proxy.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now minixtts-proxy
```

### Option 2: Direct MiniMax API

```bash
python skills/minimax-tts/scripts/tts.py synthesize --text "Hello world" --voice English_expressive_narrator
```

## Quick Start

```bash
python skills/minimax-tts/scripts/tts.py synthesize --text "Hello, this is a test message."
```

**Note:** Audio files are saved to `~/.openclaw/workspace/` by default. Override with `--output-dir` or `TTS_OUTPUT_DIR` env var.

## Setup

The `MINIMAX_API_KEY` must be set in your environment:

```bash
# In ~/git/clawbie/.env
MINIMAX_API_KEY=sk-api-xxxxx
```

## Commands

### Synthesize speech (short text)

For texts under 1000 characters:

```bash
python skills/minimax-tts/scripts/tts.py synthesize --text "Your text here"
python skills/minimax-tts/scripts/tts.py synthesize --text "Hello world" --model speech-2.8-hd --voice English_expressive_narrator --use-proxy
```

Options:
- `--text`: Text to synthesize (required)
- `--model`: TTS model (default: speech-2.8-hd via proxy, speech-2.8-turbo direct)
- `--voice`: Voice ID (default: English_expressive_narrator)
- `--use-proxy`: Use local OpenAI-compatible proxy instead of direct API
- `--output-dir`: Output directory (default: ~/.openclaw/workspace/)

### Synthesize speech (long text)

For texts over 1000 characters, use async mode:

```bash
python skills/minimax-tts/scripts/tts.py async --text "$(cat long_article.txt)"
python skills/minimax-tts/scripts/tts.py async --file long_article.txt --output long.mp3
```

### List available voices

```bash
python skills/minimax-tts/scripts/tts.py voices
python skills/minimax-tts/scripts/tts.py voices --lang english
```

### List available models

```bash
python skills/minimax-tts/scripts/tts.py models
```

## Models

| Model | Status | Description |
|-------|--------|-------------|
| speech-2.8-hd | ✅ Works | Highest quality, perfect tonal nuances |
| speech-2.8-turbo | ⚠️ May not work | Fast, affordable, great quality |
| speech-2.6-hd | ⚠️ May not work | Ultra-low latency, enhanced naturalness |
| speech-2.6-turbo | ⚠️ May not work | Fastest, most affordable |
| speech-02-hd | ❌ Error 2061 | Superior rhythm and stability |
| speech-02-turbo | ❌ Error 2061 | Enhanced multilingual capabilities |

**Note:** Only `speech-2.8-hd` is confirmed working with the current MiniMax plan. Other models return status 2061 ("your current token plan not support model").

## Popular Voices

**English:**
- `English_expressive_narrator` - Natural storytelling voice (default)
- `English_Friendly_Guide` - Warm, approachable
- `English_Professional` - Clear, authoritative
- `English_Storyteller` - Engaging narrative

Run `tts.py voices` for the full list.

## Python API

You can also use the service directly from Python:

```python
import sys
sys.path.insert(0, '~/git/clawbie/src')
from minimax_tts import MinimaxTTSService

service = MinimaxTTSService(api_key="your-key")
response = service.synthesize(
    text="Hello, world!",
    model="speech-2.8-hd",
    voice_id="English_expressive_narrator"
)

# Get audio bytes
audio_bytes = response.audio_bytes

# Or save directly
response.save_to_file("output.mp3")
```

## Error Handling

The service raises specific exceptions:
- `AuthenticationError`: Invalid API key
- `RateLimitError`: Too many requests
- `InvalidTextError`: Text contains invalid characters (>10%)
- `ModelNotSupportedError`: Unknown model ID (or token plan doesn't support it)
- `VoiceNotFoundError`: Unknown voice ID
- `AsyncTaskError`: Async task failed or timed out

## Troubleshooting

See `troubleshooting.md` for common issues including proxy setup, authentication errors, and deployment problems.
