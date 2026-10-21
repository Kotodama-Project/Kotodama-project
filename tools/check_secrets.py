"""Scan tracked working files with a checksum-pinned official Gitleaks binary.

No credentials, package installation, persistent downloads or history rewriting.
Stage new files first. Deleted paths are omitted. CI runs from a clean checkout.
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
        names = subprocess.check_output(["git", "ls-files", "-z"], cwd=ROOT).decode().split("\0")
        for name in filter(None, names):
            relative = PurePosixPath(name)
            source = ROOT / relative
            if relative.is_absolute() or ".." in relative.parts or source.is_symlink():
                raise SystemExit("Unsafe tracked path; secret scan refused.")
            if not source.exists():
                continue
            if not source.is_file() or ROOT not in source.resolve().parents:
                raise SystemExit("Unsafe tracked file; secret scan refused.")
            destination = snapshot / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, destination)
        return subprocess.run(
            [str(binary), "dir", "--redact", "--no-banner", str(snapshot)],
            cwd=temporary, check=False,
        ).returncode


if __name__ == "__main__":
    raise SystemExit(main())
