"""Themes: everything that belongs to one topic on the card.

A theme is more than a story.  It is the identity of the card -- the name a
child sees in the Yoto app -- and it carries everything that goes with it:

* a **story**, told out loud in somebody's voice
* a **fact corner**, the true parts, checked against a source
* a **song**, with lyrics and a style for the music generator to render

Keeping the three together is the point.  A card is one thing to a child, so
the thing it holds should be one thing too.

The writers produce the bundle.  ``template`` needs nothing but this package;
``ollama`` asks a model running on the same machine.  Neither is a toy: both
produce a card a child would sit through.
"""

from __future__ import annotations

import json
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from .ollama import DEFAULT_ENDPOINT, DEFAULT_MODEL, OllamaClient, OllamaError


def slugify(text: str) -> str:
    """A short, URL-safe name for a topic."""
    slug = re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")
    return slug[:48] or "theme"


def titleise(text: str) -> str:
    """``exoplanets`` -> ``Exoplanets``."""
    words = re.sub(r"[-_]+", " ", (text or "").strip()).split()
    return " ".join(w[:1].upper() + w[1:] for w in words) if words else "Theme"


@dataclass
class Theme:
    """One day's content, for one topic."""

    slug: str
    name: str
    title: str
    story: str
    facts: str
    song_title: str = ""
    song_lyrics: str = ""
    song_prompt: str = ""
    backend: str = ""
    meta: dict[str, Any] = field(default_factory=dict)

    @property
    def word_count(self) -> int:
        """How many words the whole thing is, spoken and sung."""
        return len(
            (self.story + " " + self.facts + " " + self.song_lyrics).split()
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "slug": self.slug,
            "name": self.name,
            "title": self.title,
            "story": self.story,
            "facts": self.facts,
            "song_title": self.song_title,
            "song_lyrics": self.song_lyrics,
            "song_prompt": self.song_prompt,
            "backend": self.backend,
            "meta": dict(self.meta),
        }


# ----------------------------------------------------------------------
# writers
# ----------------------------------------------------------------------
class ThemeWriter(ABC):
    """Produces a :class:`Theme` for a topic."""

    name = "base"

    @abstractmethod
    def write(
        self,
        theme: str,
        *,
        audience: str = "",
        notes: str = "",
        fact_lines: list[str] | None = None,
        fact_text: str = "",
        fact_corner: str = "",
        focus: str = "",
        focus_detail: str = "",
        claims: list[str] | None = None,
        life_claims: list[str] | None = None,
    ) -> Theme:
        """Write the theme.

        ``fact_corner`` is a finished narration of the facts, written from a
        source.  When it is there it is used as it is -- the model is not
        asked to restate the numbers, because a model that restates numbers
        gets them wrong.
        ``focus`` names the one world the story should be about.
        ``claims`` are things the story must not say.
        """

    def available(self) -> bool:
        return True

    def describe(self) -> dict[str, Any]:
        return {"backend": self.name, "available": self.available()}


