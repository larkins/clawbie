"""
MiniMax TTS Proxy — Flask app providing OpenAI-compatible TTS endpoint.

Accepts OpenAI-format TTS requests and translates them to MiniMax TTS API.
OpenClaw (and any OpenAI TTS-compatible client) can use this as a local proxy.

Run:
    python -m minixtts_proxy.app
    or
    flask --app minixtts_proxy.app run --port 18793 --host 127.0.0.1

Environment variables:
    MINIMAX_API_KEY   — MiniMax API key (required)
    MINIMAX_BASE_URL  — MiniMax API base URL (default: https://api.minimax.io)
    PROXY_PORT        — Port to listen on (default: 18793)
    PROXY_HOST        — Host to bind to (default: 127.0.0.1)
    LOG_LEVEL         — Log level (default: INFO)
"""

import io
import logging
import os
import traceback
from flask import Flask, request, jsonify, Response

from .models import resolve_voice, resolve_model, DEFAULT_MODEL, DEFAULT_VOICE, MINIMAX_VOICES, SUPPORTED_MODELS

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger("minixtts_proxy")

app = Flask(__name__)


# ---------------------------------------------------------------------------
# MiniMax API client (minimal, inline — no extra deps)
# ---------------------------------------------------------------------------

def _minimax_tts(text: str, voice_id: str, model: str, speed: float = 1.0, output_format: str = "mp3") -> bytes:
    """Call MiniMax TTS API and return raw audio bytes."""
    import requests

    base_url = os.environ.get("MINIMAX_BASE_URL", "https://api.minimax.io")
    api_key = os.environ.get("MINIMAX_API_KEY")
    if not api_key:
        raise ValueError("MINIMAX_API_KEY environment variable is not set")

    # Map output format
    format_map = {
        "mp3": "mp3",
        "opus": "opus",
        "aac": "aac",
        "wav": "wav",
        "pcm": "pcm",
    }
    minimax_format = format_map.get(output_format.lower(), "mp3")

    # Speed: MiniMax accepts 0.5–2.0
    speed = max(0.5, min(2.0, speed))

    url = f"{base_url}/v1/t2a_v2"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
    }
    payload = {
        "model": model,
        "text": text,
        "stream": False,
        "voice_setting": {
            "voice_id": voice_id,
            "speed": speed,
            "volume": 1.0,
            "pitch": 0,
        },
        "audio_setting": {
            "format": minimax_format,
            "sample_rate": 32000,
            "bitrate": 128000,
            "channel": 1,
        },
        "Token": api_key,  # MiniMax requires token in body too
    }

    resp = requests.post(url, json=payload, headers=headers, timeout=60)
    if resp.status_code != 200:
        log.error(f"MiniMax API error: {resp.status_code} — {resp.text[:500]}")
        resp.raise_for_status()

    data = resp.json()
    if data.get("base_resp") and data["base_resp"].get("status_code") != 0:
        code = data["base_resp"]["status_code"]
        msg = data["base_resp"].get("status_msg", "unknown error")
        raise RuntimeError(f"MiniMax TTS error {code}: {msg}")

    # Audio returned as hex string in data.audio field
    audio_hex = data.get("data", {}).get("audio", "")
    if not audio_hex:
        raise RuntimeError("No audio data in MiniMax response")
    try:
        return bytes.fromhex(audio_hex)
    except Exception:
        raise RuntimeError(f"Failed to decode audio from MiniMax response")


# ---------------------------------------------------------------------------
# OpenAI-compatible endpoints
# ---------------------------------------------------------------------------

@app.route("/v1/audio/speech", methods=["POST"])
def audio_speech():
    """
    OpenAI-compatible /v1/audio/speech endpoint.

    Request body (JSON):
        model:    str  — model name (default: speech-2.8-hd)
        input:    str  — text to synthesize
        voice:    str  — OpenAI-style voice name (alloy, nova, etc)
                  OR MiniMax voice ID (English_expressive_narrator, etc)
        speed:    float — playback speed 0.25–4.0 (default: 1.0)
        response_format: str — mp3, opus, aac, wav, pcm (default: mp3)
    """
    try:
        body = request.get_json(force=True)
    except Exception:
        return jsonify({"error": {"message": "Invalid JSON body", "type": "invalid_request_error"}}), 400

    text = body.get("input") or body.get("text")
    if not text:
        return jsonify({"error": {"message": "input is required", "type": "invalid_request_error"}}), 400

    model = resolve_model(body.get("model", DEFAULT_MODEL))
    voice_raw = body.get("voice", DEFAULT_VOICE)
    speed_raw = float(body.get("speed", 1.0))
    # OpenAI speed 0.25–4.0 → MiniMax speed 0.5–2.0
    speed = max(0.5, min(2.0, speed_raw * 0.75))
    output_format = body.get("response_format", "mp3").lower()

    voice_id = resolve_voice(voice_raw)
    log.info(f"TTS request: model={model} voice={voice_id} speed={speed:.2f} format={output_format} chars={len(text)}")

    try:
        audio_bytes = _minimax_tts(text, voice_id=voice_id, model=model, speed=speed, output_format=output_format)
    except ValueError as e:
        log.error(f"Config error: {e}")
        return jsonify({"error": {"message": str(e), "type": "invalid_request_error"}}), 400
    except Exception as e:
        log.error(f"TTS error: {e}\n{traceback.format_exc()}")
        return jsonify({"error": {"message": f"TTS generation failed: {e}", "type": "internal_error"}}), 500

    mimetype = {
        "mp3": "audio/mpeg",
        "opus": "audio/opus",
        "aac": "audio/aac",
        "wav": "audio/wav",
        "pcm": "audio/pcm",
    }.get(output_format, "audio/mpeg")

    return Response(audio_bytes, mimetype=mimetype)


@app.route("/v1/models", methods=["GET"])
def list_models():
    """OpenAI-compatible model list endpoint."""
    return jsonify({
        "object": "list",
        "data": [
            {"id": m, "object": "model", "created": 1700000000, "owned_by": "minimax"}
            for m in SUPPORTED_MODELS
        ],
    })


@app.route("/health", methods=["GET"])
def health():
    """Health check endpoint."""
    api_key = os.environ.get("MINIMAX_API_KEY")
    return jsonify({
        "status": "healthy" if api_key else "configured",
        "has_api_key": bool(api_key),
        "default_voice": DEFAULT_VOICE,
        "default_model": DEFAULT_MODEL,
    })


@app.route("/", methods=["GET"])
def index():
    return jsonify({
        "service": "MiniMax TTS Proxy",
        "version": "1.0.0",
        "endpoints": {
            "POST /v1/audio/speech": "OpenAI-compatible TTS",
            "GET /v1/models": "List models",
            "GET /health": "Health check",
        },
    })


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main():
    import argparse
    parser = argparse.ArgumentParser(description="MiniMax TTS Proxy")
    parser.add_argument("--port", "-p", type=int, default=int(os.environ.get("PROXY_PORT", 18793)))
    parser.add_argument("--host", type=str, default=os.environ.get("PROXY_HOST", "127.0.0.1"))
    parser.add_argument("--debug", action="store_true")
    args = parser.parse_args()

    log.info(f"Starting MiniMax TTS Proxy on {args.host}:{args.port}")
    app.run(host=args.host, port=args.port, debug=args.debug)


if __name__ == "__main__":
    main()
