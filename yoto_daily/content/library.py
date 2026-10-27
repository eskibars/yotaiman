"""The content library: themes written by hand.

A small local model can write a decent sentence.  It cannot write a story a
child wants to hear twice, and it cannot write facts that are both true and
worth hearing.  So the themes that matter are written here, by hand, and the
model is only used for topics this library does not cover.

Every number in here was read out of the NASA Exoplanet Archive.  The words
around them are the point.

A theme is a list of segments, and a segment is one thing on the card:

============ ============ ====================================================
kind         read by      what it is
============ ============ ====================================================
``story``    the narrator a story, with a beginning and an end
``song``     ACE-Step     lyrics and a description of how to sing it
``facts``    the narrator the true parts, said like a person, not a list
``explainer`` the narrator how something was worked out, step by step
============ ============ ====================================================

The order of the segments is the order they play in.  A story is followed
by the song that goes with it, and the true parts come last, so a child
gets a story, a song, another story, another song, and then the facts
they can go and check.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

#: The audience the library is written for.  One child is five, the other
#: is ten, and they are listening together, so the short one must never be
#: bored and the older one must never be talked down to.
DEFAULT_AUDIENCE = "two children, one about five years old and one about ten"


@dataclass
class Segment:
    """One thing on the card."""

    kind: str  # "story" | "song" | "facts" | "explainer"
    title: str
    text: str = ""
    lyrics: str = ""
    prompt: str = ""
    #: Which planet the segment is about, when it helps to say so.
    subject: str = ""
    #: The picture to show next to the track: book, note, star, telescope,
    #: suns, clock or planet.  Empty lets the kind of segment decide.
    icon: str = ""
    #: How long a song should be, in seconds.  Ignored by everything else.
    seconds: float = 0.0

    @property
    def is_song(self) -> bool:
        return self.kind == "song"


@dataclass
class AuthoredTheme:
    """A whole theme, written by hand."""

    slug: str
    name: str
    title: str
    segments: list[Segment] = field(default_factory=list)
    #: The facts behind the theme, for the manifest.
    source: str = ""
    #: The picture on the card's cover.  Empty uses the first segment's.
    icon: str = ""

    @property
    def words(self) -> int:
        return sum(len(s.text.split()) for s in self.segments)

    @property
    def narration_seconds(self) -> float:
        """How long the spoken parts run, at a storybook pace."""
        return self.words / (WORDS_PER_MINUTE / 60.0)

    def to_dict(self) -> dict[str, Any]:
        return {
            "slug": self.slug,
            "name": self.name,
            "title": self.title,
            "source": self.source,
            "segments": [
                {
                    "kind": s.kind,
                    "title": s.title,
                    "text": s.text,
                    "lyrics": s.lyrics,
                    "prompt": s.prompt,
                    "subject": s.subject,
                    "icon": s.icon,
                    "seconds": s.seconds,
                }
                for s in self.segments
            ],
        }


#: The pace a story is read at when a grown-up reads it to a child who is
#: not quite ready for bed.
WORDS_PER_MINUTE = 145


# ======================================================================
# Exoplanets
# ======================================================================
EXOPLANETS = AuthoredTheme(
    slug="exoplanets",
    name="Exoplanets",
    title="Exoplanets",
    source="NASA Exoplanet Archive",
    icon="planet",
    segments=[
        # ------------------------------------------------------------------
        Segment(
            kind="story",
            title="The Year That Lasted Six Days",
            subject="TRAPPIST-1 e",
            icon="clock",
            text="""Hello you two. Come here, I want to tell you about a birthday.

Not your birthday. Somebody else's, on a planet you have never heard of. A planet where a birthday comes round every six days. Not every year. Every six days. You would be seven days old on the day you were born, and you would be eight before you had finished your first cup of tea.

Now. How does a year work on the planet where you live? The Earth goes round the Sun, and that trip takes a whole year. Three hundred and sixty-five days. You go round once, and when you get back to where you started, somebody has put another cake on the table.

So imagine a planet that goes round its star much faster. So fast that the trip takes six days instead of six hundred and fifty-one. That is a real planet. It is called TRAPPIST-one e, and it is one of seven worlds circling a single small star, out past where our Sun ends.

Seven planets. All of them going round the same little star, like seven children running round a lamppost. And three of the seven are in the warm zone. The warm zone is the band around a star where it is not boiling hot and not freezing cold, where water could sit on the ground as a liquid and not turn to ice and not boil away. Right here, where you live, Earth sits in the warm zone of our Sun. TRAPPIST-one d, TRAPPIST-one e and TRAPPIST-one f sit in the warm zone of theirs.

Here is the strange thing about that little star, though. It is much smaller than our Sun. It is red. It is dimmer than a candle compared with the Sun. And yet here are three worlds in its warm zone, and they are not boiling, and they are not frozen solid.

So how would it feel to live on TRAPPIST-1 e? Cold, for a start. The average temperature there is about minus twenty-three degrees. Colder than a snowy day where you live, but not so cold that everything is ice. The planet is a little smaller than Earth, a bit narrower, and it is made of rock, and it probably has a thick blanket of gas around it, like a giant winter coat.