#: Hand-written themes for the topics the project ships with.  These are the
#: fallback when no model is available, so they are written to be actually
#: good rather than to be obviously generated.
THEME_BANK: list[dict[str, Any]] = [
    {
        "slug": "exoplanets",
        "name": "Exoplanets",
        "title": "The Planets Next Door",
        "story": [
            "Hello you two. Do you know that there are worlds out there that "
            "nobody has ever stood on? Not one, not two, but thousands of them.",
            "They are called exoplanets, which just means planets that go around "
            "a star that is not our Sun. Our Sun has eight planets. The rest of "
            "the galaxy has a lot more.",
            "Imagine a planet where a year goes by in less time than a lunch "
            "break. That is real. That is TRAPPIST-1 e, and it spins around its "
            "star so fast that its own day is shorter than ours.",
            "Imagine a planet with two suns in its sky. That is real too. Kepler-16 "
            "b goes around two stars at once, so one of them rises and sets for it "
            "just like our Sun does for us.",
            "And imagine a planet so hot that the rock has melted into rivers of "
            "lava, and another one so close to its star that it has been stretched "
            "into an egg shape.",
            "None of them are Earth. But one of them might be a lot like Earth. And "
            "that is the big question, the one that people are working on right "
            "now, while you are listening to this.",
        ],
        "facts": [
            "Astronomers have confirmed more than six thousand exoplanets.",
            "Proxima b is the closest one we have found. It is only about four "
            "light years away.",
            "TRAPPIST-1 has seven planets around a single small star, and three "
            "of them sit in the warm zone where water could be liquid.",
            "Kepler-186 f was the first Earth-sized planet found in the warm zone. "
            "That discovery told us Earth-sized worlds are common.",
            "Kepler-16 b has two suns.",
            "The very first exoplanet ever found circles the remains of a star "
            "that had exploded.",
        ],
        "song_lyrics": [
            "Twinkle little planet, far away,",
            "Seven sisters round a small red star.",
            "One year is shorter than a day,",
            "Two suns come up where you can see them play.",
            "Six thousand worlds and counting,",
            "Every one a place we might go.",
            "Is there one out there like ours?",
            "We will find out, we just have to know.",
        ],
        "song_prompt": (
            "bright children's educational song, acoustic guitar, ukulele, "
            "clapping, warm and upbeat, simple melody for young singers"
        ),
    },
    {
        "slug": "dinosaurs",
        "name": "Dinosaurs",
        "title": "When Giants Roamed",
        "story": [
            "Hello you two. Today we are going back to a time before there was "
            "any grass at all.",
            "Dinosaurs lived on Earth for about a hundred and sixty-five million "
            "years. That is so long that mountains have risen and fallen while "
            "they were walking.",
            "The really enormous ones, the long necks and the heavy ones with "
            "cracked skulls, are called theropods. And if you have ever seen a "
            "bird, you have seen a dinosaur. Every sparrow and every chicken "
            "carries that family in its bones.",
            "But not all dinosaurs were giants. Some were the size of a chicken. "
            "One of them had feathers and could probably glide.",
            "The dinosaurs did not all die at once. They went away slowly, over "
            "millions of years, and a few of them are still here. Small ones. "
            "With feathers.",
        ],
        "facts": [
            "Dinosaurs lived for about 165 million years.",
            "Birds are living dinosaurs. They are the only ones left.",
            "The biggest dinosaur we know of, Argentinosaurus, was about 30 metres "
            "long and as heavy as fourteen elephants.",
            "Some dinosaurs were only the size of a chicken.",
            "The first dinosaur bone was noticed by scientists in 1824.",
        ],
        "song_lyrics": [
            "Long ago the world was green,",
            "Giants walked where we now walk.",
            "Then the ground began to burn,",
            "And the little ones took over the turn.",
            "But listen close and you will find,",
            "Every bird is of that kind.",
        ],
        "song_prompt": (
            "playful children's song about dinosaurs, bouncy acoustic guitar, "
            "ukulele, hand claps, playful and warm"
        ),
    },
]


