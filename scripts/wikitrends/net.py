"""Small, dependency-free HTTP client tuned for Wikimedia APIs.

- identifies itself with a policy-compliant User-Agent (see config.user_agent)
- throttles itself below Wikimedia's per-minute limit (token bucket)
- retries 429/5xx/network errors with exponential backoff, honouring Retry-After
- turns 404 into a NotFound exception (the Pageviews API uses 404 for "no data")
- falls back to the certifi CA bundle when the system trust store is missing
  (common with python.org installers on macOS)

A custom `transport` can be injected for offline tests.
"""

from __future__ import annotations

import gzip
import json
import random
import ssl
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass, field

from . import config

# transport(url, headers, timeout) -> (status, response_headers, body_bytes)
Transport = Callable[[str, dict, float], "tuple[int, dict, bytes]"]


class HttpError(Exception):
    def __init__(self, message: str, status: int = 0, url: str = "", body: str = ""):
        super().__init__(message)
        self.status = status
        self.url = url
        self.body = body


class NotFound(HttpError):
    """404 — for the Pageviews API this means "no data for this title/range"."""


class NetworkBlocked(HttpError):
    """The request never reached Wikimedia (DNS/proxy/firewall/TLS)."""


class RateLimiter:
    """Thread-safe token bucket: at most `per_minute` requests per rolling minute."""

    def __init__(self, per_minute: int):
        self.capacity = max(1, per_minute)
        self.tokens = float(min(self.capacity, 10))  # small initial burst only
        self.rate = self.capacity / 60.0
        self.updated = time.monotonic()
        self.lock = threading.Lock()

    def acquire(self) -> None:
        while True:
            with self.lock:
                now = time.monotonic()
                self.tokens = min(self.capacity, self.tokens + (now - self.updated) * self.rate)
                self.updated = now
                if self.tokens >= 1:
                    self.tokens -= 1
                    return
                wait = (1 - self.tokens) / self.rate
            time.sleep(min(wait, 2.0))


@dataclass
class HttpStats:
    requests: int = 0
    retries: int = 0
    not_found: int = 0
    bytes: int = 0
    lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def add(self, **kw: int) -> None:
        with self.lock:
            for k, v in kw.items():
                setattr(self, k, getattr(self, k) + v)


_SSL_CONTEXT: ssl.SSLContext | None = None
_SSL_LOCK = threading.Lock()


def _ssl_context(use_certifi: bool = False) -> ssl.SSLContext:
    global _SSL_CONTEXT
    with _SSL_LOCK:
        if use_certifi:
            try:
                import certifi  # type: ignore

                _SSL_CONTEXT = ssl.create_default_context(cafile=certifi.where())
            except ImportError:  # pragma: no cover - depends on environment
                _SSL_CONTEXT = ssl.create_default_context()
        elif _SSL_CONTEXT is None:
            _SSL_CONTEXT = ssl.create_default_context()
        return _SSL_CONTEXT


def urllib_transport(url: str, headers: dict, timeout: float) -> tuple[int, dict, bytes]:
    """Default transport. Respects HTTPS_PROXY/NO_PROXY like any urllib client."""
    req = urllib.request.Request(url, headers=headers, method="GET")
    for attempt_certifi in (False, True):
        try:
            with urllib.request.urlopen(req, timeout=timeout, context=_ssl_context(attempt_certifi)) as resp:
                return resp.status, dict(resp.headers), resp.read()
        except urllib.error.HTTPError as e:
            body = e.read() if hasattr(e, "read") else b""
            return e.code, dict(e.headers or {}), body
        except urllib.error.URLError as e:
            reason = getattr(e, "reason", e)
            if isinstance(reason, ssl.SSLCertVerificationError) and not attempt_certifi:
                continue  # retry once with the certifi bundle
            raise
    raise RuntimeError("unreachable")  # pragma: no cover


RETRY_STATUSES = {429, 500, 502, 503, 504}


class HttpClient:
    def __init__(
        self,
        transport: Transport | None = None,
        rate_per_min: int = config.RATE_PER_MIN,
        timeout: float = config.HTTP_TIMEOUT_S,
        retries: int = config.HTTP_RETRIES,
        sleep: Callable[[float], None] = time.sleep,
    ):
        self.transport = transport or urllib_transport
        self.limiter = RateLimiter(rate_per_min)
        self.timeout = timeout
        self.retries = retries
        self.sleep = sleep
        self.stats = HttpStats()
        self.headers = {
            "User-Agent": config.user_agent(),
            "Api-User-Agent": config.user_agent(),
            "Accept": "application/json",
            "Accept-Encoding": "gzip",
        }

    @staticmethod
    def build_url(url: str, params: dict | None = None) -> str:
        if not params:
            return url
        return url + ("&" if "?" in url else "?") + urllib.parse.urlencode(params, safe="|")

    def get_json(self, url: str, params: dict | None = None) -> dict:
        full = self.build_url(url, params)
        last_error: Exception | None = None
        for attempt in range(self.retries + 1):
            self.limiter.acquire()
            try:
                status, headers, body = self.transport(full, self.headers, self.timeout)
            except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as e:
                last_error = e
                if attempt < self.retries:
                    self.stats.add(retries=1)
                    self.sleep(self._backoff(attempt))
                    continue
                raise NetworkBlocked(
                    f"Cannot reach {urllib.parse.urlsplit(full).netloc}: {e}. "
                    "Check the internet connection/proxy; run `wiki.py doctor`.",
                    url=full,
                ) from e
            self.stats.add(requests=1, bytes=len(body))
            headers = {k.lower(): v for k, v in (headers or {}).items()}
            if headers.get("content-encoding", "").lower() == "gzip" or body[:2] == b"\x1f\x8b":
                try:
                    body = gzip.decompress(body)
                except OSError:
                    pass
            text = body.decode("utf-8", errors="replace")
            if status == 200:
                try:
                    return json.loads(text)
                except json.JSONDecodeError as e:
                    raise HttpError(f"Invalid JSON from {full}: {text[:200]}", status, full, text) from e
            if status == 404:
                self.stats.add(not_found=1)
                raise NotFound("404 Not Found", status, full, text)
            if status in RETRY_STATUSES and attempt < self.retries:
                self.stats.add(retries=1)
                self.sleep(self._retry_after(headers) or self._backoff(attempt))
                continue
            if status in (401, 403, 407) and "wikimedia" not in text.lower() and "wikipedia" not in text.lower():
                raise NetworkBlocked(
                    f"HTTP {status} before reaching Wikimedia (proxy or firewall?) for {full}", status, full, text
                )
            raise HttpError(f"HTTP {status} for {full}: {text[:300]}", status, full, text)
        raise HttpError(f"Giving up on {full}: {last_error}", 0, full)

    @staticmethod
    def _backoff(attempt: int) -> float:
        return min(30.0, 1.5 * (2**attempt)) + random.uniform(0, 0.5)

    @staticmethod
    def _retry_after(headers: dict) -> float | None:
        value = headers.get("retry-after")
        if not value:
            return None
        try:
            return min(float(value), config.MAX_RETRY_AFTER_S)
        except ValueError:
            return None
