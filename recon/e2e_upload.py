#!/usr/bin/env python3
"""End-to-end probe of the Yoto media upload -> transcode -> content write flow."""
import json
import sys
import time

import requests

API = "https://api.yotoplay.com"
TOKEN = open("recon/.token").read().strip()
H = {"Authorization": f"Bearer {TOKEN}", "Origin": "https://my.yotoplay.com"}


def step(n, msg):
    print(f"\n=== {n}. {msg} ===")


def j(resp):
    try:
        return resp.json()
    except Exception:
        return resp.text[:400]


scratch = None
try:
    step(1, "POST /content -> create scratch card")
    r = requests.post(f"{API}/content", headers={**H, "Content-Type": "application/json"},
                      json={}, timeout=30)
    print(j(r))
    scratch = j(r)["card"]["cardId"]
    print(f"scratch cardId = {scratch}")

    step(2, "GET /media/transcode/audio/uploadUrl")
    r = requests.get(f"{API}/media/transcode/audio/uploadUrl", headers=H, timeout=30)
    up = j(r)["upload"]
    upload_id, upload_url = up["uploadId"], up["uploadUrl"]
    print(f"uploadId = {upload_id}")
    print(f"uploadUrl host = {upload_url.split('/')[2]}")

    step(3, "PUT audio file to presigned S3 URL")
    data = open("recon/media/test.mp3", "rb").read()
    r = requests.put(upload_url,
                     data=data,
                     headers={"Content-Disposition": 'attachment; filename="test.mp3"'},
                     timeout=300)
    print(f"HTTP {r.status_code} {r.text[:200]}")

    step(4, "poll GET /media/upload/{uploadId}/transcoded")
    media_id = None
    for i in range(40):
        time.sleep(3)
        r = requests.get(f"{API}/media/upload/{upload_id}/transcoded", headers=H, timeout=30)
        t = j(r).get("transcode", {})
        state = {k: t.get(k) for k in ("progress", "error", "erroredAt", "transcodedAt",
                                      "uploadFilename", "uploadSha256")}
        print(f"  [{i}] keys={list(t.keys())}")
        print(f"      {json.dumps(state)[:300]}")
        # look for any media id anywhere in the payload
        for k, v in t.items():
            if isinstance(v, str) and len(v) > 20 and k not in ("uploadFilename", "uploadSha256"):
                print(f"      candidate[{k}] = {v}")
        if t.get("progress") == 100 or t.get("transcodedAt") or t.get("error"):
            break

    print("\n--- full transcode payload ---")
    r = requests.get(f"{API}/media/upload/{upload_id}/transcoded", headers=H, timeout=30)
    print(json.dumps(j(r), indent=2)[:2000])

    step(5, "PUT /content/{cardId} with a real track")
    # placeholder media id filled below
    if media_id:
        body = {
            "title": "Probe Card",
            "content": {
                "activity": "yoto_Player",
                "playbackType": "linear",
                "config": {"resumeTimeout": 2592000, "onlineOnly": False},
                "chapters": [{
                    "key": "00", "title": "Chapter 1",
                    "tracks": [{
                        "key": "01", "title": "Test Track", "format": "aac",
                        "trackUrl": f"yoto:#{media_id}", "type": "audio",
                        "duration": 3, "fileSize": len(data), "channels": "mono",
                    }],
                }],
            },
        }
        r = requests.put(f"{API}/content/{scratch}", headers={**H, "Content-Type": "application/json"},
                         json=body, timeout=30)
        print(f"HTTP {r.status_code}", j(r))
    else:
        print("no media id captured - see payload above")

finally:
    if scratch:
        step(6, f"DELETE /content/{scratch} (cleanup)")
        r = requests.delete(f"{API}/content/{scratch}", headers=H, timeout=30)
        print(f"HTTP {r.status_code} {j(r)}")
