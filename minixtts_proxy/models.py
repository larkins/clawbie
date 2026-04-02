"""
Voice name mappings between OpenAI-style names and MiniMax voice IDs.

OpenClaw sends OpenAI-style voice names (alloy, nova, shimmer, etc).
MiniMax uses its own voice IDs (English_expressive_narrator, etc).
"""

# Default voice to use when none specified
DEFAULT_VOICE = "English_expressive_narrator"
DEFAULT_MODEL = "speech-2.8-hd"

# MiniMax voice ID registry (as returned by the API)
MINIMAX_VOICES = {
    # English
    "English_expressive_narrator": "English_expressive_narrator",
    "English_storyteller": "English_Storyteller",
    "English_friendly_guide": "English_Friendly_Guide",
    "English_professional": "English_Professional",
    # Chinese
    "female-tianmei": "female-tianmei",
    "male-qn-qingse": "male-qn-qingse",
    "male-qn-jingping": "male-qn-jingping",
    "presenter_male": "presenter_male",
    # Other languages
    "Japanese_female": "Japanese_female",
    "Japanese_male": "Japanese_male",
    "Korean_female": "Korean_female",
    "Korean_male": "Korean_male",
    "Spanish_female": "Spanish_female",
    "Spanish_male": "Spanish_male",
    "French_female": "French_female",
    "French_male": "French_male",
    "German_female": "German_female",
    "German_male": "German_male",
}

# OpenAI voice names that map to MiniMax voices
# Strategy: map by "vibe" rather than 1:1
OPENAI_VOICE_MAP = {
    # Alloy = neutral, good for general purpose — expressive narrator
    "alloy": "English_expressive_narrator",
    # Nova = warm, friendly — friendly guide
    "nova": "English_Friendly_Guide",
    # Onyx = deep, professional male — professional
    "onyx": "English_Professional",
    # Shimmer = expressive female — expressive narrator
    "shimmer": "English_expressive_narrator",
    # Echo = deeper male — professional
    "echo": "English_Professional",
    # Fable = storytelling — storyteller
    "fable": "English_Storyteller",
    # Onix = deep male — professional
    "onyx": "English_Professional",
    # Coral = bright female — friendly guide
    "coral": "English_Friendly_Guide",
    # Sage = calm neutral — expressive narrator
    "sage": "English_expressive_narrator",
    # Verse = clear neutral — expressive narrator
    "verse": "English_expressive_narrator",
}

# Supported MiniMax models
SUPPORTED_MODELS = ["speech-02-hd", "speech-02-turbo", "speech-2.8-hd", "speech-2.8-turbo"]


def resolve_voice(voice_name: str) -> str:
    """
    Resolve an OpenAI-style voice name to a MiniMax voice ID.
    Falls back to DEFAULT_VOICE if unknown.
    """
    if not voice_name:
        return DEFAULT_VOICE
    # Already a MiniMax voice ID
    if voice_name in MINIMAX_VOICES:
        return voice_name
    # Try OpenAI voice mapping
    return OPENAI_VOICE_MAP.get(voice_name.lower(), DEFAULT_VOICE)


def resolve_model(model: str) -> str:
    """Resolve a model name to a MiniMax model ID."""
    if not model:
        return DEFAULT_MODEL
    model = model.lower().strip()
    if model.startswith("speech-"):
        return model
    if model in ["hd", "high-definition"]:
        return "speech-02-hd"
    if model in ["turbo", "fast"]:
        return "speech-02-turbo"
    return DEFAULT_MODEL
