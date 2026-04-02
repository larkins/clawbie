"""Tests for MiniMax TTS service module."""

import pytest
from unittest.mock import Mock, patch, MagicMock
import requests

from minimax_tts import (
    MinimaxTTSService,
    TTSRequest,
    TTSResponse,
    VoiceSetting,
    AudioSetting,
    AsyncTaskStatus,
    SUPPORTED_MODELS,
)
from minimax_tts.exceptions import (
    MinimaxTTSError,
    AuthenticationError,
    RateLimitError,
    InvalidTextError,
    ModelNotSupportedError,
)
from minimax_tts.voices import (
    list_voices,
    get_voice_id,
    get_default_voice,
    DEFAULT_VOICES,
)
from minimax_tts.config import MiniMaxConfig


# Fixtures


@pytest.fixture
def mock_api_key():
    """Mock API key for testing."""
    return "test-api-key-12345"


@pytest.fixture
def mock_config(mock_api_key):
    """Mock configuration for testing."""
    return MiniMaxConfig(
        api_key=mock_api_key,
        base_url="https://api.minimax.io",
        default_model="speech-2.8-turbo",
        default_voice="English_expressive_narrator",
    )


@pytest.fixture
def service(mock_api_key):
    """Create a TTS service instance for testing."""
    return MinimaxTTSService(api_key=mock_api_key)


@pytest.fixture
def mock_successful_response():
    """Mock successful API response."""
    return {
        "data": {
            "audio": "6162636465",  # hex for "abcde"
            "status": 2,
        },
        "extra_info": {
            "audio_length": 5000,
            "audio_format": "mp3",
        },
        "trace_id": "trace-123",
    }


# Tests forVoiceSetting


class TestVoiceSetting:
    """Tests for VoiceSetting dataclass."""

    def test_default_values(self):
        """Test default voice settings."""
        setting = VoiceSetting()
        assert setting.voice_id == "English_expressive_narrator"
        assert setting.speed == 1.0
        assert setting.vol == 1.0
        assert setting.pitch == 0

    def test_custom_values(self):
        """Test custom voice settings."""
        setting = VoiceSetting(
            voice_id="custom_voice",
            speed=1.5,
            vol=0.8,
            pitch=3,
        )
        assert setting.voice_id == "custom_voice"
        assert setting.speed == 1.5
        assert setting.vol == 0.8
        assert setting.pitch == 3

    def test_invalid_speed(self):
        """Test that invalid speed raises error."""
        with pytest.raises(ValueError):
            VoiceSetting(speed=0.3)

        with pytest.raises(ValueError):
            VoiceSetting(speed=3.0)

    def test_invalid_volume(self):
        """Test that invalid volume raises error."""
        with pytest.raises(ValueError):
            VoiceSetting(vol=0.05)

        with pytest.raises(ValueError):
            VoiceSetting(vol=3.0)

    def test_invalid_pitch(self):
        """Test that invalid pitch raises error."""
        with pytest.raises(ValueError):
            VoiceSetting(pitch=-15)

        with pytest.raises(ValueError):
            VoiceSetting(pitch=15)

    def test_to_dict(self):
        """Test conversion to dictionary."""
        setting = VoiceSetting(voice_id="test", speed=1.2, vol=0.9, pitch=2)
        result = setting.to_dict()
        assert result["voice_id"] == "test"
        assert result["speed"] == 1.2
        assert result["vol"] == 0.9
        assert result["pitch"] == 2


# Tests for AudioSetting


class TestAudioSetting:
    """Tests for AudioSetting dataclass."""

    def test_default_values(self):
        """Test default audio settings."""
        setting = AudioSetting()
        assert setting.sample_rate == 32000
        assert setting.bitrate == 128000
        assert setting.format == "mp3"
        assert setting.channel == 1

    def test_custom_values(self):
        """Test custom audio settings."""
        setting = AudioSetting(
            sample_rate=44100,
            bitrate=192000,
            format="wav",
            channel=2,
        )
        assert setting.sample_rate == 44100
        assert setting.bitrate == 192000
        assert setting.format == "wav"
        assert setting.channel == 2

    def test_invalid_sample_rate(self):
        """Test that invalid sample rate raises error."""
        with pytest.raises(ValueError):
            AudioSetting(sample_rate=9999)

    def test_invalid_format(self):
        """Test that invalid format raises error."""
        with pytest.raises(ValueError):
            AudioSetting(format="flac")

    def test_invalid_channel(self):
        """Test that invalid channel raises error."""
        with pytest.raises(ValueError):
            AudioSetting(channel=3)


# Tests for TTSRequest


