"""Custom exceptions for MiniMax TTS service."""


class MinimaxTTSError(Exception):
    """Base exception for MiniMax TTS errors."""

    def __init__(self, message: str, trace_id: str | None = None):
        self.message = message
        self.trace_id = trace_id
        super().__init__(self.message)

    def __str__(self) -> str:
        if self.trace_id:
            return f"{self.message} (trace_id: {self.trace_id})"
        return self.message


class AuthenticationError(MinimaxTTSError):
    """Raised when API authentication fails."""

    def __init__(self, message: str = "Authentication failed. Check your API key.", trace_id: str | None = None):
        super().__init__(message, trace_id)


class RateLimitError(MinimaxTTSError):
    """Raised when API rate limit is exceeded."""

    def __init__(self, message: str = "Rate limit exceeded. Please retry after some time.", trace_id: str | None = None, retry_after: int | None = None):
        super().__init__(message, trace_id)
        self.retry_after = retry_after

    def __str__(self) -> str:
        base = super().__str__()
        if self.retry_after:
            return f"{base} (retry after {self.retry_after}s)"
        return base


class InvalidTextError(MinimaxTTSError):
    """Raised when the input text is invalid."""

    def __init__(self, message: str = "Invalid text input.", trace_id: str | None = None):
        super().__init__(message, trace_id)


class ModelNotSupportedError(MinimaxTTSError):
    """Raised when an unsupported model is specified."""

    def __init__(self, model: str, supported_models: list[str] | None = None):
        message = f"Model '{model}' is not supported."
        if supported_models:
            message += f" Supported models: {', '.join(supported_models)}"
        super().__init__(message)


class VoiceNotFoundError(MinimaxTTSError):
    """Raised when a specified voice is not found."""

    def __init__(self, voice_id: str):
        super().__init__(f"Voice '{voice_id}' not found.")


class AsyncTaskError(MinimaxTTSError):
    """Raised when an async TTS task fails."""

    def __init__(self, task_id: str, message: str = "Async task failed"):
        super().__init__(f"{message} (task_id: {task_id})")