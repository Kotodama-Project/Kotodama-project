#!/usr/bin/env python3
"""Build and verify exact public Python candidate artifacts; never upload them."""
from __future__ import annotations

import argparse
import base64
import configparser
import csv
from email.parser import BytesParser
import gzip
import hashlib
import importlib.metadata
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tarfile
import time
import tomllib
import zipfile

ROOT = Path(__file__).resolve().parents[1]
MODULES = {"__init__", "cancellation", "codex", "confidential", "mcp_server", "owner_file", "payload_budget", "payloads", "privacy", "protocol", "sqlite_work", "state", "task_backend", "task_contract", "task_planning", "task_runner", "task_schemas", "transport"}
PUBLIC = {"__init__.py", "__main__.py", "cli.py"}
SOURCE_PATHS = {"LICENSE", "MANIFEST.in", "pyproject.toml", "python/README.md"} | {"python/src/kotodama_core/" + name for name in PUBLIC} | {"runtime/task_swarm/" + name + ".py" for name in MODULES}
BUILDER_PATHS = {"tools/build_python_candidate.py", "tools/build_release_sbom.py", "tools/record_python_candidate_execution.py",
                 "requirements-ci.txt", "requirements-package-ci.txt", "requirements-task-swarm-ci.txt",
                 ".github/workflows/python-package-candidate.yml", ".github/workflows/release.yml", "python/package_probe.py"}
SDIST_META = {"PKG-INFO", "setup.cfg", "kotodama_core.egg-info/SOURCES.txt"}
WHEEL_META = {"licenses/LICENSE", "METADATA", "WHEEL", "entry_points.txt", "top_level.txt", "RECORD"}


def require(condition, reason):
    if not condition:
        raise ValueError(reason)


def git(*args):
    return subprocess.run(["git", "--no-lazy-fetch", "-c", "core.fsmonitor=false", "-C", str(ROOT), *args], check=True, capture_output=True, timeout=30).stdout


def source_snapshot():
    commit = git("rev-parse", "HEAD").decode().strip()
    tree = git("rev-parse", "HEAD^{tree}").decode().strip()
    epoch = int(git("show", "-s", "--format=%ct", "HEAD"))
    files = pinned_files(commit, SOURCE_PATHS)
    builder_files = pinned_files(commit, BUILDER_PATHS)
    return commit, tree, epoch, files, builder_files


def pinned_files(commit, paths):
    files = {}
    for name in sorted(paths):
        raw = git("show", f"{commit}:{name}")
        require(raw == (ROOT / name).read_bytes(), "SOURCE_DIFFERS_FROM_COMMIT")
        require(len(raw) <= 1024 * 1024 and b"\r" not in raw, "SOURCE_BYTES_INVALID")
        files[name] = raw
    return files


def archive_contents(path, version):
    prefix = f"kotodama_core-{version}"
    if path.suffix == ".whl":
        with zipfile.ZipFile(path) as archive:
            entries = archive.infolist()
            require(len(entries) <= 100 and sum(row.file_size for row in entries) <= 4 * 1024 * 1024, "ARCHIVE_TOO_LARGE")
            require(all(not row.is_dir() for row in entries), "UNEXPECTED_WHEEL_DIRECTORY")
            names = [row.filename for row in entries]
            expected = {"kotodama_core/" + name for name in PUBLIC} | {"kotodama_core/task_swarm/" + name + ".py" for name in MODULES} | {prefix + ".dist-info/" + name for name in WHEEL_META}
            require(set(names) == expected and len(names) == len(expected), "WHEEL_FILE_ALLOWLIST")
            result = {name: archive.read(name) for name in names}
        config = configparser.ConfigParser()
        config.read_string(result[prefix + ".dist-info/entry_points.txt"].decode())
        require(config.sections() == ["console_scripts"] and dict(config["console_scripts"]) == {"kotodama-core": "kotodama_core.cli:main"}, "CONSOLE_SCRIPT_COLLISION")
        record_name = prefix + ".dist-info/RECORD"
        rows = list(csv.reader(io.StringIO(result[record_name].decode())))
        require(len(rows) == len(result) and {row[0] for row in rows} == set(result), "WHEEL_RECORD_PATHS")
        for name, encoded, size in rows:
            if name == record_name:
                require(encoded == size == "", "WHEEL_RECORD_SELF")
            else:
                expected_digest = "sha256=" + base64.urlsafe_b64encode(hashlib.sha256(result[name]).digest()).decode().rstrip("=")
                require(encoded == expected_digest and size == str(len(result[name])), "WHEEL_RECORD_HASH")
        metadata = result[prefix + ".dist-info/METADATA"]
    else:
        with tarfile.open(path, "r:gz") as archive:
            entries = archive.getmembers()
            require(len(entries) <= 100 and sum(row.size for row in entries) <= 4 * 1024 * 1024, "ARCHIVE_TOO_LARGE")
            require(all(row.isdir() or row.isfile() for row in entries), "SDIST_LINK_REFUSED")
            require(all(row.name == prefix or row.name.startswith(prefix + "/") for row in entries), "SDIST_PREFIX")
            names = [row.name[len(prefix) + 1:] for row in entries if row.isfile()]
            expected = SOURCE_PATHS | SDIST_META
            require(set(names) == expected and len(names) == len(expected), "SDIST_FILE_ALLOWLIST")
            result = {row.name: archive.extractfile(row).read() for row in entries if row.isfile()}
        metadata = result[prefix + "/PKG-INFO"]
    parsed = BytesParser().parsebytes(metadata)
    require(parsed["Name"] == "kotodama-core" and parsed["Version"] == version, "PACKAGE_IDENTITY")
    require(parsed["License-Expression"] == "MIT", "PACKAGE_LICENSE")
    dependencies = set(parsed.get_all("Requires-Dist", []))
    require(dependencies == {'mcp==2.2.0; extra == "swarm"', 'psutil==7.2.2; extra == "swarm"'}, "PACKAGE_DEPENDENCIES")
    return result