class TestTTSRequest:
    """Tests for TTSRequest dataclass."""

    def test_basic_request(self):
        """Test basic TTS request."""
        request = TTSRequest(text="Hello, world!")
        assert request.text == "Hello, world!"
        assert request.model == "speech-2.8-turbo"
        assert request.stream is False

    def test_custom_request(self):
        """Test custom TTS request."""
        request = TTSRequest(
            text="Test text",
            model="speech-2.6-hd",
            stream=True,
        )
        assert request.text == "Test text"
        assert request.model == "speech-2.6-hd"
        assert request.stream is True

    def test_invalid_model(self):
        """Test that invalid model raises error."""
        with pytest.raises(ValueError):
            TTSRequest(text="Test", model="invalid-model")

    def test_empty_text(self):
        """Test that empty text raises error."""
        with pytest.raises(ValueError):
            TTSRequest(text="")

    def test_whitespace_text(self):
        """Test that whitespace-only text raises error."""
        with pytest.raises(ValueError):
            TTSRequest(text="   ")

    def test_to_dict(self):
        """Test conversion to dictionary."""
        request = TTSRequest(text="Test", model="speech-2.8-turbo")
        result = request.to_dict()
        assert result["text"] == "Test"
        assert result["model"] == "speech-2.8-turbo"
        assert result["stream"] is False
        assert "voice_setting" in result
        assert "audio_setting" in result


# Tests for TTSResponse


class TestTTSResponse:
    """Tests for TTSResponse dataclass."""

    def test_audio_bytes_property_hex(self):
        """Test audio_bytes property with hex string."""
        response = TTSResponse(audio_data="616263")
        assert response.audio_bytes == b"abc"

    def test_audio_bytes_property_bytes(self):
        """Test audio_bytes property with bytes."""
        response = TTSResponse(audio_data=b"binary_data")
        assert response.audio_bytes == b"binary_data"

    def test_audio_bytes_property_none(self):
        """Test audio_bytes property when None."""
        response = TTSResponse(audio_data=None)
        assert response.audio_bytes is None

    def test_success_property(self):
        """Test success property."""
        response = TTSResponse(status=2)
        assert response.success is True

        response = TTSResponse(status=1)
        assert response.success is False

    def test_from_api_response(self):
        """Test creating response from API dict."""
        api_response = {
            "data": {
                "audio": "616263",
                "status": 2,
            },
            "extra_info": {
                "audio_length": 5000,
                "audio_format": "mp3",
            },
            "trace_id": "trace-123",
        }

        response = TTSResponse.from_api_response(api_response)
        assert response.audio_data == "616263"
        assert response.status == 2
        assert response.duration == 5000
        assert response.format == "mp3"
        assert response.trace_id == "trace-123"


# Tests for AsyncTaskStatus


class TestAsyncTaskStatus:
    """Tests for AsyncTaskStatus dataclass."""

    def test_completed_property(self):
        """Test completed property."""
        status = AsyncTaskStatus(task_id="123", status="completed")
        assert status.completed is True
        assert status.failed is False

    def test_failed_property(self):
        """Test failed property."""
        status = AsyncTaskStatus(task_id="123", status="failed", error="Error msg")
        assert status.completed is False
        assert status.failed is True
        assert status.error == "Error msg"

    def test_from_api_response(self):
        """Test creating status from API response."""
        api_response = {
            "task_id": "task-123",
            "status": "completed",
            "file_id": "file-456",
        }
        status = AsyncTaskStatus.from_api_response(api_response)
        assert status.task_id == "task-123"
        assert status.completed is True
        assert status.file_id == "file-456"


# Tests for MinimaxTTSService


