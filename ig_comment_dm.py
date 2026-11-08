#!/usr/bin/env python3
"""Comment-to-DM for your own Instagram reels, using Instagram's official API.

Someone comments a keyword (e.g. TEST) on a reel -> they get one private reply
with your link. Runs on a schedule (GitHub Actions); no server needed.

Official endpoints used. Default is the Instagram API with Unified Login
(host graph.facebook.com, the only option Meta gives new apps since 2026; its
system-user token can be set to never expire). IG_LOGIN=instagram switches to
the older Instagram Login (host graph.instagram.com, 60-day tokens).
  GET  /me/assigned_instagram_accounts  your Instagram account ID (unified)
  GET  /<ig-user-id>/media            find the reel from its URL
  GET  /<media-id>/comments           read comments (50 per page, newest first)
  POST /<ig-user-id>/messages         private reply: {"recipient":{"comment_id":..}}
  GET  /refresh_access_token          extend the 60-day token (instagram login only)
Rules from Meta: one private reply per comment, within 7 days of the comment.
It lands in their Inbox if they follow you, otherwise in their Requests folder.

Env:
  IG_ACCESS_TOKEN   required. Never commit it.
  DRY_RUN=1         print what would be sent, send nothing.
  IG_API_VERSION    default v27.0
  IG_LOGIN          unified (default) or instagram
  IG_USER_ID        optional: which Instagram account, if the token covers several
Commands:
  python ig_comment_dm.py run        process all campaigns in config.json once
  python ig_comment_dm.py watch [--every 10] [--hours 48]
                                     keep checking every N seconds (run on your Mac
                                     with caffeinate while a reel is fresh)
  python ig_comment_dm.py whoami     check the token works
  python ig_comment_dm.py media      list your recent posts with their IDs
  python ig_comment_dm.py refresh    print a refreshed token (for the weekly job)
"""
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
CONFIG_PATH = HERE / "config.json"
STATE_PATH = HERE / "state.json"
LOGIN = os.environ.get("IG_LOGIN", "unified").strip().lower()
HOST = "https://graph.instagram.com" if LOGIN == "instagram" else "https://graph.facebook.com"
VERSION = os.environ.get("IG_API_VERSION", "v27.0")
REPLY_WINDOW = timedelta(days=7)
SAFETY_MARGIN = timedelta(hours=1)  # don't try at 6d 23h 59m
MAX_PAGES = 40  # 40 x 50 = 2,000 comments per reel per run


class ApiError(Exception):
    def __init__(self, status, body):
        super().__init__(f"HTTP {status}: {body}")
        self.status = status
        self.body = body


def error_code(err):
    try:
        return json.loads(err.body).get("error", {}).get("code")
    except (ValueError, AttributeError):
        return None


def is_auth_error(err):
    return err.status == 401 or error_code(err) == 190


class Api:
    """Tiny stdlib HTTP client. Swappable in tests."""

    def __init__(self, token):
        self.token = token

    def _request(self, method, url, payload=None):
        headers = {"Authorization": f"Bearer {self.token}"}
        data = None
        if payload is not None:
            data = json.dumps(payload).encode()
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.loads(r.read().decode() or "{}")
        except urllib.error.HTTPError as e:
            raise ApiError(e.code, e.read().decode(errors="replace")) from None

    def get(self, path, params=None):
        url = path if path.startswith("http") else f"{HOST}/{VERSION}/{path}"
        if params:
            url += ("&" if "?" in url else "?") + urllib.parse.urlencode(params)
        return self._request("GET", url)

    def post(self, path, payload):
        return self._request("POST", f"{HOST}/{VERSION}/{path}", payload)

    def account(self):
        """Your Instagram account as {"id", "username"}."""
        if LOGIN == "instagram":
            me = self.get("me", {"fields": "user_id,username,account_type"})
            return {"id": me.get("user_id") or me.get("id"), "username": me.get("username", "")}
        # Unified login: /me is a system user, so ask which Instagram accounts it can use.
        accts = self.get("me/assigned_instagram_accounts", {"fields": "id,username"}).get("data", [])
        want = os.environ.get("IG_USER_ID")
        if want:
            accts = [a for a in accts if a.get("id") == want]
        if not accts:
            raise SystemExit("This token can't see any Instagram account. Re-generate it "
                             "and make sure your Instagram account is selected.")
        if len(accts) > 1:
            print("token covers several accounts, using the first; set IG_USER_ID to choose: "
                  + ", ".join(f"{a['id']} (@{a.get('username')})" for a in accts), file=sys.stderr)
        return {"id": accts[0]["id"], "username": accts[0].get("username", "")}

    def refresh(self):
        url = f"{HOST}/refresh_access_token?" + urllib.parse.urlencode(
            {"grant_type": "ig_refresh_token", "access_token": self.token})
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read().decode())


