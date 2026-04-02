#!/usr/bin/env python3
"""MiniMax TTS CLI - Generate speech from text using MiniMax TTS API.

Usage:
    python tts.py synthesize --text "Hello world"
    python tts.py async --file long_article.txt
    python tts.py voices --lang english
    python tts.py models
"""

import argparse
import os
import sys
import tempfile
from pathlib import Path

# Add clawbie src to path (supports CLAWBIE_SRC env var)
_clawbie_src = os.environ.get("CLAWBIE_SRC", str(Path(__file__).resolve().parents[3] / "src"))
if Path(_clawbie_src).exists():
    sys.path.insert(0, _clawbie_src)

from minimax_tts import (
    MinimaxTTSService,
    TTSResponse,
    load_minimax_config,
    SUPPORTED_MODELS,
    SUPPORTED_FORMATS,
    list_voices,
    list_english_voices,
    list_chinese_voices,
    get_default_voice,
)
from minimax_tts.exceptions import (
    MinimaxTTSError,
    AuthenticationError,
    RateLimitError,
    InvalidTextError,
)


# Default output directory for generated audio files (set via TTS_OUTPUT_DIR env var)
DEFAULT_OUTPUT_DIR = Path(os.environ.get("TTS_OUTPUT_DIR", str(Path.home() / ".openclaw" / "workspace")))

def get_service() -> MinimaxTTSService:
    """Create TTS service from environment config."""
    config = load_minimax_config()
    if not config.api_key:
        print("Error: MINIMAX_API_KEY not found in environment or .env file")
        print("Set it in your .env file or export MINIMAX_API_KEY=your-key")
        sys.exit(1)
    return MinimaxTTSService(
        api_key=config.api_key,
        base_url=config.base_url
    )


def cmd_synthesize(args):
    """Synthesize speech from text (synchronous)."""
    service = get_service()
    
    if not args.text:
        print("Error: --text is required for synthesize command")
        sys.exit(1)
    
    print(f"Synthesizing: '{args.text[:50]}{'...' if len(args.text) > 50 else ''}'")
    print(f"Model: {args.model}")
    print(f"Voice: {args.voice}")
    
    try:
        response = service.synthesize(
            text=args.text,
            model=args.model,
            voice_id=args.voice,
            speed=args.speed,
            pitch=args.pitch,
            audio_format=args.format,
            sample_rate=args.sample_rate
        )
        
        # Determine output path
        if args.output:
            output_path = Path(args.output)
        else:
            # Use workspace directory as default output location
            output_path = DEFAULT_OUTPUT_DIR / f"tts_output.{args.format}"
        
        response.save_to_file(output_path)
        
        print(f"✓ Audio saved to: {output_path}")
        print(f"  Duration: {response.audio_length_ms / 1000:.2f}s")
        print(f"  Format: {response.audio_format}")
        print(f"  Size: {response.audio_size_bytes / 1024:.1f} KB")
        
        return output_path
        
    except AuthenticationError:
        print("Error: Invalid API key")
        sys.exit(1)
    except RateLimitError as e:
        print(f"Error: Rate limit exceeded - {e}")
        sys.exit(1)
    except InvalidTextError as e:
        print(f"Error: Invalid text - {e}")
        sys.exit(1)
    except MinimaxTTSError as e:
        print(f"Error: {e}")
        sys.exit(1)


def cmd_async(args):
    """Synthesize speech from long text (asynchronous)."""
    service = get_service()
    
    # Get text from file or argument
    if args.file:
        text = Path(args.file).read_text()
    elif args.text:
        text = args.text
    else:
        print("Error: --text or --file is required for async command")
        sys.exit(1)
    
    print(f"Creating async task for {len(text)} characters...")
    
    try:
        # Submit async task
        task_id = service.synthesize_async(
            text=text,
            model=args.model,
            voice_id=args.voice,
            audio_format=args.format
        )
        
        print(f"Task ID: {task_id}")
        print(f"Waiting for completion (timeout: {args.timeout}s)...")
        
        # Wait for completion
        audio_bytes = service.wait_for_task(
            task_id=task_id,
            timeout=args.timeout
        )
        
        # Determine output path
        if args.output:
            output_path = Path(args.output)
        else:
            # Use workspace directory as default output location
            output_path = DEFAULT_OUTPUT_DIR / f"tts_async_output.{args.format}"
        
        output_path.write_bytes(audio_bytes)
        
        print(f"✓ Audio saved to: {output_path}")
        print(f"  Size: {len(audio_bytes) / 1024:.1f} KB")
        
        return output_path
        
    except MinimaxTTSError as e:
        print(f"Error: {e}")
        sys.exit(1)


