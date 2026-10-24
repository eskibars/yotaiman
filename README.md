# yotaiman

A local SDK and Flask service for the [Yoto](https://yotoplay.com) player.

It exists to solve one problem: **a Yoto card is a static playlist, and this
makes it dynamic.** The service generates content, narrates it, uploads it to
Yoto's media pipeline and rewrites a card — so a single physical card can carry
a fresh story every morning.

```
topic -> text -> speech -> upload -> transcode -> card write
```

Two capabilities ship working:

| capability | what it does |
|---|---|
| `daily-story` | Writes a story about a topic, narrates it, publishes it as the daily card. |
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

# 1. Copy the login cookies out of a logged-in Chrome.
#    Chrome must be running with:  --remote-debugging-port=9222
python -m yoto.auth bootstrap

# 2. Publish today's story.
python -m yoto_daily daily --topic dolphins --child-name "Alex"

# 3. Or run the service.
#    The HTML desk is at http://127.0.0.1:8787/
#    The JSON API is at http://127.0.0.1:8787/api/
python -m yoto_daily serve
```

Step 1 copies four cookies (`auth0`, `auth0_compat`, `did`, `did_compat`) from
`login.yotoplay.com` into `~/.config/yotaiman/cookies.json`. The SDK then
mints its own access tokens without a browser. See
[Authentication](#authentication) for why that works.

Installing the package also puts a `yotaiman` command on your path.
`python -m yoto_daily ...` does the same thing if you would rather not install.

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
```

```bash
curl -s localhost:8787/api/health | jq
curl -s localhost:8787/api/cards  | jq '.cards[] | {card_id, title, duration}'
curl -s localhost:8787/api/generators/music | jq
curl -s -X POST localhost:8787/api/daily \
     -H 'Content-Type: application/json' \
     -d '{"topic":"dolphins","child_name":"Alex"}' | jq
```

The service binds to `127.0.0.1` and has no authentication of its own — it
drives a personal account. `YOTO_ALLOW_REMOTE=true` widens the bind, so only do
that on a trusted network.

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
{"type": "file", "path": "/path/to/lullaby.mp3"}
{"type": "file", "url": "https://example.com/lullaby.mp3"}
```

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

yoto_daily/              the service
  app.py                 Flask application, registers both blueprints
  api.py                 the JSON API blueprint (/api)
  web.py                 the HTML control desk blueprint (/)
  config.py              settings: config.yaml plus the environment
  state.py               small JSON state store
  tracks.py              the track service (stream / file / generate)
  generators/            music and speech generators
    base.py              MusicSpec, MusicGenerator, SpeechGenerator
    music.py             ACE-Step 1.5, and a procedural fallback
    speech.py            macOS say, and a generic HTTP endpoint
    registry.py          builds the generators from config.yaml
  capabilities/          the extension point
    base.py              Capability ABC + registry
    daily_story.py       the daily story
    read_aloud.py        read supplied text
  content/
    text.py              text generation backends
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
locales (`Karen` en_AU, `Samantha` en_US, `Daniel` en_GB, `Junior`).

**`http`** covers both a local model server and a hosted service with one
implementation. The contract is:

```
POST <url>   {"text": "...", "voice": "..."}   ->   audio bytes
```

A JSON response containing base64 audio under `audio` or `data` also works.
Kokoro, MLX-Audio and similar servers need only a few lines of glue to that
contract; the URL may contain `{voice}` and `{text}` placeholders if the
service prefers path parameters.

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

| variable | default | meaning |
|---|---|---|
| `YOTO_STATE_DIR` | `~/.config/yotaiman` | cookies, token, state, audio |
| `YOTO_HOST` / `YOTO_PORT` | `127.0.0.1` / `8787` | where the API listens |
| `YOTO_ALLOW_REMOTE` | `false` | bind to all interfaces |
| `YOTO_DAILY_CARD_ID` | *(empty)* | pin the daily card; empty means create one |
| `YOTO_DAILY_MODE` | `replace` | `replace` (one story/day) or `history` (keep N days) |
| `YOTO_HISTORY_DAYS` | `7` | how many days `history` keeps |
| `YOTO_TTS_VOICE` | `Karen` | macOS `say` voice |
| `YOTO_LLM_BACKEND` | `auto` | `auto`, `template`, `script` or `openai` |

The state directory was called `~/.config/yoto-daily` before the project was
renamed. If that directory exists and the new one does not, it is still used,
so upgrading does not force a fresh login.

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

### Text to speech

The default is macOS `say`, which needs no API key and has voices for most
locales — `Karen` (en_AU), `Samantha` (en_US), `Daniel` (en_GB), `Junior`.
The output goes through `ffmpeg` to a mono MP3, which is what Yoto's
transcoder wants.

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

The pipeline is:

1. `GET /media/transcode/audio/uploadUrl?sha256=..&filename=..` returns
   `uploadId` and a presigned S3 `PUT` URL (valid 15 minutes).
2. `PUT` the raw bytes to that URL with a `Content-Disposition` header.
3. Poll `/media/upload/{uploadId}/transcoded` until `transcodedSha256` appears.
4. **The media id is `"yoto:#" + transcodedSha256`** — a 43-character base64url
   SHA-256 of the *transcoded* file. No endpoint returns it; it is derived.

The server transcodes to OGG/Opus, mono or stereo, loudness-normalised to
-16 LUFS.

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
