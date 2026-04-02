"""MiniMax TTS Service Module.

This module provides the core TTS (Text-to-Speech) service for the MiniMax API.
"""

from typing import Any

import requests

from .config import MiniMaxConfig, load_minimax_config
from .exceptions import (
    AuthenticationError,
    AsyncTaskError,
    InvalidTextError,
    MinimaxTTSError,
    ModelNotSupportedError,
    RateLimitError,
)
from .models import (
    AsyncTaskStatus,
    SUPPORTED_MODELS,
    TTSRequest,
    TTSResponse,
)
from .voices import get_default_voice


class MinimaxTTSService:
    """MiniMax Text-to-Speech Service.

    This class provides methods for synthesizing speech from text using
    the MiniMax TTS API.

    Example:
        >>> service = MinimaxTTSService(api_key="your-api-key")
        >>> response = service.synthesize("Hello, world!")
        >>> audio_bytes = response.audio_bytes
    """

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str = "https://api.minimax.io",
        config: MiniMaxConfig | None = None,
    ):
        """Initialize the TTS service.

        Args:
            api_key: MiniMax API key. If not provided, loads from environment.
            base_url: Base URL for the MiniMax API.
            config: Pre-loaded configuration. If provided, other args are ignored.

        Raises:
            ValueError: If no API key is provided and none found in environment.
        """
        if config:
            self._config = config
        elif api_key:
            self._config = MiniMaxConfig(api_key=api_key, base_url=base_url)
        else:
            self._config = load_minimax_config()

        self._session = requests.Session()
        self._session.headers.update(
            {
                "Authorization": f"Bearer {self._config.api_key}",
                "Content-Type": "application/json",
            }
        )

    @property
    def base_url(self) -> str:
        """Get the base URL for the API."""
        return self._config.base_url

    @property
    def default_model(self) -> str:
        """Get the default TTS model."""
        return self._config.default_model

    @property
    def default_voice(self) -> str:
        """Get the default voice ID."""
        return self._config.default_voice

    def synthesize(
        self,
        text: str,
        model: str | None = None,
        voice_id: str | None = None,
        speed: float = 1.0,
        pitch: int = 0,
        volume: float = 1.0,
        audio_format: str = "mp3",
        sample_rate: int = 32000,
        stream: bool = False,
        **kwargs: Any,
    ) -> TTSResponse:
        """Synthesize speech from text.

        Args:
            text: The text to synthesize.
            model: TTS model to use (default: speech-2.8-turbo).
            voice_id: Voice identifier (default: English_expressive_narrator).
            speed: Speech speed multiplier (0.5-2.0, default 1.0).
            pitch: Pitch adjustment (-12 to 12, default 0).
            volume: Volume level (0.1-2.0, default 1.0).
            audio_format: Output format ("mp3", "wav", "pcm", "ogg").
            sample_rate: Sample rate in Hz.
            stream: Whether to stream the response.
            **kwargs: Additional options passed to TTSRequest.

        Returns:
            A TTSResponse containing the synthesized audio.

        Raises:
            AuthenticationError: If API authentication fails.
            RateLimitError: If rate limit is exceeded.
            InvalidTextError: If the input text is invalid.
            MinimaxTTSError: For other API errors.
        """
        model = model or self._config.default_model
        voice_id = voice_id or self._config.default_voice

        # Validate model
        if model not in SUPPORTED_MODELS:
            raise ModelNotSupportedError(model, SUPPORTED_MODELS)

        # Validate text
        if not text or not text.strip():
            raise InvalidTextError("Text cannot be empty")

        # Build request
        from .models import AudioSetting, VoiceSetting

        voice_setting = VoiceSetting(
            voice_id=voice_id,
            speed=speed,
            vol=volume,
            pitch=pitch,
        )

        audio_setting = AudioSetting(
            sample_rate=sample_rate,
            format=audio_format,
        )

        request = TTSRequest(
            text=text,
            model=model,
            voice_setting=voice_setting,
            audio_setting=audio_setting,
            stream=stream,
        )

        return self._synthesize(request)

    def _synthesize(self, request: TTSRequest) -> TTSResponse:
        """Execute a TTS synthesis request.

        Args:
            request: The TTS request to execute.

        Returns:
            A TTSResponse with the synthesized audio.

        Raises:
            MinimaxTTSError: For API errors.
        """
        url = f"{self._config.base_url}/v1/t2a_v2"

        try:
            response = self._session.post(
                url,
                json=request.to_dict(),
                timeout=self._config.timeout,
            )

            return self._handle_response(response)

        except requests.Timeout:
            raise MinimaxTTSError("Request timed out")
        except requests.RequestException as e:
            raise MinimaxTTSError(f"Request failed: {e}")

    def _handle_response(self, response: requests.Response) -> TTSResponse:
        """Handle an API response.

        Args:
            response: The HTTP response.

        Returns:
            A TTSResponse instance.

        Raises:
            AuthenticationError: For auth failures.
            RateLimitError: For rate limit errors.
            InvalidTextError: For invalid input.
            MinimaxTTSError: For other errors.
        """
        trace_id = None

        try:
            data = response.json()
            trace_id = data.get("trace_id")
        except Exception:
            data = {}

        if response.status_code == 401:
            raise AuthenticationError(trace_id=trace_id)

        if response.status_code == 429:
            retry_after = response.headers.get("Retry-After")
            retry_seconds = int(retry_after) if retry_after else None
            raise RateLimitError(trace_id=trace_id, retry_after=retry_seconds)

        if response.status_code == 400:
            error_msg = data.get("message", "Invalid request")
            if "text" in error_msg.lower():
                raise InvalidTextError(error_msg, trace_id)
            raise MinimaxTTSError(error_msg, trace_id)

        if response.status_code >= 400:
            error_msg = data.get("message", f"API error: {response.status_code}")
            raise MinimaxTTSError(error_msg, trace_id)

        return TTSResponse.from_api_response(data)

    def synthesize_async(
        self,
        text: str,
        model: str | None = None,
        voice_id: str | None = None,
        **kwargs: Any,
    ) -> str:
        """Start an async TTS task for long texts.

        Use this for texts longer than 1000 characters.

        Args:
            text: The text to synthesize.
            model: TTS model to use.
            voice_id: Voice identifier.
            **kwargs: Additional options.

        Returns:
            A task ID for tracking the async task.

        Raises:
            MinimaxTTSError: For API errors.
        """
        model = model or self._config.default_model
        voice_id = voice_id or self._config.default_voice

        if model not in SUPPORTED_MODELS:
            raise ModelNotSupportedError(model, SUPPORTED_MODELS)

        from .models import AudioSetting, VoiceSetting

        voice_setting = kwargs.get("voice_setting", VoiceSetting(voice_id=voice_id))
        audio_setting = kwargs.get("audio_setting", AudioSetting())

        request = TTSRequest(
            text=text,
            model=model,
            voice_setting=voice_setting,
            audio_setting=audio_setting,
        )

        url = f"{self._config.base_url}/v1/t2a_async_v2"

        try:
            response = self._session.post(
                url,
                json=request.to_dict(),
                timeout=self._config.timeout,
            )

            data = response.json()

            if response.status_code >= 400:
                error_msg = data.get("message", "Failed to create async task")
                raise MinimaxTTSError(error_msg, data.get("trace_id"))

            task_id = data.get("task_id")
            if not task_id:
                raise MinimaxTTSError("No task_id in response")

            return task_id

        except requests.Timeout:
            raise MinimaxTTSError("Request timed out")
        except requests.RequestException as e:
            raise MinimaxTTSError(f"Request failed: {e}")

    def get_task_status(self, task_id: str) -> AsyncTaskStatus:
        """Get the status of an async TTS task.

        Args:
            task_id: The task ID returned by synthesize_async.

        Returns:
            An AsyncTaskStatus with the current task status.

        Raises:
            MinimaxTTSError: For API errors.
        """
        url = f"{self._config.base_url}/v1/query/t2a_async_query_v2"
        params = {"task_id": task_id}

        try:
            response = self._session.get(
                url,
                params=params,
                timeout=self._config.timeout,
            )

            data = response.json()

            if response.status_code >= 400:
                error_msg = data.get("message", "Failed to get task status")
                raise MinimaxTTSError(error_msg, data.get("trace_id"))

            return AsyncTaskStatus.from_api_response(data)

        except requests.Timeout:
            raise MinimaxTTSError("Request timed out")
        except requests.RequestException as e:
            raise MinimaxTTSError(f"Request failed: {e}")

    def download_audio(self, file_id: str) -> bytes:
        """Download audio from a completed async task.

        Args:
            file_id: The file ID from a completed async task.

        Returns:
            The audio data as bytes.

        Raises:
            MinimaxTTSError: For API errors.
        """
        url = f"{self._config.base_url}/v1/files/retrieve_content"
        params = {"file_id": file_id}

        try:
            response = self._session.get(
                url,
                params=params,
                timeout=self._config.timeout,
            )

            if response.status_code >= 400:
                try:
                    data = response.json()
                    error_msg = data.get("message", "Failed to download audio")
                except Exception:
                    error_msg = f"Failed to download audio: {response.status_code}"
                raise MinimaxTTSError(error_msg)

            return response.content

        except requests.Timeout:
            raise MinimaxTTSError("Request timed out")
        except requests.RequestException as e:
            raise MinimaxTTSError(f"Request failed: {e}")

    def wait_for_task(
        self,
        task_id: str,
        poll_interval: float = 2.0,
        max_wait: float = 300.0,
    ) -> bytes:
        """Wait for an async task to complete and return the audio.

        Args:
            task_id: The task ID to wait for.
            poll_interval: Seconds between status checks (default 2.0).
            max_wait: Maximum seconds to wait (default 300.0 / 5 minutes).

        Returns:
            The audio data as bytes.

        Raises:
            AsyncTaskError: If the task fails.
            MinimaxTTSError: If max_wait is exceeded.
        """
        import time

        elapsed = 0.0
        while elapsed < max_wait:
            status = self.get_task_status(task_id)

            if status.completed:
                if not status.file_id:
                    raise AsyncTaskError(task_id, "Task completed but no file_id")
                return self.download_audio(status.file_id)

            if status.failed:
                error = status.error or "Task failed"
                raise AsyncTaskError(task_id, error)

            time.sleep(poll_interval)
            elapsed += poll_interval

        raise MinimaxTTSError(f"Task {task_id} did not complete within {max_wait} seconds")

    def synthesize_long(
        self,
        text: str,
        model: str | None = None,
        voice_id: str | None = None,
        **kwargs: Any,
    ) -> bytes:
        """Synthesize long text using async API and wait for result.

        This is a convenience method that handles async synthesis
        automatically.

        Args:
            text: The text to synthesize.
            model: TTS model to use.
            voice_id: Voice identifier.
            **kwargs: Additional options.

        Returns:
            The audio data as bytes.
        """
        task_id = self.synthesize_async(text, model, voice_id, **kwargs)
        return self.wait_for_task(task_id)

    def close(self) -> None:
        """Close the HTTP session."""
        self._session.close()

    def __enter__(self) -> "MinimaxTTSService":
        """Context manager entry."""
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        """Context manager exit."""
        self.close()