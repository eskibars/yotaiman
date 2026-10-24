#!/usr/bin/env python3
"""Test browserless Auth0 silent re-auth variants."""
import base64
import hashlib
import json
import re
import secrets
import sys

import requests

CLIENT_ID = "cR9ffsEW9mQKgyVhpvyZpq5AX4gnd3p2"
AUDIENCE = "https://api.yotoplay.com"
REDIRECT = "https://my.yotoplay.com/authorization/callback"
LOGIN = "https://login.yotoplay.com"

FULL_SCOPE = ("openid email family:view family:library:view family:library:share-card "
              "family:library:card-audio user:content:manage user:account:view")
MIN_SCOPE = ("openid email family:view family:library:view family:library:share-card "
             "family:library:card-audio user:content:manage")

cookies = json.load(open("recon/.auth0cookies.json"))


def attempt(label, scope, use_all_cookies, prompt="none"):
    print(f"\n########## {label}")
    verifier = base64.urlsafe_b64encode(secrets.token_bytes(64)).rstrip(b"=").decode()
    challenge = base64.urlsafe_b64encode(
        hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()

    params = {
        "client_id": CLIENT_ID, "scope": scope, "redirect_uri": REDIRECT,
        "audience": AUDIENCE, "prompt": prompt, "response_type": "code",
        "response_mode": "web_message",
        "state": base64.urlsafe_b64encode(secrets.token_bytes(16)).decode(),
        "nonce": base64.urlsafe_b64encode(secrets.token_bytes(16)).decode(),
        "code_challenge": challenge, "code_challenge_method": "S256",
        "auth0Client": json.dumps({"name": "auth0-spa-js", "version": "2.24.1"}),
    }

    s = requests.Session()
    if use_all_cookies:
        for c in cookies:
            s.cookies.set(c["name"], c["value"], domain=c["domain"], path=c.get("path", "/"))
    else:
        s.cookies.set("auth0", cookies[0]["value"], domain="login.yotoplay.com", path="/")

    r = s.get(f"{LOGIN}/authorize", params=params, timeout=30,
              headers={"User-Agent": "Mozilla/5.0", "Accept": "text/html"})

    m = re.search(r"authorizationResponse\s*=\s*(\{.*?\});", r.text, re.S)
    if not m:
        print("  no response payload; HTTP", r.status_code)
        print("  ", r.text[:250])
        return None
    # JS object literal, not JSON: pull the fields we need directly
    obj = m.group(1)
    resp = re.search(r"response:\s*\{(.*?)\}\s*,\s*state:", obj, re.S)
    resp = resp.group(1) if resp else obj

    def field(name):
        mm = re.search(rf'"{name}"\s*:\s*"([^"]*)"', resp)
        return mm.group(1) if mm else None

    payload = {"error": field("error"), "error_description": field("error_description"),
               "code": field("code")}
    if payload.get("error"):
        print(f"  ERROR: {payload.get('error')} :: {payload.get('error_description')}")
        return None

    code = payload["code"]
    print(f"  got code ({len(code)} chars)")

    tok = s.post(f"{LOGIN}/oauth/token", data={
        "grant_type": "authorization_code", "client_id": CLIENT_ID,
        "code": code, "code_verifier": verifier, "redirect_uri": REDIRECT,
    }, timeout=30, headers={"Content-Type": "application/x-www-form-urlencoded"})

    tj = tok.json()
    if "access_token" not in tj:
        print("  token error:", json.dumps(tj)[:300])
        return None

    print(f"  token OK. keys={list(tj.keys())} expires_in={tj.get('expires_in')}")
    print(f"  granted scope: {tj.get('scope')}")
    print(f"  refresh_token present: {'refresh_token' in tj}")
    open("recon/.token2", "w").write(tj["access_token"])

    api = requests.get("https://api.yotoplay.com/content/mine",
                       headers={"Authorization": f"Bearer {tj['access_token']}"}, timeout=30)
    print(f"  api -> {api.status_code} cards={[c['cardId'] for c in api.json().get('cards', [])]}")
    return tj


attempt("A: min scope, auth0 cookie only", MIN_SCOPE, False)
attempt("B: full scope, ALL cookies", FULL_SCOPE, True)
attempt("C: min scope, ALL cookies", MIN_SCOPE, True)
