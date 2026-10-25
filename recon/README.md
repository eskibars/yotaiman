# recon

The Yoto API is not publicly documented. There is no developer portal, no
published OpenAPI schema and no documentation for the endpoints that read or
write card content. Everything this project knows about it was recovered by
observing a real account: the web app's own network traffic, the request
schemas in its minified JavaScript bundles, and a series of probes against the
live API.

These are the tools that did it. They are kept because they are the evidence
behind the behaviour documented in the main README — if you want to check a
claim there, or work on the SDK, this is where the answers came from.

**They are research tools, not a library.** They are not packaged, not
covered by the test suite, and they will not be maintained as carefully as
the SDK and service are. Most of them write to a real account; the probes
create a scratch card and delete it when they finish.

## What is not here

The captured traffic, the card dumps and the minified Yoto bundles are
gitignored. They contain live bearer tokens, the contents of real cards and
Yoto's own compiled code, so none of it belongs in a public repository. If
you want to work with them, capture them yourself.

## Setup

The Python probes need a bearer token in `recon/.token` and read the Yoto API
at `https://api.yotoplay.com`:

```bash
# Mint a token and write it to recon/.token
python -m yoto.auth token > recon/.token
```

The Node tools need a Chrome running with the DevTools protocol enabled, and
the logged-in Yoto tab open:

```bash
# Chrome 136+ ignores --remote-debugging-port for the default profile,
# so turn remote debugging on instead:
#   chrome://inspect/#remote-debugging  ->  Enable
#
# Or start a separate Chrome on a throwaway profile:
google-chrome --remote-debugging-port=9222 --user-data-dir=/tmp/yoto-debug
```

`cdp.mjs` finds the browser endpoint the same way the Python SDK does: it
reads the `DevToolsActivePort` file Chrome writes into the profile directory,
so it works against a browser started through `chrome://inspect` as well as
one started with `--remote-debugging-port`. Set `YOTO_CHROME_USER_DATA_DIR` if
the profile is somewhere else.

## The tools

### Chrome DevTools Protocol

| file | what it does |
|---|---|
| `cdp.mjs` | A minimal CDP client over Node's built-in WebSocket. No npm dependencies. |
| `capture.mjs` | Records every request the Yoto tab makes and dumps the API-shaped ones to `recon/traffic.json`. |
| `dump_auth.mjs` | Lists the auth cookies and storage the Yoto tab holds. |
| `extract-endpoints.mjs` | Pulls endpoint paths and methods out of the minified bundles in `recon/assets`. |
| `shot.mjs` | Screenshots a page over CDP. Used to review the HTML desk. |

`capture.mjs` and `dump_auth.mjs` write live credentials to disk. Both
outputs are gitignored. Treat them as secrets.

### API probes

Each probe creates a scratch card, runs its checks against it, and deletes it
in a `finally` block.

| file | question it answered |
|---|---|
| `probe_auth.py` | Which Auth0 silent-re-auth scopes and cookie combinations actually work? |
| `probe_write.py` | Is the write a `PUT` or a `POST`? Does `POST /content` upsert? |
| `probe_options.py` | Which card and track options does the API accept *and persist*? |
| `e2e_upload.py` | Does the full upload → transcode → content-write path work end to end? |

The answers are written up in the main README: the API's write semantics are
under [Content](#content), and the playback options under
[Playback options](#playback-options).
