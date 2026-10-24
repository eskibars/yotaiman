#!/usr/bin/env python3
"""Determine the correct write method + body shape for card content."""
import json
import os

import requests

API = "https://api.yotoplay.com"
TOKEN = open("recon/.token").read().strip()
H = {"Authorization": f"Bearer {TOKEN}", "Origin": "https://my.yotoplay.com"}

# A media id from an earlier upload. Set YOTO_MEDIA_ID to reuse one.
MEDIA_ID = os.environ.get("YOTO_MEDIA_ID", "")


def body(title="Probe"):
    return {
        "title": title,
        "content": {
            "activity": "yoto_Player",
            "playbackType": "linear",
            "version": "1",
            "config": {"resumeTimeout": 2592000, "onlineOnly": False},
            "chapters": [{
                "key": "00", "title": "Chapter 1",
                "tracks": [{
                    "key": "01", "title": "Test Track", "format": "opus",
                    "trackUrl": MEDIA_ID, "type": "audio",
                    "duration": 3, "fileSize": 22673, "channels": "mono",
                }],
            }],
        },
    }


def show(tag, r):
    print(f"  {tag}: HTTP {r.status_code} -> {json.dumps(r.json())[:300] if 'json' in r.headers.get('content-type','') else r.text[:300]}")


scratch = requests.post(f"{API}/content", headers={**H, "Content-Type": "application/json"},
                        json={}, timeout=30).json()["card"]["cardId"]
print(f"scratch cardId = {scratch}\n")

try:
    print("A) PUT /content/{id}")
    show("PUT", requests.put(f"{API}/content/{scratch}", headers={**H, "Content-Type": "application/json"},
                             json=body(), timeout=30))

    print("\nB) GET back")
    r = requests.get(f"{API}/content/{scratch}", headers=H, timeout=30)
    print(json.dumps(r.json(), indent=1)[:1200])

    print("\nC) POST /content with cardId in body (upsert?)")
    b = body("Upsert Probe")
    b["cardId"] = scratch
    show("POST", requests.post(f"{API}/content", headers={**H, "Content-Type": "application/json"},
                               json=b, timeout=30))

    print("\nD) GET media url for our media id")
    if MEDIA_ID:
        bare = MEDIA_ID.replace("yoto:#", "")
        show("GET media", requests.get(f"{API}/card/{scratch}/media/{bare}",
                                       headers=H, params={"accel": "false"}, timeout=30))
    else:
        print("  (set YOTO_MEDIA_ID to a media id to run this step)")

    print("\nE) GET /content/mine")
    r = requests.get(f"{API}/content/mine", headers=H, timeout=30)
    for c in r.json().get("cards", []):
        print("   ", c["cardId"], "|", c.get("title"))

finally:
    print(f"\ncleanup DELETE {scratch}")
    show("DELETE", requests.delete(f"{API}/content/{scratch}", headers=H, timeout=30))
