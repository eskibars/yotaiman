#!/usr/bin/env python3
"""Probe which card/track fields the Yoto API actually accepts and persists."""
import json

import requests

API = "https://api.yotoplay.com"
TOKEN = open("recon/.token").read().strip()
H = {"Authorization": f"Bearer {TOKEN}", "Origin": "https://my.yotoplay.com"}


def j(r):
    try:
        return r.json()
    except Exception:
        return r.text[:300]


def show(tag, r):
    print(f"  {tag}: HTTP {r.status_code}")
    body = j(r)
    if isinstance(body, dict) and "error" in body:
        print(f"    ERROR: {body['error'].get('message')}")
    return body


scratch = requests.post(f"{API}/content", headers={**H, "Content-Type": "application/json"},
                        json={}, timeout=30).json()["card"]["cardId"]
print(f"scratch = {scratch}\n")

try:
    print("A) full option payload")
    body = {
        "title": "Option Probe",
        "metadata": {"description": "A card description."},
        "content": {
            "activity": "yoto_Player",
            "playbackType": "linear",
            "version": "1",
            "config": {
                "onlineOnly": False,
                "resumeTimeout": 0,
                "shuffle": [{"start": 0, "end": 0, "limit": 1}],
                "trackNumberOverlayTimeout": 0,
                "disableTrackNav": False,
                "disableChapterNav": False,
            },
            "editSettings": {"autoOverlayLabels": "disabled"},
            "chapters": [{
                "key": "00",
                "title": "Stream Chapter",
                "tracks": [{
                    "key": "01",
                    "title": "https://example.com/stream.mp3",
                    "trackUrl": "https://example.com/stream.mp3",
                    "type": "stream",
                    "format": "mp3",
                }],
            }],
        },
    }
    show("POST", requests.post(f"{API}/content", headers={**H, "Content-Type": "application/json"},
                                json={**body, "cardId": scratch}, timeout=30))

    print("\nB) GET back — what survived?")
    got = requests.get(f"{API}/content/{scratch}", headers=H, timeout=30).json()
    card = got.get("card", got)
    print(json.dumps(card, indent=1)[:2200])

    print("\nC) card summary (metadata present?)")
    summary = requests.get(f"{API}/content/mine", headers=H, timeout=30).json()
    mine = [c for c in summary.get("cards", []) if c.get("cardId") == scratch]
    if mine:
        print(json.dumps(mine[0], indent=1)[:1200])

finally:
    print(f"\ncleanup DELETE {scratch}")
    show("DELETE", requests.delete(f"{API}/content/{scratch}", headers=H, timeout=30))
