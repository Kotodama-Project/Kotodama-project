"""Classify owned SQLite trace queries without depending on SELECT projection.

This is measurement for the repository's simple SELECT statements, not a SQL
parser or an admission check. VM instructions measure scan work independently.
"""
from __future__ import annotations

import re


def normalized_select(sql: str) -> str:
    # Literal contents and comments are not table names. SQLite identifiers may
    # use any of these quote forms; the owned tables contain only word chars.
    sql = re.sub(r"'(?:''|[^'])*'", "?", sql)
    sql = re.sub(r"--[^\n]*|/\*.*?\*/", " ", sql, flags=re.S)
    sql = re.sub(r'["`\[\]]', '', sql).lower()
    return " ".join(sql.split())


def selected_tables(sql: str) -> set[str]:
    normalized = normalized_select(sql)
    if not re.match(r"^(select|with)\b", normalized):
        return set()
    return set(re.findall(r"\b(?:from|join)\s+(?:\w+\.)?(\w+)", normalized))


def attempt_history_select(sql: str) -> bool:
    normalized = normalized_select(sql)
    return "attempts" in selected_tables(sql) and not re.search(
        r"\b(?:count|max|min|sum|avg|total|group_concat)\s*\(", normalized
    )


def global_job_select(sql: str) -> bool:
    # Per-run queries bind run_id to a value. Merely projecting run_id or using
    # IS NOT NULL must not hide a global read behind a field-name match.
    predicates = normalized_select(sql).partition(" where ")[2]
    scoped = re.search(r"\brun_id\s*=\s*\?", predicates)
    return "jobs" in selected_tables(sql) and not scoped
