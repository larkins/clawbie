#!/usr/bin/env python3
"""
Minimal MiniMax TTS Proxy - Simplified Flask app.
"""
import os
import base64
import logging
from flask import Flask, request, jsonify, Response

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("proxy")

app = Flask(__name__)

MINIMAX_API_KEY = os.environ.get("MINIMAX_API_KEY", "")
DEFAULT_MODEL = "speech-2.8-hd"

# Voice mapping
VOICE_MAP = {
    "alloy": "English_expressive_narrator",
    "nova": "English_Friendly_Guide", 
    "onyx": "English_Professional",
    "shimmer": "English_expressive_narrator",
    "fable": "English_Storyteller",
}

def generate_speech(text: str, voice: str = "alloy") -> bytes:
    """Call MiniMax TTS API."""
    import requests
    
    voice_id = VOICE_MAP.get(voice, voice)  # use mapped value, or pass through unknown voices directly
    
    url = "https://api.minimax.io/v1/t2a_v2"
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {MINIMAX_API_KEY}"}
    payload = {
        "model": DEFAULT_MODEL,
        "text": text,
        "stream": False,
        "voice_setting": {"voice_id": voice_id, "speed": 1.0, "volume": 1.0, "pitch": 0},
        "audio_setting": {"format": "mp3", "sample_rate": 32000, "bitrate": 128000, "channel": 1},
        "Token": MINIMAX_API_KEY,
    }
    
    resp = requests.post(url, json=payload, headers=headers, timeout=60)
    if resp.status_code != 200:
        log.error(f"MiniMax error: {resp.status_code} - {resp.text}")
        raise RuntimeError(f"API error: {resp.status_code}")
    
    data = resp.json()
    if data.get("base_resp", {}).get("status_code", 0) != 0:
        raise RuntimeError(f"MiniMax error: {data.get('base_resp', {}).get('status_msg')}")
    
    audio_hex = data.get("data", {}).get("audio", "")
    if not audio_hex:
        raise RuntimeError("No audio data in MiniMax response")
    return bytes.fromhex(audio_hex)

@app.route("/v1/audio/speech", methods=["POST"])
def audio_speech():
    try:
        data = request.get_json(force=True) or {}
        text = data.get("input", "")
        voice = data.get("voice", "alloy")
        
        if not text:
            return jsonify({"error": "input required"}), 400
            
        audio = generate_speech(text, voice)
        return Response(audio, mimetype="audio/mpeg")
    except Exception as e:
        log.exception("TTS error")
        return jsonify({"error": str(e)}), 500

@app.route("/health")
def health():
    return jsonify({"status": "healthy" if MINIMAX_API_KEY else "no_api_key"})

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=18793, threaded=True)