# ---------- pure logic (tested offline) ----------

def matches_keyword(text, keyword):
    """True if the comment contains the keyword as a whole word, any case.
    'TEST', 'test 🙏', 'Test!!', 'pls send TEST' match. 'testing', 'contest' don't."""
    if not text:
        return False
    return re.search(rf"(?<![A-Za-z0-9]){re.escape(keyword)}(?![A-Za-z0-9])",
                     text, flags=re.IGNORECASE) is not None


def parse_ts(ts):
    # Meta format: 2026-11-08T15:41:43+0000
    return datetime.strptime(ts, "%Y-%m-%dT%H:%M:%S%z")


def still_in_window(ts, now):
    return now - parse_ts(ts) < REPLY_WINDOW - SAFETY_MARGIN


def shortcode(url):
    m = re.search(r"instagram\.com/(?:[^/]+/)?(?:reel|reels|p|tv)/([A-Za-z0-9_-]+)", url or "")
    return m.group(1) if m else None


def pick_comments_to_answer(comments, keyword, own_username, done_ids, now):
    out = []
    for c in comments:
        cid = c.get("id")
        if not cid or cid in done_ids:
            continue
        if own_username and (c.get("username") or "").lower() == own_username.lower():
            continue
        if not matches_keyword(c.get("text"), keyword):
            continue
        if not c.get("timestamp") or not still_in_window(c["timestamp"], now):
            continue
        out.append(c)
    return out


# ---------- API steps ----------

def load_json(path, default):
    return json.loads(path.read_text()) if path.exists() else default


def save_state(state):
    STATE_PATH.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n")


def find_media_id(api, reel_url, ig_id):
    want = shortcode(reel_url)
    if not want:
        raise SystemExit(f"Can't read a reel shortcode from {reel_url!r}")
    page = api.get(f"{ig_id}/media", {"fields": "id,permalink,timestamp", "limit": 50})
    for _ in range(5):  # last ~250 posts
        for m in page.get("data", []):
            if shortcode(m.get("permalink")) == want:
                return m["id"]
        nxt = page.get("paging", {}).get("next")
        if not nxt:
            break
        page = api.get(nxt)
    raise SystemExit(f"Reel {reel_url} not found in your recent posts")


def fetch_recent_comments(api, media_id, now):
    """Newest first; stop paging once comments are older than the reply window."""
    comments = []
    page = api.get(f"{media_id}/comments",
                   {"fields": "id,text,timestamp,username", "limit": 50})
    for _ in range(MAX_PAGES):
        data = page.get("data", [])
        comments.extend(data)
        if data and not still_in_window(data[-1].get("timestamp", "1970-01-01T00:00:00+0000"), now):
            break
        nxt = page.get("paging", {}).get("next")
        if not nxt:
            break
        page = api.get(nxt)
    return comments


def run(api, dry_run=False, now=None, sleep=time.sleep, me=None, quiet=False):
    now = now or datetime.now(timezone.utc)
    config = load_json(CONFIG_PATH, None)
    if not config:
        raise SystemExit("config.json missing")
    state = load_json(STATE_PATH, {"replied": {}, "media_ids": {}})
    me = me or api.account()
    ig_id = me["id"]
    username = me.get("username", "")

    sent = skipped = 0
    for camp in config["campaigns"]:
        if not camp.get("active", True):
            continue
        url, kw = camp["reel_url"], camp["keyword"]
        media_id = state["media_ids"].get(url) or find_media_id(api, url, ig_id)
        state["media_ids"][url] = media_id
        done = state["replied"].setdefault(media_id, {})
        todo = pick_comments_to_answer(fetch_recent_comments(api, media_id, now),
                                       kw, username, set(done), now)
        if todo or not quiet:
            print(f"[{kw}] {url}: {len(todo)} new matching comment(s)")
        for c in todo:
            text = camp["message"]
            if dry_run:
                print(f"  DRY RUN would reply to comment {c['id']} ({c.get('timestamp')})")
                continue
            try:
                api.post(f"{ig_id}/messages",
                         {"recipient": {"comment_id": c["id"]}, "message": {"text": text}})
                done[c["id"]] = now.strftime("%Y-%m-%dT%H:%M:%SZ")
                sent += 1
                print(f"  sent -> comment {c['id']}")
            except ApiError as e:
                # Already replied, comment deleted, outside window: mark so we don't retry forever.
                if e.status in (400, 403, 404) and not is_auth_error(e) and not is_rate_limited(e):
                    done[c["id"]] = "error:" + str(e.status)
                    skipped += 1
                    print(f"  skipped comment {c['id']}: {e.body[:200]}")
                else:
                    save_state(state)
                    raise
            save_state(state)  # save after every send, so a crash never double-sends
            sleep(1.5)  # be gentle with rate limits
    if not dry_run:
        save_state(state)
    if sent or skipped or not quiet:
        print(f"done: {sent} sent, {skipped} skipped")
    return sent, skipped


