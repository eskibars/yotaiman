"""Music and speech generators.

``MusicGenerator`` and ``SpeechGenerator`` are the two families a capability
asks for audio.  Which concrete implementation runs is decided by
``config.yaml``.
"""

from __future__ import annotations

from .base import (
    AudioResult,
    Generator,
    GeneratorInfo,
    MusicGenerator,
    MusicSpec,
    SpeechGenerator,
)
from .ming_tts import MingTTSSpeechGenerator, build_ming_tts_generator
from .music import AceStepMusicGenerator, SynthMusicGenerator
from .registry import (
    GeneratorError,
    GeneratorRegistry,
    build_registry,
    default_registry,
)
from .speech import HTTPSpeechGenerator, SaySpeechGenerator

__all__ = [
    "AudioResult",
    "Generator",
    "GeneratorInfo",
    "MusicGenerator",
    "MusicSpec",
    "SpeechGenerator",
    "AceStepMusicGenerator",
    "MingTTSSpeechGenerator",
    "SynthMusicGenerator",
    "SaySpeechGenerator",
    "HTTPSpeechGenerator",
    "GeneratorRegistry",
    "GeneratorError",
    "build_ming_tts_generator",
    "build_registry",
    "default_registry",
]
