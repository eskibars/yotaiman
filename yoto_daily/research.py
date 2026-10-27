"""Facts about a topic, fetched from somewhere that knows them.

The stories on a card are only as good as the facts underneath them, so the
pipeline asks a source rather than trusting a model to remember numbers.

Right now that source is the NASA Exoplanet Archive, queried over its TAP
service.  The archive is the authority on what has actually been confirmed,
so the numbers in a fact corner are the real ones -- and they are fetched at
the moment the card is built, so they cannot drift into the fiction.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

#: The archive's TAP endpoint.  It speaks SQL over HTTP and answers in JSON.
ARCHIVE_TAP = "https://exoplanetarchive.ipac.caltech.edu/TAP/sync"

#: Parsecs to light years.
PARSEC_TO_LIGHT_YEARS = 3.26156

#: The planets worth putting on a card, and why a child should care.
#: The numbers come from the archive; the reason is ours.
NOTABLE: dict[str, str] = {
    "Proxima Cen b": (
        "The closest planet we have ever found to Earth. You can almost see "
        "its star from here on a very dark night."
    ),
    "TRAPPIST-1 d": (
        "One of seven planets circling a single tiny star. Three of the seven "
        "sit in the warm middle zone, where water could be liquid."
    ),
    "TRAPPIST-1 e": (
        "The second of the three TRAPPIST-1 worlds in the warm zone. Its whole "
        "year lasts less than a day -- the planet spins around its star faster "
        "than we turn."
    ),
    "TRAPPIST-1 f": (
        "The outermost of the three warm worlds, and the biggest of them: a "
        "little larger than Earth."
    ),
    "Kepler-186 f": (
        "The first planet ever found that is about the size of Earth and in the "
        "warm zone. It was the first really good hint that Earth-sized planets "
        "are common out there."
    ),
    "Kepler-452 b": (
        "An older cousin of Earth: bigger than Earth, in the warm zone, and "
        "orbiting a star that is older than our Sun."
    ),
    "TOI-700 d": (
        "The first Earth-sized planet in the warm zone found by NASA's TESS "
        "telescope, which looks for the tiny shadow a planet casts."
    ),
    "55 Cnc e": (
        "A super-Earth that is much bigger than ours and far too close to its "
        "star. The heat turns its rock into lava rivers."
    ),
    "GJ 1214 b": (
        "A super-Earth wrapped in a thick blanket of gas, a bit like a beach "
        "ball under a duvet."
    ),
    "HD 189733 b": (
        "A gas giant that races around its star in just over two days, so hot "
        "that its atmosphere is blowing off into space."
    ),
    "LHS 1140 b": (
        "A rocky world in the warm zone that may have an atmosphere, and so "
        "may have kept its air."
    ),
    "K2-18 b": (
        "A planet in the warm zone that astronomers have looked at closely for "
        "signs of an atmosphere."
    ),
    "Kepler-16 b": (
        "A planet with two suns. It circles both of them, so one of them rises "
        "and sets just like our Sun does."
    ),
    "PSR B1257+12 b": (
        "The very first planet ever found outside our solar system, and it "
        "circles the dead remains of a star that exploded."
    ),
    "WASP-12 b": (
        "A gas giant so close to its star that it is stretched out like an egg "
        "and being pulled apart."
    ),
}


@dataclass
class PlanetFact:
    """One planet, with the numbers the archive holds."""

    name: str
    host: str = ""
    distance_ly: float = 0.0
    year_days: float = 0.0
    earth_radii: float = 0.0
    earth_masses: float = 0.0
    temp_c: float = 0.0
    discovered: int = 0
    method: str = ""
    note: str = ""
    extra: dict[str, Any] = field(default_factory=dict)

    # ------------------------------------------------------------------
    @property
    def year_years(self) -> float:
        """The length of one of its years, in Earth years."""
        return self.year_days / 365.25

    def as_sentences(self) -> list[str]:
        """The fact, said out loud.

        Every number that appears here was read from the archive, and it is
        rounded the way a person would say it to a child: "about four light
        years", not "4.246".
        """
        lines: list[str] = []
        if self.note:
            lines.append(self.note)

        if self.distance_ly:
            lines.append(
                f"It is about {round(self.distance_ly)} light years away from Earth."
            )
        if self.year_days:
            if self.year_days < 2:
                hours = round(self.year_days * 24)
                lines.append(f"One of its days is only {hours} hours long.")
            elif self.year_days < 300:
                lines.append(f"Its year is {round(self.year_days)} Earth days long.")
            else:
                lines.append(
                    f"One of its years is {self.year_years:.1f} Earth years long."
                )
        if self.earth_radii:
            if self.earth_radii >= 8:
                lines.append(
                    f"It is a gas giant, {round(self.earth_radii)} times the size of Earth."
                )
            else:
                lines.append(
                    f"It is {self.earth_radii:.1f} times the size of Earth."
                )
        if self.temp_c:
            lines.append(
                f"The temperature there is about {round(self.temp_c / 5) * 5} degrees."
            )
        if self.discovered:
            lines.append(f"We found it in {self.discovered}.")
        return lines

    def narration(self) -> str:
        """This planet, as a short paragraph meant to be read aloud."""
        lines = self.as_sentences()
        if not lines:
            return ""
        opening = f"{self.name}."
        if self.host:
            opening += f" It goes around the star {self.host}."
        return opening + " " + " ".join(lines)


# ----------------------------------------------------------------------
# fetching
# ----------------------------------------------------------------------
def _query(names: list[str]) -> list[dict[str, Any]]:
    """Ask the archive about a list of planets."""
    import requests

    quoted = ",".join("'" + n.replace("'", "''") + "'" for n in names)
    sql = (
        "select pl_name,hostname,sy_dist,pl_orbper,pl_rade,pl_bmasse,"
        "pl_eqt,disc_year,discoverymethod "
        f"from ps where default_flag=1 and pl_name in ({quoted})"
    )
    resp = requests.get(
        ARCHIVE_TAP,
        params={"query": sql, "format": "json"},
        timeout=120,
    )
    resp.raise_for_status()
    rows = resp.json()
    return rows if isinstance(rows, list) else []


def _number(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def exoplanet_facts(
    names: list[str] | None = None,
    *,
    limit: int = 8,
    timeout_note: str = "",
) -> list[PlanetFact]:
    """The facts for a set of notable planets.

    The archive is asked for the numbers; :data:`NOTABLE` says why each one
    is worth a child's attention.  A planet the archive has not confirmed is
    simply left out -- the point of asking an authority is that it does not
    make things up.
    """
    wanted = names or list(NOTABLE)[: max(limit, 1)]
    rows = _query(wanted)

    found: dict[str, PlanetFact] = {}
    for row in rows:
        name = str(row.get("pl_name") or "")
        if not name or name in found:
            continue
        dist_pc = _number(row.get("sy_dist"))
        found[name] = PlanetFact(
            name=name,
            host=str(row.get("hostname") or "").replace(" ", " "),
            distance_ly=dist_pc * PARSEC_TO_LIGHT_YEARS if dist_pc else 0.0,
            year_days=_number(row.get("pl_orbper")),
            earth_radii=_number(row.get("pl_rade")),
            earth_masses=_number(row.get("pl_bmasse")),
            temp_c=_number(row.get("pl_eqt")) - 273.15 if row.get("pl_eqt") else 0.0,
            discovered=int(_number(row.get("disc_year"))),
            method=str(row.get("discoverymethod") or ""),
            note=NOTABLE.get(name, ""),
        )

    ordered: list[PlanetFact] = []
    for name in wanted:
        fact = found.get(name)
        if fact is not None:
            ordered.append(fact)
    return ordered


def confirmed_count() -> int:
    """How many planets the archive says have been confirmed."""
    import requests

    sql = "select count(*) as n from ps where default_flag=1"
    try:
        resp = requests.get(
            ARCHIVE_TAP, params={"query": sql, "format": "json"}, timeout=180
        )
        resp.raise_for_status()
        rows = resp.json()
        if isinstance(rows, list) and rows:
            return int(_number(rows[0].get("n")))
    except Exception:
        pass
    return 0


#: The planets that make a good story, best first.  A story about one world
#: cannot get the facts mixed up the way a story about eight can.
STORY_PICKS: list[str] = [
    "Kepler-16 b",
    "Proxima Cen b",
    "TRAPPIST-1 e",
    "WASP-12 b",
    "PSR B1257+12 b",
]


#: Claims a story about an exoplanet must not make.
#:
#: These are the ways a story about another star's planet goes wrong: it
#: puts the planet in our solar system, and it says we have found life.
#: Neither is true, and a five year old will believe both.
EXOPLANET_CLAIMS: list[str] = [
    "around the sun",
    "around our sun",
    "orbits the sun",
    "orbit our sun",
    "around our star",
    "its own sun",
    "our star",
    "closest planet to our own star",
    "closest planet to our sun",
]

#: Claims about life somewhere else.  These are only wrong when they are
#: about another world; a story may say that there is life on Earth.
EXOPLANET_LIFE_CLAIMS: list[str] = [
    "life exists",
    "we found life",
    "found life on",
    "there's life",
    "there is life",
    "has life",
    "second earth",
    "another earth",
]


def research(topic: str, *, limit: int = 8) -> dict[str, Any]:
    """The research notes for a topic.

    Only the topics that have a source behind them come back with facts; the
    rest come back empty and the writer is left to its own devices.

    Two things come back.  ``fact_corner`` is the finished narration for the
    facts track, written from the archive and grouped planet by planet, so
    that the numbers on the card are the real ones however badly the model
    writes the story.  ``focus`` is the single world the story should be
    about.
    """
    slug = topic.strip().lower().replace(" ", "-")
    if slug not in ("exoplanets", "exoplanet", "planets", "exo-planets"):
        return {
            "topic": topic,
            "facts": [],
            "groups": [],
            "fact_corner": "",
            "focus": "",
            "focus_detail": "",
            "notes": "",
            "source": "",
            "fact_text": "",
            "claims": [],
            "life_claims": [],
        }

    facts = exoplanet_facts(limit=limit)

    groups: list[dict[str, Any]] = []
    blocks: list[str] = []
    for fact in facts:
        lines = fact.as_sentences()
        groups.append(
            {
                "name": fact.name,
                "host": fact.host,
                "note": fact.note,
                "lines": lines,
            }
        )
        block = [fact.name]
        if fact.host:
            block.append(f"(it goes around the star {fact.host})")
        block.extend(f"- {line}" for line in lines)
        blocks.append("\n".join(block))

    total = confirmed_count()
    notes = ""
    if total:
        notes = (
            f"The NASA Exoplanet Archive currently lists {total:,} confirmed "
            f"planets outside our solar system."
        )

    # The fact corner: the archive, told straight.
    corner_parts: list[str] = []
    if notes:
        corner_parts.append(notes)
    for fact in facts:
        paragraph = fact.narration()
        if paragraph:
            corner_parts.append(paragraph)

    # The world the story is about.
    focus = ""
    focus_detail = ""
    by_name = {f.name: f for f in facts}
    for wanted in STORY_PICKS:
        candidate = by_name.get(wanted)
        if candidate is None:
            continue
        focus = candidate.name
        detail = [f"{candidate.name}."]
        if candidate.host:
            detail.append(f"It goes around the star {candidate.host}.")
        detail.extend(candidate.as_sentences())
        focus_detail = " ".join(detail)
        break

    return {
        "topic": topic,
        "facts": [f.as_sentences() for f in facts],
        "groups": groups,
        "fact_corner": "\n\n".join(corner_parts),
        "focus": focus,
        "focus_detail": focus_detail,
        "notes": notes,
        "source": "NASA Exoplanet Archive (exoplanetarchive.ipac.caltech.edu)",
        "fact_text": "\n\n".join(blocks),
        "claims": EXOPLANET_CLAIMS,
        "life_claims": EXOPLANET_LIFE_CLAIMS,
    }


__all__ = [
    "ARCHIVE_TAP",
    "EXOPLANET_CLAIMS",
    "EXOPLANET_LIFE_CLAIMS",
    "NOTABLE",
    "STORY_PICKS",
    "PlanetFact",
    "confirmed_count",
    "exoplanet_facts",
    "research",
]
