import gzip
import json
import unittest

import helpers  # noqa: F401
from wikitrends import config
from wikitrends.net import HttpClient, HttpError, NetworkBlocked, NotFound


class Scripted:
    """Transport returning scripted (status, headers, body) tuples in order."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.headers_seen = []

    def __call__(self, url, headers, timeout):
        self.headers_seen.append(headers)
        r = self.responses.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


def ok(obj, gz=False):
    body = json.dumps(obj).encode()
    if gz:
        return 200, {"Content-Encoding": "gzip"}, gzip.compress(body)
    return 200, {}, body


class TestNet(unittest.TestCase):
    def client(self, responses):
        t = Scripted(responses)
        sleeps = []
        return HttpClient(transport=t, sleep=sleeps.append, rate_per_min=100000), t, sleeps

    def test_user_agent_identifies_client_with_contact(self):
        c, t, _ = self.client([ok({"a": 1})])
        c.get_json("https://example.org/x")
        ua = t.headers_seen[0]["User-Agent"]
        self.assertTrue(ua.startswith(f"{config.SKILL_NAME}/"))
        self.assertIn("(", ua)  # "(contact)" part required by Wikimedia policy

    def test_retries_429_honouring_retry_after(self):
        c, _t, sleeps = self.client([(429, {"Retry-After": "3"}, b"{}"), (503, {}, b"{}"), ok({"v": 2})])
        self.assertEqual(c.get_json("https://example.org/x"), {"v": 2})
        self.assertEqual(sleeps[0], 3.0)
        self.assertEqual(c.stats.retries, 2)

    def test_404_raises_not_found(self):
        c, _t, _s = self.client([(404, {}, b'{"title":"Not Found"}')])
        with self.assertRaises(NotFound):
            c.get_json("https://example.org/x")

    def test_gzip_body(self):
        c, _t, _s = self.client([ok({"z": 1}, gz=True)])
        self.assertEqual(c.get_json("https://example.org/x"), {"z": 1})

    def test_network_error_becomes_network_blocked_after_retries(self):
        c, _t, sleeps = self.client([OSError("boom")] * 5)
        with self.assertRaises(NetworkBlocked):
            c.get_json("https://example.org/x")
        self.assertEqual(len(sleeps), 4)

    def test_other_4xx_is_http_error(self):
        c, _t, _s = self.client([(400, {}, b'{"error":"bad"}')])
        with self.assertRaises(HttpError):
            c.get_json("https://example.org/x")

    def test_build_url_keeps_pipes(self):
        self.assertEqual(HttpClient.build_url("https://h/api", {"titles": "A|B"}), "https://h/api?titles=A|B")


if __name__ == "__main__":
    unittest.main()
