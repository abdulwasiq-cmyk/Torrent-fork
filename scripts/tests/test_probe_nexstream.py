"""Tests for the NexStream availability probe."""
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "probe_nexstream.py"
SPEC = importlib.util.spec_from_file_location("probe_nexstream", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MODULE)

NOW = 1_800_000_000.0


class ClassifyTests(unittest.TestCase):
    def test_sources_mean_ok(self):
        self.assertEqual(MODULE.classify(200, json.dumps({"sources": [{"url": "x"}]})), "ok")

    def test_empty_sources_mean_none(self):
        self.assertEqual(MODULE.classify(200, json.dumps({"sources": []})), "none")

    def test_no_supported_source_is_none(self):
        body = json.dumps({"detail": "NexStream returned no supported player source."})
        self.assertEqual(MODULE.classify(502, body), "none")

    def test_connection_trouble_is_retry_not_none(self):
        self.assertEqual(MODULE.classify(502, json.dumps({"detail": "Could not connect to NexStream."})), "retry")
        self.assertEqual(MODULE.classify(429, "slow down"), "retry")
        self.assertEqual(MODULE.classify(200, "not json"), "retry")

    def test_missing_key_is_fatal(self):
        with self.assertRaises(MODULE.Fatal):
            MODULE.classify(503, "NexStream is not configured")


class ProbeTests(unittest.TestCase):
    def titles(self):
        return {
            "movie:1": {"type": "movie", "tmdbId": 1, "title": "A"},
            "tv:2": {"type": "tv", "tmdbId": 2, "title": "B"},
            "movie:3": {"type": "movie", "tmdbId": 3, "title": "C"},
        }

    def test_records_ok_and_none_but_not_retry(self):
        answers = {1: (200, json.dumps({"sources": [1]})), 2: (502, "no supported player source"), 3: (429, "")}
        existing = {}
        counts = MODULE.probe(self.titles(), existing, lambda media, tid: answers[tid], now=NOW, max_age=86400)
        self.assertEqual((counts["ok"], counts["none"], counts["retry"]), (1, 1, 1))
        self.assertTrue(existing["movie:1"]["ok"])
        self.assertFalse(existing["tv:2"]["ok"])
        self.assertNotIn("movie:3", existing)

    def test_recent_results_are_skipped_unless_forced(self):
        existing = {"movie:1": {"ok": True, "checkedAt": int(NOW) - 100}}
        calls = []

        def resolve(media, tid):
            calls.append(tid)
            return 200, json.dumps({"sources": [1]})

        MODULE.probe(self.titles(), existing, resolve, now=NOW, max_age=86400)
        self.assertNotIn(1, calls)
        calls.clear()
        MODULE.probe(self.titles(), existing, resolve, now=NOW, max_age=86400, force=True)
        self.assertIn(1, calls)

    def test_network_error_is_retry(self):
        def resolve(media, tid):
            raise OSError("down")

        existing = {}
        counts = MODULE.probe(self.titles(), existing, resolve, now=NOW, max_age=1)
        self.assertEqual(counts["retry"], 3)
        self.assertEqual(existing, {})

    def test_limit(self):
        counts = MODULE.probe(self.titles(), {}, lambda m, t: (200, json.dumps({"sources": [1]})), now=NOW, max_age=1, limit=2)
        self.assertEqual(counts["checked"], 2)


class CollectTests(unittest.TestCase):
    def test_collects_unique_titles_across_sections(self):
        with tempfile.TemporaryDirectory() as folder:
            seed = Path(folder)
            row = {"title": "Dup", "tmdbId": 5, "mediaType": "movie"}
            for name in ("marvel", "dc"):
                (seed / f"{name}.json").write_text(json.dumps({"subsections": {
                    "movies": {"results": [row, {"title": "Show", "tmdbId": 9, "mediaType": "tv"}, {"title": "No id"}]},
                }}))
            found = MODULE.collect_titles(seed)
            self.assertEqual(sorted(found), ["movie:5", "tv:9"])


if __name__ == "__main__":
    unittest.main()