Now. Here is the question I find I cannot put down. If a year is six days, then a holiday is six days. A summer holiday would be gone before you had finished the first one. Your favourite day of the year would come round nine times before the end of the year. Every single day would be somebody's birthday, and the party would never stop.

Would you like that? I genuinely do not know the answer. I think I would want to know somebody who had been there. Would you get tired of cake? Would you miss a birthday that took a whole year to arrive? Or would it feel like the best thing in the world to wake up and know that something wonderful was only ever six sleeps away?

Six sleeps. And then it all happens again.

Nobody knows the answer yet, because nobody has ever stood on TRAPPIST-one e. Nobody has even seen it properly. It is a dot. A very small dot, in a very long way away, six light years from here, and it takes light from there six whole years to reach us, so when you look at it tonight, you are seeing the planet as it was six years ago. Every time you look up, you are looking at the past. You do that with everything, of course. You are always looking at the past when you look at a star. But this one is a whole six years of past.

Six days for a year. Six years for the light to come. And two kids on Earth, looking at it, and arguing about what it would be like to have a birthday every six days.

What do you think? Would you want to live somewhere your birthday came round every week? I will tell you what I think, but you can go first.""",
        ),
        # ------------------------------------------------------------------
        Segment(
            kind="song",
            title="Six Days",
            subject="TRAPPIST-1 e",
            icon="note",
            seconds=120,
            lyrics="""Six days round the lamppost, six days round the star
Your birthday comes on a Tuesday, and it is back by Sunday's dark
Six days and a candle, six days and a cake
You would be eight by Wednesday, you'd have had eight years by eight
Seven worlds round one small red sun
Three of them are warm, and we are only looking for one
Six days and a lantern, six days and a light
Somebody's always having a birthday, and somebody always might
Six days is a short year, but it is long enough to play
Round the lamppost six times before the light goes out of the day""",
            prompt=(
                "gentle children's storybook song, acoustic guitar, ukulele, "
                "soft hand clapping, warm and unhurried, a little wonder"
            ),
        ),
        # ------------------------------------------------------------------
        Segment(
            kind="story",
            title="Two Suns in the Sky",
            subject="Kepler-16 b",
            icon="suns",
            text="""Hello again, you two. I want you to close your eyes for a moment and picture the sky where you live.

One Sun. One big yellow one, up in the middle of the blue. If you look to the left, it is still that Sun. If you look to the right, still that Sun. Turn all the way around, and there it is again. One Sun, and it never really goes anywhere.

Now imagine you look up and there are two.

Not one Sun and one Moon. Two Suns. Two stars, hanging in the same sky, and you cannot tell which one is which, because they are the same colour and about the same size, and they are close enough together that they look like one big star with a slightly fat middle.

I am going to tell you about a planet that lives under a sky like that. It is called Kepler-sixteen b, and it is the first planet ever found that goes round two stars at once. Two Suns, and this planet goes round both of them, the way a person goes round a lamppost, except the lamppost is two lampposts stuck together.

Nobody used to think that could happen. A planet orbits a star. That is the rule. One star, one planet, going round. There was no room in the story for a planet with a family of two Suns. Then somebody found Kepler-16, and the story had to grow.

And this is the part that gets me. On Kepler-sixteen b, one of the two Suns goes down, and the other one comes up. Not both at once. One of them sets, and while it is still sinking, the other one is already rising. There is a stretch of sky in the evening where both of them are there together, and then a stretch where only one is, and then a stretch where only the other is, and then they swap over again.

If you were standing on that planet, looking up, you would have to learn which Sun was which. You would name them. You would have a word for the time when both are out, and it would be a special word. And there would be a word for the time when only one is out, and it would be a different word. And there would be a word for the time when neither is out, because the planet turns once every twenty-two and a half hours, and half of that is night.

Do you know what the whole year is like there? Two hundred and twenty-nine days. Longer than a school term, and a bit shorter than a whole year at home. And that planet is enormous. Bigger than Saturn, which is the second biggest planet in our own solar system. It is a gas world, made mostly of hydrogen, with no solid surface to land on at all. Imagine that. You are in a spaceship, in the middle of a cloud of hydrogen, going round two Suns, and your day is a little shorter than the day you know.

You have been on a journey of four hundred and fifty million kilometres every time it goes round. That is a very long walk.

Here is the thing that surprises me most about Kepler-sixteen b, and it is not the two Suns. It is the size of the two Suns themselves. They are tiny. Red dwarfs, they are called. Each one of them is smaller than half the size of our Sun, and dimmer, and cooler, and they are so close together that they are practically touching.

Two small dim Suns, close together. And going round them both, a planet bigger than Saturn.

I do not know what it would be like to stand under that sky. I think I would want to see it in a picture, and I think the picture would have to be drawn by somebody very good, because I do not think I could hold it in my head. Two Suns in the same sky. One going down while the other comes up.

