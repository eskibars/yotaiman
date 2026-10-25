"""Tests for the perimeter and the guards around it.

These cover the things that keep the service from being used by somebody
who is not the operator: the token, the Host allowlist, the Origin check,
the CSRF token, the SSRF guard and the path confinement.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from yoto_daily.security import (  # noqa: E402
    UnsafePathError,
    UnsafeURLError,
    resolve_within,
    safe_fetch,
    scrub_paths,
)


# ----------------------------------------------------------------------
# the token
# ----------------------------------------------------------------------
def test_the_api_needs_a_token(anon_client):
    assert anon_client.get("/api/").status_code == 401
    assert anon_client.get("/api/cards").status_code == 401


def test_a_wrong_token_is_refused(anon_client):
    resp = anon_client.get("/api/", headers={"Authorization": "Bearer wrong"})
    assert resp.status_code == 401


def test_the_right_token_is_accepted(client):
    assert client.get("/api/").status_code == 200


def test_the_token_can_come_in_the_query_string(anon_client, token):
    # A phone cannot set a header, so the desk takes the token in the URL.
    # It is moved into the session and taken back out of the address bar.
    resp = anon_client.get(f"/api/?token={token}")
    assert resp.status_code == 302
    assert "token=" not in resp.headers["Location"]
    # The session now carries the sign-in.
    assert anon_client.get("/api/").status_code == 200


def test_the_html_desk_asks_for_the_token(anon_client):
    resp = anon_client.get("/")
    assert resp.status_code == 302
    assert "/unlock" in resp.headers["Location"]


def test_the_unlock_page_is_public(anon_client):
    assert anon_client.get("/unlock").status_code == 200


def test_unlocking_with_the_token_opens_the_desk(anon_client, token):
    resp = anon_client.post(
        "/unlock",
        data={"token": token},
        headers={"Origin": "http://localhost"},
    )
    assert resp.status_code == 302
    assert anon_client.get("/").status_code == 200


def test_unlocking_with_the_wrong_token_does_not(anon_client):
    resp = anon_client.post(
        "/unlock",
        data={"token": "wrong"},
        headers={"Origin": "http://localhost"},
    )
    assert resp.status_code == 302
    assert anon_client.get("/").status_code == 302


def test_the_unlock_form_needs_a_same_origin_post(anon_client, token):
    # Another site cannot sign the operator in on their behalf.
    resp = anon_client.post(
        "/unlock",
        data={"token": token},
        headers={"Origin": "http://attacker.example"},
    )
    assert resp.status_code == 403


# ----------------------------------------------------------------------
# the Host allowlist
# ----------------------------------------------------------------------
def test_a_host_that_is_not_allowed_is_refused(client):
    # A rebound DNS name arrives carrying the attacker's own Host header.
    resp = client.get("/api/", headers={"Host": "attacker.example"})
    assert resp.status_code == 403


def test_the_loopback_names_are_allowed(client):
    for host in ("localhost", "127.0.0.1"):
        assert client.get("/api/", headers={"Host": host}).status_code == 200


# ----------------------------------------------------------------------
# cross-site requests
# ----------------------------------------------------------------------
def test_a_cross_site_post_is_refused(anon_client):
    """A session cookie does not make a cross-site post acceptable."""
    resp = anon_client.post(
        "/api/daily",
        content_type="application/x-www-form-urlencoded",
        data={"topic": "dolphins"},
        headers={"Origin": "http://attacker.example"},
    )
    assert resp.status_code == 403


def test_a_cross_site_form_post_is_refused_even_without_a_token(anon_client):
    resp = anon_client.post(
        "/api/daily",
        content_type="application/x-www-form-urlencoded",
        data={"topic": "dolphins"},
        headers={"Origin": "http://attacker.example"},
    )
    assert resp.status_code == 403


def test_a_cross_site_post_is_refused_once_the_session_is_signed_in(anon_client, token):
    anon_client.get("/unlock")
    with anon_client.session_transaction() as session:
        session["yoto_authed"] = True
    resp = anon_client.post(
        "/api/daily",
        content_type="application/x-www-form-urlencoded",
        data={"topic": "dolphins"},
        headers={"Origin": "http://attacker.example"},
    )
    assert resp.status_code == 403


def test_the_forms_carry_a_csrf_token(client):
    page = client.get("/cards/some-card/add").get_data(as_text=True)
    assert 'name="csrf_token"' in page


# ----------------------------------------------------------------------
# fetching a caller-supplied URL
# ----------------------------------------------------------------------
@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1:8787/",
        "http://localhost/",
        "http://169.254.169.254/latest/meta-data/",
        "http://10.0.0.1/",
        "http://192.168.1.1/",
        "http://[::1]/",
        "file:///etc/passwd",
        "ftp://example.com/x",
    ],
)
def test_safe_fetch_refuses_the_local_network(url):
    with pytest.raises(UnsafeURLError):
        safe_fetch(url, timeout=1)


def test_safe_fetch_refuses_a_redirect_into_the_local_network(monkeypatch):
    """A public URL that redirects inward is refused, not followed."""
    import requests

    from yoto_daily import security

    class _Response:
        status_code = 302
        headers = {"Location": "http://127.0.0.1:8787/"}

        def is_redirect(self):
            return True

        def is_permanent_redirect(self):
            return False

        def close(self):
            pass

    monkeypatch.setattr(
        security, "_assert_public_host", lambda host: None
    )
    monkeypatch.setattr(
        security.requests.Session, "request", lambda *a, **kw: _Response()
    )
    with pytest.raises(UnsafeURLError):
        safe_fetch("http://example.com/", timeout=1)


# ----------------------------------------------------------------------
# a caller-supplied path
# ----------------------------------------------------------------------
def test_a_path_inside_the_content_directory_is_accepted(tmp_path):
    (tmp_path / "story.txt").write_text("hello")
    resolved = resolve_within([tmp_path], "story.txt")
    assert resolved == (tmp_path / "story.txt").resolve()


def test_a_path_outside_the_content_directory_is_refused(tmp_path):
    with pytest.raises(UnsafePathError):
        resolve_within([tmp_path], "/etc/passwd")
    with pytest.raises(UnsafePathError):
        resolve_within([tmp_path], "../../etc/passwd")


def test_a_symlink_out_of_the_content_directory_is_refused(tmp_path):
    root = tmp_path / "content"
    root.mkdir()
    outside = tmp_path / "secret.txt"
    outside.write_text("secret")
    link = root / "link.txt"
    try:
        link.symlink_to(outside)
    except (OSError, NotImplementedError):  # pragma: no cover - platform
        pytest.skip("symlinks are not available here")
    with pytest.raises(UnsafePathError):
        resolve_within([root], "link.txt")


def test_the_track_service_confines_a_local_path(tmp_path):
    from yoto_daily.tracks import TrackError, TrackService

    service = TrackService.__new__(TrackService)
    service.settings = type("S", (), {"content_dirs": [tmp_path]})()
    with pytest.raises(TrackError):
        service._resolve_content_path("/etc/passwd")


def test_a_url_is_not_mistaken_for_a_path(tmp_path):
    from yoto_daily.security import UnsafePathError

    with pytest.raises(UnsafePathError):
        resolve_within([tmp_path], "file:///etc/passwd")


def test_setting_a_cover_leaves_the_operators_file_alone(app, tmp_path):
    """The endpoint uploads the file; it does not tidy it away."""
    content = tmp_path / "content"
    content.mkdir()
    cover = content / "cover.png"
    cover.write_bytes(b"png")

    app.config["YOTO_SETTINGS"].content_dirs = [content]

    class _Media:
        def upload_cover_image(self, path):
            raise RuntimeError("no account")

    app.extensions["yoto"].media = _Media()

    resp = app.test_client().post(
        "/api/cards/some-card/cover",
        # A relative name, so the resolved path and the one that was asked
        # for are not the same string.
        json={"path": "cover.png"},
        headers={"Authorization": f"Bearer {app.config['YOTO_TOKEN']}"},
    )
    assert resp.status_code >= 400
    assert cover.exists(), "the operator's file was deleted"
    assert cover.read_bytes() == b"png"


def test_a_cover_url_must_be_http(app):
    resp = app.test_client().post(
        "/api/cards/some-card/cover",
        json={"url": "file:///etc/passwd"},
        headers={"Authorization": f"Bearer {app.config['YOTO_TOKEN']}"},
    )
    assert resp.status_code == 400
    assert "http" in resp.get_json()["error"]


# ----------------------------------------------------------------------
# the speech generator
# ----------------------------------------------------------------------
def test_the_text_is_not_put_on_the_command_line(tmp_path, monkeypatch):
    """The narration text never reaches the command line.

    A caller who controls the text could otherwise make `say` treat it as
    one of its own options.
    """
    from yoto_daily.generators.speech import SaySpeechGenerator

    commands: list[list[str]] = []
    scripts: dict[str, str] = {}

    def fake_run(cmd, **kwargs):
        commands.append(list(cmd))
        if "-f" in cmd:
            path = Path(cmd[cmd.index("-f") + 1])
            scripts[str(path)] = path.read_text(encoding="utf-8")
        # `say` writes the audio file; stand in for it.
        if "-o" in cmd:
            Path(cmd[cmd.index("-o") + 1]).write_bytes(b"aiff")
        return type("P", (), {"returncode": 0, "stderr": "", "stdout": ""})()

    monkeypatch.setattr("yoto_daily.generators.speech.subprocess.run", fake_run)
    monkeypatch.setattr(
        "yoto_daily.generators.speech.shutil.which", lambda name: "/usr/bin/say"
    )

    generator = SaySpeechGenerator()
    try:
        generator.synthesize(
            "--input-file=/etc/passwd", tmp_path / "out.mp3", voice="Karen"
        )
    except Exception:
        pass  # the ffmpeg step is not what this test is about

    say_commands = [cmd for cmd in commands if "passwd" in " ".join(cmd)]
    assert not say_commands, "the narration text reached the command line"

    say_command = next(cmd for cmd in commands if "-o" in cmd)
    assert "-f" in say_command
    # The text is in the file the command points at, not in the arguments.
    script = Path(say_command[say_command.index("-f") + 1])
    assert scripts[str(script)] == "--input-file=/etc/passwd"


def test_a_voice_name_cannot_move_the_path():
    from yoto_daily.generators.speech import _url_segment

    assert _url_segment("rachel") == "rachel"
    assert _url_segment("en-US-Andrew") == "en-US-Andrew"
    for bad in ("../../admin", "a/b", "a?b", "a#b", "", ".."):
        with pytest.raises(RuntimeError):
            _url_segment(bad)


# ----------------------------------------------------------------------
# the perimeter itself
# ----------------------------------------------------------------------
def test_debug_is_refused_on_a_network_bind():
    from yoto_daily.__main__ import _check_debug_bind
    from yoto_daily.config import Settings

    settings = Settings()
    settings.debug = True
    settings.host = "0.0.0.0"
    assert _check_debug_bind(settings)

    settings.host = "127.0.0.1"
    assert _check_debug_bind(settings) is None


def test_debug_is_refused_when_the_service_is_open_to_the_network():
    from yoto_daily.__main__ import _check_debug_bind
    from yoto_daily.config import Settings

    settings = Settings()
    settings.debug = True
    settings.allow_remote = True
    assert _check_debug_bind(settings)


def test_the_token_file_is_readable_only_by_its_owner(tmp_path):
    from yoto_daily.security import load_api_token

    token = load_api_token(tmp_path)
    path = tmp_path / "api-token"
    assert path.read_text().strip() == token
    if os.name != "nt":
        assert path.stat().st_mode & 0o077 == 0


def test_the_cookie_jar_is_readable_only_by_its_owner(tmp_path):
    from yoto.auth import YotoAuth

    auth = YotoAuth(state_dir=tmp_path)
    auth.save_cookies([{"name": "session", "value": "abc"}])
    if os.name != "nt":
        assert auth.cookies_file.stat().st_mode & 0o077 == 0


def test_a_call_cannot_ask_for_more_work_than_the_allowance(app, token):
    """The capabilities cost money, so they are rate limited."""
    app.config["YOTO_RATE_LIMITER"].limit = 2
    test_client = app.test_client()
    test_client.environ_base["HTTP_AUTHORIZATION"] = f"Bearer {token}"

    codes = [
        test_client.post("/api/capabilities/read-aloud", json={"text": "hi"}).status_code
        for _ in range(4)
    ]
    assert 429 in codes


# ----------------------------------------------------------------------
# what the service tells the caller
# ----------------------------------------------------------------------
def test_an_error_message_does_not_name_the_directory_it_came_from():
    message = scrub_paths(
        "No Yoto cookie jar at C:\\Users\\ann\\AppData\\Local\\yotaiman\\cookies.json"
    )
    assert "Users" not in message
    assert "cookies.json" in message


def test_a_url_in_an_error_message_is_left_alone():
    message = scrub_paths("HTTP endpoint at http://127.0.0.1:8880/tts")
    assert message == "HTTP endpoint at http://127.0.0.1:8880/tts"
