"""Check current tracked Git snapshots against published migration source metadata.

No private source is fetched. This is exact-copy / literal-path detection, not
a historical secret scan or proof of migration completion.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess
import sys

from validate_resolved_compose_candidate import load_strict_json_bytes

ROOT = Path(__file__).resolve().parents[1]
MAX_BYTES = 8 * 1024 * 1024
# Pin source rows, not evolving destination or acceptance metadata.
MANIFESTS = {
    "migration/a017-hierarchy-templates.manifest.json": "f83ce9251270265a624d248aa8b0ab03a134fd5301d70febe7872b39077af9d5",
    "migration/a019-registry-contracts.manifest.json": "51a142ac3b3378614ceb9069fb34706cbc6eb573a84365ee8cb560e2af7fa451",
    "migration/a022-public-architecture.manifest.json": "0d42e931336e411dadc80ae4531c4509841cd59effd6165cf8b05408bd3fb306",
}
# A017's superseded template has existing, reviewed metadata/test references.
# Counts apply only to that manifest's SUPERSEDED row, never PRIVATE_RETAIN.
A017_REFERENCES = {
    "migration/a017-hierarchy-templates.provenance.json": 1,
    "tools/validate_migration_batch_a017.py": 2,
    "tests/test_migration_batch_a017.py": 2,
}


def tracked_path(root, relative):
    """Do not traverse links inside the operator-selected checkout."""
    parts = relative.split("/")
    if any(p in {"", ".", "..", ".git"} for p in parts) or any(c in relative for c in "\\:\0"):
        raise ValueError("invalid tracked path")
    path = root
    for part in parts[:-1]:
        path /= part
        details = path.lstat()
        if not stat.S_ISDIR(details.st_mode) or getattr(details, "st_file_attributes", 0) & 0x400:
            raise ValueError("linked parent")
    return path / parts[-1]


def read_bound(root, relative, limit, *, allow_symlink=False):
    """Read regular bytes or a link's stored text, never its target bytes."""
    path = tracked_path(root, relative)
    before = path.lstat()
    identity = lambda s: (s.st_dev, s.st_ino, s.st_mode, s.st_nlink, s.st_size, s.st_mtime_ns)
    if stat.S_ISLNK(before.st_mode) and allow_symlink:
        data = os.fsencode(os.readlink(path))
        if len(data) > limit:
            raise ValueError("oversized link")
        after = path.lstat()
    else:
        if (not stat.S_ISREG(before.st_mode) or before.st_size > limit or before.st_nlink != 1
                or getattr(before, "st_file_attributes", 0) & 0x400):
            raise ValueError("not a bounded regular file")
        flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
        fd = os.open(path, flags)
        try:
            if identity(before) != identity(os.fstat(fd)):
                raise ValueError("changed file")
            chunks, size = [], 0
            while size <= limit:
                chunk = os.read(fd, min(65536, limit + 1 - size))
                if not chunk:
                    break
                chunks.append(chunk)
                size += len(chunk)
            after = os.fstat(fd)
        finally:
            os.close(fd)
        if size > limit:
            raise ValueError("oversized file")
        data = b"".join(chunks)
    final = tracked_path(root, relative).lstat()
    if identity(before) != identity(after) or identity(after) != identity(final):
        raise ValueError("changed file")
    return data


def mapping_digest(rows):
    projection = [{key: row[key] for key in ("source_path", "source_blob_sha", "decision")} for row in rows]
    return hashlib.sha256(json.dumps(projection, ensure_ascii=False, sort_keys=True,
                                     separators=(",", ":")).encode()).hexdigest()


def git(root, *args, input=None):
    # Read only local objects, including when a checkout is partial/promisor.
    environment = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    environment.update(GIT_NO_LAZY_FETCH="1", GIT_NO_REPLACE_OBJECTS="1",
                       GIT_OPTIONAL_LOCKS="0", GIT_TERMINAL_PROMPT="0")
    return subprocess.run(["git", *args], cwd=root, env=environment, input=input,
                          capture_output=True, check=True, timeout=30).stdout


def entries(root, snapshot):
    args = ("ls-tree", "-r", "-z", "HEAD") if snapshot == "HEAD" else ("ls-files", "-s", "-z")
    result = {}
    for record in git(root, *args).split(b"\0"):
        if not record:
            continue
        metadata, raw_path = record.split(b"\t", 1)
        mode, second, third = metadata.decode("ascii").split()
        if snapshot == "index" and third != "0":
            raise ValueError("unmerged index")
        if mode not in {"100644", "100755", "120000"}:
            raise ValueError("unsupported tracked object")
        name = raw_path.decode("utf-8")
        if name.startswith("/") or any(p in {"", ".", ".."} for p in name.split("/")):
            raise ValueError("invalid tracked path")
        result[name] = third if snapshot == "HEAD" else second
    return result


