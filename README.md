# yotaiman

A local SDK and Flask service for the [Yoto](https://yotoplay.com) player.

It exists to solve one problem: **a Yoto card is a static playlist, and this
makes it dynamic.** The service generates content, narrates it, uploads it to
Yoto's media pipeline and rewrites a card — so a single physical card can carry
a fresh story every morning.

```
theme -> research -> text -> voice -> music -> upload -> card write
                         \\-> a folder for the day
```

Four capabilities ship working:

| capability | what it does |
|---|---|
| `daily-theme` | Builds today's themed card: a story, a song and the checked facts, all in one voice. |
| `daily-story` | Writes a story about a topic, narrates it, publishes it as the daily card. |
| `restore-day` | Puts a saved day back on the card, exactly as it was. |
| `read-aloud` | Narrates text you supply (a story typed on a phone, a book chapter) onto any card. |

The Yoto API is not publicly documented. Everything this project knows about it
was recovered by observing a real account, and that record is kept in the
[How the Yoto API actually works](#how-the-yoto-api-actually-works) section
and in `recon/`.

---

## Quick start

```bash
git clone https://github.com/eskibars/yotaiman
cd yotaiman
pip install -e .            # or: pip install -e '.[dev]'

# 0. Copy the settings file and adjust it.  Every value has a working default.
cp .env.example .env

# 1. Copy the login cookies out of a logged-in Chrome.
#    Turn on remote debugging first:  chrome://inspect/#remote-debugging -> Enable
python -m yoto.auth bootstrap

# 2. Publish today's story.
python -m yoto_daily daily --topic dolphins --child-name "Alex"

# 2b. Or publish today's themed card: two stories, two songs, an explainer
#     and the facts, in your own voice, with a picture next to each track.
#     See "Themed cards" below.
python -m yoto_daily theme exoplanets

# 3. Or run the service.
#    The HTML desk is at http://127.0.0.1:8787/
#    The JSON API is at http://127.0.0.1:8787/api/
#    The desk asks for a token the first time; print it with:
python -m yoto_daily token
python -m yoto_daily serve
```

Step 1 copies four cookies (`auth0`, `auth0_compat`, `did`, `did_compat`) from
`login.yotoplay.com` into `~/.config/yotaiman/cookies.json`. The SDK then
mints its own access tokens without a browser. See
[Authentication](#authentication) for why that works.

Installing the package also puts a `yotaiman` command on your path.
`python -m yoto_daily ...` does the same thing if you would rather not install.

---

## Themed cards

A card is a theme. "Exoplanets" is a card; "Dinosaurs" is a card; whatever
you like is a card. One physical card is enough — the daily job rewrites it
each morning with the day's theme, so the card in a child's hand is always
about whatever that day's theme is.

```bash
python -m yoto_daily theme exoplanets
```

That one command does the whole morning:

1. **Research.** The facts come from a source, not from a model's memory.
   For exoplanets that is the NASA Exoplanet Archive, queried live.
2. **Plan.** The theme becomes a playlist: two stories, two songs, an
   explainer and a fact corner, in that order. A story is followed by the
   song that goes with it, and the true parts come last.
3. **Narrate.** The stories, the explainer and the facts are read out loud
   in your cloned voice, by [Ming-3.0-tts](#speech), at a storybook pace.
4. **Compose.** ACE-Step writes the songs, with lyrics from the plan. Two
   to four minutes each, because a forty-second song is not a song a child
   learns.
5. **Draw.** Every track gets a 16×16 picture — a book for a story, a
   note for a song, a star for the facts. See [Pixel art](#pixel-art).
6. **Publish.** The tracks go on the card, under one chapter named after
   the theme, on the card that is paired with your player.
7. **Save.** Everything is written to a folder of its own — see
   [Days on disk](#days-on-disk).

A themed card runs to **at least ten minutes**. The exoplanets card is
about twenty-two: two stories of five minutes each, a three-minute song
and a two-minute song, and then the explainer and the facts.

The audience is set in `config.yaml`:

```yaml
theme:
  audience: "two children, one about five years old and one about ten"
```

Every part can be turned off while you are trying something:

```bash
python -m yoto_daily theme exoplanets --plan-only   # what would go on it
python -m yoto_daily theme exoplanets --no-song
python -m yoto_daily theme exoplanets --voice dad --instruction "slow and sleepy"
```

### The words are written by hand, not by the model

This is the one rule worth keeping. A small local model can write a decent
sentence. It cannot write a story a child wants to hear twice, and it
cannot write facts that are both true and worth hearing — a model given
eight sets of numbers to restate will eventually mix them up, and a child
listening to a wrong number is worse off than one listening to no number
at all.

So the themes that matter live in `yoto_daily/content/library.py`, written
by hand, with every number checked against the NASA Exoplanet Archive. The
model is only asked for topics the library does not cover, and when it is
asked it writes the story and the song while the facts are handed over
already finished.

A library theme is also a *long* theme, because it was written to be one:
two stories, two songs, an explainer and a fact corner. A model-written
theme is three tracks — a story, a song and the facts — and the card says
so.

To add a theme, add a `Segment` to the library and give it a slug:

```python
Segment(
    kind="story",                  # story | song | facts | explainer
    title="The Year That Lasted Six Days",
    subject="TRAPPIST-1 e",        # picks the picture, too
    text="""Hello you two. ...""",
)
```

### The card is adopted, never invented

A Yoto card is paired with a player in the Yoto app. The card that is
paired is the one that matters: content written to a card nobody has paired
is a card nobody will ever hear. So the daily card is adopted, in this
order:

1. `daily.card_id` in `config.yaml` — the strongest statement of intent
2. the id remembered from the last run
3. an existing card whose title looks like the daily card, for the case
   where the state file was lost but the card is still there
4. only then, a new card

```yaml
daily:
  card_id: "1LHgD"      # the card paired with your player
```

---

## Pixel art

The Yoto app and the player show a little 16×16 picture next to each
track. The pictures are drawn in code rather than shipped as files, in
`yoto_daily/pixelart.py`, so changing what a story looks like is a
one-line edit:

```python
from yoto_daily.pixelart import preview

print(preview(pixelart.icon_for("story", "TRAPPIST-1 e")))
```

```
      ###                    
     ##  ##                   
    ##      ##                 
   ##        ##                
  ##          ##               
 ##            ##              
 #              #             
 #              #             
 #              #             
 #              #             
 #              #             
  #            #              
  ##          ##              
   ##        ##               
    ##      ##                
     ##  ##                   
      ###                    
```

There are seven shapes — a book, a note, a star, a telescope, two suns, a
clock and a planet — and each kind of track gets one by default. A track
that names a planet gets the planet; one that is about a year gets the
clock; one about how we found them gets the telescope. A segment in the
content library says which picture it wants, and that always wins.

Each picture is uploaded once and then shared by every track that wants
the same picture, so a six-track card does not carry six copies of the
same book. The ids are remembered in the state file, so tomorrow's card
reuses them.

The card gets a cover as well: the theme's picture, blown up on a night
sky, drawn at 512×512 and uploaded to the card's cover slot. It is drawn
the same way, so a new theme gets a new cover without anybody opening an
image editor.

---

## Days on disk

A card on Yoto is a pointer to media that lives on somebody else's server.
That is a thin thing to own a year of mornings with, so every run writes the
day out as well:

```
~/.config/yotaiman/work/2026-10-27-exoplanets/
  manifest.json                        how the card was put together
  01-the-year-that-lasted-six-days.txt  the words of the story
  01-the-year-that-lasted-six-days.mp3  the story, in your voice
  02-six-days.txt                     the lyrics
  02-six-days.mp3                     the song
  03-two-suns-in-the-sky.txt          the words of the second story
  03-two-suns-in-the-sky.mp3          the second story, in your voice
  04-two-suns.txt                     the lyrics
  04-two-suns.mp3                     the song
  05-how-we-found-them.txt            the words of the explainer
  05-how-we-found-them.mp3            the explainer, in your voice
  06-fact-corner.txt                  the words of the facts
  06-fact-corner.mp3                  the facts, in your voice
```

The transcripts and the audio sit next to a manifest that says how the card
was built, so any morning can be put back exactly as it was:

```bash
python -m yoto_daily days                    # what is saved
python -m yoto_daily restore --date 2026-10-27   # put it back on the card
python -m yoto_daily restore --slug exoplanets  # by theme, newest first
```

Restoring re-uploads the audio from the folder and rewrites the card, so it
works even if the card has moved on to a later theme. The folder is the
source of truth; the card is a copy of it.

A build that is interrupted picks up where it stopped: the audio already in
the folder is reused rather than made again, so re-running the theme after a
crash costs minutes rather than an afternoon.

---

## Your voice, as a reference clip

Ming-3.0-tts clones a voice from a short clip and its exact transcript. The
clip has to be short. The model shares one 512-position budget between the
reference clip, its transcript and the words it has to speak, so a long
clip does not merely sound worse — it eats the budget, and what is left is
enough for a handful of words.

The recording you actually make is a minute and a half of you reading a
script. `prepare-voice` cuts it down:

```bash
python -m yoto_daily prepare-voice \
    --wav my-recording.wav \
    --out-wav voice/reference.wav \
    --out-text voice/reference.txt \
    --transcript my-recording.txt
```

It finds a window of speech between three and eight seconds long, prefers
one that starts at the beginning of a sentence and runs without a long
pause, and cuts the audio to match. The words are taken from **your**
transcript, not from the speech recogniser: the recogniser only supplies
the timings, so the spelling, the punctuation and the capitalisation are
the ones you wrote. A model that conditions on a mis-heard word reproduces
the mis-heard word.

Then point a voice at the two files:

```yaml
generators:
  speech:
    default: ming-tts
    options:
      ming-tts:
        type: ming-tts
        code_path: ../Ming-3.0-tts
        voice: dad
        voices:
          dad:
            reference_wav: voice/reference.wav
            reference_text: "the exact words spoken in that clip"
```

The transcript has to be the words in *that* clip, not the words in the
whole recording. `prepare-voice` writes the right ones for you.

---

## Asking the service for a token

The service drives a personal account, so it does not serve anybody who has
not shown a token. One is generated on the first run and kept in
`~/.config/yotaiman/api-token`, readable only by you.

```bash
# Print it.
python -m yoto_daily token

# Use it against the JSON API.
curl -H "Authorization: Bearer $(python -m yoto_daily token)" \
     http://127.0.0.1:8787/api/

# Or put it in the address bar, which is the only option on a phone.
open "http://127.0.0.1:8787/?token=$(python -m yoto_daily token)"
```

The desk moves a token out of the address bar into a session cookie as soon
as it has it, so it does not linger in the browser history.

Set `YOTO_API_TOKEN` to choose the token yourself, or `YOTO_AUTH=off` to turn
the check off — only do that on a network nobody else can reach.

---

## The HTML desk

`python -m yoto_daily serve` brings up two front ends over the same service
layer: a browser UI at `/` and the JSON API at `/api/`. The desk is not a
separate implementation — every action it offers calls the same
`yoto_daily.tracks.TrackService` and `yoto_daily.cards` code the API calls.

| page | what it does |
|---|---|
| `/` | The shelf: every card on the account, the daily card's status, and a button to publish today's story. |
| `/cards/<card_id>` | One card: its programme track by track, the playback options, and the destructive actions. |
| `/cards/<card_id>/add` | Add a track — stream, file, or generate. |
| `/generators` | The configured music and speech generators, and which one is the default. |

```
GET  /                              the shelf
GET  /cards/<card_id>               one card
GET  /cards/<card_id>/add           the add-a-track form
POST /cards/<card_id>/add           add a track
POST /cards/<card_id>/options       save the playback options
POST /cards/<card_id>/delete        delete the card
POST /cards/<card_id>/tracks/<key>/delete   delete one track
POST /daily                         publish today's story
GET  /generators                    the generator catalogue
```

Forms use POST-redirect-GET, so a browser refresh never republishes a story or
re-adds a track. The result of a submission comes back as a flash message.

The one thing worth knowing about the layout is the **duration spine**: each
track is drawn as a horizontal bar whose width is that track's share of the
card's total runtime, so a 29-second story next to a 6-minute book reads as
proportion rather than as a list of numbers. Each card also gets a deterministic
edge colour derived from its id, so the same physical card is recognisable at a
glance on the shelf.

The templates live in `yoto_daily/templates/`, the stylesheet in
`yoto_daily/static/style.css`, and the panel switching in
`yoto_daily/static/composer.js`. The composer is the one piece of JavaScript:
it shows only the panel for the chosen track type and disables the inputs in
the hidden ones, so a stale `url` field from another panel cannot be submitted.
Without it, `<noscript>` still renders every panel and the form still works.

---

## The JSON API

```
GET    /api/health              service and session status
GET    /api/cards               every card on the account
GET    /api/cards/<card_id>     one card with its chapters and tracks
DELETE /api/cards/<card_id>     delete a card entirely
DELETE /api/cards/<card_id>/<key>   delete one track
PUT    /api/cards/<card_id>     reset a card (remove tracks, set options)
POST   /api/cards/<card_id>/cover    set the cover image
POST   /api/cards/<card_id>/tracks   add a track
GET    /api/generators          every generator
GET    /api/generators/music    the music generators
GET    /api/generators/speech   the speech generators
GET    /api/capabilities        the capability catalogue
POST   /api/capabilities/<name> run one capability
GET    /api/topics              the rotating topic bank
GET    /api/daily               what is on the daily card right now
POST   /api/daily               publish today's story
GET    /api/days                the days that were saved on disk
POST   /api/days/<date>/restore put a saved day back on the card
POST   /api/themes              build today's themed card
```

```bash
TOKEN=$(python -m yoto_daily token)

curl -s -H "Authorization: Bearer $TOKEN" localhost:8787/api/health | jq
curl -s -H "Authorization: Bearer $TOKEN" localhost:8787/api/cards  | jq '.cards[] | {card_id, title, duration}'
curl -s -H "Authorization: Bearer $TOKEN" localhost:8787/api/generators/music | jq
curl -s -X POST localhost:8787/api/daily \
     -H "Authorization: Bearer $TOKEN" \
     -H 'Content-Type: application/json' \
     -d '{"topic":"dolphins","child_name":"Alex"}' | jq

# The themed card.
curl -s -X POST localhost:8787/api/themes \
     -H "Authorization: Bearer $TOKEN" \
     -H 'Content-Type: application/json' \
     -d '{"theme":"exoplanets"}' | jq

# The saved days, and putting one back.
curl -s -H "Authorization: Bearer $TOKEN" localhost:8787/api/days | jq
curl -s -X POST localhost:8787/api/days/2026-10-26/restore \
     -H "Authorization: Bearer $TOKEN" | jq
```

Every endpoint asks for the token; see
[The perimeter](#the-perimeter). The service binds to `127.0.0.1` by
default. `YOTO_ALLOW_REMOTE=true` widens the bind, so only do that on a
trusted network — and put the address your phone will use in
`YOTO_ALLOWED_HOSTS` when you do.

### Cards

`PUT /api/cards/<card_id>` resets a card: every track is removed, and the
name, description and playback options can be set in the same call.

```bash
curl -s -X PUT localhost:8787/api/cards/CARD_ID \
     -H 'Content-Type: application/json' \
     -d '{"title": "Bedtime",
          "description": "Stories for the end of the day",
          "options": {"always_play_from_start": true,
                      "shuffle": true,
                      "hide_track_numbers": true}}' | jq
```

Those three options map onto the API exactly as the Yoto web app writes them:

| option | API field |
|---|---|
| always play from start | `content.config.resumeTimeout = 0` |
| shuffle tracks each time | `content.config.shuffle = [{start: 0, end: n-1, limit: n}]` |
| hide track numbers | overlay labels removed, `content.editSettings.autoOverlayLabels = "disabled"` |

The shuffle range covers chapter indices, so it is recomputed on every write —
switching shuffle on for an empty card keeps the switch on once tracks arrive.

`DELETE /api/cards/<card_id>/<key>` removes one track by its key. Add
`?chapter=<chapterKey>` when the same key appears in more than one chapter.

`POST /api/cards/<card_id>/cover` takes an uploaded image file, a `url` or a
`path`.

### Tracks

`POST /api/cards/<card_id>/tracks` adds a track. The body always has a `type`:

**Stream** — plays from a URL; nothing is uploaded.

```json
{"type": "stream", "url": "https://example.com/episode.mp3"}
```

**File** — an audio file on disk, or one fetched from a URL.

```json
{"type": "file", "path": "lullaby.mp3"}
{"type": "file", "url": "https://example.com/lullaby.mp3"}
```

A `path` has to resolve inside one of the content directories —
`~/yotaiman` by default, or whatever `YOTO_CONTENT_DIRS` says. It may be
absolute or relative to one of them; anything that lands outside is
refused, so the service cannot be used to read a file it should not reach.
A `url` is only fetched if it is `http` or `https` and it does not point
back at this machine or the local network.

**Generate** — the audio is produced first, then uploaded like a file. The
`kind` selects what produces it.

```json
{"type": "generate", "kind": "music", "generator": "ace-step-local",
 "params": {"prompt": "gentle solo piano, calm bedtime music",
            "bpm": 80, "key_scale": "C Major", "duration": 60,
            "tags": ["calm", "instrumental"]}}

{"type": "generate", "kind": "text-to-speech", "generator": "say",
 "params": {"text": "Once upon a time...", "voice": "Karen"}}

{"type": "generate", "kind": "read-book", "generator": "say",
 "params": {"source": "/path/to/whale.epub", "chapters": 3}}
```

A read-book track produces one track per chapter of the book, so one request
can add several tracks.

The `generator` name is optional — it defaults to whichever generator is
marked `default` in `config.yaml`. The same parameters also work at the top
level of the body, so `{"type": "generate", "kind": "music", "bpm": 90}` is
valid too.

---

## Layout

```
yoto/                    the SDK
  auth.py                Auth0 PKCE silent auth, token cache
  client.py              retrying HTTP client for api.yotoplay.com
  cards.py               card CRUD (read, create, upsert, reset, delete)
  media.py               upload -> transcode -> media id, cover images
  models.py              Card / CardContent / Chapter / Track
  errors.py              exception hierarchy
  _ws.py                 stdlib WebSocket, used by the cookie bootstrap
  _cdp.py                finds the Chrome DevTools endpoint

yoto_daily/              the service
  app.py                 Flask application, registers both blueprints
  api.py                 the JSON API blueprint (/api)
  web.py                 the HTML control desk blueprint (/)
  config.py              settings: config.yaml plus the environment
  daily_card.py          which card is the daily one: adopted, never invented
  days.py                one folder per day: transcripts, audio, manifest
  gate.py                the perimeter: token, Host, Origin, CSRF
  icons.py               uploads the little pictures, once per picture
  numbers.py             writes numbers out so they are read out correctly
  pixelart.py            the 16x16 pictures, drawn in code
  research.py            checked facts, from the NASA Exoplanet Archive
  security.py            the guards: safe_fetch, path confinement, token
  state.py               small JSON state store
  token_refresher.py     keeps the access token fresh in the background
  tracks.py              the track service (stream / file / generate)
  voice.py               cuts a usable voice reference out of a recording
  generators/            music and speech generators
    base.py              MusicSpec, MusicGenerator, SpeechGenerator
    ming_tts.py          Ming-3.0-tts, narrating in a cloned voice
    music.py             ACE-Step 1.5, and a procedural fallback
    speech.py            macOS say, and a generic HTTP endpoint
    registry.py          builds the generators from config.yaml
  capabilities/          the extension point
    base.py              Capability ABC + registry
    daily_story.py       the daily story
    daily_theme.py       the themed card: the stories, the songs, the facts
    read_aloud.py        read supplied text
    restore_day.py       put a saved day back on the card
  content/
    library.py           the themes written by hand
    ollama.py            a local Ollama server
    plan.py              the theme, turned into the tracks of a playlist
    text.py              text generation backends
    theme.py             themes: a story, a song and the facts
    tts.py               text-to-speech backends
    books.py             mobi / epub / pdf / html / url -> text
  templates/             the Jinja templates for the HTML desk
    base.html            shell, navigation, flash messages
    index.html           the shelf
    card.html            one card: programme, options, actions
    add_track.html       the add-a-track composer
    generators.html      the generator catalogue
  static/
    style.css            the design system
    composer.js          panel switching for the composer form

config.yaml              generator configuration (this is the file you edit)

recon/                   the research tools that recovered the API
  capture.mjs            record the Yoto web app's network traffic
  cdp.mjs                a minimal Chrome DevTools Protocol client
  dump_auth.mjs          list the auth cookies and storage
  extract-endpoints.mjs  pull endpoints out of the minified bundles
  probe_auth.py          which Auth0 silent-reauth variants work
  probe_write.py         the correct write method and body shape
  probe_options.py       which playback options actually persist
  e2e_upload.py          upload -> transcode -> content write, end to end
  shot.mjs               screenshot a page for a look

tests/
  test_unit.py           offline tests
  test_generators.py     offline tests for generators, books and options
  test_acestep.py        offline tests against a stub ACE-Step server
  test_web.py            offline tests for the HTML desk
  test_live.py           live tests against the real API
  test_live_tracks.py    live tests for the card and track API
```

---

## Using the SDK directly

```python
from yoto import Yoto

y = Yoto()

for card in y.cards.list():
    print(card.card_id, card.title, card.duration, "seconds")

upload = y.media.upload_audio("story.mp3")
print(upload.media_id)          # 'yoto:#<43-char sha256>'
print(upload.duration, upload.format)

track = y.cards.build_track("01", "Tonight's Story", upload.media_id,
                            duration=upload.duration, file_size=upload.file_size)
chapter = y.cards.build_chapter("00", "Tonight's Story", [track])
content = y.cards.build_content([chapter])

y.cards.update_content("CARD_ID", content, title="Tonight")
```

`CardService.update_content` writes through `POST /content`, which upserts:
with a `cardId` in the body it updates that card, without one it creates a
new card. `PUT /content/{id}` is a different, S3-backed operation and is
rejected for normal use.

---

## Adding a capability

Subclass `Capability`, implement `run`, decorate it with `register`:

```python
# yoto_daily/capabilities/bird_of_the_day.py
from .base import Capability, CapabilityResult, register

@register
class BirdOfTheDay(Capability):
    name = "bird-of-the-day"
    description = "Play the calls of the birds heard near the house."
    parameters = [{"name": "species", "type": "string", "required": True}]

    def run(self, **params):
        clip = download_call(params["species"])       # your logic
        upload = self.yoto.media.upload_audio(clip)
        track = self.yoto.cards.build_track("01", params["species"], upload.media_id,
                                             duration=upload.duration,
                                             file_size=upload.file_size)
        chapter = self.yoto.cards.build_chapter("00", params["species"], [track])
        self.yoto.cards.update_content(self.daily_card_id,
                                       self.yoto.cards.build_content([chapter]))
        return CapabilityResult(ok=True, message=f"Published {params['species']}")
```

It is available immediately at `POST /api/capabilities/bird-of-the-day`.
Capabilities receive the shared `Yoto` client, settings and state through
`caps.get_context()`.

---

## Generators

`config.yaml` is the file you edit to choose what generates the audio. It has
two families: **music** and **speech**.

```yaml
generators:
  music:
    default: ace-step-local
    options:
      ace-step-local:
        type: ace-step
        enabled: true
        endpoint: http://127.0.0.1:8001
        model: acestep-v15-turbo
        defaults:
          audio_duration: 60
          inference_steps: 8
          thinking: true

  speech:
    default: say
    options:
      say:
        type: say
        enabled: true
        voice: Karen
      hosted:
        type: http
        enabled: false
        url: https://api.elevenlabs.io/v1/text-to-speech/{voice}
        api_key_env: ELEVENLABS_API_KEY
        voice: rachel
```

`GET /api/generators/music` and `GET /api/generators/speech` list what is
configured, which one is the default, and whether each one is reachable right
now.

### Music

The music interface takes **structured metadata**, not just a prompt:
`prompt`, `lyrics`, `bpm`, `key_scale`, `time_signature`, `duration`,
`instrumental`, `tags` and `seed`. Each backend decides how to render those
into whatever its model expects.

**`ace-step`** talks to a local [ACE-Step 1.5](https://ace-step.github.io/ACE-Step-1.5/en/INFERENCE)
API server:

```
POST /release_task   -> task_id
POST /query_result   -> status (0 running, 1 done, 2 failed)
GET  /v1/audio?path= -> the audio bytes
```

The server's `result` field comes back as a JSON *string* inside the usual
`{data, code, error, timestamp}` wrapper; the client unwraps both. If the
server was started with `ACESTEP_API_KEY`, set the same variable here, or
point `api_key_env` at wherever you keep it.

```bash
python -m acestep.api_server --host 127.0.0.1 --port 8001
```

**`synth`** is a procedural fallback that needs no model or GPU. It renders an
arpeggio of the requested length and tempo. It is not music — it is there so
the track pipeline can be exercised without a GPU.

### Speech

**`say`** uses macOS `say`, which needs no credentials and has voices for most
locales (`Karen` en_AU, `Samantha` en_US, `Daniel` en_GB, `Junior`). It only
exists on macOS — elsewhere it stays in the catalogue but reports itself as
unavailable, and a request that needs narration picks another generator that
does work. If none does, the service says which backend is missing instead of
failing mid-story.

**`http`** covers both a local model server and a hosted service with one
implementation. The contract is:

```
POST <url>   {"text": "...", "voice": "..."}   ->   audio bytes
```

A JSON response containing base64 audio under `audio` or `data` also works.
Kokoro, MLX-Audio and similar servers need only a few lines of glue to that
contract; the URL may contain `{voice}` and `{text}` placeholders if the
service prefers path parameters.

**`ming-tts`** narrates in a voice cloned from a recording, using the local
[Ming-3.0-tts](https://github.com/inclusionAI/Ming-3.0-tts) checkpoint. It is
the only generator that pulls a model into the service process, so it fetches
the checkpoint on first use and keeps it warm afterwards.

It needs two things: the inference code from the GitHub checkout, and the
weights from the Hub.

```bash
# the inference code
git clone https://github.com/inclusionAI/Ming-3.0-tts

# the runtime, in the environment that runs the service
pip install --index-url https://download.pytorch.org/whl/cpu \
    torch==2.6.0 torchaudio==2.6.0
pip install transformers==4.46.3 accelerate==1.3.0 x_transformers==2.9.2 \
    diffusers==0.33.0 onnxruntime soundfile==0.12.1 inflect einops \
    loguru tqdm huggingface_hub
```

Then point `config.yaml` at both and pick a voice:

```yaml
generators:
  speech:
    default: voice          # the daily story follows this too
    options:
      voice:
        type: ming-tts
        code_path: ../Ming-3.0-tts
        model_path: ../Ming-3.0-tts/models/Ming-3.0-tts-0.5b
        reference_wav: ~/yotaiman/my_voice.wav
        reference_text: "the exact words spoken in the clip"
        instruction: "Speak in a warm, intimate storytelling voice, unhurried."
```

`reference_wav` is four to eight seconds of clean speech and
`reference_text` is the **exact** transcript of it — the model conditions on
the words, so a summary of what was said will not clone the voice properly.
The clip has to be short: the model shares one 512-position budget between
the reference, its transcript and the words it speaks, so a long clip leaves
almost nothing to say. `prepare-voice` cuts a usable clip out of a longer
recording — see [Your voice, as a reference clip](#your-voice-as-a-reference-clip).
Leave `model_path` empty and the checkpoint is pulled from the Hub into
`cache_dir` on first use instead.

Several voices can live side by side and be picked by name with the `voice`
parameter:

```yaml
        voices:
          dad:
            reference_wav: ~/yotaiman/dad.wav
            reference_text: "the exact words spoken in dad.wav"
            instruction: "Speak in a warm, intimate storytelling voice, unhurried."
```

Two details are worth knowing. The model caps one generation at a fixed
number of positions, so a long paragraph is split at clause boundaries and
rendered in pieces — the generator does this itself and joins the pieces
with a short pause. And the whole thing runs about three times slower than
realtime on a CPU, which is fine for a card that is refreshed once a day.

Text normalization uses FST grammars that need `pynini`, which has no
Windows wheel; set `text_normalization: false` there.

### Numbers, and how they are read out

A model that is handed "6,451" says "six four fifty one" — three numbers
where there should be one — and a child listening learns that a fact about
planets is a string of digits rather than a quantity.

So the numbers are written out in words before the text reaches the
narrator, in `yoto_daily/numbers.py`:

| written | read out |
|---|---|
| `6,451` | six thousand four hundred and fifty-one |
| `4.2` | four point two |
| `-55` | minus fifty-five |
| `1/2` | one half |
| `16x16` | sixteen by sixteen |
| `45%` | forty-five per cent |
| `1992` | nineteen ninety-two |
| `2016` | twenty sixteen |

The years are treated specially, because "twenty six" is twenty-six and a
discovery year is not. A year from 1900 to 2029 is said the way people
say it.

A **catalogue name** is treated differently again, because it is a name
and not a measurement. `TRAPPIST-1 e` is "TRAPPIST-one e", and `PSR B1257`
is "PSR B one two five seven" — the digits one at a time, the way anybody
says a catalogue number, and never "PSR B one thousand two hundred and
fifty-seven". A short prefix is an acronym said letter by letter ("H D one
eight nine seven three three"); a long one is a word ("TRAPPIST" is said
"trap-ist", not "tee ar ay pee pee eye ess tee").

The same words are written into the transcript beside the audio, so the
transcript is what was actually said.

**Overriding the delivery per request.** The `instruction` in the
configuration is the default. Any request may replace it, which is how one
voice reads a story differently from another:

```bash
curl -X POST http://127.0.0.1:8787/api/cards/<card_id>/tracks \
  -H "Authorization: Bearer $(python -m yoto_daily token)" \
  -H 'Content-Type: application/json' \
  -d '{
        "type": "generate",
        "kind": "text-to-speech",
        "text": "Once upon a time...",
        "instruction": "excited, like a child hearing it for the first time"
      }'
```

The same key works on `read-book` tracks, on the `read-aloud` and
`daily-story` capabilities, and on the add-track form, where it is the
**How to read it** field. Generators that cannot honour it ignore it.

### Adding a generator

```python
from yoto_daily.generators import MusicGenerator, MusicSpec

class MyMusic(MusicGenerator):
    type = "mine"
    def __init__(self, name): self.name = name
    def available(self): return True
    def generate(self, spec: MusicSpec, out_path):
        ...  # write an audio file to out_path
        return AudioResult(path=out_path, backend=self.name)
```

Register the type in `yoto_daily/generators/registry.py` and it becomes
configurable with `type: mine`.

### Reading books

`read-book` converts a book to text and then reads it aloud, one track per
chapter:

| format | reader | needs |
|---|---|---|
| `.epub` | follows the OPF spine | — |
| `.mobi`, `.azw`, `.azw3` | converted to EPUB first | `mobi` |
| `.pdf` | text layer only; scanned images have no text | `pypdf` |
| `.html` | tags stripped, paragraphs kept | — |
| a URL | fetched, then read as HTML, PDF or text | — |

```bash
pip install mobi pypdf
```

`GET /api/generators` reports which of these are available in the current
installation.

---

## Configuration

Every setting is an environment variable; see `.env.example` for the full list
with defaults.

Copy `.env.example` to `.env` and edit it — the command line tools
(`yotaiman`, `python -m yoto_daily`, `python -m yoto.auth`) read that file on
startup, so the same setup works on a machine with no shell profile. A value
already exported in the shell wins over the file, and the file is only read by
the command line: importing the library leaves the environment alone.

| variable | default | meaning |
|---|---|---|
| `YOTO_STATE_DIR` | `~/.config/yotaiman` | cookies, token, state, audio |
| `YOTO_HOST` / `YOTO_PORT` | `127.0.0.1` / `8787` | where the API listens |
| `YOTO_ALLOW_REMOTE` | `false` | bind to all interfaces |
| `YOTO_API_TOKEN` | *(generated)* | the token the service expects; empty means use the one in the state directory |
| `YOTO_AUTH` | `on` | `off` drops the token check — only safe on a network nobody else can reach |
| `YOTO_ALLOWED_HOSTS` | `localhost,127.0.0.1` | Host names the service answers to, comma separated |
| `YOTO_CONTENT_DIRS` | `~/yotaiman` | where a caller-supplied file path may point, `:` separated |
| `YOTO_MAX_TEXT` | `5000` | the longest text that may be narrated |
| `YOTO_RATE_LIMIT` | `30` | how many generated tracks one caller may ask for per minute; `0` removes the limit |
| `YOTO_DEBUG` | `false` | the Flask debugger; refused on anything but the loopback interface |
| `YOTO_DAILY_CARD_ID` | *(empty)* | pin the daily card; empty means create one |
| `YOTO_DAILY_MODE` | `replace` | `replace` (one story/day) or `history` (keep N days) |
| `YOTO_HISTORY_DAYS` | `7` | how many days `history` keeps |
| `YOTO_TTS_VOICE` | `Karen` | macOS `say` voice |
| `YOTO_TTS_BACKEND` | `auto` | `auto`, `say`, `http` or `ming-tts`; follows `generators.speech.default` |
| `YOTO_MING_TTS_CODE_PATH` | *(empty)* | where the Ming-3.0-tts checkout lives |
| `YOTO_LLM_BACKEND` | `auto` | `auto`, `template`, `script` or `openai` |
| `YOTO_THEME_BACKEND` | `auto` | `auto`, `ollama` or `template`; `auto` prefers the local model |
| `YOTO_THEME_AUDIENCE` | *two children* | who the card is written for |
| `YOTO_THEME_VOICE` | *(empty)* | the named voice the daily capabilities narrate in |
| `YOTO_THEME_SONG_SECONDS` | `60` | how long the theme song should be |
| `YOTO_THEME_ATTEMPTS` | `3` | how many times to ask the model before falling back |
| `YOTO_OLLAMA_ENDPOINT` | `http://127.0.0.1:11434` | the local Ollama server |
| `YOTO_OLLAMA_MODEL` | `qwen3:1.7b` | the model that writes the story and the song |
| `YOTO_RESEARCH_FACTS` | `8` | how many planets to pull facts about |

The `theme` section of `config.yaml` holds the same settings, and the
environment wins over it:

```yaml
theme:
  audience: "two children, one about five years old and one about ten"
  backend: auto                 # auto, ollama, template
  ollama_endpoint: http://127.0.0.1:11434
  ollama_model: llama3.2:3b
  attempts: 3
  song_seconds: 60
  research_facts: 8
```

The state directory was called `~/.config/yoto-daily` before the project was
renamed. If that directory exists and the new one does not, it is still used,
so upgrading does not force a fresh login. The path is the same on every
platform — on Windows `~/.config/yotaiman` means
`C:\Users\<you>\.config\yotaiman` — and `YOTO_STATE_DIR` overrides it.

---

## The perimeter

The service can read the shelf, rewrite the daily card and spend money on
speech and text generation, so it does not serve anybody who has not shown a
token. Four things stand between a request and the account.

**A token.** Generated on the first run and kept in
`~/.config/yotaiman/api-token`, readable only by you. It is sent as
`Authorization: Bearer <token>`, as `X-Yoto-Token: <token>`, or as
`?token=<token>` in the address bar — the last one is there for a phone,
which cannot set a header.

**A Host allowlist.** A name that is rebound to this machine arrives
carrying the attacker's own `Host` header, so the service only answers to
`localhost`, `127.0.0.1` and whatever `YOTO_ALLOWED_HOSTS` says. If you open
the service to the network with `YOTO_ALLOW_REMOTE=true`, put the address the
phone will use in `YOTO_ALLOWED_HOSTS` as well:

```bash
YOTO_ALLOW_REMOTE=true YOTO_ALLOWED_HOSTS=192.168.1.20 python -m yoto_daily serve
```

**An Origin check.** A browser sends `Origin` on every POST it makes, so a
request that carries one from somewhere else is refused. A request that
presents the token in a header skips this check: a browser cannot set a
header on another site's behalf.

**A CSRF token** on the forms, for the requests that ride on the session
cookie.

On top of that:

- a caller-supplied URL is only fetched if it is `http` or `https` and every
  address it resolves to is publicly routable — the loopback interface, the
  local network and the cloud metadata address are all refused, and each
  redirect is checked again;
- a caller-supplied path has to resolve inside `YOTO_CONTENT_DIRS`;
- the narration text is written to a file rather than passed on the command
  line, so it cannot become one of `say`'s own options;
- the service refuses to start with the debugger on and a network bind; and
- a caller may only ask for so much generated work per minute.

### Text generation

`auto` tries a real model first and falls back to the local template writer, so
the pipeline never dies for want of a credential.

- **`script`** shells out to the local `llm-call` helper, which reads provider
  settings from the runtime's `config.yaml`.
- **`openai`** uses `OPENAI_API_KEY` when it is set.
- **`template`** is a local writer with a hand-written topic bank. It needs
  nothing, which is what makes the whole pipeline testable offline.

A backend that fails with an auth or configuration error is skipped for the
rest of the process, so one broken provider costs one failed call.

### A theme, written locally

The themed card has its own writer, and it is a different job from writing
a story. A theme is a title, a story, a song and a set of facts, and the
facts come from a source rather than from the model.

**The content library comes first.** `yoto_daily.content.library` holds
themes written by hand, and when it has the topic, that is what goes on
the card — the words are used exactly as they were written, and the model
is not asked at all. The library exists because a story somebody wrote by
hand is worth more than a story a small model produced at seven in the
morning, and because a library theme is a *long* theme: two stories, two
songs, an explainer and a fact corner, rather than the three tracks a
model writes.

When the library does not have the topic, the writer below takes over:

`yoto_daily.content.theme` holds it:

| writer | what it does |
|---|---|
| `ollama` | asks a model running on this machine |
| `template` | a hand-written theme bank; needs nothing at all |
| `fallback` | `ollama` first, `template` when the model is not there |

The local model is reached through `yoto_daily.content.ollama`, a small
client for the Ollama API. Two details matter:

- **The context window is capped.** Ollama defaults to 32k, and attention
  is quadratic in it; on a machine without a dedicated GPU that costs
  minutes per story. The client asks for 8k, which is plenty for these
  prompts and much faster.
- **The answer is read as labelled sections, not as JSON.** A model that
  forgets to escape a quotation mark inside a story does not break the
  parse. The client also accepts JSON, for models that insist on it.

What comes back is checked before it reaches a card. A story that repeats
a paragraph, repeats a sentence, runs to fewer than four paragraphs or
reads as a list of things you will do is thrown away and written again,
up to `attempts` times. After that the hand-written theme is used, so a
bad model produces a worse card rather than no card.

Whatever the writer, the facts are handed over already finished. The model
is asked for a story and a song; it is never asked to restate a number.

### Text to speech

The default is macOS `say`, which needs no API key and has voices for most
locales — `Karen` (en_AU), `Samantha` (en_US), `Daniel` (en_GB), `Junior`.
The output goes through `ffmpeg` to a mono MP3, which is what Yoto's
transcoder wants.

On Windows and Linux there is no `say`, so enable one of the other backends in
`config.yaml` — `ming-tts`, `local-model` or `hosted`. The generator that a
request picks is the configured default when it can run, and otherwise the
first one that can, so a config carried over from a Mac still works.

Set `generators.speech.default` to a `ming-tts` generator and the daily
story and read-aloud capabilities narrate in that cloned voice as well, so
one switch moves the whole service over. `YOTO_TTS_BACKEND` overrides the
choice directly.

---

## Authentication

Yoto's web app is an Auth0 SPA. It requests a scope set that **omits
`offline_access`**, so Auth0 issues no refresh token and the SPA silently
re-authorizes on every page load using `prompt=none` plus
`response_mode=web_message`.

This SDK reproduces that exchange without a browser: it replays the
`login.yotoplay.com` session cookies, requests an authorization code with a
fresh PKCE pair, and swaps it for an access token. Tokens last eight hours and
are cached on disk; when they expire the SDK mints another one silently.

Two details matter and are easy to get wrong:

- The **`auth0` cookie alone is not enough**. `auth0_compat` carries the
  tenant hint that lets Auth0 match the existing SSO session. The bootstrap
  copies the whole jar.
- **`user:account:view` is not pre-approved for silent auth.** Requesting it
  directly gets `access_denied`. The SDK asks for the subset that works;
  Auth0 still returns `user:account:view` in the token because the user
  already approved it interactively.

Refresh the cookie jar whenever the session lapses:

```bash
python -m yoto.auth bootstrap     # re-copy from Chrome
python -m yoto.auth status        # what is cached right now
```

### Keeping the token warm while the service runs

`yotaiman serve` refreshes the token in the background, every hour by
default. A token lasts eight hours, so an hourly refresh means it is always
fresh when a request needs it and a long run never trips over an expired
one.

The refresh is plain HTTP — the stored cookies are replayed, Auth0 is asked
for a code, the code is swapped for a token — so **no browser is needed
while the service runs and none has to be kept open**. Chrome is only
required for the one-off `bootstrap` that copies the cookie jar onto disk.

```bash
yotaiman serve
# yotaiman listening on http://127.0.0.1:8787
# Refreshing the access token every 1 h in the background.
# [token] token refreshed, valid for 8.0 h
```

The interval is configurable, and `0` turns the refresher off:

```bash
YOTO_TOKEN_REFRESH_INTERVAL=1800 yotaiman serve   # every 30 minutes
```

```yaml
service:
  token_refresh_interval: 3600
```

What the refresher last managed to do is part of the service status, so a
session that has genuinely lapsed is visible before it turns into a failed
request:

```bash
curl -s http://127.0.0.1:8787/api/health | jq .token_refresh
```

```json
{
  "enabled": true,
  "running": true,
  "interval": 3600,
  "last_refresh": "2026-10-25T11:38:16+00:00",
  "last_ok": true,
  "error": "",
  "next_refresh": "2026-10-25T12:38:16+00:00",
  "expires_at": "2026-10-25T19:38:16+00:00",
  "expires_in": 28793
}
```

When a refresh fails, the desk says so at the top of the page and the error
carries the instructions for putting it right.

### Getting a DevTools endpoint

`bootstrap` reads the cookies straight out of a running Chrome over the
DevTools protocol. It finds the browser endpoint the same way the DevTools
frontend does, so it works on macOS, Windows and Linux, and on both ways of
exposing Chrome:

| how Chrome was started | where the endpoint comes from |
|---|---|
| `chrome://inspect/#remote-debugging` → Enable | the `DevToolsActivePort` file Chrome writes into the profile directory |
| `--remote-debugging-port=9222` with a non-default `--user-data-dir` | the `/json/version` HTTP endpoint |

**Since Chrome 136, `--remote-debugging-port` is ignored for the default
profile directory.** A Chrome started the old way still looks like it is
listening on 9222 but serves nothing useful. Two consequences:

- For your everyday profile, turn on remote debugging at
  `chrome://inspect/#remote-debugging` → Enable. That is the route the
  bootstrap expects.
- A browser started with `--remote-debugging-port` and a *throwaway*
  `--user-data-dir` serves the older `/json/version` endpoint. The bootstrap
  accepts that too, but a throwaway profile is not signed in to Yoto, so sign
  in there first.

Chrome holds on to a debugging session for a while after a client
disconnects, and while it does it accepts new connections without ever
completing the handshake. If the bootstrap reports that Chrome accepted the
connection but never answered, leave the browser alone and run it again —
retrying straight away keeps Chrome busy, and ten quiet minutes is what it
took here. If it does not clear, turn remote debugging off and on again at
`chrome://inspect/#remote-debugging`.

---

## How the Yoto API actually works

Everything below was established by observing the live API, not from docs.

### Base URL and headers

`https://api.yotoplay.com`, bearer JWT, plus `Origin` and `Referer` of
`https://my.yotoplay.com`. The API rejects calls without them.

### How the physical card resolves content

The NFC tag on a card carries a small URL/identifier; the player then asks
Yoto's own infrastructure for that card's content and audio. Two consequences
matter here:

- The m3u/manifest is **server-side**. Nothing about it is hosted locally and
  nothing about it needs to be hosted locally -- the card resolves by card
  ID, and `POST /content` with that ID changes exactly what the player
  serves. The player never reads a playlist from your machine.
- `card-content.yotoplay.com` is an S3 bucket holding public cover art under
  `yoto/pub/<mediaId>`; the per-card media itself is served from
  `secure-media.yotoplay.com` behind a signed, expiring URL obtained through
  `GET /card/{cardId}/media/{mediaId}`.

So the whole job reduces to: keep the server-side content for a card ID
current. That is what this SDK does.

### Content

| method | path | purpose |
|---|---|---|
| `GET` | `/content/mine` | summaries of your cards (no chapters, only `metadata.media`) |
| `GET` | `/content/{id}` | the full card body |
| `POST` | `/content` | **upsert** — create, or update when the body carries `cardId` |
| `DELETE` | `/content/{id}` | delete a card |

A card is `card -> content -> chapters[] -> tracks[]`. Each track points at an
uploaded file through `trackUrl = "yoto:#" + media_id`.

### Tracks

A track has `type` of either `audio` or `stream`, and carries `key` (up to
20 characters), `title`, `trackUrl`, `format`, `duration`, `fileSize`,
`channels` and an optional `display.icon16x16`. A **stream** track puts the
URL itself in `trackUrl` and has no media id. Accepted formats are `mp3`,
`aac`, `alac`, `flac`, `pcm_s16le`, `opus`, `ogg`, `x-m4a`, `wav`, `aiff` and
`mpeg`.

`display.icon16x16` is the little 16×16 picture shown next to the track. It
is a media id in the usual `yoto:#<43 characters>` form, pointing at a
16×16 PNG with a 24-bit RGBA colour format and alpha transparency. The SDK
uploads one with `media.upload_display_icon(png)`, and
`cards.build_track(..., icon_media_id=...)` puts it on a track.

A track can also carry `events` — `onEnd`, `onLhb`, `onRhb`, `onRhbClockwise`
and `onRhbAntiClockwise` — each with a `cmd` of `repeat`, `stop`, `none`,
`goto`, `cardEnd` or `chapterEnd`.

### Playback options

The card's `content.config` carries the playback switches:

| field | meaning |
|---|---|
| `resumeTimeout` | `0` means always play from start; the default is 2592000 (30 days) |
| `shuffle` | `[{start, end, limit}]` over chapter indices; the app writes `[{0, n-1, n}]` |
| `trackNumberOverlayTimeout` | `0` hides the track-number overlay |
| `disableTrackNav` / `disableChapterNav` | hide the player's navigation |
| `onlineOnly` | refuse to play without a network connection |

`content.editSettings.autoOverlayLabels = "disabled"` removes the chapter and
track overlay labels. The card's **description** lives in
`card.metadata.description`, not at the top level.

### Media

| method | path | purpose |
|---|---|---|
| `GET` | `/media/transcode/audio/uploadUrl` | presigned S3 `PUT` URL + an `uploadId` |
| `GET` | `/media/upload/{uploadId}/transcoded` | transcode status |
| `GET` | `/card/{cardId}/media/{mediaId}` | a time-limited signed media URL |
| `POST` | `/media/coverImage/user/me/upload` | card cover image |
| `POST` | `/media/displayIcons/user/me/upload` | a 16×16 track icon |
| `GET` | `/media/displayIcons/user/{yoto\|me}` | Yoto's icon library, or yours |
| `DELETE` | `/media/displayIcon/{displayIconId}` | remove an uploaded icon |

The pipeline is:

1. `GET /media/transcode/audio/uploadUrl?sha256=..&filename=..` returns
   `uploadId` and a presigned S3 `PUT` URL (valid 15 minutes).
2. `PUT` the raw bytes to that URL with a `Content-Disposition` header.
3. Poll `/media/upload/{uploadId}/transcoded` until `transcodedSha256` appears.
4. **The media id is `"yoto:#" + transcodedSha256`** — a 43-character base64url
   SHA-256 of the *transcoded* file. No endpoint returns it; it is derived.

The server transcodes to OGG/Opus, mono or stereo, loudness-normalised to
-16 LUFS.

A display icon is uploaded as a raw PNG with `Content-Type: image/png` and
`?autoConvert=false`, and comes back as `{"displayIcon": {"mediaId": ...}}`
— a 43-character id, the same shape as an audio media id. Note that the
**delete** endpoint is keyed by the icon's `displayIconId`, not by the
`mediaId` a track points at; look the `displayIconId` up in
`/media/displayIcons/user/me` first.

### Behaviours that will bite you

- **`POST /content` echoes your payload.** It does not return the persisted
  state: the server re-derives track durations and file sizes asynchronously
  after the write. Use `cards.save_and_refresh()` when you need the truth.
- **Uploads are idempotent per content hash.** Re-uploading byte-identical
  audio returns the existing `uploadId` with `uploadUrl: None` — there is
  nothing to upload. The SDK treats that as a cache hit.
- **Reads of deleted cards are cached.** `GET /content/{id}` keeps serving a
  deleted card for a short while. `GET /content/mine` is authoritative, which
  is why `cards.exists()` uses it.
- **Track duration is recomputed from the transcoded Opus file** and can
  differ by a second from what the transcode status reported.

---

## Tests

```bash
# offline — models, state, text, tts, generators, books, routes, the HTML desk
python -m pytest tests/test_unit.py tests/test_generators.py tests/test_acestep.py tests/test_web.py -v

# offline — the theme, the day folders, the library, the numbers, the pixel art
python -m pytest tests/test_theme.py -v

# live — creates a scratch card, exercises the whole pipeline, deletes it
python -m pytest tests/test_live.py tests/test_live_tracks.py -v

# everything
python -m pytest tests/ -q
```

The live tests create and remove a scratch card, so they are safe to run
against a real account.

---

## What this does not do yet

- **Stories written on a device.** The desk has a transcript form, and
  `read-aloud` takes text over the API, but both need the phone to reach this
  machine. The service binds to `127.0.0.1`; `YOTO_ALLOW_REMOTE=true` widens it
  to the LAN, which is enough for a phone on the same wifi and nothing more.
- **Research for themes other than exoplanets.** `yoto_daily.research` has a
  source for one topic. A theme with no source behind it falls back to the
  model and the hand-written bank, and its numbers are only as good as the
  model's memory.
- **More themes in the library.** The library holds one: exoplanets. The
  shape is there — add a `Segment`, and the plan, the pictures and the
  playlist length follow — but there is only one to prove it.
- **Scheduled publishing.** The daily job is a command you run, not a timer
  that runs itself. There is no cron entry, no scheduler and no retry.
- **Bird calls.** Same shape as music and speech: fetch a recording, upload
  it, publish it. The `file` track type covers it.
- **A local TTS model.** The `http` speech generator speaks a one-line
  protocol, so pointing it at Kokoro or MLX-Audio is configuration, not code —
  but nothing has been run against one yet.
- **Long-form audio.** A book becomes several tracks, one per chapter. The
  player caps how long a single chapter may be, and that limit is the
  player's, not the API's.
- **Cover images for generated cards.** `POST /api/cards/<id>/cover` works,
  but nothing generates cover art automatically yet.
