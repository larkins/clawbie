"""Data models for MiniMax TTS API requests and responses."""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# Supported TTS models
SUPPORTED_MODELS = [
    "speech-2.8-hd",
    "speech-2.8-turbo",
    "speech-2.6-hd",
    "speech-2.6-turbo",
    "speech-02-hd",
    "speech-02-turbo",
]

# Supported audio formats
SUPPORTED_FORMATS = ["mp3", "wav", "pcm", "ogg"]

# Supported sample rates
SUPPORTED_SAMPLE_RATES = [8000, 16000, 24000, 32000, 44100, 48000]


@dataclass
class PronunciationDict:
    """Pronunciation dictionary for custom pronunciations.

    Used to customize how specific words or phrases are pronounced.

    Attributes:
        tone: Tone setting for pronunciation (used for Chinese voices).
        pronunciation: List of pronunciation entries with word/replacement pairs.
    """

    tone: str | None = None
    pronunciation: list[dict[str, str]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Convert to API-compatible dictionary."""
        result = {}
        if self.tone is not None:
            result["tone"] = self.tone
        if self.pronunciation:
            result["pronunciation"] = self.pronunciation
        return result


@dataclass
class VoiceSetting:
    """Voice settings for TTS synthesis.

    Attributes:
        voice_id: The voice identifier (e.g., "English_expressive_narrator").
        speed: Speech speed multiplier (0.5 to 2.0, default 1.0).
        vol: Volume level (0.1 to 2.0, default 1.0).
        pitch: Pitch adjustment (-12 to 12, default 0).
        pronunciation_dict: Optional pronunciation dictionary settings.
    """

    voice_id: str = "English_expressive_narrator"
    speed: float = 1.0
    vol: float = 1.0
    pitch: int = 0
    pronunciation_dict: PronunciationDict | None = None

    def __post_init__(self):
        """Validate voice settings."""
        if not 0.5 <= self.speed <= 2.0:
            raise ValueError(f"Speed must be between 0.5 and 2.0, got {self.speed}")
        if not 0.1 <= self.vol <= 2.0:
            raise ValueError(f"Volume must be between 0.1 and 2.0, got {self.vol}")
        if not-12 <= self.pitch <= 12:
            raise ValueError(f"Pitch must be between -12 and 12, got {self.pitch}")

    def to_dict(self) -> dict[str, Any]:
        """Convert to API-compatible dictionary."""
        result = {
            "voice_id": self.voice_id,
            "speed": self.speed,
            "vol": self.vol,
            "pitch": self.pitch,
        }
        if self.pronunciation_dict:
            result["pronunciation_dict"] = self.pronunciation_dict.to_dict()
        return result


@dataclass
class AudioSetting:
    """Audio output settings for TTS synthesis.

    Attributes:
        sample_rate: Audio sample rate in Hz (default 32000).
        bitrate: Audio bitrate in bits per second (default 128000).
        format: Output audio format ("mp3", "wav", "pcm", "ogg").
        channel: Number of audio channels (1 = mono, 2 = stereo).
    """

    sample_rate: int = 32000
    bitrate: int = 128000
    format: str = "mp3"
    channel: int = 1

    def __post_init__(self):
        """Validate audio settings."""
        if self.sample_rate not in SUPPORTED_SAMPLE_RATES:
            raise ValueError(f"Sample rate {self.sample_rate} not supported. Use one of {SUPPORTED_SAMPLE_RATES}")
        if self.format not in SUPPORTED_FORMATS:
            raise ValueError(f"Format '{self.format}' not supported. Use one of {SUPPORTED_FORMATS}")
        if self.channel not in [1, 2]:
            raise ValueError(f"Channel must be 1 (mono) or 2 (stereo), got {self.channel}")

    def to_dict(self) -> dict[str, Any]:
        """Convert to API-compatible dictionary."""
        return {
            "sample_rate": self.sample_rate,
            "bitrate": self.bitrate,
            "format": self.format,
            "channel": self.channel,
        }


@dataclass
class TTSRequest:
    """Request payload for TTS synthesis.

    Attributes:
        text: The text to synthesize.
        model: The TTS model to use (default: "speech-2.8-turbo").
        voice_setting: Voice configuration settings.
        audio_setting: Audio output configuration.
        stream: Whether to stream the response (default: False).
        pronunciation_dict: Optional pronunciation dictionary.
    """

    text: str
    model: str = "speech-2.8-turbo"
    voice_setting: VoiceSetting | None = None
    audio_setting: AudioSetting | None = None
    stream: bool = False
    pronunciation_dict: PronunciationDict | None = None

    def __post_init__(self):
        """Validate request parameters."""
        if self.model not in SUPPORTED_MODELS:
            raise ValueError(f"Model '{self.model}' not supported. Use one of {SUPPORTED_MODELS}")
        if not self.text or not self.text.strip():
            raise ValueError("Text cannot be empty")
        # Set defaults if not provided
        if self.voice_setting is None:
            self.voice_setting = VoiceSetting()
        if self.audio_setting is None:
            self.audio_setting = AudioSetting()

    def to_dict(self) -> dict[str, Any]:
        """Convert to API-compatible dictionary."""
        result = {
            "model": self.model,
            "text": self.text,
            "stream": self.stream,
            "voice_setting": self.voice_setting.to_dict() if self.voice_setting else VoiceSetting().to_dict(),
            "audio_setting": self.audio_setting.to_dict() if self.audio_setting else AudioSetting().to_dict(),
        }
        if self.pronunciation_dict:
            result["pronunciation_dict"] = self.pronunciation_dict.to_dict()
        return result


@dataclass
class TTSResponse:
    """Response from TTS synthesis.

    Attributes:
        audio_data: The synthesized audio data (hex-encoded string or bytes).
        audio_url: URL todownload the audio file (if applicable).
        duration: Duration of the audio in milliseconds.
        format: Audio format ("mp3", "wav", etc.).
        trace_id: Trace ID for debugging/logging.
        status: Status code (2 = success in MiniMax API).
        extra_info: Additional metadata from the response.
    """

    audio_data: str | bytes | None = None
    audio_url: str | None = None
    duration: int | None = None
    format: str | None = None
    trace_id: str | None = None
    status: int | None = None
    extra_info: dict[str, Any] = field(default_factory=dict)

    @property
    def audio_bytes(self) -> bytes | None:
        """Get audio data as bytes, decoding from hex if necessary."""
        if self.audio_data is None:
            return None
        if isinstance(self.audio_data, bytes):
            return self.audio_data
        # Decode hex string to bytes
        try:
            return bytes.fromhex(self.audio_data)
        except ValueError:
            # If not valid hex, return as-is encoded
            return self.audio_data.encode("utf-8")

    @property
    def audio_length_ms(self) -> int:
        """Get audio duration in milliseconds."""
        return self.duration or self.extra_info.get("audio_length", 0)

    @property
    def audio_size_bytes(self) -> int:
        """Get audio file size in bytes."""
        return self.extra_info.get("audio_size", 0)

    @property
    def audio_format(self) -> str:
        """Get audio format."""
        return self.format or self.extra_info.get("audio_format", "mp3")

    def save_to_file(self, path: str | Path) -> None:
        """Save audio data to a file.

        Args:
            path: Path to save the audio file.

        Raises:
            ValueError: If no audio data is available.
        """
        audio = self.audio_bytes
        if audio is None:
            raise ValueError("No audio data available to save")
        Path(path).write_bytes(audio)

    @property
    def success(self) -> bool:
        """Check if synthesis was successful."""
        # MiniMax API returns status 2 for success
        return self.status == 2

    @classmethod
    def from_api_response(cls, response: dict[str, Any]) -> "TTSResponse":
        """Create a TTSResponse from an API response dictionary.

        Args:
            response: The raw API response.

        Returns:
            A TTSResponse instance.
        """
        data = response.get("data", {})
        extra_info = response.get("extra_info", {})

        return cls(
            audio_data=data.get("audio"),
            audio_url=data.get("audio_url"),
            duration=extra_info.get("audio_length"),
            format=extra_info.get("audio_format"),
            trace_id=response.get("trace_id"),
            status=data.get("status"),
            extra_info=extra_info,
        )


@dataclass
class AsyncTaskStatus:
    """Status of an async TTS task.

    Attributes:
        task_id: The task identifier.
        status: Task status ("pending", "processing", "completed", "failed").
        file_id: The file ID for downloading (when completed).
        error: Error message (if failed).
    """

    task_id: str
    status: str = "pending"
    file_id: str | None = None
    error: str | None = None

    @property
    def completed(self) -> bool:
        """Check if task is completed."""
        return self.status == "completed"

    @property
    def failed(self) -> bool:
        """Check if task failed."""
        return self.status == "failed"

    @classmethod
    def from_api_response(cls, response: dict[str, Any]) -> "AsyncTaskStatus":
        """Create an AsyncTaskStatus from an API response."""
        return cls(
            task_id=response.get("task_id", ""),
            status=response.get("status", "pending"),
            file_id=response.get("file_id"),
            error=response.get("error"),
        )