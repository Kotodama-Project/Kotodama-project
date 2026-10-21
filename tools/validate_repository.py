#!/usr/bin/env python3
"""Offline checks for Kotodama's deliberately small, Codex-native repository."""
from __future__ import annotations

import argparse
import html
import posixpath
import re
import subprocess
import sys
from pathlib import Path
from urllib.parse import unquote, urlsplit

REQUIRED = frozenset({
    'README.md', 'README.en.md', 'AGENTS.md', 'CONTRIBUTING.md', 'SECURITY.md',
    'LICENSE', 'STATUS.md', 'ROADMAP.md', 'docs/OPENAI-ALIGNMENT.md',
    'docs/OWNER-INTENT-COMPANY-AGI.md', 'docs/RETIREMENT.md', 'docs/WORKFLOW.md',
    'docs/DECISIONS.md', 'docs/FIVE-MINUTE-TOUR.md', 'docs/PROJECT-MAP.md',
    'templates/project-brief.md', 'tools/validate_repository.py',
    'tools/check_secrets.py', 'tests/test_repository.py',
    '.github/workflows/repository-validation.yml',
    '.github/workflows/dependency-review.yml',
})
RETIRED_DIRECTORIES = frozenset({
    'runtime', 'schemas', 'python', 'knowledge', 'governance', 'experiments',
    'migration', 'examples', '.agents', '.claude', '.codex',
})
RETIRED_ROOT_FILES = frozenset({
    'pyproject.toml', 'MANIFEST.in', 'package.json', 'package-lock.json',
    'pnpm-lock.yaml', 'uv.lock', 'CONTEXT.md',
})
ALLOWED_WORKFLOWS = frozenset({
    '.github/workflows/repository-validation.yml',
    '.github/workflows/dependency-review.yml',
})
ALLOWED_TOOLS = frozenset({'tools/validate_repository.py', 'tools/check_secrets.py'})
USES = re.compile(r'^\s*(?:-\s*)?["\']?uses["\']?\s*:\s*(.*?)\s*$')
PINNED_ACTION = re.compile(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_./-]+@[0-9a-f]{40}\Z')
LINK = re.compile(r'!?\[[^\]\n]*\]\(\s*(<[^>\n]+>|[^\s)\n]+)(?:\s+["\'][^\n]*?["\'])?\s*\)')
REFERENCE = re.compile(r'^\s{0,3}\[[^\]\n]+\]:\s*(<[^>\n]+>|\S+)', re.MULTILINE)


def without_code(text: str, strip_inline: bool = True) -> str:
    """Exclude fenced examples and inline code from link checking."""
    lines = []
    fence = None
    for line in text.splitlines():
        match = re.match(r'^\s{0,3}(`{3,}|~{3,})', line)
        if match:
            marker = match.group(1)
            if fence is None:
                fence = marker
            elif marker[0] == fence[0] and len(marker) >= len(fence):
                fence = None
            lines.append('')
        else:
            lines.append(line if fence is None else '')
    prose = '\n'.join(lines)
    return re.sub(r'(`+).*?\1', '', prose) if strip_inline else prose


def heading_ids(text: str) -> set[str]:
    seen: dict[str, int] = {}
    result = set()
    for line in without_code(text, strip_inline=False).splitlines():
        match = re.match(r'^\s{0,3}#{1,6}\s+(.+?)\s*#*\s*$', line)
        if not match:
            continue
        label = re.sub(r'\[([^\]]+)\]\([^)]*\)', r'\1', match.group(1))
        label = re.sub(r'<[^>]+>', '', html.unescape(label)).lower()
        slug = re.sub(r'[^\w\- ]', '', label).replace(' ', '-')
        count = seen.get(slug, 0)
        seen[slug] = count + 1
        result.add(slug if count == 0 else f'{slug}-{count}')
    result.update(re.findall(r'<a\s+(?:id|name)=["\']([^"\']+)', text))
    return result


def secret_filename(path: str) -> bool:
    """Reject secret/state files by name; content scanning belongs to Gitleaks."""
    name = Path(path).name.lower()
    return (
        name == '.env' or name.startswith('.env.') or
        name.startswith(('.dev.vars', 'credentials.', 'service-account', 'service_account')) or
        name in {'credentials.json', 'id_rsa', 'id_ed25519'} or
        name.endswith(('.pem', '.key', '.p12', '.pfx', '.sqlite', '.sqlite-wal',
                       '.sqlite-shm', '.db', '.db-wal', '.db-shm', '.tfstate'))
    )