class TemplateThemeWriter(ThemeWriter):
    """Writes a theme from the hand-written bank.

    It needs no model and no network, which makes it the safety net: if the
    local model is down, the card still gets something worth listening to.
    """

    name = "template"

    def __init__(self, themes: list[dict[str, Any]] | None = None) -> None:
        self.themes = themes or THEME_BANK

    def available(self) -> bool:
        return bool(self.themes)

    def write(
        self,
        theme: str,
        *,
        audience: str = "",
        notes: str = "",
        fact_lines: list[str] | None = None,
        fact_text: str = "",
        fact_corner: str = "",
        focus: str = "",
        focus_detail: str = "",
        claims: list[str] | None = None,
        life_claims: list[str] | None = None,
    ) -> Theme:
        slug = slugify(theme)
        entry = next((t for t in self.themes if t["slug"] == slug), None)

        if entry is None:
            name = titleise(theme)
            entry = {
                "slug": slug,
                "name": name,
                "title": f"A Morning About {name}",
                "story": [
                    f"Hello you two. Today we are going to talk about {name.lower()}.",
                    "There is always more to find out than you would expect, and "
                    "the best way to find it is to ask a good question and then "
                    "go and look.",
                ],
                "facts": [
                    f"{name} is a big subject, and people are still learning new "
                    "things about it all the time.",
                ],
                "song_lyrics": [
                    f"Here's a song about {name.lower()},",
                    "Sing it with me and don't be shy.",
                    "One more fact before we go,",
                    "There is always more to know.",
                ],
                "song_prompt": (
                    "bright children's educational song, acoustic guitar, ukulele, "
                    "clapping, warm and upbeat"
                ),
            }

        story = "\n\n".join(entry["story"])
        facts = "\n\n".join(entry["facts"])
        if fact_corner.strip():
            facts = fact_corner.strip()
        elif notes:
            facts = f"{notes}\n\n{facts}"

        return Theme(
            slug=entry["slug"],
            name=entry["name"],
            title=entry["title"],
            story=story,
            facts=facts,
            song_title=f"The {entry['name']} Song",
            song_lyrics="\n".join(entry["song_lyrics"]),
            song_prompt=entry["song_prompt"],
            backend=self.name,
        )


