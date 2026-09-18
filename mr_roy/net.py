"""Network helpers. Mostly one workaround that buys a 40x speedup.

This Mac's network advertises AAAA records but drops IPv6 traffic. Python's
socket layer walks getaddrinfo results in order and waits the full connect
timeout on each, so every request stalled ~12-20s on a dead IPv6 address
before falling back to IPv4. curl hides this with Happy Eyeballs (it races
both families); urllib does not.

We sort IPv4 first rather than dropping IPv6, so a genuinely IPv6-only
network still works -- it just pays one fast failure first.
"""

from __future__ import annotations

import hashlib
import json
import socket
import time
import urllib.error
import urllib.parse
import urllib.request

_patched = False

# Wikimedia rate-limits anonymous API traffic and answers 429. A fixed floor
# between requests keeps a 200-word backfill under the limit without anyone
# having to think about it; the retry handles the rest.
MIN_INTERVAL = 1.0
MAX_RETRIES = 2  # was 4: with 12s timeouts and 30s backoff one word could take a minute
_last_request = 0.0


class TransientError(Exception):
    """The network or the API failed. Says nothing about whether the word exists.

    Kept separate from a genuine 404 so a rate limit is never cached as
    "this word has no pronunciation" -- that poisons the cache permanently.
    """


def _throttle() -> None:
    global _last_request
    wait = MIN_INTERVAL - (time.monotonic() - _last_request)
    if wait > 0:
        time.sleep(wait)
    _last_request = time.monotonic()


def _open(url: str, user_agent: str, timeout: int):
    """One request, throttled, retrying on 429 and 5xx with backoff."""
    prefer_ipv4()
    req = urllib.request.Request(url, headers={"User-Agent": user_agent})
    delay = 1.0
    for attempt in range(MAX_RETRIES):
        _throttle()
        try:
            return urllib.request.urlopen(req, timeout=timeout)
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                raise
            if exc.code not in (429, 500, 502, 503, 504) or attempt == MAX_RETRIES - 1:
                raise TransientError(f"HTTP {exc.code} for {url}") from exc
            retry_after = exc.headers.get("Retry-After") if exc.headers else None
            try:
                sleep_for = float(retry_after) if retry_after else delay
            except ValueError:
                sleep_for = delay
            time.sleep(min(sleep_for, 30.0))
            delay *= 2
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            if attempt == MAX_RETRIES - 1:
                raise TransientError(f"{type(exc).__name__} for {url}") from exc
            time.sleep(delay)
            delay *= 2
    raise TransientError(f"gave up after {MAX_RETRIES} attempts: {url}")


def prefer_ipv4() -> None:
    """Idempotent. Call before any HTTP work."""
    global _patched
    if _patched:
        return
    original = socket.getaddrinfo

    def ipv4_first(*args, **kwargs):
        # IPv4 ONLY when any IPv4 address exists; the full list otherwise.
        # Sorting was not enough: when the IPv4 attempt failed fast, the
        # connection loop fell through to the IPv6 address and hung there
        # with no CPU and, in practice, no effective timeout -- a nightly
        # job sat on one such socket for eight minutes. An IPv6-only network
        # still works because the fallback keeps the whole list.
        results = original(*args, **kwargs)
        v4 = [r for r in results if r[0] == socket.AF_INET]
        return v4 if v4 else results

    socket.getaddrinfo = ipv4_first
    _patched = True


def get_json(url: str, user_agent: str, timeout: int) -> dict:
    with _open(url, user_agent, timeout) as resp:
        return json.load(resp)


def get_bytes(url: str, user_agent: str, timeout: int) -> bytes:
    with _open(url, user_agent, timeout) as resp:
        return resp.read()


def commons_url(file_title: str) -> str:
    """Where a Commons file lives, computed instead of asked for.

    Wikimedia lays files out by the MD5 of the underscored filename:
    .../commons/<h[0]>/<h[0:2]>/<Name>. Deriving it saves an API round trip
    and one more thing that can fail.
    """
    name = file_title.split(":", 1)[-1].replace(" ", "_")
    # MediaWiki capitalises the first character of every filename before
    # storing it, and the MD5 is taken of that canonical form. Hashing the
    # title as the API returned it ("en-us-measure.ogg") yields a 404.
    name = name[:1].upper() + name[1:]
    digest = hashlib.md5(name.encode("utf-8")).hexdigest()
    quoted = urllib.parse.quote(name)
    return f"https://upload.wikimedia.org/wikipedia/commons/{digest[0]}/{digest[:2]}/{quoted}"


def transcode_url(file_title: str) -> str:
    """The .mp3 Wikimedia generates for every audio file. afplay reads mp3."""
    base = commons_url(file_title)
    head, name = base.rsplit("/", 1)
    return f"{head.replace('/commons/', '/commons/transcoded/', 1)}/{name}/{name}.mp3"
