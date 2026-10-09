"""Normalize the hosted Ubuntu runner's known mirrors; preserve apt signature configuration."""
import argparse
import json
from pathlib import Path
import re
import stat

REPLACEMENTS = {
    "http://azure.archive.ubuntu.com/ubuntu": "https://archive.ubuntu.com/ubuntu",
    "mirror+file:/etc/apt/apt-mirrors.txt": "https://archive.ubuntu.com/ubuntu",
    "mirror+file:/etc/apt/apt-mirrors-security.txt": "https://security.ubuntu.com/ubuntu",
}


def normalize(text):
    # Replace entire whitespace-delimited URI tokens, not a URL prefix or a regex hostname.
    parts = re.split(r"(\s+)", text)
    return "".join(REPLACEMENTS.get(part.rstrip("/"), part) for part in parts)


def prepare(root, *, apply=False):
    if root.is_symlink() or not root.is_dir():
        raise ValueError("APT_ROOT_REFUSED")
    directory = root / "sources.list.d"
    if directory.is_symlink():
        raise ValueError("APT_SOURCE_DIRECTORY_REFUSED")
    paths = [root / "sources.list"] if (root / "sources.list").exists() else []
    if directory.exists():
        paths.extend(sorted(path for path in directory.iterdir() if path.suffix in {".list", ".sources"}))
    pending = []
    for path in paths:
        details = path.lstat()
        if not stat.S_ISREG(details.st_mode) or details.st_size > 256 * 1024:
            raise ValueError("APT_SOURCE_FILE_REFUSED")
        before = path.read_bytes()
        after = normalize(before.decode("utf-8")).encode("utf-8")
        if after != before:
            pending.append((path, before, after))
    if apply:
        for path, before, after in pending:
            if path.is_symlink() or path.read_bytes() != before:
                raise ValueError("APT_SOURCE_CHANGED")
            path.write_bytes(after)
            if path.read_bytes() != after:
                raise ValueError("APT_SOURCE_READBACK_FAILED")
    return {"status": "APT_SOURCES_APPLIED" if apply else "APT_SOURCES_PLANNED", "changed_files": len(pending)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sources-dir", type=Path, default=Path("/etc/apt"))
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    try:
        result = prepare(args.sources_dir, apply=args.apply)
    except (OSError, UnicodeError, ValueError):
        print('{"status":"APT_SOURCES_REFUSED"}')
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
