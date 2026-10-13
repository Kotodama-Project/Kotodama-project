"""Exact full-sort parity and retained-match bounds, without a timing gate."""
from __future__ import annotations

import copy
import dataclasses
import gc
from pathlib import Path
import re
import sys
import unicodedata
import unittest
from unittest import mock
import weakref

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from kotodama_kb import cli, foundation, retrieve


def full_sort_reference(bundle, query, *, limit=10, type_filter=None, tag_filter=None,
                        include_stale=False, goals=(), kgis=(), initiatives=()):
    """Independent exhaustive scorer: retain/sort everything as the old baseline did."""
    normalize = lambda text: unicodedata.normalize("NFKC", text).casefold()
    query = normalize(query.strip())
    tokens = re.findall(r"[\w-]+", query)
    requested = {"goal_refs": set(goals), "kgi_refs": set(kgis), "initiative_refs": set(initiatives)}
    for key, values in requested.items():
        if values - {ref for item in bundle.concepts for ref in item.extension.get(key, [])}:
            raise foundation.KnowledgeBaseError("QUERY_REFERENCE_UNKNOWN")
    matches = []
    for item in bundle.concepts:
        meta, ext = item.metadata, item.extension
        if any(values and not values.intersection(ext.get(key, [])) for key, values in requested.items()):
            continue
        if (not ext.get("agent_use", {}).get("discoverable", False)
                or meta.get("status") == "deprecated" or ext.get("knowledge_state") in {"revoked", "deprecated"}
                or (item.is_stale and not include_stale)):
            continue
        if type_filter and normalize(str(meta.get("type", ""))) != normalize(type_filter):
            continue
        if tag_filter and normalize(tag_filter) not in {normalize(str(tag)) for tag in meta.get("tags", [])}:
            continue
        fields = (
            ("id", 5.0, item.concept_id), ("title", 8.0, str(meta.get("title", ""))),
            ("description", 5.0, str(meta.get("description", ""))),
            ("tags", 4.0, " ".join(str(tag) for tag in meta.get("tags", []))),
            ("refs", 5.0, " ".join(str(ref) for key in requested for ref in ext.get(key, []))),
            ("body", 1.0, re.sub(r"```.*?```|~~~.*?~~~", "", item.document.body, flags=re.DOTALL)),
        )
        score, reasons = 0.0, set()
        for field, weight, raw in fields:
            text = normalize(raw)
            if query in text:
                score += weight * 2
                reasons.add("query-in-" + field)
            for token in tokens:
                if token in text:
                    score += weight
                    reasons.add("token-in-" + field)
        if score > 0:
            score += {"human-reviewed": 2.0, "machine-confirmed": 1.0}.get(item.trust_tier, 0.0)
            score += max(0, 100 - int(ext.get("context_priority", 100))) / 100.0
            matches.append((item.concept_id, score, tuple(sorted(reasons)), item))
    matches.sort(key=lambda row: (-row[1], int(row[3].extension.get("context_priority", 1000)), row[0]))
    return tuple((row[0], row[1], row[2]) for row in matches[:limit])


def projected(results):
    return tuple((row.concept.concept_id, row.score, row.reasons) for row in results)


class BoundedRetrievalTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bundle = cli.load_bundle(ROOT, as_of=cli._parse_as_of("2026-10-10T00:00:00Z"))

    def corpus(self, count=257, *, mixed=True):
        # A synthetic scorer fixture, not an admitted large CLI bundle or RSS benchmark.
        seed = self.bundle.concepts[0]
        concepts = []
        for number in range(count):
            meta = copy.deepcopy(seed.metadata)
            meta.update(title="ＡＢＣ café 漢字" if number % 2 else "Common e\u0301", type="Goal",
                        description="a a 漢字 ｶﾀｶﾅ", tags=["ＭＩＸ", "漢字"], status="draft")
            ext = meta["kotodama"]
            ext.update(goal_refs=[f"OUT-{number % 3}"], kgi_refs=[f"KGI-{number % 2}"],
                       initiative_refs=[f"INIT-{number % 4}"], context_priority=(number % 7) * 20,
                       knowledge_state="candidate")
            ext["agent_use"]["discoverable"] = True
            if mixed:
                if number % 17 == 0:
                    ext["knowledge_state"] = "revoked"
                if number % 19 == 0:
                    ext["agent_use"]["discoverable"] = False
                if number % 23 == 0:
                    meta["status"] = "deprecated"
            document = dataclasses.replace(seed.document, frontmatter=meta,
                body="共通 漢字 a ＡＢＣ café e\u0301 ㍿ ｶﾀｶﾅ\n```onlyfencedneedle```\n")
            concepts.append(dataclasses.replace(seed, document=document, concept_id=f"fixture/{number:05}",
                trust_tier=("human-reviewed", "machine-confirmed", "unverified")[number % 3],
                is_stale=mixed and number % 13 == 0))
        # Deliberately opposite the final ID tie order and larger than top-100.
        return dataclasses.replace(self.bundle, concepts=tuple(reversed(concepts)))

    def test_exact_full_sort_parity_for_dense_nfkc_and_filtered_queries(self):
        bundle = self.corpus()
        queries = ("漢", "漢字", "a", "a a", "ＡＢＣ", "CAFÉ", "é", "株式会社", "カタカナ",
                   "fixture/00007", "onlyfencedneedle", "no-match-xyz")
        filters = ({}, {"include_stale": True}, {"type_filter": "Ｇｏａｌ", "tag_filter": "mix"},
                   {"goals": ["OUT-1", "OUT-2"], "kgis": ["KGI-1"], "initiatives": ["INIT-3"]},
                   {"type_filter": " "}, {"tag_filter": " "})
        for limit in (1, 100):
            for query in queries:
                for options in filters:
                    with self.subTest(limit=limit, query=query, options=options):
                        expected = full_sort_reference(bundle, query, limit=limit, **options)
                        self.assertEqual(expected, projected(retrieve.query_bundle(bundle, query, limit=limit, **options)))

    def test_known_references_are_checked_beyond_deliverable_matches(self):
        bundle = self.corpus(5, mixed=False)
        hidden = bundle.concepts[0]
        hidden.extension["agent_use"]["discoverable"] = False
        for argument, key in (("goals", "goal_refs"), ("kgis", "kgi_refs"), ("initiatives", "initiative_refs")):
            with self.subTest(argument=argument):
                hidden.extension[key] = ["ONLY-HIDDEN"]
                self.assertEqual((), retrieve.query_bundle(bundle, "no-match", **{argument: ["ONLY-HIDDEN"]}))
                with self.assertRaisesRegex(foundation.KnowledgeBaseError, "QUERY_REFERENCE_UNKNOWN"):
                    retrieve.query_bundle(bundle, "no-match", **{argument: ["UNKNOWN"]})

    def test_limit_keeps_the_previous_integer_index_requirement(self):
        class IndexedLimit:
            def __init__(self, value):
                self.value = value

            def __index__(self):
                return self.value

            def __le__(self, other):
                return self.value <= other

            def __ge__(self, other):
                return self.value >= other

        bundle = self.corpus(5, mixed=False)
        # heapq's n == 1 shortcut would otherwise accept 1.0 unlike list slicing.
        for value in (1.0, 2.0, 100.0):
            with self.subTest(limit=value), self.assertRaises(TypeError):
                retrieve.query_bundle(bundle, "漢", limit=value)
        for value in (1, 100, True, IndexedLimit(1), IndexedLimit(100)):
            with self.subTest(limit=value):
                self.assertEqual(full_sort_reference(bundle, "漢", limit=value),
                                 projected(retrieve.query_bundle(bundle, "漢", limit=value)))
        for value in (0, -1, 101, False):
            with self.subTest(limit=value), self.assertRaisesRegex(foundation.KnowledgeBaseError, "QUERY_LIMIT_INVALID"):
                retrieve.query_bundle(bundle, "漢", limit=value)

    def test_mutable_metadata_is_not_replaced_with_cached_search_fields(self):
        bundle = self.corpus(1, mixed=False)
        concept = bundle.concepts[0]
        self.assertEqual((), retrieve.query_bundle(bundle, "laterneedle"))
        concept.metadata["title"] = "laterneedle"
        concept.metadata["tags"] = ["newtag"]
        concept.extension["goal_refs"] = ["NEW-REF"]
        options = {"tag_filter": "newtag", "goals": ["NEW-REF"]}
        self.assertEqual(full_sort_reference(bundle, "laterneedle", **options),
                         projected(retrieve.query_bundle(bundle, "laterneedle", **options)))
        concept.extension["knowledge_state"] = "revoked"
        self.assertEqual((), retrieve.query_bundle(bundle, "laterneedle", **options))

    def test_filter_normalization_is_once_per_request(self):
        bundle = self.corpus(127, mixed=False)
        normalizer = retrieve._normalized_text
        seen = []
        def normalize(value):
            if value in {"Ｇｏａｌ", "ｍｉｘ"}:
                seen.append(value)
            return normalizer(value)
        with mock.patch.object(retrieve, "_normalized_text", normalize):
            self.assertTrue(retrieve.query_bundle(bundle, "漢", type_filter="Ｇｏａｌ", tag_filter="ｍｉｘ"))
        self.assertCountEqual(["Ｇｏａｌ", "ｍｉｘ"], seen)

    def test_dense_search_retains_only_top_k_match_objects(self):
        bundle = self.corpus(2000, mixed=False)
        result_type = foundation.SearchResult
        for limit in (1, 100):
            with self.subTest(limit=limit):
                live, counts = {}, {"peak": 0, "created": 0}
                def track(*args, **kwargs):
                    result = result_type(*args, **kwargs)
                    identity = id(result)
                    live[identity] = weakref.ref(result, lambda _, identity=identity: live.pop(identity, None))
                    counts["created"] += 1
                    counts["peak"] = max(counts["peak"], len(live))
                    return result
                with mock.patch.object(retrieve, "SearchResult", track):
                    result = retrieve.query_bundle(bundle, "漢", limit=limit)
                self.assertEqual(2000, counts["created"])
                self.assertEqual(limit, len(live))
                self.assertLessEqual(counts["peak"], limit + 2)
                self.assertEqual(full_sort_reference(bundle, "漢", limit=limit), projected(result))
                del result
                gc.collect()
                self.assertEqual({}, live)


if __name__ == "__main__":
    unittest.main()