class OllamaThemeWriter(ThemeWriter):
    """Asks a model running on this machine to write the theme.

    The model is given the theme, the audience and -- when there is one --
    the checked facts from :mod:`yoto_daily.research`.  It is told to invent
    the story and to use the facts as they are, so the fiction stays
    fictional and the numbers stay true.
    """

    name = "ollama"

    def __init__(
        self,
        client: OllamaClient | None = None,
        *,
        endpoint: str = DEFAULT_ENDPOINT,
        model: str = DEFAULT_MODEL,
        timeout: float = 600.0,
        attempts: int = 3,
    ) -> None:
        self.client = client or OllamaClient(endpoint, model, timeout=timeout)
        self.attempts = max(1, attempts)

    def available(self) -> bool:
        return self.client.available()

    def describe(self) -> dict[str, Any]:
        return {
            "backend": self.name,
            "available": self.available(),
            "model": self.client.model,
            "endpoint": self.client.endpoint,
            "attempts": self.attempts,
        }

    # ------------------------------------------------------------------
    def build_prompt(
        self,
        theme: str,
        *,
        audience: str,
        notes: str,
        fact_text: str,
        focus: str,
        focus_detail: str,
        claims: list[str] | None = None,
        life_claims: list[str] | None = None,
        extra: str = "",
    ) -> tuple[str, str]:
        """The system prompt and the user prompt.

        The shape of the answer is spelled out rather than left to the
        model, because a small local model asked for "a story" gives you a
        summary instead.  A beat sheet and a set of rules get a usable
        result out of a model that fits in a laptop.

        The model is asked for the *story* and the *song* only.  The facts
        are written from the source and handed over finished: a model given
        eight sets of numbers to restate ends up mixing them up, and a
        child listening to a wrong number is worse off than one listening to
        no number at all.
        """
        system = (
            "You write content for a Yoto audio player that two children "
            "listen to. You always answer with the five labelled sections "
            "that are asked for, and nothing else. No JSON, no commentary, "
            "no code fences."
        )

        if focus:
            subject = focus
            detail = focus_detail or f"About {focus}:"
            subject_block = f"""The story is about one planet: {subject}.

Here is what is true about it. These are the only facts you may use, and
you must not change any of them:
{detail}

Do not put any number in the story except the ones written above. Do not
mention any other planet by name."""
        else:
            subject = theme
            subject_block = f"""The story is about {theme}.

Here are the checked facts you may use. Do not change any of them:
{fact_text.strip() or "- (none supplied; keep the story free of specific numbers)"}

Do not put any number in the story except the ones written above."""

        if claims or life_claims:
            forbidden = "\n".join(
                f"- {claim}" for claim in list(claims or []) + list(life_claims or [])
            )
            claims_block = f"""
The story and the lyrics must never say any of these things. They are not
true:
{forbidden}

If you want to talk about whether there is life there, say that nobody
knows yet. That is the truth, and it is more interesting than a guess."""
        else:
            claims_block = ""

        extra_block = f"\n{extra.strip()}\n" if extra.strip() else ""

        prompt = f"""Write a themed audio set about: {theme}

The listeners are {audience or "two children, one about five years old and one about ten"}.

Answer in exactly this shape. Each label goes on a line of its own,
followed by a colon. The title and the song prompt go on the same line as
their label; the story and the lyrics go on the lines below it. Do not use
JSON. Do not use quotation marks. Do not add any other label.

TITLE: a short, exciting title for the set, at most six words.

STORY:
The story, of 400 to 550 words, told out loud to the listener. Write it as
narration in six paragraphs, separated by a blank line. Each paragraph does
one of these things, in this order:
1. You greet the listeners and tell them where you are taking them.
2. You take them there -- describe what they would see.
3. Something surprising happens, and you tell them what you found.
4. You explain why it matters, in terms they can feel.
5. You ask them a question to think about.
6. You say goodbye warmly and promise something for next time.

Rules for the story:
- Address the listeners as you two. Never say the kids.
- Never describe the story itself. No the story ends with, no the kids are
  amazed, no imagine. Write the thing itself.
- Never walk through a list of facts. This is a story with a beginning, a
  middle and an end, not a tour.
- Sentences short enough to say out loud. No headings, no lists, no emoji.
- Leave a blank line between paragraphs.

SONG TITLE: The title of a song about the topic, at most five words.

SONG LYRICS:
Eight lines of lyrics a child could sing, one line per line break. A
simple repeating chorus, so a line may appear twice, but never three
times. Keep every line short and easy to sing. The topic's own words
should appear in it. Do not put planet names in the lyrics.

SONG PROMPT: How the song should sound, in a few words: instruments, mood,
tempo. For example: bright children's song, acoustic guitar, ukulele,
clapping, warm and upbeat

{subject_block}
{claims_block}
{extra_block}
Answer with the five labelled sections and nothing else."""
        return system, prompt

    def write(
        self,
        theme: str,
        *,
        audience: str = "",
        notes: str = "",
        fact_lines: list[str] | None = None,
        fact_text: str = "",
        fact_corner: str = "",
        focus: str = "",
        focus_detail: str = "",
        claims: list[str] | None = None,
        life_claims: list[str] | None = None,
    ) -> Theme:
        system, prompt = self.build_prompt(
            theme,
            audience=audience,
            notes=notes,
            fact_text=fact_text,
            focus=focus,
            focus_detail=focus_detail,
            claims=claims or [],
            life_claims=life_claims or [],
        )

        problems: list[str] = []
        for attempt in range(self.attempts):
            raw = self.client.generate(prompt, system=system)

            # A labelled answer is what is asked for; a JSON object is
            # accepted too, because some models insist on one.
            data = _parse_sections(raw)
            if not data and raw.lstrip().startswith("{"):
                try:
                    data = _extract_json(raw)
                except ValueError:
                    data = {}

            story = _tidy(str(data.get("STORY") or data.get("story") or ""))
            lyrics = str(
                data.get("SONG_LYRICS") or data.get("song_lyrics") or ""
            ).strip()
            title = str(data.get("TITLE") or data.get("title") or "").strip()
            song_title = str(
                data.get("SONG_TITLE") or data.get("song_title") or ""
            ).strip()
            song_prompt = str(
                data.get("SONG_PROMPT") or data.get("song_prompt") or ""
            ).strip()

            if not story:
                problems = ["the model returned no story"]
            else:
                problems = (
                    story_problems(story)
                    + lyrics_problems(lyrics)
                    + claim_problems(story, claims, life_claims)
                    + claim_problems(lyrics, claims, life_claims)
                )
                if not problems:
                    # The facts are the source's, not the model's.
                    facts = fact_corner.strip() or _tidy(str(data.get("facts") or ""))
                    name = titleise(theme)
                    return Theme(
                        slug=slugify(theme),
                        name=name,
                        title=title or name,
                        story=story,
                        facts=facts,
                        song_title=song_title or f"The {name} Song",
                        song_lyrics=lyrics,
                        song_prompt=song_prompt,
                        backend=self.name,
                        meta={
                            "model": self.client.model,
                            "attempts": attempt + 1,
                            "rejected": problems if attempt else [],
                        },
                    )

            # Say what was wrong and try again.
            system, prompt = self.build_prompt(
                theme,
                audience=audience,
                notes=notes,
                fact_text=fact_text,
                focus=focus,
                focus_detail=focus_detail,
                extra=(
                    "Your last attempt was rejected: "
                    + "; ".join(problems)
                    + ". Fix those problems. Write six different paragraphs, "
                    "each one saying something new, and do not use the words "
                    "'you will' more than twice."
                ),
            )
        raise ValueError(
            "the model could not write a usable story after "
            f"{self.attempts} attempt(s): " + "; ".join(problems)
        )


