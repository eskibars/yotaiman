"""Content backends: text generation and text-to-speech."""

from __future__ import annotations

from .text import (
    Story,
    TextSource,
    OpenAITextSource,
    ScriptTextSource,
    TemplateTextSource,
    build_text_source,
    topic_suggestions,
)
from .tts import AudioResult, HTTPVoiceBackend, MacSayBackend, TTSBackend, build_tts_backend

__all__ = [
    "Story",
    "TextSource",
    "TemplateTextSource",
    "ScriptTextSource",
    "OpenAITextSource",
    "build_text_source",
    "topic_suggestions",
    "AudioResult",
    "TTSBackend",
    "MacSayBackend",
    "HTTPVoiceBackend",
    "build_tts_backend",
]
