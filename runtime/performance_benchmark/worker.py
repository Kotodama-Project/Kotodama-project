"""One fixed local fixture in a fresh child; never dispatches a model."""
from pathlib import Path
from importlib import metadata
import json
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "runtime"))
from performance_benchmark.runner import VERSION, code_snapshot, digest  # noqa: E402


def peak_rss():
    if sys.platform not in {"linux", "darwin"}:
        return None, "UNSUPPORTED_PLATFORM"
    try:
        import resource
        value = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        measured = int(value * (1024 if sys.platform == "linux" else 1))
        return (measured, None) if measured > 0 else (None, "COUNTER_UNAVAILABLE")
    except (ImportError, ValueError, OSError, OverflowError):
        return None, "COUNTER_UNAVAILABLE"


def dependency_versions():
    versions = {}
    for name in ("jsonschema", "referencing", "PyYAML", "mcp", "psutil"):
        try:
            versions[name] = metadata.version(name)
        except metadata.PackageNotFoundError:
            versions[name] = None
    return versions


def run():
    pinned = code_snapshot()
    try:
        import task_swarm_benchmark as fixture
    except ImportError:
        return {"schema": VERSION, "status": "REFUSED", "code": "DEPENDENCIES_UNAVAILABLE"}
    profile = fixture.PROFILES[0]
    original_sources = fixture.sources
    observed_pages = []
    # Observe the exact generated input used by the existing fixture, not a
    # second generation. This hook exists only in this dedicated child process.
    def capture_sources(selected):
        pages = original_sources(selected)
        observed_pages.append(pages)
        return pages
    fixture.sources = capture_sources
    try:
        report = fixture.report((profile,))
    except Exception:
        return {"schema": VERSION, "status": "FAIL", "code": "FIXTURE_FAILED"}
    finally:
        fixture.sources = original_sources
    if not observed_pages or any(pages != observed_pages[0] for pages in observed_pages[1:]):
        return {"schema": VERSION, "status": "FAIL", "code": "FIXTURE_FAILED"}
    inputs = {"fixture": "swarm-short", "profile": {"name": profile.name, "pages": profile.pages,
              "records_per_page": profile.records_per_page, "retained_messages": profile.retained_messages},
              "objective": fixture.OBJECTIVE, "pages": observed_pages[0]}
    if code_snapshot() != pinned:
        return {"schema": VERSION, "status": "FAIL", "code": "CODE_CHANGED_DURING_RUN"}
    verification = {key: value for key, value in report["profiles"][0].items() if key != "elapsed_seconds"}
    semantic = {"verification": verification, "status": report["status"],
                "model_called": report["model_called"], "code_digest": report["code_digest"]}
    rss, rss_missing = peak_rss()
    return {"schema": VERSION, "status": report["status"], "fixture": "swarm-short",
            "model_called": report["model_called"], "input_digest": digest(inputs),
            "result_digest": digest(semantic), "code_digest": pinned["digest"],
            "sqlite_version": report["sqlite_version"], "peak_rss_bytes": rss, "peak_rss_missing": rss_missing,
            "dependency_versions": dependency_versions(),
            "verification": verification}


if __name__ == "__main__":
    try:
        value = run()
    except Exception:
        value = {"schema": VERSION, "status": "FAIL", "code": "FIXTURE_FAILED"}
    print(json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False))
    raise SystemExit(0 if value["status"] == "PASS" else 1)