class FallbackThemeWriter(ThemeWriter):
    """Tries writers in order until one produces a theme."""

    name = "fallback"

    def __init__(self, writers: list[ThemeWriter]) -> None:
        self.writers = list(writers)
        self._disabled: set[str] = set()

    def available(self) -> bool:
        return any(w.name not in self._disabled and w.available() for w in self.writers)

    def describe(self) -> dict[str, Any]:
        return {
            "backend": self.name,
            "available": self.available(),
            "chain": [
                {
                    "backend": w.name,
                    "available": w.available(),
                    "disabled": w.name in self._disabled,
                }
                for w in self.writers
            ],
        }

    def write(
        self,
        theme: str,
        *,
        audience: str = "",
        notes: str = "",
        fact_lines: list[str] | None = None,
        fact_text: str = "",
        fact_corner: str = "",
        focus: str = "",
        focus_detail: str = "",
        claims: list[str] | None = None,
        life_claims: list[str] | None = None,
    ) -> Theme:
        errors: list[str] = []
        for writer in self.writers:
            if writer.name in self._disabled:
                continue
            if not writer.available():
                continue
            try:
                result = writer.write(
                    theme,
                    audience=audience,
                    notes=notes,
                    fact_lines=fact_lines,
                    fact_text=fact_text,
                    fact_corner=fact_corner,
                    focus=focus,
                    focus_detail=focus_detail,
                    claims=claims,
                    life_claims=life_claims,
                )
            except Exception as exc:
                errors.append(f"{writer.name}: {exc}")
                if isinstance(exc, (OllamaError, FileNotFoundError)):
                    self._disabled.add(writer.name)
                continue
            result.meta.setdefault("fallback_errors", errors)
            return result
        raise RuntimeError(
            "no theme writer could write: "
            + ("; ".join(errors) if errors else "none available")
        )


def story_problems(text: str) -> list[str]:
    """What is wrong with a story a model wrote.

    Small models fail in characteristic ways: they write one paragraph and
    repeat it, they run out of steam half way, or they turn into a list.
    A story with any of those faults is worse than no story at all, so it
    is checked before it reaches a card.
    """
    problems: list[str] = []
    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    words = text.split()

    if not paragraphs:
        return ["the story is empty"]
    if len(paragraphs) < 4:
        problems.append(f"the story has only {len(paragraphs)} paragraph(s)")
    if len(words) < 200:
        problems.append(f"the story is only {len(words)} words")

    # A paragraph repeated verbatim is the classic small-model loop.
    seen: dict[str, int] = {}
    for paragraph in paragraphs:
        key = " ".join(paragraph.lower().split())
        seen[key] = seen.get(key, 0) + 1
    repeated = [k for k, v in seen.items() if v > 1]
    if repeated:
        problems.append("the story repeats a paragraph")

    # The same sentence repeated is the same failure in miniature.
    sentences = [
        " ".join(s.lower().split())
        for s in re.split(r"(?<=[.!?])\s+", text)
        if len(s.split()) > 4
    ]
    if sentences:
        counts: dict[str, int] = {}
        for sentence in sentences:
            counts[sentence] = counts.get(sentence, 0) + 1
        worst = max(counts.values())
        if worst > 2:
            problems.append("the story repeats a sentence")

    # A story that keeps saying "you will" is a list, not a story.
    if len(re.findall(r"\byou will\b", text, flags=re.IGNORECASE)) > 8:
        problems.append("the story reads as a list of what you will do")

    return problems