def object_batches(root, oids):
    """Read each public blob once; bound a batch to 16 MiB, not one Git per file."""
    if not oids:
        return
    ordered = sorted(oids)
    sizes = {}
    output = git(root, "cat-file", "--batch-check=%(objectname) %(objecttype) %(objectsize)",
                 input=("\n".join(ordered) + "\n").encode())
    for line in output.decode("ascii").splitlines():
        oid, kind, size = line.split()
        if kind != "blob":
            raise ValueError("missing blob")
        sizes[oid] = int(size)
    if set(sizes) != oids:
        raise ValueError("missing size")
    batch, total = [], 0
    for oid in ordered + [None]:
        if batch and (oid is None or total + sizes[oid] > 2 * MAX_BYTES):
            raw = git(root, "cat-file", "--batch", input=("\n".join(batch) + "\n").encode())
            offset = 0
            for expected in batch:
                end = raw.index(b"\n", offset)
                actual, kind, size = raw[offset:end].decode("ascii").split()
                size = int(size)
                start = end + 1
                if actual != expected or kind != "blob" or size != sizes[expected] or raw[start + size:start + size + 1] != b"\n":
                    raise ValueError("invalid blob response")
                yield expected, raw[start:start + size]
                offset = start + size + 1
            if offset != len(raw):
                raise ValueError("extra blob response")
            batch, total = [], 0
        if oid is not None:
            if sizes[oid] > MAX_BYTES:
                yield oid, None
            else:
                batch.append(oid)
                total += sizes[oid]


def scan(root: Path, manifests=None):
    manifests = MANIFESTS if manifests is None else manifests
    findings, source_blobs, restricted_paths = [], set(), {}
    checked = 0

    def finding(name, snapshot, code, line=1):
        # A copied file can itself be named after a private source path.
        label = name if not any(p in name for p in restricted_paths) else "[redacted tracked path]"
        findings.append({"path": label, "line": line, "snapshot": snapshot, "code": code})

    try:
        root = root.resolve(strict=True)
        for manifest, expected in manifests.items():
            value = load_strict_json_bytes(read_bound(root, manifest, 128 * 1024))
            rows = value["entries"]
            if mapping_digest(rows) != expected:
                raise ValueError("source mapping drift")
            for row in rows:
                source_blobs.add(row["source_blob_sha"])
                if row["decision"] in {"PRIVATE_RETAIN", "SUPERSEDED"}:
                    allowed = {manifest: 1}
                    if manifest == "migration/a017-hierarchy-templates.manifest.json" and row["decision"] == "SUPERSEDED":
                        allowed.update(A017_REFERENCES)
                    restricted_paths[row["source_path"]] = allowed

        def inspect(name, snapshot, data=None, oid=None):
            nonlocal checked
            checked += 1
            if any(p in name for p in restricted_paths):
                finding(name, snapshot, "SOURCE_PATH_IN_FILENAME")
            if oid is None:
                oid = hashlib.sha1(f"blob {len(data)}\0".encode() + data).hexdigest()
            if oid in source_blobs:
                finding(name, snapshot, "SOURCE_BLOB_REUSED")
                return
            if data is None:
                finding(name, snapshot, "FILE_TOO_LARGE")
                return
            # Raw bytes also cover binary containers; BOM encodings are handled
            # without converting a binary file into an unbounded text guess.
            decoded = None
            if data.startswith((b"\xff\xfe", b"\xfe\xff", b"\x00\x00\xfe\xff")):
                encoding = "utf-32" if data.startswith((b"\xff\xfe\x00\x00", b"\x00\x00\xfe\xff")) else "utf-16"
                try:
                    decoded = data.decode(encoding)
                except UnicodeError:
                    pass  # Binary files can coincidentally start with a BOM.
            for source_path, allowed in restricted_paths.items():
                needle = source_path.encode()
                raw_count = data.count(needle)
                decoded_count = decoded.count(source_path) if decoded is not None else 0
                count = max(raw_count, decoded_count)
                if count > allowed.get(name, 0):
                    line = (decoded.count("\n", 0, decoded.index(source_path)) + 1 if decoded_count > raw_count
                            else data.count(b"\n", 0, data.index(needle)) + 1)
                    finding(name, snapshot, "SOURCE_PATH_COPIED", line)

        if git(root, "rev-parse", "--show-object-format").strip() != b"sha1":
            raise ValueError("unsupported object format")
        head, index = entries(root, "HEAD"), entries(root, "index")
        seen, uses = set(), {}
        for snapshot, objects in (("HEAD", head), ("index", index)):
            for name, oid in sorted(objects.items()):
                # Same path/bytes needs one check even if HEAD and index agree.
                key = (name, oid)
                if key not in seen:
                    if oid in source_blobs:
                        inspect(name, snapshot, oid=oid)
                    else:
                        uses.setdefault(oid, []).append((name, snapshot))
                    seen.add(key)
        for oid, data in object_batches(root, set(uses)):
            for name, snapshot in uses[oid]:
                inspect(name, snapshot, data=data, oid=oid)
        for name in sorted(set(head) | set(index)):
            try:
                data = read_bound(root, name, MAX_BYTES, allow_symlink=True)
            except FileNotFoundError:
                continue  # Deleted working file still has HEAD/index coverage.
            except (OSError, ValueError):
                finding(name, "working tree", "FILE_UNREADABLE")
                continue
            oid = hashlib.sha1(f"blob {len(data)}\0".encode() + data).hexdigest()
            if (name, oid) not in seen:
                inspect(name, "working tree", data=data, oid=oid)
        # Require every fixed metadata file in both committed and staged trees.
        if not set(manifests) <= set(head) & set(index):
            raise ValueError("manifest missing from tracked snapshot")
    except (OSError, ValueError, KeyError, TypeError, UnicodeError, RecursionError,
            subprocess.SubprocessError):
        finding(".", "repository", "SCAN_INCOMPLETE")
    return {"status": "FAIL" if findings else "PASS", "checked_snapshots": checked,
            "source_blob_count": len(source_blobs), "restricted_path_count": len(restricted_paths),
            "findings": findings, "scope": "current_tracked_snapshots"}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args(argv)
    result = scan(args.root)
    print(json.dumps(result, ensure_ascii=True, sort_keys=True))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
