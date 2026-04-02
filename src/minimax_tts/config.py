"""Configuration for MiniMax TTS service."""

from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv
import os


@dataclass(frozen=True)
class MiniMaxConfig:
    """Configuration for MiniMax TTS API.

    Attributes:
        api_key: The MiniMax API key for authentication.
        base_url: The base URL for the MiniMax API.
        default_model: Default TTS model to use.
        default_voice: Default voice ID to use.
        default_format: Default audio output format.
        default_sample_rate: Default sample rate in Hz.
        timeout: Request timeout in seconds.
    """

    api_key: str
    base_url: str = "https://api.minimax.io"
    default_model: str = "speech-2.8-turbo"
    default_voice: str = "English_expressive_narrator"
    default_format: str = "mp3"
    default_sample_rate: int = 32000
    timeout: int = 60


def load_minimax_config(env_path: Path | None = None) -> MiniMaxConfig:
    """Load MiniMax configuration from environment.

    Args:
        env_path: Optional path to .env file. If None, uses default search.

    Returns:
        A MiniMaxConfig instance with loaded values.

    Raises:
        ValueError: If MINIMAX_API_KEY is not set.
    """
    if env_path and env_path.exists():
        load_dotenv(env_path)
    else:
        # Try to load from current directory or parent directories
        load_dotenv()

    api_key = os.getenv("MINIMAX_API_KEY")
    if not api_key:
        raise ValueError(
            "MINIMAX_API_KEY not found in environment. "
            "Please set it in your .env file or export it as an environment variable."
        )

    return MiniMaxConfig(
        api_key=api_key,
        base_url=os.getenv("MINIMAX_BASE_URL", "https://api.minimax.io"),
        default_model=os.getenv("MINIMAX_DEFAULT_MODEL", "speech-2.8-turbo"),
        default_voice=os.getenv("MINIMAX_DEFAULT_VOICE", "English_expressive_narrator"),
        default_format=os.getenv("MINIMAX_DEFAULT_FORMAT", "mp3"),
        default_sample_rate=int(os.getenv("MINIMAX_DEFAULT_SAMPLE_RATE", "32000")),
        timeout=int(os.getenv("MINIMAX_TIMEOUT", "60")),
    )