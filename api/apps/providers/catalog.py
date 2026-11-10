"""What each capability can be served by, with sensible defaults.
Model/voice lists are suggestions shown in the admin UI; admins may type others."""

# Sarvam Bulbul speakers per model (docs.sarvam.ai, Oct 2026). The first entry per language is the default speaker.
# v4-flash names carry their language (`<name>_<lang>_<style>`); v2/v3 speakers are multilingual.
SARVAM_VOICES = {
    "bulbul:v4-flash": {
        "en": [
            "shubh_en_narration",
            "simran_en_customer",
            "ishita_en_customer",
            "neha_en_customer",
            "simran_en_narration",
        ],
        "ta": ["vijay_ta_narration", "gokul_ta_narration", "aravind_ta_ads", "aravind_ta_suspense"],
    },
    "bulbul:v3": {
        "en": ["shubh", "kavya", "priya", "rahul", "aditya", "ritu", "neha", "rohan"],
        "ta": ["gokul", "vijay", "kavitha", "mani", "shruti"],
    },
    "bulbul:v2": {
        "en": ["anushka", "abhilash", "manisha", "vidya", "arya", "karun", "hitesh"],
        "ta": ["anushka", "abhilash", "manisha", "vidya", "arya", "karun", "hitesh"],
    },
}

# Two clearly different podcast host voices per model and language: [host A (curious learner), host B (friendly
# expert)]. Sarvam's v4-flash Tamil catalog (docs.sarvam.ai voices, Oct 2026) has only male personas, so its Tamil hosts
# are two different male narrators; bulbul:v3 has a female Tamil voice (kavitha) for a woman/man pair.
SARVAM_HOSTS = {
    "bulbul:v4-flash": {
        "en": ["simran_en_narration", "shubh_en_narration"],
        "ta": ["gokul_ta_narration", "vijay_ta_narration"],
    },
    "bulbul:v3": {"en": ["priya", "rahul"], "ta": ["kavitha", "vijay"]},
    "bulbul:v2": {"en": ["anushka", "abhilash"], "ta": ["manisha", "karun"]},
}

_SARVAM_TTS = {
    "models": ["bulbul:v4-flash", "bulbul:v3", "bulbul:v2"],
    "default_model": "bulbul:v4-flash",
    # Each Bulbul model has its own speakers (a v2 name is rejected by v3/v4). `voices` is for the default model;
    # `voices_by_model` drives the admin suggestions and the adapter's per-model default speaker.
    "voices": SARVAM_VOICES["bulbul:v4-flash"],
    "voices_by_model": SARVAM_VOICES,
    "host_voices": SARVAM_HOSTS["bulbul:v4-flash"],
    "host_voices_by_model": SARVAM_HOSTS,
}
_GOOGLE_TTS = {
    "models": ["standard"],
    "default_model": "standard",
    "voices": {
        "en": ["en-IN-Wavenet-A", "en-IN-Wavenet-B", "en-IN-Neural2-A"],
        "ta": ["ta-IN-Wavenet-A", "ta-IN-Wavenet-B", "ta-IN-Standard-A"],
    },
    "host_voices": {
        "en": ["en-IN-Wavenet-A", "en-IN-Wavenet-B"],
        "ta": ["ta-IN-Wavenet-A", "ta-IN-Wavenet-B"],
    },
}
_OPENAI_TTS = {
    "models": ["gpt-4o-mini-tts", "tts-1"],
    "default_model": "gpt-4o-mini-tts",
    "voices": {"en": ["alloy", "coral", "sage", "verse"], "ta": ["alloy", "coral", "sage", "verse"]},
    "host_voices": {"en": ["coral", "verse"], "ta": ["coral", "verse"]},
}

# Speaking capabilities: "tts" (English, and Tamil until "tts_ta" is set up) and "tts_ta" (Tamil lines).
TTS_CAPABILITIES = ("tts", "tts_ta")

