---
okf_version: "0.2"
---

# Kotodama project knowledge

This bundle is a **public-safe, rebuildable knowledge projection** for humans and agents. It is not the Human Intent source of truth, the Task ledger, an access-control authority, a deployment record, or a publication decision. Open the cited source before using a concept for a consequential decision.

## Project

* [Project goal](project/goal.md) - The source-backed outcome this project is trying to advance.
* [Current state](project/current-state.md) - What this branch establishes and what remains unproved.
* [現在の候補と次の作業](project/catchup.md) - 2026-09-09のGitHub観測に束縛した再開検証。期限と出典変更を確認する。
* [Success model](project/success-model.md) - Goal, KGI, KPI and candidate knowledge-quality measurements without treating proxies as outcomes.

## Governance

* [Authority boundaries](governance/authority-boundaries.md) - What this bundle may describe and what it can never authorize.
* [Knowledge lifecycle](governance/knowledge-lifecycle.md) - Candidate, verification, conflict, staleness, deprecation and invalidation handling.
* [Agent responsibilities](governance/agent-responsibilities.md) - Bounded responsibilities for the librarian, auditor, coordinator and builder.

## Operations

* [Refresh loop](operations/refresh-loop.md) - Source change to affected-concept rebuild, independent review and readback.
* [Retrieval quality](operations/retrieval-quality.md) - How lexical, graph and future embedding retrieval are evaluated against required context.
* [Agent context assembly](operations/agent-context.md) - Progressive disclosure for producing bounded working context without replacing authority.

## Machine-readable projections

* [`_generated/catalog.json`](_generated/catalog.json) - Deterministic concept catalog.
* [`_generated/graph.json`](_generated/graph.json) - Deterministic relationship and provenance graph.
* [`profile.yaml`](profile.yaml) - Kotodama's stricter producer profile layered on OKF v0.2.
