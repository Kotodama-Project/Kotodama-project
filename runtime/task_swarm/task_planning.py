"""Optional objective projection over an existing owner-bound Task input.

Source spans are checked against the supplied input, not an external history or
knowledge registry. This module creates neither a Task nor execution authority.
"""
from __future__ import annotations

import re

from .protocol import SwarmError, finite, integer


STOP_CONDITIONS = ["cancelled", "binding_changed", "deadline_exceeded"]
OBJECTIVE_KEYS = {"owner_ref", "intent", "references", "constraints", "unknowns",
                  "acceptance", "budget", "stop_conditions", "rollback"}
SPAN_KEYS = {"source_key", "source_revision", "start", "end"}
REFERENCE_PREFIXES = {"goal": "OUT", "kgi": "KGI", "initiative": "INIT"}


def _require(value, code):
    if not value:
        raise SwarmError(code, "Task objective contract refused")


def _shape(value, keys, code):
    _require(isinstance(value, dict) and set(value) == keys, code)


class _Sources:
    def __init__(self, payload):
        self.texts = {(s["key"], s["revision"]): s["text"] for s in payload["sources"]}
        self.latest = {}
        for key, revision in self.texts:
            self.latest[key] = max(revision, self.latest.get(key, revision))

    def span(self, value, *, current=True):
        _shape(value, SPAN_KEYS, "OBJECTIVE_SPAN_INVALID")
        key, revision = value["source_key"], value["source_revision"]
        _require(isinstance(key, str), "OBJECTIVE_SOURCE_UNKNOWN")
        integer(revision, "objective Source revision", minimum=0, maximum=2**53-1)
        source = self.texts.get((key, revision))
        _require(source is not None, "OBJECTIVE_SOURCE_UNKNOWN")
        if current:
            _require(revision == self.latest[key], "OBJECTIVE_SOURCE_STALE")
        start = integer(value["start"], "objective span start", minimum=0, maximum=len(source))
        end = integer(value["end"], "objective span end", minimum=1, maximum=len(source))
        _require(start < end, "OBJECTIVE_SPAN_INVALID")
        return source[start:end]

    def spans(self, values, *, maximum=20):
        _require(isinstance(values, list) and len(values) <= maximum, "OBJECTIVE_SPANS_INVALID")
        result, seen = [], set()
        for value in values:
            text = self.span(value)
            _require(bool(text.strip()) and len(text) <= 1000, "OBJECTIVE_STATEMENT_INVALID")
            result.append(text)
            identity = tuple(value[key] for key in sorted(SPAN_KEYS))
            _require(identity not in seen, "OBJECTIVE_SPAN_DUPLICATE")
            seen.add(identity)
        return result


def validate_objective(payload, binding, *, now):
    """Check v2 data against the input and current Task binding only."""
    objective = payload["objective"]
    _shape(objective, OBJECTIVE_KEYS, "OBJECTIVE_INVALID")
    _require(objective["owner_ref"] == binding["owner_ref"], "OBJECTIVE_OWNER_MISMATCH")
    sources = _Sources(payload)
    intent = objective["intent"]
    _shape(intent, {"original", "replacements"}, "OBJECTIVE_INTENT_INVALID")
    original = intent["original"]
    original_text = sources.span(original, current=False)
    _require(bool(original_text.strip()) and len(original_text) <= 4000, "OBJECTIVE_INTENT_INVALID")
    replacements = intent["replacements"]
    _require(isinstance(replacements, list) and len(replacements) <= 9, "OBJECTIVE_INTENT_INVALID")
    previous = original
    for replacement in replacements:
        replacement_text = sources.span(replacement, current=False)
        _require(bool(replacement_text.strip()) and len(replacement_text) <= 4000, "OBJECTIVE_INTENT_INVALID")
        _require(replacement["source_key"] == original["source_key"] and
                 replacement["source_revision"] > previous["source_revision"], "OBJECTIVE_CORRECTION_ORDER")
        previous = replacement
    # A replacement is a complete current request snapshot, not an ambiguous
    # delta. Old text remains referenced; the worker receives the current text.
    _require(sources.span(previous) == payload["request"], "OBJECTIVE_REQUEST_MISMATCH")
    references = objective["references"]
    _require(isinstance(references, list) and 1 <= len(references) <= 20, "OBJECTIVE_REFERENCES_INVALID")
    seen, has_goal = set(), False
    for reference in references:
        _shape(reference, {"kind", "id", "source"}, "OBJECTIVE_REFERENCE_INVALID")
        kind, identifier = reference["kind"], reference["id"]
        _require(isinstance(kind, str) and kind in REFERENCE_PREFIXES, "OBJECTIVE_REFERENCE_INVALID")
        _require(isinstance(identifier, str) and len(identifier) <= 128 and re.fullmatch(
            REFERENCE_PREFIXES[kind] + r"(?:-[A-Z0-9]+)+", identifier) is not None, "OBJECTIVE_REFERENCE_INVALID")
        _require((kind, identifier) not in seen, "OBJECTIVE_REFERENCE_DUPLICATE")
        seen.add((kind, identifier))
        _require(sources.span(reference["source"]) == identifier, "OBJECTIVE_REFERENCE_MISMATCH")
        has_goal |= kind == "goal"
    _require(has_goal, "OBJECTIVE_GOAL_REQUIRED")
    sources.spans(objective["constraints"])
    sources.spans(objective["unknowns"])
    _require(sources.spans(objective["acceptance"]) == payload["acceptance"], "OBJECTIVE_ACCEPTANCE_MISMATCH")
    budget = objective["budget"]
    _shape(budget, {"attempt_budget", "deadline"}, "OBJECTIVE_BUDGET_INVALID")
    integer(budget["attempt_budget"], "objective attempt budget", minimum=4, maximum=6)
    deadline = finite(budget["deadline"], "objective deadline")
    _require(now < deadline <= binding["expires_at"], "OBJECTIVE_DEADLINE_INVALID")
    _require(objective["stop_conditions"] == STOP_CONDITIONS, "OBJECTIVE_STOP_INVALID")
    _require(objective["rollback"] == "not_applicable_read_only", "OBJECTIVE_ROLLBACK_INVALID")


def objective_criteria(payload):
    """Make supplied constraints and unknowns visible to the existing verifier."""
    objective = payload["objective"]
    sources = _Sources(payload)
    result = {f"O{i+1}": "この制約を満たす: " + text
              for i, text in enumerate(sources.spans(objective["constraints"]))}
    result.update({f"Q{i+1}": "この未知を根拠なく確定値へ置き換えない: " + text
                   for i, text in enumerate(sources.spans(objective["unknowns"]))})
    return result
