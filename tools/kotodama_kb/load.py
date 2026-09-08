from __future__ import annotations

from .foundation import *  # noqa: F401,F403
from .reserved import *  # noqa: F401,F403

def load_bundle(repository_root: Path, *, as_of: dt.datetime | None = None) -> Bundle:
    root = repository_root.resolve()
    bundle_root = root / "knowledge"
    profile_path = bundle_root / "profile.yaml"
    profile_schema_path = root / "schemas" / "kotodama-okf-profile.schema.json"
    concept_schema_path = root / "schemas" / "kotodama-okf-concept.schema.json"
    if not profile_path.is_file():
        raise KnowledgeBaseError(f"missing profile: {profile_path}")
    if not profile_schema_path.is_file() or not concept_schema_path.is_file():
        raise KnowledgeBaseError("missing Kotodama OKF profile schemas")

    profile = _load_yaml(profile_path.read_text(encoding="utf-8"), path=profile_path)
    profile_validator = Draft202012Validator(
        _read_json(profile_schema_path), format_checker=FormatChecker()
    )
    concept_validator = Draft202012Validator(
        _read_json(concept_schema_path), format_checker=FormatChecker()
    )

    issues = _schema_issues(
        validator=profile_validator,
        value=profile,
        path="knowledge/profile.yaml",
        code="PROFILE_SCHEMA",
    )
    issues.extend(_validate_reserved_files(bundle_root))

    as_of = as_of or dt.datetime.now(dt.timezone.utc)
    concept_paths = sorted(
        path
        for path in bundle_root.rglob("*.md")
        if path.name not in {RESERVED_INDEX, RESERVED_LOG}
        and "_generated" not in path.parts
    )

    documents: list[MarkdownDocument] = []
    for path in concept_paths:
        relative = path.relative_to(root).as_posix()
        try:
            document = _parse_frontmatter(path, bundle_root)
        except KnowledgeBaseError as exc:
            issues.append(Issue("error", "FRONTMATTER", relative, str(exc)))
            continue
        documents.append(document)
        issues.extend(
            _schema_issues(
                validator=concept_validator,
                value=document.frontmatter,
                path=relative,
                code="CONCEPT_SCHEMA",
            )
        )

    document_by_resolved_path = {document.path.resolve(): document for document in documents}
    concept_id_to_path: dict[str, str] = {}
    concepts: list[Concept] = []
    allowed_classifications = set(profile.get("allowed_classifications", []))

    for document in documents:
        relative_repo_path = document.path.relative_to(root).as_posix()
        expected_id = _concept_id_for_path(document.path, bundle_root)
        extension = document.frontmatter.get("kotodama")
        if not isinstance(extension, dict):
            extension = {}
        concept_id = str(extension.get("id", expected_id))
        if concept_id != expected_id:
            issues.append(Issue("error", "CONCEPT_ID_PATH", relative_repo_path, f"kotodama.id must be '{expected_id}', got '{concept_id}'"))
        if concept_id in concept_id_to_path:
            issues.append(Issue("error", "DUPLICATE_CONCEPT_ID", relative_repo_path, f"concept id is also used by {concept_id_to_path[concept_id]}"))
        else:
            concept_id_to_path[concept_id] = relative_repo_path

        classification = extension.get("classification")
        if classification not in allowed_classifications:
            issues.append(Issue("error", "CLASSIFICATION", relative_repo_path, f"classification '{classification}' is not allowed in this public bundle"))

        owner_role = extension.get("owner_role")
        reviewer_role = extension.get("reviewer_role")
        if owner_role and owner_role == reviewer_role:
            issues.append(Issue("error", "REVIEW_INDEPENDENCE", relative_repo_path, "owner_role and reviewer_role must differ"))

        generated = document.frontmatter.get("generated")
        generator_actor = generated.get("by") if isinstance(generated, dict) else None
        verifications = _verification_entries(document.frontmatter)
        for verification in verifications:
            if generator_actor and verification.get("by") == generator_actor:
                issues.append(Issue("error", "SELF_VERIFICATION", relative_repo_path, "the generating actor cannot verify the same concept"))

        knowledge_state = extension.get("knowledge_state")
        if knowledge_state == "confirmed" and not verifications:
            issues.append(Issue("error", "CONFIRMED_WITHOUT_VERIFICATION", relative_repo_path, "confirmed knowledge requires an independent verification event"))
        if knowledge_state in {"deprecated", "revoked"} and document.frontmatter.get("status") != "deprecated":
            issues.append(Issue("error", "LIFECYCLE_MISMATCH", relative_repo_path, f"knowledge_state '{knowledge_state}' requires status: deprecated"))
        if knowledge_state not in {"deprecated", "revoked"} and document.frontmatter.get("status") == "deprecated":
            issues.append(Issue("warning", "LIFECYCLE_MISMATCH", relative_repo_path, "status is deprecated but knowledge_state is still active"))

        tags = document.frontmatter.get("tags", [])
        if not isinstance(tags, list):
            tags = []
        stale_after_value = document.frontmatter.get("stale_after")
        is_stale = False
        if isinstance(stale_after_value, str):
            try:
                stale_at = _parse_datetime(stale_after_value, field="stale_after", path=relative_repo_path)
                is_stale = as_of >= stale_at
            except KnowledgeBaseError as exc:
                issues.append(Issue("error", "STALE_AFTER", relative_repo_path, str(exc)))
        if is_stale:
            level = "warning"
            marker = "critical " if set(tags) & set(profile.get("quality", {}).get("critical_tags", [])) else ""
            issues.append(Issue(level, "STALE_CONCEPT", relative_repo_path, f"{marker}concept is stale at {as_of.isoformat()}"))

        if not verifications:
            issues.append(Issue("warning", "UNVERIFIED_CONCEPT", relative_repo_path, "no independent verification event is recorded"))
        if knowledge_state == "conflicted":
            issues.append(Issue("warning", "UNRESOLVED_CONFLICT", relative_repo_path, "concept is explicitly marked conflicted"))
        if knowledge_state == "unknown":
            issues.append(Issue("warning", "UNKNOWN_KNOWLEDGE", relative_repo_path, "concept contains an explicit knowledge gap"))

        source_entries = document.frontmatter.get("sources", [])
        source_resources: list[str] = []
        source_ids: set[str] = set()
        if not isinstance(source_entries, list):
            source_entries = []
        for index, source in enumerate(source_entries):
            if not isinstance(source, dict):
                continue
            source_id = source.get("id")
            if source_id:
                source_id = str(source_id)
                if source_id in source_ids:
                    issues.append(Issue("error", "DUPLICATE_SOURCE_ID", relative_repo_path, f"duplicate sources[].id: {source_id}"))
                source_ids.add(source_id)
            resource = source.get("resource")
            if not isinstance(resource, str) or not resource:
                continue
            source_resources.append(resource)
            resolved_source = _resolve_source_resource(
                source_path=document.path,
                resource=resource,
                repository_root=root,
                bundle_root=bundle_root,
            )
            if resolved_source == Path("/__OUTSIDE_REPOSITORY__"):
                issues.append(Issue("error", "SOURCE_PATH_ESCAPE", relative_repo_path, f"source leaves repository: {resource}"))
            elif resolved_source is not None and not resolved_source.exists():
                level = "error" if "sha256" in source or profile.get("quality", {}).get("fail_on_missing_repository_sources", True) else "warning"
                issues.append(Issue(level, "MISSING_SOURCE", relative_repo_path, f"source does not exist: {resource}"))
            elif "sha256" in source:
                # Optional producer pin for local source bytes. Remote sources
                # must first be captured by an authorized adapter; no network here.
                expected = source["sha256"]
                if not isinstance(expected, str) or not re.fullmatch(r"[0-9a-f]{64}", expected):
                    issues.append(Issue("error", "SOURCE_DIGEST_INVALID", relative_repo_path, "source sha256 must be 64 lowercase hex characters"))
                elif resolved_source is None or not resolved_source.is_file():
                    issues.append(Issue("error", "SOURCE_DIGEST_UNAVAILABLE", relative_repo_path, "source sha256 requires a repository-local file"))
                else:
                    try:
                        actual = hashlib.sha256(resolved_source.read_bytes()).hexdigest()
                    except OSError:
                        issues.append(Issue("error", "SOURCE_DIGEST_UNAVAILABLE", relative_repo_path, "cannot read pinned source"))
                    else:
                        if actual != expected:
                            issues.append(Issue("error", "SOURCE_DIGEST_MISMATCH", relative_repo_path, f"pinned source changed: {resource}; review the concept before rebinding"))

        used_footnotes = set(FOOTNOTE_RE.findall(_without_code_fences(document.body)))
        defined_footnotes = set(
            re.findall(r"^\[\^([A-Za-z0-9._-]+)\]:", document.body, flags=re.MULTILINE)
        )
        for footnote in sorted(used_footnotes):
            if footnote not in source_ids:
                issues.append(Issue("error", "UNKNOWN_SOURCE_FOOTNOTE", relative_repo_path, f"footnote '{footnote}' has no matching sources[].id"))
            if footnote not in defined_footnotes:
                issues.append(Issue("warning", "UNDEFINED_FOOTNOTE", relative_repo_path, f"footnote '{footnote}' has no body definition"))

        targets = _markdown_targets(document.body)
        resolved_concept_links: list[str] = []
        for target in targets:
            resolved = _resolve_markdown_target(
                source_path=document.path,
                target=target,
                repository_root=root,
                bundle_root=bundle_root,
            )
            if resolved == Path("/__OUTSIDE_REPOSITORY__"):
                issues.append(Issue("error", "LINK_PATH_ESCAPE", relative_repo_path, f"link leaves repository: {target}"))
                continue
            if resolved is None:
                continue
            if not resolved.exists():
                level = "error" if profile.get("quality", {}).get("fail_on_broken_internal_links", True) else "warning"
                issues.append(Issue(level, "BROKEN_LINK", relative_repo_path, f"link target does not exist: {target}"))
                continue
            linked_doc = document_by_resolved_path.get(resolved.resolve())
            if linked_doc is not None:
                linked_id = _concept_id_for_path(linked_doc.path, bundle_root)
                resolved_concept_links.append(linked_id)

        concepts.append(
            Concept(
                document=document,
                concept_id=concept_id,
                links=targets,
                resolved_concept_links=tuple(sorted(set(resolved_concept_links))),
                source_resources=tuple(source_resources),
                content_sha256=hashlib.sha256(document.raw.encode("utf-8")).hexdigest(),
                trust_tier=_trust_tier(document.frontmatter),
                stale_after=stale_after_value if isinstance(stale_after_value, str) else None,
                is_stale=is_stale,
            )
        )

    index_targets: list[str] = []
    indexed_concepts: set[str] = set()
    generated_paths = {
        (root / relative).resolve()
        for relative in profile.get("generated_outputs", {}).values()
        if isinstance(relative, str)
    }
    for index_path in sorted(bundle_root.rglob(RESERVED_INDEX)):
        raw = index_path.read_text(encoding="utf-8")
        for target in _markdown_targets(raw):
            index_targets.append(target)
            resolved = _resolve_markdown_target(
                source_path=index_path,
                target=target,
                repository_root=root,
                bundle_root=bundle_root,
            )
            if resolved == Path("/__OUTSIDE_REPOSITORY__"):
                issues.append(Issue("error", "INDEX_PATH_ESCAPE", index_path.relative_to(root).as_posix(), f"index link leaves repository: {target}"))
                continue
            if resolved is None:
                continue
            if not resolved.exists():
                if resolved.resolve() in generated_paths:
                    issues.append(Issue("warning", "GENERATED_OUTPUT_MISSING", index_path.relative_to(root).as_posix(), f"generated projection is missing and can be rebuilt: {target}"))
                    continue
                level = "error" if profile.get("quality", {}).get("fail_on_broken_internal_links", True) else "warning"
                issues.append(Issue(level, "BROKEN_INDEX_LINK", index_path.relative_to(root).as_posix(), f"index link target does not exist: {target}"))
                continue
            linked_doc = document_by_resolved_path.get(resolved.resolve())
            if linked_doc is not None:
                indexed_concepts.add(_concept_id_for_path(linked_doc.path, bundle_root))

    linked_concepts = {
        linked_id for concept in concepts for linked_id in concept.resolved_concept_links
    }
    for concept in concepts:
        if concept.concept_id not in indexed_concepts and concept.concept_id not in linked_concepts:
            issues.append(Issue("error", "ORPHAN_CONCEPT", concept.document.path.relative_to(root).as_posix(), "concept is not reachable from an index or another concept"))

    return Bundle(
        root=root,
        bundle_root=bundle_root,
        profile=profile,
        concepts=tuple(sorted(concepts, key=lambda item: item.concept_id)),
        issues=tuple(sorted(set(issues))),
        index_links=tuple(index_targets),
    )



__all__ = [name for name in globals() if not name.startswith("__")]