def verify_source_contents(contents, files, version, *, wheel):
    prefix = f"kotodama_core-{version}"
    for name, raw in files.items():
        if wheel:
            if name.startswith("python/src/"):
                target = name.removeprefix("python/src/")
            elif name.startswith("runtime/task_swarm/"):
                target = name.replace("runtime/", "kotodama_core/", 1)
            elif name == "LICENSE":
                target = prefix + ".dist-info/licenses/LICENSE"
            else:
                continue
        else:
            target = prefix + "/" + name
        require(contents[target] == raw, "ARCHIVE_SOURCE_MISMATCH")


def normalize_metadata(contents, *, wheel):
    result = dict(contents)
    for name, data in contents.items():
        generated = name.endswith(".dist-info/METADATA") if wheel else name.endswith(("/PKG-INFO", "/setup.cfg"))
        if generated:
            result[name] = data.replace(b"\r\n", b"\n")
    if wheel:
        record = next(name for name in contents if name.endswith(".dist-info/RECORD"))
        text = io.StringIO(newline="")
        writer = csv.writer(text, lineterminator="\n")
        for name, data in sorted(result.items()):
            if name == record:
                writer.writerow([name, "", ""])
            else:
                encoded = "sha256=" + base64.urlsafe_b64encode(hashlib.sha256(data).digest()).decode().rstrip("=")
                writer.writerow([name, encoded, str(len(data))])
        result[record] = text.getvalue().encode("utf-8")
    return result


def normalize_archive(path, contents, epoch, *, wheel):
    # Canonical member data is supplied separately; this fixes archive headers.
    output = io.BytesIO()
    if wheel:
        stamp = time.gmtime(max(epoch, 315532800))[:6]
        with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
            for name, data in sorted(contents.items()):
                entry = zipfile.ZipInfo(name, date_time=stamp)
                entry.create_system = 3
                entry.external_attr = 0o100644 << 16
                entry.compress_type = zipfile.ZIP_DEFLATED
                archive.writestr(entry, data, compresslevel=9)
    else:
        with gzip.GzipFile(fileobj=output, mode="wb", filename="", mtime=epoch, compresslevel=9) as compressed:
            with tarfile.open(fileobj=compressed, mode="w", format=tarfile.USTAR_FORMAT) as archive:
                for name, data in sorted(contents.items()):
                    entry = tarfile.TarInfo(name)
                    entry.size, entry.mtime, entry.mode = len(data), epoch, 0o644
                    archive.addfile(entry, io.BytesIO(data))
    return output.getvalue()


