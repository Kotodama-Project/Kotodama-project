"""Bounded child views of an already validated, immutable v2 Task input.

The caller retains the parent binding, validates its current owner/source scope,
and binds the returned view to the dispatched plan. This pure projection neither
loads new sources nor grants execution, publication, or knowledge adoption.
"""
from __future__ import annotations

import hashlib
import json
import re

from .protocol import canonical, digest, digest_ref
from .task_contract import MAX_INPUT_BYTES, WORK_JOBS, require, shape, validate_report
from .task_planning import SPAN_KEYS, _Sources


MAX_SELECTED_SPANS = 32
MAX_VIEW_SPANS = 122  # At most 90 objective spans plus 32 selected spans.
MAX_VIEW_BYTES = MAX_INPUT_BYTES
_RECORD_KEYS = SPAN_KEYS | {"text", "sha256"}
_VIEW_KEYS = {"version", "task_id", "revision", "parent_input_digest", "plan_digest",
              "previous_critic_digest", "job_id", "request", "acceptance", "objective",
              "spans", "view_digest"}


def _job_id(value):
    require(isinstance(value, str) and re.fullmatch(r"[a-z][a-z0-9_-]{0,63}", value)
            is not None, "CLOSED_LOOP_JOB_INVALID")
    return value


def _mandatory(payload):
    require(isinstance(payload, dict) and type(payload.get("version")) is int and
            payload["version"] == 2 and isinstance(payload.get("objective"), dict),
            "CLOSED_LOOP_OBJECTIVE_REQUIRED")
    objective = payload["objective"]
    # Original intent and its correction history deliberately keep old revisions.
    result = [(objective["intent"]["original"], False)]
    result.extend((span, False) for span in objective["intent"]["replacements"])
    result.extend((item["source"], True) for item in objective["references"])
    for field in ("constraints", "unknowns", "acceptance"):
        result.extend((span, True) for span in objective[field])
    return result


def _identity(span):
    return tuple(span[key] for key in ("source_key", "source_revision", "start", "end"))


def derive_child_view(parent_payload, job_id, selected_spans, *, plan_digest,
                      previous_critic_digest=None):
    """Render required objective spans and explicit current-source selections.

    ``parent_payload`` must have passed ``validate_input`` in the caller. Source
    offsets remain Unicode codepoint offsets into that full parent; selection is
    not another Task input. View and plan digests are bindings, not owner grants.
    """
    _job_id(job_id)
    digest_ref(plan_digest, "plan digest")
    if previous_critic_digest is not None:
        digest_ref(previous_critic_digest, "previous critic digest")
    require(isinstance(selected_spans, list) and len(selected_spans) <= MAX_SELECTED_SPANS,
            "CLOSED_LOOP_SELECTION_LIMIT")
    mandatory = _mandatory(parent_payload)
    sources = _Sources(parent_payload)
    records, seen = [], set()
    for span, current in [*mandatory, *((span, True) for span in selected_spans)]:
        text = sources.span(span, current=current)
        identity = _identity(span)
        if identity not in seen:
            records.append({**span, "text": text,
                            "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest()})
            seen.add(identity)
    require(len(records) <= MAX_VIEW_SPANS, "CLOSED_LOOP_SELECTION_LIMIT")
    view = {"version": 1, "task_id": parent_payload["task_id"],
            "revision": parent_payload["revision"], "parent_input_digest": digest(parent_payload),
            "plan_digest": plan_digest, "previous_critic_digest": previous_critic_digest,
            "job_id": job_id, "request": parent_payload["request"],
            "acceptance": parent_payload["acceptance"], "objective": parent_payload["objective"],
            "spans": records}
    view["view_digest"] = digest(view)
    encoded = canonical(view).encode("utf-8")
    require(len(encoded) <= MAX_VIEW_BYTES, "CLOSED_LOOP_CONTEXT_LIMIT")
    return json.loads(encoded)


def validate_child_view(view, payload, *, job_id, plan_digest, previous_critic_digest):
    """Rebuild a view and match its caller-pinned job and plan identity.

    The caller must separately bind these bytes to the stored dispatch. A
    self-consistent projection alone does not prove what a worker received.
    """
    shape(view, _VIEW_KEYS, "CLOSED_LOOP_VIEW_INVALID")
    require(isinstance(view["spans"], list) and len(view["spans"]) <= MAX_VIEW_SPANS,
            "CLOSED_LOOP_VIEW_INVALID")
    sources = _Sources(payload)
    mandatory = {_identity(span) for span, _current in _mandatory(payload)}
    selected = []
    for record in view["spans"]:
        shape(record, _RECORD_KEYS, "CLOSED_LOOP_VIEW_INVALID")
        span = {key: record[key] for key in SPAN_KEYS}
        sources.span(span, current=False)
        if _identity(span) not in mandatory:
            selected.append(span)
    expected = derive_child_view(payload, view["job_id"], selected,
                                 plan_digest=view["plan_digest"],
                                 previous_critic_digest=view["previous_critic_digest"])
    require(canonical(view) == canonical(expected), "CLOSED_LOOP_VIEW_MISMATCH")
    require(view["job_id"] == job_id and view["plan_digest"] == plan_digest
            and view["previous_critic_digest"] == previous_critic_digest,
            "CLOSED_LOOP_VIEW_BINDING")
    return expected


def validate_report_in_view(report, view, payload, *, allowed_jobs=WORK_JOBS):
    """Validate a report against the parent and its exact delivered span view.

    The coordinator must compare this view with its stored dispatch binding;
    this function cannot authenticate a caller-supplied plan or critic digest.
    An evidence span must fit within one delivered span, including for inference
    and unknown claims. It cannot bridge separately delivered pieces of text.
    """
    shape(view, _VIEW_KEYS, "CLOSED_LOOP_VIEW_INVALID")
    validate_child_view(view, payload, job_id=view["job_id"], plan_digest=view["plan_digest"],
                        previous_critic_digest=view["previous_critic_digest"])
    checked = validate_report(report, view["job_id"], payload, allowed_jobs=allowed_jobs)
    for claim in checked["claims"]:
        for evidence in claim["evidence"]:
            require(any(record["source_key"] == evidence["source_key"] and
                        record["source_revision"] == evidence["source_revision"] and
                        record["start"] <= evidence["start"] < evidence["end"] <= record["end"]
                        for record in view["spans"]), "REPORT_EVIDENCE_NOT_DELIVERED")
    return checked