#: Words that make a claim a question rather than an assertion.
#:
#: "there is life on this world" is a false claim.  "nobody knows whether
#: there is life on this world" is the most interesting fact in the whole
#: story.  The claim guard has to tell those apart.
NEGATION_CUES = (
    "nobody knows",
    "no one knows",
    "nobody is sure",
    "no one is sure",
    "don't know",
    "do not know",
    "not known",
    "no evidence",
    "not yet",
    "whether",
    "if there",
    "unknown",
    "mystery",
    "might be",
    "may be",
    "could be",
    "maybe",
    "perhaps",
    "we wonder",
    "we ask",
)


def claim_problems(
    text: str,
    claims: list[str] | None,
    life_claims: list[str] | None = None,
) -> list[str]:
    """Claims the story must not make.

    A story about a planet around another star will sometimes put it in
    our solar system, and will sometimes say that life has been found
    there.  Both are the kind of thing a child takes as true, so they are
    caught and the story is written again.

    A claim inside a sentence that is asking a question is allowed: not
    knowing whether there is life somewhere is the point.  A life claim
    about Earth is allowed too, because that one is true.
    """
    problems: list[str] = []
    sentences = re.split(r"(?<=[.!?])\s+", text or "")
    for claim in list(claims or []) + list(life_claims or []):
        needle = claim.lower()
        is_life = claim in (life_claims or [])
        for sentence in sentences:
            lowered = sentence.lower()
            index = lowered.find(needle)
            if index == -1:
                continue
            if is_life and ("earth" in lowered or "our planet" in lowered):
                # A claim about our own world is a true one.
                continue
            before = lowered[:index]
            if not any(cue in before for cue in NEGATION_CUES):
                problems.append(f"the story says {claim!r}, which is not true")
                break
    return problems


def lyrics_problems(lyrics: str) -> list[str]:
    """What is wrong with a set of song lyrics.

    A chorus may come round twice.  Three times is a model padding its
    answer, and ACE-Step will sing all of it.
    """
    problems: list[str] = []
    lines = [line.strip() for line in (lyrics or "").splitlines() if line.strip()]
    if not lines:
        return ["there are no lyrics"]
    if len(lines) < 6:
        problems.append(f"there are only {len(lines)} lines of lyrics")
    if len(lines) > 16:
        problems.append(f"there are {len(lines)} lines of lyrics, which is too many")

    counts: dict[str, int] = {}
    for line in lines:
        key = " ".join(line.lower().split())
        counts[key] = counts.get(key, 0) + 1
    worst = max(counts.values())
    if worst > 2:
        problems.append("a line of lyrics is repeated three times")

    return problems


def _tidy(text: str) -> str:
    """Clean up an answer from a model.

    Paragraph breaks come back in whatever shape the model chose, and the
    occasional character arrives mangled.  The narration is read out loud,
    so it wants clean paragraphs and plain punctuation.
    """
    body = (
        (text or "")
        .replace("\r\n", "\n")
        .replace("\r", "\n")
        .replace("\ufffd", "-")
    )

    if "\n\n" not in body:
        # A model that ignored the blank-line instruction still tends to
        # start each paragraph on its own line.
        parts = [part.strip() for part in body.split("\n") if part.strip()]
        if len(parts) > 2:
            body = "\n\n".join(parts)

    paragraphs: list[str] = []
    for block in re.split(r"\n\s*\n", body):
        cleaned = re.sub(r"[ \t]*\n[ \t]*", " ", block)
        cleaned = re.sub(r"[ \t]{2,}", " ", cleaned).strip()
        if cleaned:
            paragraphs.append(cleaned)
    return "\n\n".join(paragraphs)


