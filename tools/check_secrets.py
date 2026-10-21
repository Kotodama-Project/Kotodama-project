"""Scan HEAD, index and tracked working files with pinned official Gitleaks.

No credentials, package installation, persistent downloads or history rewriting.
Stage new files first. Missing working files remain covered by the Git snapshots.
"""
from __future__ import annotations

import hashlib
import io
import platform
from pathlib import Path, PurePosixPath
import shutil
import subprocess
import tarfile
import tempfile
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
VERSION = "8.30.1"
BUILDS = {
    ("Darwin", "arm64"): ("darwin_arm64", "b40ab0ae55c505963e365f271a8d3846efbc170aa17f2607f13df610a9aeb6a5"),
    ("Linux", "x86_64"): ("linux_x64", "551f6fc83ea457d62a0d98237cbad105af8d557003051f41f3e7ca7b3f2470eb"),
}


def checked_path(name: str) -> PurePosixPath:
    path = PurePosixPath(name)
    if path.is_absolute() or ".." in path.parts or not name:
        raise ValueError("Unsafe tracked path; secret scan refused.")
    return path


def snapshot_sources(root: Path, destination: Path) -> None:
    """Keep staged bytes even when the working copy is edited or deleted."""
    index = subprocess.check_output(["git", "ls-files", "--stage", "-z"], cwd=root)
    head = subprocess.check_output(["git", "ls-tree", "-r", "-z", "HEAD"], cwd=root)
    names = set()
    for label, records in (("index", index), ("head", head)):
        for record in filter(None, records.split(b"\0")):
            metadata, raw_name = record.split(b"\t", 1)
            fields = metadata.decode("ascii").split()
            name = raw_name.decode("utf-8")
            relative = checked_path(name)
            mode = fields[0]
            oid = fields[1] if label == "index" else fields[2]
            if (mode not in {"100644", "100755"} or
                    (label == "index" and fields[2] != "0")):
                raise ValueError("Non-regular or unmerged Git entry; secret scan refused.")
            output = destination / label / relative
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_bytes(subprocess.check_output(["git", "cat-file", "blob", oid], cwd=root))
            if label == "index":
                names.add(name)
    for name in names:
        relative = checked_path(name)
        source = root / relative
        if source.is_symlink():
            raise ValueError("Symlink in working tree; secret scan refused.")
        if not source.exists():
            continue
        if not source.is_file() or root.resolve() not in source.resolve().parents:
            raise ValueError("Unsafe working file; secret scan refused.")
        output = destination / "working" / relative
        output.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, output)


def main() -> int:
    target = BUILDS.get((platform.system(), platform.machine()))
    if target is None:
        raise SystemExit("Unsupported host: run the required Ubuntu CI secret scan; not checked locally.")
    name, expected = target
    url = f"https://github.com/gitleaks/gitleaks/releases/download/v{VERSION}/gitleaks_{VERSION}_{name}.tar.gz"
    with urllib.request.urlopen(url, timeout=60) as response:
        data = response.read(32 * 1024 * 1024 + 1)
    if len(data) > 32 * 1024 * 1024 or hashlib.sha256(data).hexdigest() != expected:
        raise SystemExit("Gitleaks download failed the pinned checksum/size check.")
    with tempfile.TemporaryDirectory(prefix="kotodama-secret-check-") as folder:
        temporary = Path(folder)
        binary = temporary / "gitleaks"
        with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as archive:
            member = archive.getmember("gitleaks")
            if not member.isfile() or member.size > 128 * 1024 * 1024:
                raise SystemExit("Unexpected Gitleaks archive member.")
            stream = archive.extractfile(member)
            if stream is None:
                raise SystemExit("Missing Gitleaks binary.")
            binary.write_bytes(stream.read())
        binary.chmod(0o700)
        snapshot = temporary / "source"
        snapshot.mkdir()
        snapshot_sources(ROOT, snapshot)
        return subprocess.run(
            [str(binary), "dir", "--redact", "--no-banner", str(snapshot)],
            cwd=temporary, check=False,
        ).returncode


if __name__ == "__main__":
    raise SystemExit(main())