def cmd_voices(args):
    """List available voices."""
    print("Available MiniMax TTS Voices\n")
    
    if args.lang == "english":
        voices = list_english_voices()
        print("=== English Voices ===\n")
    elif args.lang == "chinese":
        voices = list_chinese_voices()
        print("=== Chinese Voices ===\n")
    else:
        voices = list_voices()
        print("=== All Voices ===\n")
    
    # Group by language
    by_lang = {}
    for voice_id, name in voices.items():
        lang = voice_id.split("_")[0] if "_" in voice_id else "Other"
        if lang not in by_lang:
            by_lang[lang] = []
        by_lang[lang].append((voice_id, name))
    
    for lang, voice_list in sorted(by_lang.items()):
        print(f"\n{lang}:")
        for voice_id, name in voice_list:
            default_marker = " (default)" if voice_id == get_default_voice() else ""
            print(f"  {voice_id}{default_marker}")
            if name and name != voice_id:
                print(f"    {name}")


def cmd_models(args):
    """List available models."""
    print("Available MiniMax TTS Models\n")
    
    model_info = {
        "speech-2.8-hd": "Premium quality, perfect tonal nuances and timbre similarity",
        "speech-2.8-turbo": "Fast, affordable, great quality (recommended)",
        "speech-2.6-hd": "Ultra-low latency, intelligence parsing, enhanced naturalness",
        "speech-2.6-turbo": "Fastest, most affordable, ideal for agents",
        "speech-02-hd": "Superior rhythm and stability, high replication similarity",
        "speech-02-turbo": "Enhanced multilingual capabilities",
    }
    
    for model in SUPPORTED_MODELS:
        info = model_info.get(model, "Speech synthesis model")
        default_marker = " (default)" if model == "speech-2.8-turbo" else ""
        print(f"  {model}{default_marker}")
        print(f"    {info}\n")


def cmd_test(args):
    """Test TTS with a short message."""
    service = get_service()
    
    test_text = args.text or "Hello! This is a test of the MiniMax TTS system."
    
    print(f"Testing TTS: '{test_text}'")
    
    try:
        response = service.synthesize(
            text=test_text,
            model="speech-2.8-turbo",
            voice_id="English_expressive_narrator"
        )
        
        # Save to workspace directory
        output_path = DEFAULT_OUTPUT_DIR / "tts_test.mp3"
        response.save_to_file(output_path)
        
        print(f"✓ Test successful!")
        print(f"  Audio file: {output_path}")
        print(f"  Duration: {response.audio_length_ms / 1000:.2f}s")
        
        return output_path
        
    except MinimaxTTSError as e:
        print(f"✗ Test failed: {e}")
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(
        description="MiniMax TTS CLI - Generate speech from text"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    
    # synthesize command
    syn_parser = subparsers.add_parser("synthesize", help="Synthesize speech from text (short)")
    syn_parser.add_argument("--text", "-t", help="Text to synthesize")
    syn_parser.add_argument("--model", "-m", default="speech-2.8-turbo",
                           choices=SUPPORTED_MODELS, help="TTS model")
    syn_parser.add_argument("--voice", "-v", default="English_expressive_narrator",
                           help="Voice ID")
    syn_parser.add_argument("--output", "-o", help="Output file path")
    syn_parser.add_argument("--format", "-f", default="mp3",
                           choices=SUPPORTED_FORMATS, help="Audio format")
    syn_parser.add_argument("--speed", "-s", type=float, default=1.0,
                           help="Speech speed (0.5-2.0)")
    syn_parser.add_argument("--pitch", "-p", type=int, default=0,
                           help="Pitch adjustment (-12 to 12)")
    syn_parser.add_argument("--sample-rate", "-r", type=int, default=32000,
                           help="Sample rate")
    
    # async command
    async_parser = subparsers.add_parser("async", help="Synthesize speech from long text (async)")
    async_parser.add_argument("--text", "-t", help="Text to synthesize")
    async_parser.add_argument("--file", "-f", help="Path to text file")
    async_parser.add_argument("--model", "-m", default="speech-2.8-turbo",
                              choices=SUPPORTED_MODELS, help="TTS model")
    async_parser.add_argument("--voice", "-v", default="English_expressive_narrator",
                              help="Voice ID")
    async_parser.add_argument("--output", "-o", help="Output file path")
    async_parser.add_argument("--format", default="mp3",
                              choices=SUPPORTED_FORMATS, help="Audio format")
    async_parser.add_argument("--timeout", type=int, default=300,
                              help="Max wait time in seconds")
    
    # voices command
    voices_parser = subparsers.add_parser("voices", help="List available voices")
    voices_parser.add_argument("--lang", "-l", default=None,
                              choices=["english", "chinese"],
                              help="Filter by language")
    
    # models command
    subparsers.add_parser("models", help="List available models")
    
    # test command
    test_parser = subparsers.add_parser("test", help="Test TTS with sample text")
    test_parser.add_argument("--text", "-t", help="Custom test text")
    
    args = parser.parse_args()
    
    if args.command == "synthesize":
        cmd_synthesize(args)
    elif args.command == "async":
        cmd_async(args)
    elif args.command == "voices":
        cmd_voices(args)
    elif args.command == "models":
        cmd_models(args)
    elif args.command == "test":
        cmd_test(args)


if __name__ == "__main__":
    main()