#: The labels the writer asks for.  A labelled answer is far easier to
#: read back than JSON: a model that forgets to escape a quotation mark
#: inside a story does not break the parse.
SECTION_LABELS = (
    "TITLE",
    "STORY",
    "SONG TITLE",
    "SONG LYRICS",
    "SONG PROMPT",
)

_SECTION_RE = re.compile(
    r"^[ \t]*(TITLE|STORY|SONG\s+TITLE|SONG\s+LYRICS|SONG\s+PROMPT)"
    r"[ \t]*(?::[ \t]*(.*))?$",
    re.IGNORECASE | re.MULTILINE,
)


def _parse_sections(text: str) -> dict[str, str]:
    """Read the labelled sections out of a model answer.

    The section runs from the end of its label to the start of the next
    one, so a story may contain anything at all -- including the word
    "title" on a line of its own.

    The label may be followed by a colon or not, and the value may start
    on the same line or on the next one.  Models are not consistent about
    this and the answer is still perfectly readable.
    """
    matches = list(_SECTION_RE.finditer(text or ""))
    sections: dict[str, str] = {}
    for index, match in enumerate(matches):
        name = re.sub(r"\s+", "_", match.group(1).upper())
        inline = (match.group(2) or "").strip()
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        value = " ".join(
            part for part in (inline, text[start:end].strip()) if part
        ).strip()
        if value and name not in sections:
            sections[name] = value
    return sections


def _extract_json(text: str) -> dict[str, Any]:
    """Pull the JSON object out of a model answer.

    Models wrap JSON in prose, in code fences and sometimes in a second
    paragraph of commentary, whatever they are told.  The object is
    therefore located and parsed rather than assumed: every ``{`` is tried
    in turn, and the first one that starts a complete JSON object wins.
    """
    body = (text or "").strip()
    if "```" in body:
        parts = body.split("```")
        for part in parts:
            candidate = part.strip()
            if candidate.lower().startswith("json"):
                candidate = candidate[4:].strip()
            if candidate.startswith("{"):
                body = candidate
                break

    # ``strict=False`` lets a string contain a raw newline.  Models write
    # multi-line prose into JSON without escaping it, and strict JSON
    # refuses to read that back.
    decoder = json.JSONDecoder(strict=False)
    index = body.find("{")
    while index != -1:
        try:
            data, _ = decoder.raw_decode(body[index:])
        except json.JSONDecodeError:
            index = body.find("{", index + 1)
            continue
        if isinstance(data, dict):
            return data
        index = body.find("{", index + 1)

    raise ValueError(f"the model did not return a JSON object: {body[:200]!r}")


def build_theme_writer(
    *,
    backend: str = "auto",
    ollama_endpoint: str = DEFAULT_ENDPOINT,
    ollama_model: str = DEFAULT_MODEL,
    ollama_timeout: float = 600.0,
    attempts: int = 3,
) -> ThemeWriter:
    """Pick a theme writer.

    ``auto`` prefers the local model and falls back to the hand-written
    themes, so a card is never blocked by a model that is not running.
    """
    template = TemplateThemeWriter()
    ollama = OllamaThemeWriter(
        OllamaClient(ollama_endpoint, ollama_model, timeout=ollama_timeout),
        attempts=attempts,
    )

    if backend == "template":
        return template
    if backend == "ollama":
        return ollama
    return FallbackThemeWriter([ollama, template])


__all__ = [
    "THEME_BANK",
    "FallbackThemeWriter",
    "OllamaThemeWriter",
    "TemplateThemeWriter",
    "Theme",
    "ThemeWriter",
    "build_theme_writer",
    "slugify",
    "titleise",
]