Do you think you would get used to it? I do not think you would. I think you would keep looking up, just to check.""",
        ),
        # ------------------------------------------------------------------
        Segment(
            kind="song",
            title="Two Suns",
            subject="Kepler-16 b",
            icon="note",
            seconds=180,
            lyrics="""Two Suns in the sky, and you can hardly tell them apart
One of them is going down while the other one starts
Two Suns in the sky and the year is long
Going round them both is a whole way to travel on
One of them is setting, one of them is rising
Half of the night is just one of them shining
Two Suns in the sky, and I still get surprised
Somebody set this one and somebody lit that one
Two Suns in the sky and the ground is far below
Nobody has ever landed, nobody has ever let it go
Two Suns in the sky and I wonder what it is like
To watch one of them go, and the other arrive""",
            prompt=(
                "warm children's song about two stars, acoustic guitar, ukulele, "
                "gentle clapping, dusk-time, a bit of wonder, unhurried"
            ),
        ),
        # ------------------------------------------------------------------
        Segment(
            kind="explainer",
            title="How We Found Them",
            subject="the transit method",
            icon="telescope",
            text="""Here is a question that sounds impossible: how do you find a planet when you cannot see it?

Well. You cannot see most of them. That is the surprising bit. Almost every exoplanet we have found is a planet we have never actually looked at. We know it is there because of the shape of its shadow.

Here is how it works. You point a telescope at a star, and you watch it. Just watch it. Now, if a planet happens to be in line, in between you and that star, then for a little while the planet covers a tiny piece of the star, and the star gets a little bit dimmer. Not much. A hundredth of its brightness, sometimes less. So faint that a hundred bright stars in the sky would go past without you noticing.

But we are not looking with our eyes. We are looking with a machine, and a machine that has been watching the same star for years can tell you that the star got a hair dimmer at the same moment, over and over, every time it came around. And when it comes round again, and again, and again, on a schedule, you have found yourself a planet. You have found it by its shadow.

This is how the Kepler spacecraft worked. It launched in 2009 and spent four years staring at about a hundred and fifty thousand stars, and it was very good at it. It found more than two thousand planets. And there is a whole space telescope after it now, called TESS, doing the same thing all over again, with a different set of stars.

And here is my favourite part. The very first exoplanets ever found were not found this way at all. They were found in 1992, around the dead remains of a star that had exploded, and they were found with radio telescopes. Radio telescopes. The planet was never seen, never even heard. It was found because it made the dead star pulse, the way a person walking past a fencepost makes a guitar string hum, and by measuring those tiny pulses, somebody worked out that something was going round.

And that is how we found them. Not by seeing them. By watching what they do to the light.""",
        ),
        # ------------------------------------------------------------------
        Segment(
            kind="facts",
            title="Fact Corner",
            subject="the confirmed planets",
            icon="star",
            text="""Here are some true things, and not one of them is made up.

Right now, there are more than six thousand confirmed planets going round other stars. Six thousand worlds, and every one of them was found by its shadow.

The closest one we have found is called Proxima b. It goes round the nearest star to ours, about four light years away, and it is freezing cold, about minus fifty-five degrees. Its whole year lasts eleven days, and it was found in 2016.

One of the strangest is called PSR B one two five seven plus twelve b. It was the very first planet ever found anywhere, in 1994, and it goes round the remains of a star that exploded. It is tiny. It is about the size of our Moon, and it circles a dead star that spins like a lighthouse beam, thirty times a second.

Then there is fifty-five Cancri e, which is the hottest planet we know of that is not a lump of gas. It goes round its star so close that its year is less than a single day here. It takes only seventeen and a half hours to go all the way round. And it is so hot that the rock has melted into rivers of lava.

And then there is K two eighteen b. It is about twice the size of Earth, it goes round its star every thirty-three days, and it is one of the planets that people are studying very carefully right now, because it is in the warm zone, and because it might have a thick blanket of gas around it, and that is exactly the kind of world where you would go looking for signs of life.

Nobody has found life on any of them. Not one. Every single one of these thousands of worlds is still a question, and not an answer.

And here is the last one, and I think it is the best one. There is a planet called TRAPPIST-1 e, and its year lasts six days. Its birthday comes round once a week. Somebody, somewhere, is having a birthday every six days, and they have not even noticed yet.

Nobody has stood on any of them. Not one. Every one of those six thousand is a dot in a telescope. But they are all real, and they are all out there, and they are all waiting.""",
        ),
    ],
)


# ======================================================================
# The library
# ======================================================================
THEMES: list[AuthoredTheme] = [EXOPLANETS]


def find(slug: str) -> AuthoredTheme | None:
    """The authored theme for a slug, if there is one."""
    wanted = (slug or "").strip().lower().replace(" ", "-")
    for theme in THEMES:
        if theme.slug == wanted:
            return theme
    return None


def slugs() -> list[str]:
    """The themes that are written by hand."""
    return [theme.slug for theme in THEMES]


__all__ = [
    "DEFAULT_AUDIENCE",
    "EXOPLANETS",
    "THEMES",
    "WORDS_PER_MINUTE",
    "AuthoredTheme",
    "Segment",
    "find",
    "slugs",
]