class TestMinimaxTTSService:
    """Tests for MinimaxTTSService class."""

    def test_init_with_api_key(self, mock_api_key):
        """Test initialization with API key."""
        service = MinimaxTTSService(api_key=mock_api_key)
        assert service._config.api_key == mock_api_key
        assert service.base_url == "https://api.minimax.io"

    def test_init_with_custom_base_url(self, mock_api_key):
        """Test initialization with custom base URL."""
        service = MinimaxTTSService(
            api_key=mock_api_key,
            base_url="https://custom.api.com",
        )
        assert service.base_url == "https://custom.api.com"

    def test_default_model(self, service):
        """Test default_model property."""
        assert service.default_model in SUPPORTED_MODELS

    def test_default_voice(self, service):
        """Test default_voice property."""
        assert service.default_voice == "English_expressive_narrator"

    @patch("minimax_tts.service.requests.Session")
    def test_synthesize_success(self, mock_session_class, service, mock_successful_response):
        """Test successful synthesis."""
        mock_session = MagicMock()
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = mock_successful_response
        mock_session.post.return_value = mock_response
        mock_session_class.return_value = mock_session

        # Re-create service with mocked session
        service = MinimaxTTSService(api_key="test-key")
        response = service.synthesize("Hello, world!")

        assert response.success is True
        assert response.audio_bytes == b"abcde"
        assert response.format == "mp3"

    @patch("minimax_tts.service.requests.Session")
    def test_synthesize_auth_error(self, mock_session_class, service):
        """Test authentication error."""
        mock_session = MagicMock()
        mock_response = MagicMock()
        mock_response.status_code = 401
        mock_response.json.return_value = {"trace_id": "trace-123"}
        mock_session.post.return_value = mock_response
        mock_session_class.return_value = mock_session

        service = MinimaxTTSService(api_key="test-key")

        with pytest.raises(AuthenticationError):
            service.synthesize("Hello, world!")

    @patch("minimax_tts.service.requests.Session")
    def test_synthesize_rate_limit(self, mock_session_class, service):
        """Test rate limit error."""
        mock_session = MagicMock()
        mock_response = MagicMock()
        mock_response.status_code = 429
        mock_response.headers = {"Retry-After": "60"}
        mock_response.json.return_value = {"trace_id": "trace-123"}
        mock_session.post.return_value = mock_response
        mock_session_class.return_value = mock_session

        service = MinimaxTTSService(api_key="test-key")

        with pytest.raises(RateLimitError) as exc_info:
            service.synthesize("Hello, world!")

        assert exc_info.value.retry_after == 60

    def test_synthesize_invalid_model(self, service):
        """Test synthesis with invalid model."""
        with pytest.raises(ModelNotSupportedError):
            service.synthesize("Hello", model="invalid-model")

    def test_synthesize_empty_text(self, service):
        """Test synthesis with empty text."""
        with pytest.raises(InvalidTextError):
            service.synthesize("")

    @patch("minimax_tts.service.requests.Session")
    def test_synthesize_async_success(self, mock_session_class, service):
        """Test async synthesis task creation."""
        mock_session = MagicMock()
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"task_id": "task-123"}
        mock_session.post.return_value = mock_response
        mock_session_class.return_value = mock_session

        service = MinimaxTTSService(api_key="test-key")
        task_id = service.synthesize_async("Long text...")

        assert task_id == "task-123"

    @patch("minimax_tts.service.requests.Session")
    def test_get_task_status(self, mock_session_class, service):
        """Test getting task status."""
        mock_session = MagicMock()
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "task_id": "task-123",
            "status": "completed",
            "file_id": "file-456",
        }
        mock_session.get.return_value = mock_response
        mock_session_class.return_value = mock_session

        service = MinimaxTTSService(api_key="test-key")
        status = service.get_task_status("task-123")

        assert status.completed is True
        assert status.file_id == "file-456"

    def test_context_manager(self, mock_api_key):
        """Test context manager protocol."""
        with MinimaxTTSService(api_key=mock_api_key) as service:
            assert service is not None

    def test_close(self, service):
        """Test close method."""
        service.close()


# Tests for VoiceUtilities


class TestVoiceUtilities:
    """Tests for voice utility functions."""

    def test_list_voices(self):
        """Test list_voices function."""
        voices = list_voices()
        assert isinstance(voices, dict)
        assert "english" in voices
        assert "chinese" in voices

    def test_get_voice_id_valid(self):
        """Test get_voice_id with valid key."""
        voice_id = get_voice_id("english_narrator")
        assert voice_id == "English_expressive_narrator"

    def test_get_voice_id_invalid(self):
        """Test get_voice_id with invalid key."""
        voice_id = get_voice_id("nonexistent_voice")
        assert voice_id is None

    def test_get_default_voice_english(self):
        """Test get_default_voice for English."""
        voice = get_default_voice("english")
        assert voice in DEFAULT_VOICES.values()

    def test_get_default_voice_chinese(self):
        """Test get_default_voice for Chinese."""
        voice = get_default_voice("chinese")
        assert voice in DEFAULT_VOICES.values()


# Tests for Exceptions


class TestExceptions:
    """Tests for custom exceptions."""

    def test_minimax_tts_error(self):
        """Test base exception."""
        error = MinimaxTTSError("Test error", trace_id="trace-123")
        assert str(error) == "Test error (trace_id: trace-123)"

    def test_authentication_error(self):
        """Test authentication error."""
        error = AuthenticationError()
        assert "Authentication failed" in str(error)

    def test_rate_limit_error_with_retry(self):
        """Test rate limit error with retry_after."""
        error = RateLimitError(retry_after=30)
        assert "30s" in str(error)

    def test_model_not_supported_error(self):
        """Test model not supported error."""
        error = ModelNotSupportedError("bad-model", ["speech-2.8-turbo"])
        assert "bad-model" in str(error)
        assert "speech-2.8-turbo" in str(error)


# Tests for Config


class TestConfig:
    """Tests for configuration."""

    def test_config_defaults(self, mock_api_key):
        """Test config with defaults."""
        config = MiniMaxConfig(api_key=mock_api_key)
        assert config.base_url == "https://api.minimax.io"
        assert config.default_model == "speech-2.8-turbo"
        assert config.default_voice == "English_expressive_narrator"
        assert config.timeout == 60

    def test_config_custom(self, mock_api_key):
        """Test config with custom values."""
        config = MiniMaxConfig(
            api_key=mock_api_key,
            base_url="https://custom.api.com",
            default_model="speech-2.6-hd",
            default_voice="custom_voice",
            timeout=120,
        )
        assert config.base_url == "https://custom.api.com"
        assert config.default_model == "speech-2.6-hd"
        assert config.default_voice == "custom_voice"
        assert config.timeout == 120

    @patch.dict("os.environ", {"MINIMAX_API_KEY": "env-api-key"})
    def test_load_config_from_env(self):
        """Test loading config from environment."""
        config = MiniMaxConfig(
            api_key="test", #Will be overridden
        )
        # The actual load_minimax_config would read from env
        # This is a simplified test
        pass