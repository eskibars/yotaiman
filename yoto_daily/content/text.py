"""Text generation backends.

A capability needs prose; how that prose is produced is a pluggable choice.
Three backends ship here, picked automatically by :func:`build_text_source`:

``script``
    Shells out to the local ``llm-call`` helper, which reads provider
    settings from the runtime's ``config.yaml``.  Needs a configured provider.
``openai``
    Uses the OpenAI SDK with ``OPENAI_API_KEY``.
``template``
    A local, deterministic writer.  Always available, needs no credentials,
    and keeps the daily card working when no model is configured.

The template backend is not a toy: it produces a genuinely readable narration
from a topic plus a small hand-written fact bank, so the pipeline can be
exercised end to end without spending a token.
"""

from __future__ import annotations

import random
import subprocess
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import date
from typing import Any

#: A rotating topic bank for the template writer.  Deliberately broad and
#: durable -- these are things a young listener will not have exhausted.
TOPIC_BANK: list[dict[str, Any]] = [
    {
        "topic": "dolphins",
        "title": "The Dolphin Who Could Whistle",
        "facts": [
            "Dolphins talk to each other with clicks and whistles.",
            "They sleep with half of their brain awake, so one eye stays open.",
            "A dolphin's name is its whistle -- every dolphin has its own.",
            "They help each other when one gets stuck or hurt.",
        ],
    },
    {
        "topic": "honeybees",
        "title": "How the Honeybees Made Honey",
        "facts": [
            "Bees dance a wiggle dance to tell the hive where the flowers are.",
            "One bee visits about two thousand flowers to make one spoonful of honey.",
            "Bees never sleep in winter. They huddle and shiver to stay warm.",
            "Bees can see colours that we cannot see at all.",
        ],
    },
    {
        "topic": "rainbows",
        "title": "Why Rainbows Are Round",
        "facts": [
            "A rainbow is sunlight bent into a circle by tiny drops of rain.",
            "Every rainbow is really a full circle, but we only see the top half.",
            "With a garden hose on a sunny day, you can make your own rainbow.",
            "A rainbow always appears opposite the sun, so it is in the sky behind you.",
        ],
    },
    {
        "topic": "volcanoes",
        "title": "The Mountain That Sneezes Fire",
        "facts": [
            "A volcano is just a mountain with hot rock inside it.",
            "The rocks inside melt into a liquid called magma.",
            "When the magma pushes out of the ground it is called lava.",
            "Ash from a volcano can travel around the whole world in the wind.",
        ],
    },
    {
        "topic": "sleeping animals",
        "title": "Who Sleeps the Longest",
        "facts": [
            "Most animals sleep between two and five hours a night.",
            "A koala can sleep for twenty hours a day.",
            "Dolphins sleep with half their brain at a time so they can breathe.",
            "Little brown bats can sleep for twenty hours too, but in short naps.",
        ],
    },
    {
        "topic": "the moon",
        "title": "Why the Moon Follows the Car",
        "facts": [
            "The Moon is about four hundred thousand kilometres away.",
            "It takes the Earth a whole year to go around the Sun.",
            "The Moon has no light of its own. It bounces sunlight back at us.",
            "Footprints stay on the Moon forever, because there is no wind.",
        ],
    },
    {
        "topic": "octopuses",
        "title": "The Clever Eight-Armed Swimmer",
        "facts": [
            "An octopus has three hearts and blue blood.",
            "Each arm has its own brain and can taste what it touches.",
            "Octopuses squeeze through any gap that is bigger than their beak.",
            "They can change colour and texture in about a second.",
        ],
    },
    {
        "topic": "trees",
        "title": "How Trees Talk to Each Other",
        "facts": [
            "Trees grow rings every year, and you can count them like birthdays.",
            "Underground, fungi connect the roots of different trees.",
            "That network lets a tree pass warnings to its neighbours about bugs.",
            "A large tree moves hundreds of litres of water in a day.",
        ],
    },
    {
        "topic": "birds",
        "title": "Why Birds Sing at Dawn",
        "facts": [
            "Birds sing at dawn because it is the noisiest time for them to be heard.",
            "Their songs are different in every part of the world.",
            "Birds learn their song from their parents, just like you learn a language.",
            "Some birds can tell the difference between their own chicks and other birds.",
        ],
    },
    {
        "topic": "lightning",
        "title": "The Sky That Cracks",
        "facts": [
            "Lightning is electricity, made when clouds rub together.",
            "The flash is so bright you can see it from a hundred kilometres away.",
            "Thunder is the sound of the air being pushed by the lightning.",
            "You can count the seconds between them to work out how far away it is.",
        ],
    },
]