RATE_LIMIT_CODES = {4, 17, 32, 613}  # Meta's "too many calls" error codes


def is_rate_limited(err):
    return err.status == 429 or error_code(err) in RATE_LIMIT_CODES


def watch(api, every=10, hours=48, dry_run=False, sleep=time.sleep, clock=time.monotonic,
          max_loops=None):
    """Check every `every` seconds for `hours` hours. Survives network blips and
    backs off when Instagram says we're calling too often."""
    me = api.account()
    print(f"watching as @{me.get('username')} every {every}s for {hours}h (Ctrl+C to stop)")
    end = clock() + hours * 3600
    backoff = 0
    loops = 0
    while clock() < end and (max_loops is None or loops < max_loops):
        loops += 1
        started = clock()
        try:
            run(api, dry_run=dry_run, sleep=sleep, me=me, quiet=True)
            backoff = 0
        except ApiError as e:
            if is_rate_limited(e):
                backoff = min(max(backoff * 2, 60), 900)
                print(f"rate limited by Instagram, pausing {backoff}s")
            elif is_auth_error(e):
                raise SystemExit("Token rejected (expired?). Generate a new one.") from None
            else:
                backoff = min(max(backoff * 2, 15), 300)
                print(f"API error, retrying in {backoff}s: {e.body[:200]}")
        except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
            backoff = min(max(backoff * 2, 15), 300)
            print(f"network problem, retrying in {backoff}s: {e}")
        wait = backoff or max(0, every - (clock() - started))
        sleep(wait)
    print("watch finished")


def load_dotenv():
    env = HERE / ".env"
    if env.exists():
        for line in env.read_text().splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip("'\""))


def flag(name, default):
    if name in sys.argv:
        return float(sys.argv[sys.argv.index(name) + 1])
    return default


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "run"
    load_dotenv()
    if cmd in ("run", "watch"):
        active = [c for c in load_json(CONFIG_PATH, {"campaigns": []})["campaigns"] if c.get("active", True)]
        if not active:
            print("no active campaigns in config.json, nothing to do")
            return
    token = os.environ.get("IG_ACCESS_TOKEN")
    if not token:
        raise SystemExit("Set IG_ACCESS_TOKEN (never commit it).")
    api = Api(token)
    if cmd == "whoami":
        print(api.account())
    elif cmd == "media":
        for m in api.get(f"{api.account()['id']}/media", {"fields": "id,permalink,timestamp,caption", "limit": 15}).get("data", []):
            print(m["id"], m.get("timestamp"), m.get("permalink"), (m.get("caption") or "")[:40].replace("\n", " "))
    elif cmd == "refresh":
        if LOGIN != "instagram":
            raise SystemExit("Unified-login tokens don't use this refresh; nothing to do.")
        r = api.refresh()
        days = int(r.get("expires_in", 0)) // 86400
        print(r["access_token"])
        print(f"valid for ~{days} days", file=sys.stderr)
    elif cmd == "run":
        run(api, dry_run=os.environ.get("DRY_RUN") == "1")
    elif cmd == "watch":
        every = max(5, flag("--every", 10))  # never faster than 5s
        try:
            watch(api, every=every, hours=flag("--hours", 48),
                  dry_run=os.environ.get("DRY_RUN") == "1")
        except KeyboardInterrupt:
            print("\nstopped")
    else:
        raise SystemExit(__doc__)


if __name__ == "__main__":
    main()
