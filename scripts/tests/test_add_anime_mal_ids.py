"""Tests for storing MAL ids on anime section rows."""
import importlib.util
import urllib.error
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "add_anime_mal_ids.py"
SPEC = importlib.util.spec_from_file_location("add_anime_mal_ids", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MODULE)

NOW = 1_800_000_000.0


def document():
    return {"subsections": {
        "movies": {"results": [{"title": "Spirited Away", "year": 2001, "tmdbId": 129}]},
        "series": {"results": [
            {"title": "Naruto", "year": 2002, "tmdbId": 46260},
            {"title": "Already", "malId": 5},
            {"title": "Unknown Show", "year": 2020},
        ]},
    }}


class FillDocumentTests(unittest.TestCase):
    def test_resolved_rows_get_a_mal_id_and_unknown_rows_are_marked_checked(self):
        answers = {"Spirited Away": {"status": "resolved", "malId": 199},
                   "Naruto": {"status": "resolved", "malId": 20},
                   "Unknown Show": {"status": "not_found", "malId": None}}
        calls = []

        def resolve(title, year, tmdb_id):
            calls.append((title, year, tmdb_id))
            return answers[title]

        doc = document()
        counts = MODULE.fill_document(doc, None, resolve, now=NOW)
        rows = {r["title"]: r for node in doc["subsections"].values() for r in node["results"]}
        self.assertEqual(rows["Spirited Away"]["malId"], 199)
        self.assertEqual(rows["Naruto"]["malId"], 20)
        self.assertEqual(rows["Already"]["malId"], 5)
        self.assertNotIn("malId", rows["Unknown Show"])
        self.assertEqual(rows["Unknown Show"]["malIdCheckedAt"], int(NOW))
        self.assertEqual(counts, {"checked": 3, "resolved": 2, "unresolved": 1, "alreadyHad": 1, "errors": 0})
        self.assertEqual(calls[0], ("Spirited Away", 2001, 129))
        self.assertNotIn("Already", [c[0] for c in calls])  # rows that have an id are never looked up again

    def test_unresolved_rows_are_not_retried_until_the_retry_window_passes(self):
        doc = document()
        MODULE.fill_document(doc, None, lambda *a: {"status": "not_found"}, now=NOW)
        calls = []
        MODULE.fill_document(doc, None, lambda *a: calls.append(a) or {"status": "not_found"}, now=NOW + 86400)
        self.assertEqual(calls, [])
        MODULE.fill_document(doc, None, lambda *a: calls.append(a) or {"status": "not_found"}, now=NOW + 31 * 86400)
        self.assertEqual(len(calls), 3)

    def test_transient_errors_and_cooldowns_are_not_recorded_as_not_found(self):
        doc = document()

        def resolve(title, year, tmdb_id):
            if title == "Naruto":
                raise urllib.error.URLError("down")
            return {"status": "unavailable", "malId": None}

        counts = MODULE.fill_document(doc, None, resolve, now=NOW)
        rows = [r for node in doc["subsections"].values() for r in node["results"]]
        self.assertTrue(all("malIdCheckedAt" not in r for r in rows))
        self.assertEqual(counts["errors"], 3)

    def test_only_the_named_subsection_is_processed_and_limit_applies(self):
        doc = document()
        counts = MODULE.fill_document(doc, "series", lambda *a: {"status": "resolved", "malId": 1}, now=NOW, limit=1)
        self.assertEqual(counts["checked"], 1)
        self.assertNotIn("malId", doc["subsections"]["movies"]["results"][0])


if __name__ == "__main__":
    unittest.main()
