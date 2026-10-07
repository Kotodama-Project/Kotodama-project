"""Closed model output schemas for the bounded Task-run controller."""
from .task_contract import WORK_JOBS, criteria


def obj(properties):
    return {"type": "object", "properties": properties, "required": list(properties), "additionalProperties": False}


def string(limit):
    return {"type": "string", "minLength": 1, "maxLength": limit}


def report_schema(job):
    evidence = obj({"source_key": {"type": "string", "pattern": "^[a-f0-9]{64}$"},
                    "source_revision": {"type": "integer", "minimum": 0},
                    "start": {"type": "integer", "minimum": 0}, "end": {"type": "integer", "minimum": 1},
                    "quote": string(12000)})
    claim = obj({"text": string(3000), "status": {"type": "string", "enum": ["supported", "inference", "unknown"]},
                 "evidence": {"type": "array", "items": evidence, "maxItems": 10}})
    return obj({"job_id": {"type": "string", "const": job}, "summary": string(6000),
                "claims": {"type": "array", "items": claim, "minItems": 1, "maxItems": 30},
                "conflicts": {"type": "array", "items": string(1000), "maxItems": 20}})


def review_schema(payload):
    evidence = obj({"job_id": {"type": "string", "enum": list(WORK_JOBS)},
                    "claim_index": {"type": "integer", "minimum": 0, "maximum": 29}})
    validation = obj({"criterion_id": {"type": "string", "enum": list(criteria(payload))},
                      "status": {"type": "string", "enum": ["passed", "failed", "blocked", "not_run"]},
                      "evidence": {"type": "array", "items": evidence, "maxItems": 30},
                      "gap_reason": {"type": ["string", "null"], "maxLength": 1000}})
    return obj({"report_digests": obj({job: {"type": "string", "pattern": "^[a-f0-9]{64}$"} for job in WORK_JOBS}),
                "validations": {"type": "array", "items": validation,
                                "minItems": len(criteria(payload)), "maxItems": len(criteria(payload))}})
