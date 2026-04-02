"""MiniMax TTS (Text-to-Speech) Service Module.

This module provides a Python interface for the MiniMax TTS API,
supporting both synchronous and asynchronous text-to-speech synthesis.

Example:
    >>> from minimax_tts import MinimaxTTSService, TTSResponse
    >>> service = MinimaxTTSService(api_key="your-api-key")
    >>> response = service.synthesize("Hello, world!")
    >>> audio_bytes = response.audio_bytes

For long texts (>1000 characters), use the async API:

    >>> task_id = service.synthesize_async(long_text)
    >>> audio_bytes = service.wait_for_task(task_id)
"""

from .config import MiniMaxConfig, load_minimax_config
from .exceptions import (
    AuthenticationError,
    AsyncTaskError,
    InvalidTextError,
    MinimaxTTSError,
    ModelNotSupportedError,
    RateLimitError,
    VoiceNotFoundError,
)
from .models import (
    AudioSetting,
    AsyncTaskStatus,
    PronunciationDict,
    SUPPORTED_FORMATS,
    SUPPORTED_MODELS,
    SUPPORTED_SAMPLE_RATES,
    TTSRequest,
    TTSResponse,
    VoiceSetting,
)
from .service import MinimaxTTSService
from .voices import (
    DEFAULT_VOICES,
    SYSTEM_VOICES,
    get_all_voice_ids,
    get_default_voice,
    get_voice_id,
    list_chinese_voices,
    list_english_voices,
    list_voices,
)

__all__ = [
    # Main service
    "MinimaxTTSService",
    # Data models
    "TTSRequest",
    "TTSResponse",
    "VoiceSetting",
    "AudioSetting",
    "PronunciationDict",
    "AsyncTaskStatus",
    # Configuration
    "MiniMaxConfig",
    "load_minimax_config",
    # Exceptions
    "MinimaxTTSError",
    "AuthenticationError",
    "RateLimitError",
    "InvalidTextError",
    "ModelNotSupportedError",
    "VoiceNotFoundError",
    "AsyncTaskError",
    # Voice utilities
    "list_voices",
    "list_english_voices",
    "list_chinese_voices",
    "get_voice_id",
    "get_default_voice",
    "get_all_voice_ids",
    "DEFAULT_VOICES",
    "SYSTEM_VOICES",
    # Constants
    "SUPPORTED_MODELS",
    "SUPPORTED_FORMATS",
    "SUPPORTED_SAMPLE_RATES",
]

__version__ = "1.0.0"