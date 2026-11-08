import json, sys, tempfile, unittest
from datetime import datetime, timezone, timedelta
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import ig_comment_dm as m

NOW = datetime(2026, 11, 10, 12, 0, tzinfo=timezone.utc)
def ts(hours_ago): return (NOW - timedelta(hours=hours_ago)).strftime("%Y-%m-%dT%H:%M:%S+0000")


class Keyword(unittest.TestCase):
    def test_matches(self):
        for t in ["TEST", "test", "Test!!", "test 🙏", "pls send TEST bro", "TEST.", "#test"]:
            self.assertTrue(m.matches_keyword(t, "TEST"), t)
    def test_no_match(self):
        for t in ["testing", "contest", "tested", "", None, "great reel"]:
            self.assertFalse(m.matches_keyword(t, "TEST"), t)


class Shortcode(unittest.TestCase):
    def test(self):
        self.assertEqual(m.shortcode("https://www.instagram.com/reel/DAbc_1-2/?igsh=x"), "DAbc_1-2")
        self.assertEqual(m.shortcode("https://www.instagram.com/ft.adityas/reel/DAbc12/"), "DAbc12")
        self.assertEqual(m.shortcode("https://www.instagram.com/p/XYZ/"), "XYZ")
        self.assertIsNone(m.shortcode("https://example.com"))


class Pick(unittest.TestCase):
    def test_filters(self):
        cs = [
            {"id": "1", "text": "TEST", "timestamp": ts(1), "username": "a"},
            {"id": "2", "text": "test", "timestamp": ts(1), "username": "me"},        # own comment
            {"id": "3", "text": "TEST", "timestamp": ts(24 * 8), "username": "b"},    # too old
            {"id": "4", "text": "nice", "timestamp": ts(1), "username": "c"},         # no keyword
            {"id": "5", "text": "test pls", "timestamp": ts(2), "username": "d"},     # already done
            {"id": "6", "text": "Test", "timestamp": ts(24 * 6.97), "username": "e"},  # inside 7d but within the 1h safety margin
        ]
        got = [c["id"] for c in m.pick_comments_to_answer(cs, "TEST", "me", {"5"}, NOW)]
        self.assertEqual(got, ["1"])


class FakeApi:
    def __init__(self, comments_pages, fail_ids=()):
        self.pages = comments_pages
        self.fail_ids = set(fail_ids)
        self.sent = []
    def get(self, path, params=None):
        if path == "me":
            return {"user_id": "999", "username": "me"}
        if path == "me/media":
            return {"data": [{"id": "M1", "permalink": "https://www.instagram.com/reel/ABC/"}]}
        if path == "M1/comments":
            return self.pages[0]
        if path.startswith("http"):  # paging.next
            return self.pages[int(path.rsplit("=", 1)[1])]
        raise AssertionError(path)
    def post(self, path, payload):
        assert path == "999/messages"
        cid = payload["recipient"]["comment_id"]
        if cid in self.fail_ids:
            raise m.ApiError(400, "already replied")
        self.sent.append(cid)
        return {"recipient_id": "x", "message_id": "y"}


class Run(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        m.CONFIG_PATH = self.tmp / "config.json"
        m.STATE_PATH = self.tmp / "state.json"
        m.CONFIG_PATH.write_text(json.dumps({"campaigns": [
            {"reel_url": "https://www.instagram.com/reel/ABC/", "keyword": "TEST", "message": "link"}]}))
        self.pages = [
            {"data": [{"id": "c1", "text": "TEST", "timestamp": ts(1), "username": "u1"},
                      {"id": "c2", "text": "wow", "timestamp": ts(2), "username": "u2"}],
             "paging": {"next": "https://x/?page=1"}},
            {"data": [{"id": "c3", "text": "test", "timestamp": ts(3), "username": "u3"},
                      {"id": "c4", "text": "TEST", "timestamp": ts(5), "username": "u4"}]},
        ]

    def test_sends_once_across_runs(self):
        api = FakeApi(self.pages, fail_ids={"c4"})
        sent, skipped = m.run(api, now=NOW, sleep=lambda s: None)
        self.assertEqual((sorted(api.sent), sent, skipped), (["c1", "c3"], 2, 1))
        api2 = FakeApi(self.pages)
        self.assertEqual(m.run(api2, now=NOW, sleep=lambda s: None), (0, 0))
        self.assertEqual(api2.sent, [])
        state = json.loads(m.STATE_PATH.read_text())
        self.assertEqual(state["media_ids"], {"https://www.instagram.com/reel/ABC/": "M1"})

    def test_dry_run_sends_nothing(self):
        api = FakeApi(self.pages)
        m.run(api, dry_run=True, now=NOW, sleep=lambda s: None)
        self.assertEqual(api.sent, [])
        self.assertFalse(m.STATE_PATH.exists())


class Errors(unittest.TestCase):
    def setUp(self):
        Run.setUp(self)

    def test_expired_token_not_marked_as_done(self):
        class Expired(FakeApi):
            def post(self, path, payload):
                raise m.ApiError(400, json.dumps({"error": {"code": 190, "message": "expired"}}))
        with self.assertRaises(m.ApiError):
            m.run(Expired(self.pages), now=NOW, sleep=lambda s: None)
        state = json.loads(m.STATE_PATH.read_text())
        self.assertEqual(state["replied"].get("M1", {}), {})  # will retry after new token

    def test_rate_limit_not_marked_as_done(self):
        class Limited(FakeApi):
            def post(self, path, payload):
                raise m.ApiError(400, json.dumps({"error": {"code": 4}}))
        with self.assertRaises(m.ApiError):
            m.run(Limited(self.pages), now=NOW, sleep=lambda s: None)


class Watch(unittest.TestCase):
    def setUp(self):
        Run.setUp(self)
        self.t = [0.0]
        self.waits = []
    def clock(self): return self.t[0]
    def sleep(self, s):
        self.waits.append(s); self.t[0] += s

    def test_loops_every_10s_and_sends_once(self):
        api = FakeApi(self.pages)
        m.watch(api, every=10, hours=1, sleep=self.sleep, clock=self.clock, max_loops=5)
        self.assertEqual(sorted(api.sent), ["c1", "c3", "c4"])
        self.assertEqual([w for w in self.waits if w == 10], [10, 10, 10, 10])  # +1.5s pauses after sends

    def test_backs_off_on_rate_limit_then_recovers(self):
        calls = {"n": 0}
        pages = self.pages
        class Flaky(FakeApi):
            def get(s, path, params=None):
                if path == "M1/comments":
                    calls["n"] += 1
                    if calls["n"] <= 2:
                        raise m.ApiError(400, json.dumps({"error": {"code": 32}}))
                return FakeApi.get(s, path, params)
        api = Flaky(pages)
        m.watch(api, every=10, hours=1, sleep=self.sleep, clock=self.clock, max_loops=3)
        self.assertIn(60, self.waits)
        self.assertIn(120, self.waits)
        self.assertEqual(sorted(api.sent), ["c1", "c3", "c4"])

    def test_stops_on_expired_token(self):
        class Expired(FakeApi):
            def get(s, path, params=None):
                if path == "M1/comments":
                    raise m.ApiError(400, json.dumps({"error": {"code": 190}}))
                return FakeApi.get(s, path, params)
        with self.assertRaises(SystemExit):
            m.watch(Expired(self.pages), every=10, hours=1, sleep=self.sleep, clock=self.clock, max_loops=3)


if __name__ == "__main__":
    unittest.main()