def validate_repository(root: Path, files: set[str]) -> list[str]:
    errors = [f'missing required file: {name}' for name in sorted(REQUIRED - files)]
    contents: dict[str, str] = {}
    for name in sorted(files):
        file = root / name
        if name.startswith('/') or '..' in Path(name).parts:
            errors.append(f'unsafe tracked path: {name}')
            continue
        if file.is_symlink() or not file.is_file():
            errors.append(f'tracked path is not a regular file: {name}')
            continue
        first = name.split('/')[0]
        if (first in RETIRED_DIRECTORIES or name in RETIRED_ROOT_FILES or
                (name.startswith('requirements') and name.endswith('.txt')) or
                (name.startswith('templates/') and name != 'templates/project-brief.md') or
                (name.startswith('tools/') and name not in ALLOWED_TOOLS)):
            errors.append(f'retired surface is not allowed: {name}')
        if secret_filename(name):
            errors.append(f'secret or runtime-state filename is not allowed: {name}')
        if name.endswith(('.md', '.yml', '.yaml')):
            try:
                contents[name] = file.read_text(encoding='utf-8')
            except UnicodeError:
                errors.append(f'file is not UTF-8: {name}')
        if name.startswith('.github/workflows/'):
            if name not in ALLOWED_WORKFLOWS:
                errors.append(f'unapproved workflow: {name}')
            for number, line in enumerate(contents.get(name, '').splitlines(), 1):
                match = USES.match(line)
                if match:
                    action = match.group(1).split(' #', 1)[0].strip().strip('"\'')
                    if not PINNED_ACTION.fullmatch(action):
                        errors.append(f'action must use a full commit SHA: {name}:{number}')
                elif not line.lstrip().startswith('#') and re.search(r'\buses["\']?\s*:', line):
                    errors.append(f'use plain action syntax for pin verification: {name}:{number}')
                if re.match(r'^\s*(?:-\s*)?pull_request_target\s*:', line):
                    errors.append(f'privileged PR trigger is not allowed: {name}:{number}')

    for name, text in sorted(contents.items()):
        if not name.endswith('.md'):
            continue
        prose = without_code(text)
        targets = [m.group(1).strip('<>') for m in LINK.finditer(prose)]
        targets += [m.group(1).strip('<>') for m in REFERENCE.finditer(prose)]
        for target in targets:
            try:
                url = urlsplit(target)
            except ValueError:
                errors.append(f'invalid Markdown link: {name}: {target}')
                continue
            if url.scheme in {'https', 'http', 'mailto'}:
                continue
            if url.scheme or url.netloc:
                errors.append(f'unsupported Markdown link: {name}: {target}')
                continue
            relative = unquote(url.path)
            resolved = (posixpath.normpath(relative.lstrip('/')) if relative.startswith('/')
                        else posixpath.normpath(posixpath.join(posixpath.dirname(name), relative)))
            if not relative:
                resolved = name
            # Directory links are valid when they contain a tracked file.
            directory = resolved == '.' or any(p.startswith(resolved.rstrip('/') + '/') for p in files)
            if resolved not in files and not directory:
                errors.append(f'broken Markdown link: {name}: {target}')
            elif url.fragment and resolved.endswith('.md') and resolved in contents:
                if unquote(url.fragment) not in heading_ids(contents[resolved]):
                    errors.append(f'broken Markdown anchor: {name}: {target}')
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    root = args.root.resolve()
    try:
        result = subprocess.run(
            ['git', '-C', str(root), 'ls-files', '-z'], check=True,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
        files = set(result.stdout.decode('utf-8').split('\0')) - {''}
    except (OSError, UnicodeError, subprocess.CalledProcessError):
        print('FAIL: cannot read the tracked Git file inventory', file=sys.stderr)
        return 1
    errors = validate_repository(root, files)
    if errors:
        for error in errors:
            print(f'FAIL: {error}', file=sys.stderr)
        return 1
    print(f'PASS: {len(files)} tracked files; links, retired surfaces, action pins and filenames checked')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
