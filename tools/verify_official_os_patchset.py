"""Check the exact evaluation patch bytes and path scope before/after application.

This verifier does not apply patches or grant deployment authority. Use one
source writer; a preflight is not an atomic lock against concurrent edits.
"""
from pathlib import Path
import argparse
import hashlib
import json
import re
import subprocess

REVISION = 'c0b6f3e52ff0ab8d44d290647e256936e88e6b57'
TARGETS = {
    'document-block-validation.patch': 'packages/workshop-backend/format-blueprints/workspace-docs/files/server.js',
    'local-qwen-window.patch': 'packages/workshop-shared/src/api.ts',
}


def closed_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('duplicate manifest key')
        result[key] = value
    return result


def verify(directory: Path, source: Path | None = None, phase: str = 'before'):
    manifest = json.loads((directory / 'manifest.json').read_text(encoding='utf-8'), object_pairs_hook=closed_object)
    if manifest['upstreamRepository'] != 'cloudflare/cloudflare-os' or manifest['upstreamRevision'] != REVISION:
        raise ValueError('upstream identity mismatch')
    rows = manifest['files']
    if len(rows) != 2 or {r['patch'] for r in rows} != set(TARGETS):
        raise ValueError('patch allowlist mismatch')
    for row in rows:
        target = TARGETS[row['patch']]
        if row['path'] != target or row['changedPaths'] != [target]:
            raise ValueError('target allowlist mismatch')
        path = directory / row['patch']
        if path.is_symlink() or not path.is_file() or path.stat().st_size > 1048576:
            raise ValueError('unsafe patch file')
        data = path.read_bytes()
        if hashlib.sha256(data).hexdigest() != row['patchSha256']:
            raise ValueError('patch digest mismatch')
        for key in ['beforeSha256', 'afterSha256', 'patchSha256']:
            if not re.fullmatch(r'[0-9a-f]{64}', row[key]):
                raise ValueError('invalid digest')
        if re.search(rb'(?m)^(?:old mode|new mode|new file mode|deleted file mode|rename |copy |GIT binary patch|Binary files|similarity index)', data):
            raise ValueError('patch metadata outside content-only scope')
        result = subprocess.run(['git', 'apply', '--numstat', '-z', '-'], input=data, capture_output=True)
        if result.returncode:
            raise ValueError('invalid patch syntax')
        records = [v.split(b'\t', 2) for v in result.stdout.split(b'\0') if v]
        if len(records) != 1 or len(records[0]) != 3 or records[0][2].decode('utf-8') != target:
            raise ValueError('actual changed path set mismatch')
    if source is not None:
        def git(*args):
            return subprocess.check_output(['git', '-C', str(source), *args]).decode('utf-8').strip()
        if git('rev-parse', 'HEAD') != REVISION:
            raise ValueError('source revision mismatch')
        changes = set(filter(None, git('diff', '--name-only', 'HEAD').splitlines()))
        untracked = git('ls-files', '--others', '--exclude-standard')
        expected = set() if phase == 'before' else set(TARGETS.values())
        if changes != expected or untracked:
            raise ValueError('source changed path set mismatch')
        for row in rows:
            path = source / row['path']
            if path.is_symlink() or not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != row[phase+'Sha256']:
                raise ValueError('source content mismatch')
    return {'patches': 2, 'exact_changed_paths_verified': True, 'source_checked': source is not None, 'phase': phase, 'applied': False}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source', type=Path)
    p.add_argument('--phase', choices=['before', 'after'], default='before')
    args = p.parse_args()
    try:
        print(json.dumps(verify(Path(__file__).resolve().parents[1] / 'runtime/cloudflare-os-kotodama/patches', args.source, args.phase)))
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError):
        raise SystemExit('PATCH_SET_REFUSED')


if __name__ == '__main__':
    main()