def build(output):
    require(sys.version_info[:2] == (3, 12), "PYTHON_312_REQUIRED")
    require(not output.exists(), "NEW_OUTPUT_REQUIRED")
    commit, tree, epoch, files, builder_files = source_snapshot()
    project = tomllib.loads(files["pyproject.toml"].decode())["project"]
    version = project["version"]
    versions = {name: importlib.metadata.version(name) for name in ("build", "setuptools")}
    require(versions == {"build": "1.3.0", "setuptools": "84.0.0"}, "BUILD_TOOL_VERSION_MISMATCH")
    output.mkdir(parents=True)
    stage = output / "source"
    for name, raw in files.items():
        target = stage / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(raw)
        os.utime(target, (epoch, epoch))
    env = {key: value for key, value in os.environ.items() if key in {"SystemRoot", "WINDIR", "ComSpec", "PATHEXT", "TEMP", "TMP", "TMPDIR", "PATH"}}
    env.update(SOURCE_DATE_EPOCH=str(epoch), PYTHONUTF8="1", PYTHONDONTWRITEBYTECODE="1", PIP_NO_INDEX="1")
    raw_dir = output / "raw"
    with (output / "build.log").open("xb") as log:
        subprocess.run([sys.executable, "-I", "-m", "build", "--no-isolation", "--outdir", str(raw_dir)], cwd=stage, env=env, stdout=log, stderr=subprocess.STDOUT, check=True, timeout=300)
    artifacts = {}
    for filename in (f"kotodama_core-{version}-py3-none-any.whl", f"kotodama_core-{version}.tar.gz"):
        incoming = raw_dir / filename
        wheel = incoming.suffix == ".whl"
        contents = archive_contents(incoming, version)
        verify_source_contents(contents, files, version, wheel=wheel)
        contents = normalize_metadata(contents, wheel=wheel)
        verify_source_contents(contents, files, version, wheel=wheel)
        raw = normalize_archive(incoming, contents, epoch, wheel=wheel)
        (output / filename).write_bytes(raw)
        require(archive_contents(output / filename, version) == contents, "NORMALIZATION_CHANGED_CONTENTS")
        artifacts[filename] = {"sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)}
    # The SBOM generator describes locked candidate distributions, not an install.
    if __package__:
        from .build_release_sbom import build_bom
    else:
        from build_release_sbom import build_bom
    for label, name in (("build", "requirements-package-ci.txt"), ("swarm-extra", "requirements-task-swarm-ci.txt")):
        raw = git("show", f"{commit}:{name}")
        require(raw == (ROOT / name).read_bytes(), "LOCK_DIFFERS_FROM_COMMIT")
        bom = build_bom(raw, label, name, version)
        text = (json.dumps(bom, sort_keys=True, indent=2) + "\n").encode()
        filename = f"sbom-python-{label}.cdx.json"
        (output / filename).write_bytes(text)
        artifacts[filename] = {"sha256": hashlib.sha256(text).hexdigest(), "bytes": len(text)}
    require(git("rev-parse", "HEAD").decode().strip() == commit, "HEAD_CHANGED_DURING_BUILD")
    require(pinned_files(commit, SOURCE_PATHS) == files and pinned_files(commit, BUILDER_PATHS) == builder_files,
            "INPUT_CHANGED_DURING_BUILD")
    receipt = {"kind": "kotodama/python-candidate-build/v1", "status": "BUILT_NOT_RELEASED",
               "source_commit": commit, "source_tree": tree, "source_date_epoch": epoch,
               "version": version, "tool_versions": versions, "python": sys.version.split()[0],
               "normalization": "generated metadata LF and regenerated RECORD; sorted entries, fixed epoch, regular 0644, zero owner, stable gzip/zip headers",
               "source_files": {name: hashlib.sha256(raw).hexdigest() for name, raw in sorted(files.items())},
               "builder_inputs": {name: hashlib.sha256(raw).hexdigest() for name, raw in sorted(builder_files.items())},
               "license": "MIT", "artifacts": artifacts, "signature_verified": False,
               "private_consumer_verified": False, "public_beta": "NO_GO_UNPUBLISHED"}
    (output / "build-receipt.json").write_text(json.dumps(receipt, sort_keys=True, indent=2) + "\n", encoding="utf-8", newline="\n")
    (output / "SHA256SUMS").write_text("".join(f"{row['sha256']}  {name}\n" for name, row in sorted(artifacts.items())), encoding="utf-8", newline="\n")
    return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        receipt = build(args.output.absolute())
    except (OSError, ValueError, KeyError, subprocess.SubprocessError, importlib.metadata.PackageNotFoundError) as error:
        print(json.dumps({"status": "BUILD_REFUSED_OR_FAILED", "reason": str(error) if type(error) is ValueError else type(error).__name__}))
        return 1
    print(json.dumps({"status": receipt["status"], "source_commit": receipt["source_commit"], "artifacts": receipt["artifacts"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