CAPABILITIES = {
    "tutor": {
        "label": "Mentor chat (tutor & authoring)",
        "providers": {
            "anthropic": {
                "models": ["claude-sonnet-5-5", "claude-opus-5-5", "claude-haiku-5-5"],
                "default_model": "claude-sonnet-5-5",
            },
            "openai": {"models": ["gpt-5", "gpt-5-mini"], "default_model": "gpt-5-mini"},
            "gemini": {"models": ["gemini-2.5-pro", "gemini-2.5-flash"], "default_model": "gemini-2.5-flash"},
        },
        "default": "anthropic",
    },
    "utility": {
        "label": "Quick tasks (grading, suggestions, onboarding)",
        "providers": {
            "anthropic": {
                "models": ["claude-haiku-5-5", "claude-sonnet-5-5"],
                "default_model": "claude-haiku-5-5",
            },
            "openai": {"models": ["gpt-5-mini", "gpt-5-nano"], "default_model": "gpt-5-mini"},
            "gemini": {
                "models": ["gemini-2.5-flash", "gemini-2.5-flash-lite"],
                "default_model": "gemini-2.5-flash",
            },
        },
        "default": "anthropic",
    },
    "stt": {
        "label": "Listening (speech-to-text)",
        "providers": {
            "browser": {"models": [], "default_model": "", "no_key": True},
            "sarvam": {"models": ["saarika:v2.5"], "default_model": "saarika:v2.5"},
            "google": {"models": ["latest_long", "default"], "default_model": "latest_long"},
            "openai": {
                "models": ["gpt-4o-mini-transcribe", "gpt-4o-transcribe", "whisper-1"],
                "default_model": "gpt-4o-mini-transcribe",
            },
            # Nova-3 understands Indian English (en-IN) and Tamil (ta); Nova-2 is English-only here.
            "deepgram": {"models": ["nova-3", "nova-2"], "default_model": "nova-3"},
        },
        "default": "browser",
    },
    "tts": {
        "label": "Speaking (text-to-speech)",
        "providers": {
            "browser": {"models": [], "default_model": "", "no_key": True, "voices": {"en": [], "ta": []}},
            "sarvam": _SARVAM_TTS,
            "google": _GOOGLE_TTS,
            "openai": _OPENAI_TTS,
            # Recommended for English. Aura-2 voices are English only (no Tamil): Tamil lines use "Speaking: Tamil"
            # when it is set up, else the learner's browser voice.
            "deepgram": {
                "models": ["aura-2"],
                "default_model": "aura-2",
                "voices": {
                    "en": [
                        "aura-2-thalia-en",
                        "aura-2-andromeda-en",
                        "aura-2-helena-en",
                        "aura-2-luna-en",
                        "aura-2-apollo-en",
                        "aura-2-arcas-en",
                        "aura-2-orion-en",
                        "aura-2-draco-en",
                        "aura-2-pandora-en",
                    ],
                    "ta": [],
                },
                # Thalia (female) and Apollo (male).
                "host_voices": {"en": ["aura-2-thalia-en", "aura-2-apollo-en"], "ta": []},
            },
        },
        "default": "browser",
        "recommended": "deepgram",
    },
    # Tamil lines get their own provider, model and key (recommended: Sarvam bulbul:v4-flash). Until it is set up, Tamil
    # uses "Speaking" above, then the learner's browser voice.
    "tts_ta": {
        "label": "Speaking: Tamil",
        "providers": {
            "browser": {"models": [], "default_model": "", "no_key": True, "voices": {"en": [], "ta": []}},
            "sarvam": _SARVAM_TTS,
            "google": _GOOGLE_TTS,
            "openai": _OPENAI_TTS,
        },
        "default": "browser",
        "recommended": "sarvam",
    },
    "image": {
        "label": "Image generation (lesson illustrations)",
        "providers": {
            "openai": {"models": ["gpt-image-1", "gpt-image-1-mini"], "default_model": "gpt-image-1"},
            "gemini": {
                "models": ["imagen-4.0-generate-001", "gemini-2.5-flash-image"],
                "default_model": "imagen-4.0-generate-001",
            },
        },
        "default": "openai",
    },
    "embedding": {
        "label": "Embeddings (smarter search in uploaded notes — optional)",
        "providers": {
            "openai": {
                "models": ["text-embedding-3-small", "text-embedding-3-large"],
                "default_model": "text-embedding-3-small",
            },
            "gemini": {
                "models": ["text-embedding-004", "gemini-embedding-001"],
                "default_model": "text-embedding-004",
            },
        },
        "default": "openai",
    },
    "vision": {
        "label": "Vision (Live Class: camera & screen)",
        "providers": {
            "anthropic": {
                "models": ["claude-sonnet-5-5", "claude-opus-5-5"],
                "default_model": "claude-sonnet-5-5",
            },
            "openai": {"models": ["gpt-5", "gpt-5-mini"], "default_model": "gpt-5-mini"},
            "gemini": {"models": ["gemini-2.5-flash", "gemini-2.5-pro"], "default_model": "gemini-2.5-flash"},
        },
        "default": "anthropic",
    },
}

DEFAULT_LIMITS = {
    "stt_seconds_per_day": 1800,
    "tts_chars_per_day": 60000,
    "vision_frames_per_day": 600,
    "images_per_day": 30,
}

# Which env var holds each provider's fallback key.
ENV_KEYS = {
    "anthropic": "ANTHROPIC_API_KEY",
    "openai": "OPENAI_API_KEY",
    "gemini": "GEMINI_API_KEY",
    "google": "GOOGLE_CLOUD_API_KEY",
    "sarvam": "SARVAM_API_KEY",
    "deepgram": "DEEPGRAM_API_KEY",
}

# LLM task → capability row.
TASK_CAPABILITY = {
    "tutor": "tutor",
    "author": "tutor",
    "grade": "utility",
    "suggest": "utility",
    "onboarding": "utility",
    "adaptive_interview": "utility",  # scenario cards + checking a learner's own use case
    "adaptive_graph": "tutor",  # concept graph of a new outline
    "org_ask": "utility",  # "Ask about my organisation": picks one query from a fixed catalog
    "vision": "vision",
}