@dataclass
class Story:
    """A generated narration."""

    title: str
    body: str
    topic: str = ""
    backend: str = ""
    meta: dict[str, Any] = field(default_factory=dict)


class TextSource(ABC):
    """Produces a :class:`Story` for a topic."""

    name = "base"

    @abstractmethod
    def generate(self, topic: str | None = None, *, child_name: str = "", **kwargs: Any) -> Story:
        """Generate a story."""

    def available(self) -> bool:
        """Whether this backend can currently be used."""
        return True

    def describe(self) -> dict[str, Any]:
        return {"backend": self.name, "available": self.available()}


class TemplateTextSource(TextSource):
    """A local writer that needs no credentials.

    It picks facts from the topic bank and weaves them into a short
    narration.  The result is deliberately plain-spoken and short -- it is
    meant to be listened to, not read.
    """

    name = "template"

    def __init__(self, topics: list[dict[str, Any]] | None = None) -> None:
        self.topics = topics or TOPIC_BANK

    def available(self) -> bool:
        return bool(self.topics)

    def generate(self, topic: str | None = None, *, child_name: str = "", **kwargs: Any) -> Story:
        if topic:
            entry = next((t for t in self.topics if t["topic"] == topic), None)
            if entry is None:
                entry = {
                    "topic": topic,
                    "title": topic.replace("-", " ").title(),
                    "facts": [
                        f"{topic.replace('-', ' ').title()} is a wonderful thing to learn about.",
                        "There is always something surprising hiding in the details.",
                        "Watching carefully is how most discoveries start.",
                    ],
                }
        else:
            # Rotate by day so an unattended daily job stays varied but stable.
            seed = date.today().toordinal()
            entry = self.topics[seed % len(self.topics)]

        facts = list(entry["facts"])
        rng = random.Random(f"{date.today().isoformat()}:{entry['topic']}")
        rng.shuffle(facts)

        who = child_name or "friend"
        subject = entry["topic"].replace("-", " ")

        # Lead with the first fact, then lead-in the rest.  The number of
        # facts varies, so the body is assembled rather than templated.
        paragraphs = [
            f"Hello {who}. Today we are going to talk about {subject}.",
            facts[0],
            facts[1] if len(facts) > 1 else "",
        ]
        lead_ins = [
            "Here is one more thing.",
            "And one last surprise.",
            "And here is something else.",
        ]
        for index, fact in enumerate(facts[2:]):
            lead_in = lead_ins[index % len(lead_ins)]
            paragraphs.append(f"{lead_in} {fact}")

        paragraphs.append(
            f"{subject.capitalize()} is a good place to start if you want to "
            "learn more. Tomorrow we will find out something new together."
        )

        body = "\n\n".join(p for p in paragraphs if p).strip()

        return Story(
            title=entry["title"],
            body=body,
            topic=entry["topic"],
            backend=self.name,
        )


class ScriptTextSource(TextSource):
    """Calls the local ``llm-call`` helper script."""

    name = "script"

    def __init__(self, script: str, model: str, *, python: str = "python3") -> None:
        self.script = script
        self.model = model
        self.python = python

    def available(self) -> bool:
        import os

        return bool(self.model) and os.path.exists(self.script)

    def generate(self, topic: str | None = None, *, child_name: str = "", **kwargs: Any) -> Story:
        if not self.available():
            raise RuntimeError(f"llm script not available at {self.script}")

        topic = topic or "something wonderful in nature"
        system = (
            "You write short stories that a six year old listens to on a Yoto "
            "audio player. Use plain, warm, concrete language. No lists, no "
            "headings, no stage directions. Three to five short paragraphs, "
            "about 150 words. End by asking a question."
        )
        prompt = f"Write a short story about {topic}."
        if child_name:
            prompt += f" Address the listener as {child_name}."

        proc = subprocess.run(
            [
                self.python, self.script,
                "--model", self.model,
                "--system", system,
                "--prompt", prompt,
                "--max-tokens", "700",
            ],
            capture_output=True,
            text=True,
            timeout=kwargs.get("timeout", 300),
        )
        if proc.returncode != 0:
            raise RuntimeError(
                f"llm script failed ({proc.returncode}): {(proc.stderr or proc.stdout)[:300]}"
            )
        body = (proc.stdout or "").strip()
        if not body:
            raise RuntimeError("llm script returned no text")

        title = self._derive_title(body, topic)
        return Story(title=title, body=body, topic=topic, backend=self.name)

    @staticmethod
    def _derive_title(body: str, topic: str) -> str:
        first = body.split("\n", 1)[0].strip().rstrip(".")
        if 0 < len(first) <= 60:
            return first
        return topic.replace("-", " ").title()


