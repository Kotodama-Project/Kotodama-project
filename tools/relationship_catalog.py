"""Read-only synthetic relationship projection, shared by people and agent Context."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import html
import json
import os
from pathlib import Path
import stat

from jsonschema import Draft202012Validator, FormatChecker

ROOT = Path(__file__).resolve().parents[1]
KINDS = {"person": "人", "organization": "組織", "relationship": "関係", "activity": "活動"}


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("DUPLICATE_FIELD")
        result[key] = value
    return result


def identity(record):
    return "::".join(record[key] for key in ("tenant", "connection", "provider", "object", "record_id"))


def timestamp(value):
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.utcoffset() is None:
        raise ValueError("TIMEZONE_REQUIRED")
    return result


def validate(document):
    schema = json.loads((ROOT / "schemas/relationship-catalog.schema.json").read_text(encoding="utf-8"))
    if next(Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(document), None):
        raise ValueError("CATALOG_INVALID")
    for record in document["records"]:
        timestamp(record["expires_at"])


def project(document, *, tenant, actor, purpose, now):
    validate(document)
    if now.utcoffset() is None:
        raise ValueError("TIMEZONE_REQUIRED")
    grouped = {}
    for record in document["records"]:
        if record["tenant"] == tenant:
            grouped.setdefault(identity(record), []).append(record)
    visible = {}
    for key, rows in grouped.items():
        revision = max(row["revision"] for row in rows)
        latest = {canonical(row): row for row in rows if row["revision"] == revision}
        # Conflict, deletion and revocation suppress old versions before ACL checks.
        if len(latest) != 1:
            continue
        row = next(iter(latest.values()))
        if row["state"] != "active" or timestamp(row["expires_at"]) <= now:
            continue
        if actor not in row["readers"] or purpose not in row["purposes"]:
            continue
        visible[key] = {"id": key, **row}
    # Remove relationships/activities with unreadable ends, including transitively.
    while True:
        invalid = {key for key, row in visible.items() if any(link not in visible for link in row["links"])}
        if not invalid:
            break
        visible = {key: row for key, row in visible.items() if key not in invalid}
    records = [visible[key] for key in sorted(visible)]
    return {"kind": "kotodama/relationship-projection/v1", "synthetic": True,
            "tenant": tenant, "actor": actor, "purpose": purpose,
            "as_of": now.astimezone(timezone.utc).isoformat(), "records": records,
            "context_digest": hashlib.sha256(canonical(records).encode("utf-8")).hexdigest(),
            "connection_status": "FIXTURE_ONLY_NOT_CONNECTED", "provider_verified": False,
            "public_beta": "NO_GO_UNPUBLISHED"}


def map_salesforce_fixture(rows, *, profile, object_name, entity_type, field_map):
    """Map selected synthetic records only; no OAuth, URL, query, or write API."""
    if profile.get("synthetic") is not True or not isinstance(rows, list) or len(rows) > 512:
        raise ValueError("SYNTHETIC_MAPPING_REQUIRED")
    if object_name not in profile["objects"] or set(field_map) - set(profile["objects"][object_name]):
        raise ValueError("MAPPING_SCOPE_REFUSED")
    records = []
    for row in rows:
        # revision/expires are receipt metadata; fields are explicitly selected data.
        data = row["fields"]
        if set(data) - set(profile["objects"][object_name]) or "Id" not in data:
            raise ValueError("MAPPING_SCOPE_REFUSED")
        mapped = {target: data[source] for source, target in field_map.items() if source in data}
        if "label" not in mapped:
            raise ValueError("MAPPING_LABEL_REQUIRED")
        records.append({"tenant": profile["tenant"], "connection": profile["connection"],
                        "provider": "salesforce", "object": object_name, "record_id": data["Id"],
                        "source_revision": row["source_revision"], "revision": row["revision"],
                        "entity_type": entity_type, "label": mapped.pop("label"), "fields": mapped,
                        "owner": profile["owner"], "readers": profile["readers"], "purposes": profile["purposes"],
                        "expires_at": row["expires_at"], "state": row["state"], "links": []})
    document = {"kind": "kotodama/relationship-catalog/v1", "synthetic": True, "records": records}
    validate(document)
    return document


def render(projection):
    escape = lambda value: html.escape(str(value), quote=True)
    cards = []
    for row in projection["records"]:
        anchor = hashlib.sha256(row["id"].encode()).hexdigest()
        fields = "".join(f"<dt>{escape(key)}</dt><dd>{escape(value)}</dd>" for key, value in row["fields"].items())
        links = "".join(f'<li><a href="#{hashlib.sha256(link.encode()).hexdigest()}">{escape(link)}</a></li>' for link in row["links"])
        cards.append(f'<article id="{anchor}"><small>{KINDS[row["entity_type"]]} · revision {row["revision"]}</small><h2>{escape(row["label"])}</h2><dl>{fields}</dl><details><summary>出典・閲覧範囲</summary><p>{escape(row["id"])}<br>source revision: {escape(row["source_revision"])}<br>owner: {escape(row["owner"])}<br>期限: {escape(row["expires_at"])}</p><ul>{links}</ul></details></article>')
    return '<!doctype html><html lang="ja"><meta charset="utf-8"><meta name="viewport" content="width=device-width"><meta http-equiv="Content-Security-Policy" content="default-src \'none\'; style-src \'unsafe-inline\'"><title>人・組織・関係</title><style>body{font:16px/1.7 system-ui;background:#f3f5f6;color:#182632;max-width:980px;margin:40px auto;padding:0 24px}header{margin-bottom:24px}main{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:16px}article{padding:24px;background:white;border:1px solid #dce3e7;border-radius:16px}h1,h2{line-height:1.3}small{color:#486674}dt{font-weight:600}dd{margin:0 0 12px}details p,li{overflow-wrap:anywhere}a{color:#176f85}.tag{background:#dceef1;padding:5px 10px;border-radius:6px}</style><header><span class="tag">架空データ · 読み取り専用 · 外部接続なし</span><h1>人・組織・関係</h1><p>同じ出典と閲覧範囲から、人向け一覧とagent Contextを生成します。</p><p>表示時刻: ' + escape(projection["as_of"]) + '</p></header><main>' + ("".join(cards) or '<p>この閲覧範囲で表示できる現行recordはありません。</p>') + '</main></html>'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    for field in ("tenant", "actor", "purpose"):
        parser.add_argument("--" + field, required=True)
    parser.add_argument("--at", default=None)
    parser.add_argument("--format", choices=("json", "html"), default="json")
    args = parser.parse_args()
    try:
        descriptor = os.open(args.input, os.O_RDONLY | getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0))
        with os.fdopen(descriptor, "rb") as stream:
            if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
                raise ValueError("REGULAR_INPUT_REQUIRED")
            raw = stream.read(4 * 1024 * 1024 + 1)
        if len(raw) > 4 * 1024 * 1024:
            raise ValueError("INPUT_TOO_LARGE")
        result = project(json.loads(raw, object_pairs_hook=unique_object), tenant=args.tenant, actor=args.actor, purpose=args.purpose,
                         now=timestamp(args.at) if args.at else datetime.now(timezone.utc))
    except (OSError, ValueError, TypeError, KeyError, RecursionError):
        print('{"status":"REFUSED","provider_verified":false}')
        return 1
    print(render(result) if args.format == "html" else json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
