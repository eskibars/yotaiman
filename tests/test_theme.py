"""Offline tests for the theme, day-folder and voice-reference machinery.

None of these touch the Yoto API, and none of them need a model, a GPU or
a network.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from yoto_daily.content.plan import (  # noqa: E402
    filter_plan,
    plan_from_authored,
    plan_from_theme,
)
from yoto_daily.content.theme import (  # noqa: E402
    TemplateThemeWriter,
    _extract_json,
    _parse_sections,
    _tidy,
    claim_problems,
    lyrics_problems,
    slugify,
    story_problems,
    titleise,
)
from yoto_daily.days import (  # noqa: E402
    day_folder,
    find_day,
    list_days,
    prune_day,
    read_manifest,
    save_transcript,
    track_basename,
    write_manifest,
)
from yoto_daily.research import (  # noqa: E402
    EXOPLANET_CLAIMS,
    EXOPLANET_LIFE_CLAIMS,
    PlanetFact,
)
from yoto_daily.voice import Window, Word, pick_window, slice_transcript  # noqa: E402


# ----------------------------------------------------------------------
# naming
# ----------------------------------------------------------------------
def test_slugify_and_titleise():
    assert slugify("Exoplanets!") == "exoplanets"
    assert slugify("  the  Deep  Sea ") == "the-deep-sea"
    assert slugify("") == "theme"
    assert titleise("exoplanets") == "Exoplanets"
    assert titleise("the-deep-sea") == "The Deep Sea"


def test_track_basename():
    assert track_basename("01", "The Planets Next Door") == "01-the-planets-next-door"
    assert track_basename("02", "!!!") == "02-track"


# ----------------------------------------------------------------------
# the day folder
# ----------------------------------------------------------------------
def test_day_folder_is_named_for_the_day(tmp_path):
    folder = day_folder(tmp_path, "2026-10-26", "exoplanets")
    assert folder.name == "2026-10-26-exoplanets"


def test_manifest_round_trip(tmp_path):
    folder = day_folder(tmp_path, "2026-10-26", "exoplanets")
    folder.mkdir(parents=True)
    write_manifest(folder, {"date": "2026-10-26", "slug": "exoplanets", "title": "X"})

    manifest = read_manifest(folder)
    assert manifest["title"] == "X"
    assert manifest["version"] == 1
    # The file on disk is readable JSON, not just a dict in memory.
    assert json.loads((folder / "manifest.json").read_text())["slug"] == "exoplanets"


def test_read_manifest_of_a_missing_folder(tmp_path):
    assert read_manifest(tmp_path / "nothing-here") == {}


def test_list_days_is_newest_first(tmp_path):
    for day, slug in (
        ("2026-10-24", "dolphins"),
        ("2026-10-26", "exoplanets"),
        ("2026-10-25", "dinosaurs"),
    ):
        folder = day_folder(tmp_path, day, slug)
        write_manifest(folder, {"date": day, "slug": slug, "theme": slug.title()})

    days = list_days(tmp_path)
    assert [d.date for d in days] == ["2026-10-26", "2026-10-25", "2026-10-24"]
    assert days[0].slug == "exoplanets"
    assert days[0].theme == "Exoplanets"


def test_find_day(tmp_path):
    folder = day_folder(tmp_path, "2026-10-26", "exoplanets")
    write_manifest(folder, {"date": "2026-10-26", "slug": "exoplanets"})

    assert find_day(tmp_path, day="2026-10-26").slug == "exoplanets"
    assert find_day(tmp_path, slug="exoplanets").slug == "exoplanets"
    assert find_day(tmp_path, day="2026-10-26", slug="exoplanets") is not None
    assert find_day(tmp_path, day="2020-01-01") is None
    assert find_day(tmp_path, day="2026-10-26", slug="dolphins") is None


def test_find_day_returns_the_latest_when_unspecified(tmp_path):
    for day in ("2026-10-24", "2026-10-26"):
        write_manifest(
            day_folder(tmp_path, day, "exoplanets"),
            {"date": day, "slug": "exoplanets"},
        )
    assert find_day(tmp_path).date == "2026-10-26"


def test_save_transcript_sits_next_to_the_audio(tmp_path):
    folder = day_folder(tmp_path, "2026-10-26", "exoplanets")
    path = save_transcript(folder, "01", "The Story", "Hello you two.")
    assert path.name == "01-the-story.txt"
    assert path.exists()
    assert "Hello you two." in path.read_text()


def test_list_days_ignores_folders_without_a_manifest(tmp_path):
    (tmp_path / "not-a-day").mkdir()
    assert list_days(tmp_path) == []


def test_prune_day_removes_the_leftovers(tmp_path):
    folder = day_folder(tmp_path, "2026-10-26", "exoplanets")
    folder.mkdir(parents=True)
    keep = folder / "01-story.mp3"
    keep.write_bytes(b"audio")
    transcript = folder / "01-story.txt"
    transcript.write_text("words", encoding="utf-8")
    old = folder / "01-old-story.mp3"
    old.write_bytes(b"older audio")
    write_manifest(folder, {"date": "2026-10-26"})

    removed = prune_day(folder, ["01-story.mp3", "01-story.txt"])

    assert removed == ["01-old-story.mp3"]
    assert keep.exists()
    assert transcript.exists()
    assert not old.exists()
    # The manifest is never a leftover.
    assert (folder / "manifest.json").exists()


def test_prune_day_on_a_missing_folder(tmp_path):
    assert prune_day(tmp_path / "nothing", []) == []


# ----------------------------------------------------------------------
# the quality gate
# ----------------------------------------------------------------------
def _paragraphs(count: int, text: str = "Something happened out there.") -> str:
    return "\n\n".join([text] * count)


def test_story_problems_accepts_a_real_story():
    # Thirty different sentences, so nothing is repeated.
    sentences = [
        "The wind moved and the light changed.",
        "You two looked up at the sky.",
        "Something waited behind the far hill.",
        "The old ship creaked as the tide came in.",
        "Nobody spoke for a long moment.",
        "The lantern swung gently overhead.",
        "A gull cried somewhere out of sight.",
        "The path narrowed between two banks of grass.",
        "She pushed the door open with both hands.",
        "The stairs complained under their weight.",
        "Dust turned slowly in the shaft of light.",
        "He counted the stars twice to be sure.",
        "The map showed a river that was not there.",
        "Rain began, softly at first.",
        "The lamp went out and came back.",
        "They sat on the wall and watched the clouds.",
        "The cat arrived, decided otherwise, and left.",
        "A bell sounded somewhere across the water.",
        "The book fell open at a page she remembered.",
        "The smell of salt came in with the wind.",
        "Nobody wanted to be the first to move.",
        "The water was warm, and deeper than it looked.",
        "He drew a line in the dust and crossed it out.",
        "The train was late, and nobody minded.",
        "Fireflies came up out of the long grass.",
        "The letter had been folded and unfolded many times.",
        "She hummed the tune without meaning to.",
        "The road ended at a gate painted green.",
        "Morning arrived before they were ready for it.",
        "The last of the fire went out.",
    ]
    story = "\n\n".join(
        " ".join(sentences[index * 6 : index * 6 + 6]) for index in range(5)
    )
    assert story_problems(story) == []


def test_story_problems_catches_a_repeated_paragraph():
    assert "the story repeats a paragraph" in story_problems(_paragraphs(5))


def test_story_problems_catches_too_few_paragraphs():
    assert any(
        "paragraph" in problem for problem in story_problems(_paragraphs(2))
    )


def test_story_problems_catches_a_short_story():
    assert any("words" in problem for problem in story_problems("Too short."))


def test_story_problems_catches_a_story_that_reads_as_a_list():
    story = "\n\n".join(
        "You will see a star. " * 20 for _ in range(5)
    )
    assert any("list" in problem for problem in story_problems(story))


def test_story_problems_catches_a_repeated_sentence():
    sentence = "The planet turned slowly in the dark. "
    story = "\n\n".join([sentence * 6] * 5)
    assert any("repeats a sentence" in p for p in story_problems(story))


def test_lyrics_problems():
    assert lyrics_problems("\n".join(f"line {i}" for i in range(8))) == []
    assert any("only" in p for p in lyrics_problems("one\ntwo"))
    assert any("too many" in p for p in lyrics_problems("\n".join(f"l{i}" for i in range(20))))
    assert any("repeated three times" in p for p in lyrics_problems(
        "\n".join(["same"] * 3 + [f"other {i}" for i in range(5)])
    ))


# ----------------------------------------------------------------------
# claims the story must not make
# ----------------------------------------------------------------------
def test_claim_problems_catches_a_planet_in_our_solar_system():
    story = "It takes eleven days to go around the sun."
    problems = claim_problems(story, EXOPLANET_CLAIMS)
    assert problems
    assert "around the sun" in problems[0]


def test_claim_problems_catches_a_claim_that_life_was_found():
    assert claim_problems("We found life there!", [], EXOPLANET_LIFE_CLAIMS)
    assert claim_problems("There is life on this world.", [], EXOPLANET_LIFE_CLAIMS)
    assert claim_problems("Life exists there.", [], EXOPLANET_LIFE_CLAIMS)


def test_claim_problems_lets_a_honest_story_through():
    story = (
        "Nobody knows yet whether there is life on this world, and that is "
        "the most exciting question of all. It goes around its own star."
    )
    assert claim_problems(story, EXOPLANET_CLAIMS, EXOPLANET_LIFE_CLAIMS) == []


def test_claim_problems_allows_a_true_claim_about_earth():
    story = "There is life on Earth, and that is why we look for it elsewhere."
    assert claim_problems(story, EXOPLANET_CLAIMS, EXOPLANET_LIFE_CLAIMS) == []


def test_claim_problems_with_no_claims():
    assert claim_problems("anything at all", []) == []


# ----------------------------------------------------------------------
# reading a labelled answer
# ----------------------------------------------------------------------
def test_parse_sections():
    text = (
        "TITLE: A World Very Close to Home\n"
        "\n"
        "STORY:\n"
        "Hello you two.\n"
        "\n"
        "This is the second paragraph.\n"
        "\n"
        "SONG TITLE: The Closest Star\n"
        "\n"
        "SONG LYRICS:\n"
        "line one\n"
        "line two\n"
        "\n"
        "SONG PROMPT: acoustic guitar, ukulele\n"
    )
    sections = _parse_sections(text)
    assert sections["TITLE"] == "A World Very Close to Home"
    assert "Hello you two." in sections["STORY"]
    assert "second paragraph" in sections["STORY"]
    assert sections["SONG_TITLE"] == "The Closest Star"
    assert sections["SONG_LYRICS"].startswith("line one")
    assert "acoustic guitar" in sections["SONG_PROMPT"]


def test_parse_sections_of_an_empty_answer():
    assert _parse_sections("") == {}


def test_parse_sections_without_colons():
    # Models are not consistent about the colon, and the answer is still
    # perfectly readable.
    text = (
        "TITLE\n"
        "A World So Close to Home\n"
        "\n"
        "STORY\n"
        "\n"
        "Hello you two.\n"
        "\n"
        "SONG TITLE\n"
        "The Closest Star\n"
        "\n"
        "SONG LYRICS\n"
        "line one\n"
        "line two\n"
        "\n"
        "SONG PROMPT\n"
        "acoustic guitar\n"
    )
    sections = _parse_sections(text)
    assert sections["TITLE"] == "A World So Close to Home"
    assert "Hello you two." in sections["STORY"]
    assert sections["SONG_TITLE"] == "The Closest Star"
    assert sections["SONG_LYRICS"].startswith("line one")
    assert "acoustic guitar" in sections["SONG_PROMPT"]


def test_parse_sections_does_not_match_a_word_in_a_sentence():
    text = "TITLE: X\n\nSTORY:\n\nStory so far, the wind picked up.\n"
    sections = _parse_sections(text)
    assert sections["TITLE"] == "X"
    assert "Story so far" in sections["STORY"]


# ----------------------------------------------------------------------
# parsing model answers
# ----------------------------------------------------------------------
def test_extract_json_from_a_bare_object():
    assert _extract_json('{"title": "X"}')["title"] == "X"


def test_extract_json_from_a_code_fence():
    text = 'Sure!\n```json\n{"title": "X", "story": "s"}\n```\nHope that helps.'
    assert _extract_json(text)["title"] == "X"


def test_extract_json_ignores_trailing_prose():
    text = '{"title": "X"}\n\nI hope that helps! Let me know if you want more.'
    assert _extract_json(text)["title"] == "X"


def test_extract_json_rejects_nonsense():
    with pytest.raises(ValueError):
        _extract_json("there is no json here")


def test_tidy_normalises_paragraphs():
    assert _tidy("one\n\n\ntwo") == "one\n\ntwo"
    assert _tidy("  spaced   out  ") == "spaced out"
    assert _tidy("a\ufffdb") == "a-b"


def test_tidy_makes_single_newlines_into_paragraphs():
    # A model that ignored the blank-line instruction still starts each
    # paragraph on its own line.
    assert _tidy("one\ntwo\nthree") == "one\n\ntwo\n\nthree"


# ----------------------------------------------------------------------
# the theme writer
# ----------------------------------------------------------------------
def test_template_writer_produces_a_whole_theme():
    writer = TemplateThemeWriter()
    theme = writer.write("exoplanets")
    assert theme.slug == "exoplanets"
    assert theme.title
    assert len(theme.story.split()) > 100
    assert theme.facts
    assert theme.song_lyrics
    assert theme.song_prompt


def test_template_writer_copes_with_an_unknown_topic():
    theme = TemplateThemeWriter().write("the deep sea")
    assert theme.slug == "the-deep-sea"
    assert theme.story
    assert theme.song_lyrics


def test_template_writer_uses_a_ready_made_fact_corner():
    corner = "Proxima Cen b. It goes around the star Proxima Centauri."
    theme = TemplateThemeWriter().write("exoplanets", fact_corner=corner)
    assert theme.facts == corner


# ----------------------------------------------------------------------
# the research
# ----------------------------------------------------------------------
def test_planet_fact_rounds_for_a_child():
    fact = PlanetFact(
        name="Proxima Cen b",
        host="Proxima Centauri",
        distance_ly=4.24,
        year_days=11.18,
        earth_radii=1.07,
        temp_c=-55.0,
        discovered=2016,
    )
    text = " ".join(fact.as_sentences())
    assert "4 light years" in text
    assert "11 Earth days" in text
    assert "2016" in text
    # Rounded, so a child is not told about minus fifty-five point something.
    assert "-55" in text or "-60" in text or "-50" in text


def test_planet_fact_narration_leads_with_the_name():
    fact = PlanetFact(name="TOI-700 d", host="TOI-700", year_days=37.4)
    assert fact.narration().startswith("TOI-700 d.")


# ----------------------------------------------------------------------
# the voice reference
# ----------------------------------------------------------------------
def _words(text: str, start: float, step: float = 0.4) -> list[Word]:
    return [
        Word(text=word, start=start + index * step, end=start + index * step + 0.35)
        for index, word in enumerate(text.split())
    ]


def test_pick_window_lands_inside_the_range():
    words = _words("one two three four five six seven eight nine ten", 0.0, 0.5)
    window = pick_window(words, min_seconds=2.0, max_seconds=4.0)
    assert 2.0 <= window.duration <= 4.0
    assert window.words


def test_pick_window_prefers_a_sentence_start():
    words = _words(
        "the quick brown fox jumps over the lazy dog and keeps on running",
        0.0,
        0.5,
    )
    # The second half starts with a capital, so it should win.
    words[6].text = "Lazy"
    window = pick_window(words, min_seconds=2.0, max_seconds=3.0)
    assert window.words[0].text == "Lazy"


def test_pick_window_with_nothing_long_enough():
    words = _words("one two", 0.0, 0.4)
    window = pick_window(words, min_seconds=3.0, max_seconds=8.0)
    assert window.words


def test_slice_transcript_recovers_the_authors_words():
    transcript = (
        "Hi, my name is Shane, and this recording is the raw material. "
        "The quick brown fox jumps over the lazy dog."
    )
    recognised = _words(
        "hi my name is shane and this recording is the raw material",
        0.0,
        0.5,
    )
    window = Window(
        start=0.0,
        end=recognised[-1].end,
        words=recognised,
    )
    sliced, coverage = slice_transcript(transcript, window)
    assert "Shane" in sliced
    assert "raw material" in sliced
    assert coverage > 0.9


def test_slice_transcript_reports_a_bad_alignment():
    transcript = "entirely different words that were never spoken here"
    recognised = _words("one two three four five", 0.0, 0.4)
    window = Window(start=0.0, end=recognised[-1].end, words=recognised)
    sliced, coverage = slice_transcript(transcript, window)
    assert sliced == ""
    assert coverage == 0.0


# ----------------------------------------------------------------------
# pixel art
# ----------------------------------------------------------------------
def test_every_shape_draws_something():
    """A shape that draws nothing is a blank icon on the card.

    The shapes used to be laid out in the wrong units, which put every
    pixel outside the canvas, so every icon came out blank.
    """
    import io

    from PIL import Image

    from yoto_daily.pixelart import SHAPES

    for name, draw in SHAPES.items():
        png = draw()
        image = Image.open(io.BytesIO(png))
        assert image.size == (16, 16), name
        assert image.mode == "RGBA", name
        alpha = image.getchannel("A")
        assert alpha.getbbox() is not None, f"the {name} icon is blank"


def test_icon_for_picks_a_shape():
    from yoto_daily.pixelart import icon_for

    assert icon_for("story") == icon_for("story")
    assert icon_for("song") != icon_for("story")
    assert icon_for("facts", "two suns in the sky") == icon_for("facts", "the suns")
    assert icon_for("story", "the year that lasted six days") == icon_for(
        "facts", "a clock"
    )


def test_icon_for_falls_back_for_an_unknown_kind():
    from yoto_daily.pixelart import icon_for

    assert icon_for("something-else")


def test_the_cover_is_a_square_picture_with_something_on_it():
    import io

    from PIL import Image

    from yoto_daily.pixelart import COVER_SIZE, INK, NIGHT, cover

    png = cover("story", "TRAPPIST-1 e", "The Year That Lasted Six Days", "clock")
    image = Image.open(io.BytesIO(png))
    assert image.size == (COVER_SIZE, COVER_SIZE)
    assert image.mode == "RGBA"
    # A cover that is one flat colour is not a cover: the sky and the
    # picture have to be there.
    colours = {count for count, _ in (image.getcolors(maxcolors=100000) or [])}
    used = {colour for _, colour in (image.getcolors(maxcolors=100000) or [])}
    assert len(colours) >= 4
    assert NIGHT in used
    assert INK in used


def test_an_explicit_icon_always_wins():
    from yoto_daily.pixelart import SHAPES, icon_for

    assert icon_for("story", "the suns", "A story", "clock") == SHAPES["clock"]()
    assert icon_for("facts", "the planets", "Fact Corner", "star") == SHAPES["star"]()
    # An unknown name is ignored rather than blowing up.
    assert icon_for("facts", "", "Fact Corner", "no-such-icon") == SHAPES["star"]()


def test_the_library_says_which_picture_each_track_gets():
    from yoto_daily.content import library

    theme = library.find("exoplanets")
    assert theme is not None
    plan = plan_from_authored(theme, song_seconds=120)
    assert [t.icon_kind for t in plan.tracks] == [
        "clock",
        "note",
        "suns",
        "note",
        "telescope",
        "star",
    ]


# ----------------------------------------------------------------------
# the content library and the plan
# ----------------------------------------------------------------------
def test_the_library_has_the_exoplanets_theme():
    from yoto_daily.content import library

    theme = library.find("exoplanets")
    assert theme is not None
    assert library.find("Exoplanets") is theme
    assert library.find("dinosaurs") is None
    assert "exoplanets" in library.slugs()


def test_the_library_theme_is_long_enough_for_a_card():
    """A playlist should run to at least ten minutes."""
    from yoto_daily.content import library

    theme = library.find("exoplanets")
    assert theme is not None
    plan = plan_from_authored(theme, song_seconds=120)
    minutes = (plan.narration_seconds + plan.song_seconds) / 60.0
    assert minutes >= 10.0, minutes
    assert len(plan.tracks) >= 5


def test_the_library_theme_sings_after_each_story():
    from yoto_daily.content import library

    theme = library.find("exoplanets")
    assert theme is not None
    segments = [s.kind for s in theme.segments]
    assert segments == [
        "story",
        "song",
        "story",
        "song",
        "explainer",
        "facts",
    ], segments


def test_a_plan_numbers_its_tracks_and_keeps_the_order():
    from yoto_daily.content import library

    theme = library.find("exoplanets")
    assert theme is not None
    plan = plan_from_authored(theme, song_seconds=120)
    assert [t.key for t in plan.tracks] == ["01", "02", "03", "04", "05", "06"]
    assert plan.tracks[0].kind == "speech"
    assert plan.tracks[1].kind == "music"
    assert plan.tracks[1].seconds == 120
    assert plan.tracks[3].seconds == 180
    assert plan.tracks[4].segment == "explainer"


def test_a_plan_from_a_model_story_song_and_facts():
    from yoto_daily.content.theme import Theme

    theme = Theme(
        slug="dinosaurs",
        name="Dinosaurs",
        title="When Giants Roamed",
        story="A story.",
        facts="Some facts.",
        song_title="The Dinosaur Song",
        song_lyrics="A line.",
        song_prompt="bouncy",
        backend="ollama",
    )
    plan = plan_from_theme(theme, song_seconds=90)
    assert [t.segment for t in plan.tracks] == ["story", "song", "facts"]
    assert plan.tracks[1].seconds == 90
    assert plan.backend == "ollama"


def test_filter_plan_drops_and_renumbers():
    from yoto_daily.content import library

    theme = library.find("exoplanets")
    assert theme is not None
    plan = plan_from_authored(theme, song_seconds=120)
    filtered = filter_plan(plan, songs=False)
    assert all(not t.is_song for t in filtered.tracks)
    assert [t.key for t in filtered.tracks] == ["01", "02", "03", "04"]

    plan = plan_from_authored(theme, song_seconds=120)
    filtered = filter_plan(plan, facts=False)
    assert all(t.segment not in ("facts", "explainer") for t in filtered.tracks)
    assert [t.key for t in filtered.tracks] == ["01", "02", "03", "04"]


# ----------------------------------------------------------------------
# numbers
# ----------------------------------------------------------------------
def test_a_big_number_is_one_number():
    """The complaint: "6,451" came out as "six four fifty one"."""
    from yoto_daily.numbers import spell_numbers

    assert spell_numbers("6,451") == "six thousand four hundred and fifty-one"
    assert spell_numbers("1,234,567") == (
        "one million two hundred and thirty-four thousand five hundred and sixty-seven"
    )
    assert spell_numbers("2,000,000,000") == "two billion"


def test_decimal_points_and_signs():
    from yoto_daily.numbers import spell_numbers

    assert spell_numbers("4.2") == "four point two"
    assert spell_numbers("-55") == "minus fifty-five"
    assert spell_numbers("3.5 light years") == "three point five light years"


def test_years_are_said_the_way_people_say_them():
    from yoto_daily.numbers import spell_numbers

    assert spell_numbers("1992") == "nineteen ninety-two"
    assert spell_numbers("2016") == "twenty sixteen"
    assert spell_numbers("2009") == "two thousand and nine"
    assert spell_numbers("2026") == "twenty twenty-six"
    # "twenty six" would be twenty-six.
    assert spell_numbers("2026") != "twenty six"


def test_catalogue_names_are_not_quantities():
    """A planet's name is a name, not a measurement."""
    from yoto_daily.numbers import spell_numbers

    assert spell_numbers("TRAPPIST-1 e") == "TRAPPIST-one e"
    assert spell_numbers("Kepler-16 b") == "Kepler-sixteen b"
    assert spell_numbers("PSR B1257 plus twelve b") == (
        "PSR bee one two five seven plus twelve b"
    )
    assert spell_numbers("HD 189733 b") == (
        "aitch dee one eight nine seven three three b"
    )
    # A long acronym is a word, not a run of letters.
    assert spell_numbers("TRAPPIST-1 e").startswith("TRAPPIST")


def test_fractions_dimensions_and_percentages():
    from yoto_daily.numbers import spell_numbers

    assert spell_numbers("1/2 of the light") == "one half of the light"
    assert spell_numbers("3/4 of it") == "three quarters of it"
    assert spell_numbers("16x16 pixels") == "sixteen by sixteen pixels"
    assert spell_numbers("45 per cent") == "forty-five per cent"


def test_spelling_numbers_twice_changes_nothing():
    from yoto_daily.numbers import spell_numbers

    once = spell_numbers("There were 6,451 confirmed planets in 2016.")
    assert spell_numbers(once) == once


def test_the_library_text_survives_the_spelling():
    """Nothing in the library should come out as nonsense."""
    from yoto_daily.content import library
    from yoto_daily.numbers import spell_numbers

    theme = library.find("exoplanets")
    assert theme is not None
    spoken = " ".join(
        spell_numbers(s.text) for s in theme.segments if s.text
    )
    assert "Bone" not in spoken
    assert "Ktwo" not in spoken
    assert "one thousand two hundred and fifty-seven" not in spoken
    # The years are said as years.
    assert "nineteen ninety-two" in spoken
    assert "nineteen ninety-four" in spoken
    assert "two thousand and nine" in spoken