class OpenAITextSource(TextSource):
    """Uses the OpenAI chat completions API."""

    name = "openai"

    def __init__(self, api_key: str, model: str = "gpt-4o-mini") -> None:
        self.api_key = api_key
        self.model = model

    def available(self) -> bool:
        return bool(self.api_key)

    def generate(self, topic: str | None = None, *, child_name: str = "", **kwargs: Any) -> Story:
        if not self.available():
            raise RuntimeError("OPENAI_API_KEY is not set")

        from openai import OpenAI

        client = OpenAI(api_key=self.api_key)
        topic = topic or "something wonderful in nature"
        system = (
            "You write short stories that a six year old listens to on a Yoto "
            "audio player. Plain, warm, concrete language. Three to five short "
            "paragraphs, about 150 words. No lists or headings."
        )
        prompt = f"Write a short story about {topic}."
        if child_name:
            prompt += f" Address the listener as {child_name}."

        resp = client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
            max_tokens=700,
        )
        body = (resp.choices[0].message.content or "").strip()
        if not body:
            raise RuntimeError("OpenAI returned no text")
        return Story(
            title=ScriptTextSource._derive_title(body, topic),
            body=body,
            topic=topic,
            backend=self.name,
            meta={"model": self.model},
        )


class FallbackTextSource(TextSource):
    """Tries several backends in order until one produces a story.

    This is what ``auto`` resolves to.  A backend that fails with an
    authentication or configuration error is remembered and skipped for the
    rest of the process, so a broken provider costs one failed call rather
    than one per story.
    """

    name = "fallback"

    def __init__(self, sources: list[TextSource]) -> None:
        self.sources = list(sources)
        self._disabled: set[str] = set()

    def available(self) -> bool:
        return any(s.name not in self._disabled and s.available() for s in self.sources)

    def describe(self) -> dict[str, Any]:
        return {
            "backend": self.name,
            "available": self.available(),
            "chain": [
                {
                    "backend": s.name,
                    "available": s.available(),
                    "disabled": s.name in self._disabled,
                }
                for s in self.sources
            ],
        }

    def generate(self, topic: str | None = None, *, child_name: str = "", **kwargs: Any) -> Story:
        errors: list[str] = []
        for source in self.sources:
            if source.name in self._disabled:
                continue
            if not source.available():
                continue
            try:
                story = source.generate(topic, child_name=child_name, **kwargs)
            except Exception as exc:
                message = f"{source.name}: {exc}"
                errors.append(message)
                if _is_permanent_failure(exc):
                    self._disabled.add(source.name)
                continue
            story.meta.setdefault("fallback_errors", errors)
            return story

        raise RuntimeError(
            "no text backend could generate a story: "
            + ("; ".join(errors) if errors else "none available")
        )


def _is_permanent_failure(exc: Exception) -> bool:
    """Whether a backend failure is worth remembering rather than retrying."""
    text = f"{exc}".lower()
    if any(
        marker in text
        for marker in (
            "401",
            "403",
            "unauthorized",
            "api key",
            "token is required",
            "not configured",
            "no module named",
            "not on path",
        )
    ):
        return True
    return isinstance(exc, (ImportError, FileNotFoundError, PermissionError))


def build_text_source(
    *,
    backend: str = "auto",
    script: str = "",
    script_model: str = "",
    openai_key: str = "",
    openai_model: str = "gpt-4o-mini",
) -> TextSource:
    """Pick a text backend.

    ``auto`` prefers a real model and falls back to the local template so the
    service is never dead in the water.
    """
    template = TemplateTextSource()

    if backend == "template":
        return template
    if backend == "script":
        return ScriptTextSource(script, script_model)
    if backend == "openai":
        return OpenAITextSource(openai_key, openai_model)

    chain: list[TextSource] = []
    if openai_key:
        chain.append(OpenAITextSource(openai_key, openai_model))
    if script and script_model:
        chain.append(ScriptTextSource(script, script_model))
    chain.append(template)
    return FallbackTextSource(chain)


def topic_suggestions() -> list[dict[str, Any]]:
    """The rotating topic bank, for the API listing."""
    return [{"topic": t["topic"], "title": t["title"]} for t in TOPIC_BANK]
