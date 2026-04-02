"""Voice utilities for MiniMax TTS service.

This module provides voice-related utilities including available voice IDs
and functions for voice management.
"""

from typing import Any

# Default voice IDs for common languages
# These are commonly used built-in voices from MiniMax
DEFAULT_VOICES: dict[str, str] = {
    # English voices
    "english_narrator": "English_expressive_narrator",
    "english_female": "female-voice-1",
    "english_male": "male-voice-1",
    # Chinese voices
    "chinese_female": "female-tianmei",
    "chinese_male": "male-qn-qingse",
    # Other languages
    "japanese_female": "Japanese_female",
    "korean_female": "Korean_female",
    "spanish_female": "Spanish_female",
    "french_female": "French_female",
    "german_female": "German_female",
}

# System voices organized by language/category
SYSTEM_VOICES: dict[str, dict[str, str]] = {
    "english": {
        "expressive_narrator": "English_expressive_narrator",
        "storyteller": "English_Storyteller",
        "friendly_guide": "English_Friendly_Guide",
        "professional": "English_Professional",
    },
    "chinese": {
        "tianmei": "female-tianmei",
        "qingse": "male-qn-qingse",
        "jingping": "male-qn-jingping",
        "beijing_dialect": "presenter_male",
    },
    "japanese": {
        "female": "Japanese_female",
        "male": "Japanese_male",
    },
    "korean": {
        "female": "Korean_female",
        "male": "Korean_male",
    },
    "spanish": {
        "female": "Spanish_female",
        "male": "Spanish_male",
    },
    "french": {
        "female": "French_female",
        "male": "French_male",
    },
    "german": {
        "female": "German_female",
        "male": "German_male",
    },
}


def list_voices() -> dict[str, dict[str, str]]:
    """Return all available system voices organized by language.

    Returns:
        A dictionary of voices organized by language category.
        Each language contains voice name -> voice_id mappings.

    Example:
        >>> voices = list_voices()
        >>> print(voices["english"]["expressive_narrator"])
        'English_expressive_narrator'
    """
    return SYSTEM_VOICES.copy()


def list_english_voices() -> dict[str, str]:
    """Return available English voices.

    Returns:
        A dictionary of English voice name -> voice ID mappings.
    """
    return SYSTEM_VOICES.get("english", {}).copy()


def list_chinese_voices() -> dict[str, str]:
    """Return available Chinese voices.

    Returns:
        A dictionary of Chinese voice name -> voice ID mappings.
    """
    return SYSTEM_VOICES.get("chinese", {}).copy()


def get_voice_id(voice_key: str) -> str | None:
    """Get a voice ID by its key name.

    Args:
        voice_key: A shorthand voice key (e.g., "english_narrator", "chinese_female").

    Returns:
        The voice ID if found, None otherwise.

    Example:
        >>> get_voice_id("english_narrator")
        'English_expressive_narrator'
    """
    # First check default voices
    if voice_key in DEFAULT_VOICES:
        return DEFAULT_VOICES[voice_key]

    # Then search in system voices
    for language_voices in SYSTEM_VOICES.values():
        if voice_key in language_voices:
            return language_voices[voice_key]

    return None


def get_default_voice(language: str = "english") -> str:
    """Get the default voice ID for a language.

    Args:
        language: The language key (default: "english").

    Returns:
        The default voice ID for the specified language.

    Raises:
        KeyError: If the language is not found.
    """
    language = language.lower()
    if language == "english":
        return DEFAULT_VOICES["english_narrator"]
    elif language == "chinese":
        return DEFAULT_VOICES["chinese_female"]

    # Find in system voices
    if language in SYSTEM_VOICES:
        voices = list(SYSTEM_VOICES[language].values())
        if voices:
            return voices[0]

    raise KeyError(f"No default voice found for language: {language}")


def get_all_voice_ids() -> list[str]:
    """Return a flat list of all available voice IDs.

    Returns:
        A list of all voice ID strings.
    """
    voice_ids = []
    for voices in SYSTEM_VOICES.values():
        voice_ids.extend(voices.values())
    return voice_ids