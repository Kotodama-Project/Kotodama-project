#!/usr/bin/python3
"""Check a stopped template against its one-time, root-owned install inventory.

This proves integrity of the listed installation scopes, not absence of personal
data throughout the guest or inside the original dependency/cache artifacts.
Run --record-install once, at the end of a fresh install, before activation.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess

REVISION = 'c0b6f3e52ff0ab8d44d290647e256936e88e6b57'
INSTALL = Path('/opt/kotodama-os')
HOME = Path('/home/os-runtime')
CONFIG = Path('/etc/kotodama')
BASELINE = Path('/var/lib/kotodama-template/install-inventory.json')
SERVICE = 'kotodama-cloudflare-os.service'
INSTALL_ENTRIES = {'core', 'downloads', 'node-v24.19.0-linux-x64', 'toolchain'}
HOME_DEFAULTS = {'.bashrc', '.bash_logout', '.profile'}
# Only these pnpm install-generated locations may seed the initial inventory.
HOME_CACHES = ('.cache/pnpm', '.local/share/pnpm')


class SealError(ValueError):
    pass


def inventory(root):
    """Hash every entry without following directory links outside this scope."""
    if root.is_symlink() or not root.is_dir() or root.resolve() != root.absolute():
        raise SealError('TEMPLATE_SCOPE_INVALID')
    entries = {}

    def visit(path):
        info = path.lstat()
        try:
            path.resolve(strict=True).relative_to(root)
        except (ValueError, OSError, RuntimeError):
            raise SealError('TEMPLATE_SYMLINK_ESCAPE_OR_INVALID') from None
        entry = {'mode': stat.S_IMODE(info.st_mode)}
        if stat.S_ISLNK(info.st_mode):
            entry.update(kind='symlink', target=os.readlink(path))
        elif stat.S_ISDIR(info.st_mode):
            entry['kind'] = 'directory'
        elif stat.S_ISREG(info.st_mode):
            with path.open('rb') as stream:
                digest = hashlib.file_digest(stream, 'sha256').hexdigest()
            entry.update(kind='file', sha256=digest)
        else:
            raise SealError('TEMPLATE_SPECIAL_FILE_UNSUPPORTED')
        entries[path.relative_to(root).as_posix()] = entry
        if entry['kind'] == 'directory':
            for child in sorted(path.iterdir()):
                visit(child)

    visit(root)
    return entries


def git_evidence(core, expected_revision=REVISION, prefix=()):
    def git(*args):
        result = subprocess.run(
            [*prefix, 'git', '-C', str(core), *args], capture_output=True,
            env={**os.environ, 'GIT_OPTIONAL_LOCKS': '0'}, check=False)
        if result.returncode:
            raise SealError('TEMPLATE_GIT_CHECK_FAILED')
        return result.stdout

    head = git('rev-parse', 'HEAD').decode('ascii').strip()
    if head != expected_revision:
        raise SealError('SOURCE_REVISION_MISMATCH')
    # Do not let assume-unchanged/skip-worktree bits hide tracked modifications.
    if any(row[:1] != b'H' for row in git('ls-files', '-v', '-z').split(b'\0') if row):
        raise SealError('TEMPLATE_GIT_HIDDEN_TRACKED_STATE')
    if git('diff', '--no-ext-diff', '--no-textconv', '--name-only', 'HEAD', '--'):
        raise SealError('TEMPLATE_GIT_DIRTY')
    # Deliberately includes ignored files. .gitignore is not a seal boundary.
    for raw in git('ls-files', '--others', '-z').split(b'\0'):
        if raw and 'node_modules' not in raw.decode('utf-8').split('/')[:-1]:
            raise SealError('TEMPLATE_UNEXPECTED_CORE_DATA')
    return head


def check_home_seed(home_entries, skel):
    skeleton = inventory(skel)
    for name, entry in home_entries.items():
        if name == '.':
            continue
        if name in HOME_DEFAULTS and entry == skeleton.get(name):
            continue
        if entry['kind'] == 'directory' and any(p.startswith(name + '/') for p in HOME_CACHES):
            continue
        if any(name == p or name.startswith(p + '/') for p in HOME_CACHES):
            continue
        raise SealError('TEMPLATE_UNEXPECTED_HOME_DATA')


def inspect(install, home, config, service_state, expected_revision=REVISION, prefix=()):
    if service_state != 'inactive':
        raise SealError('TEMPLATE_RUNTIME_NOT_CONFIRMED_INACTIVE')
    trees = {key: inventory(path) for key, path in
             [('install', install), ('home', home), ('config', config)]}
    if set(p.name for p in install.iterdir()) != INSTALL_ENTRIES:
        raise SealError('TEMPLATE_UNEXPECTED_INSTALL_DATA')
    if set(trees['config']) != {'.'}:
        raise SealError('TEMPLATE_CONTAINS_INSTANCE_STATE')
    core = install / 'core'
    for name in trees['install']:
        parts = name.split('/')
        if name.startswith('core/') and ('.wrangler' in parts or parts[-1] in {'.env', '.dev.vars'}):
            raise SealError('TEMPLATE_CONTAINS_INSTANCE_STATE')
    head = git_evidence(core, expected_revision, prefix)
    return {'schema': 1, 'coreRevision': head, 'trees': trees}


def record_install(install, home, config, skel, service_state, expected_revision=REVISION, prefix=()):
    snapshot = inspect(install, home, config, service_state, expected_revision, prefix)
    check_home_seed(snapshot['trees']['home'], skel)
    return snapshot


def verify_install(baseline, install, home, config, service_state, expected_revision=REVISION, prefix=()):
    current = inspect(install, home, config, service_state, expected_revision, prefix)
    if baseline != current:
        raise SealError('TEMPLATE_INSTALL_INVENTORY_MISMATCH')
    return {
        'templateSourceClean': True, 'coreRevision': current['coreRevision'],
        'lockSha256': current['trees']['install']['core/pnpm-lock.yaml']['sha256'],
        'runtimeActive': False, 'installInventoryMatches': True,
        'proof_scope': [str(install), str(home), str(config)],
        'limits': ['Point-in-time comparison with the trusted fresh-install inventory.',
                   'Original installer artifacts, dependency and cache contents are not classified for personal data.',
                   'Other guest paths and services are outside this proof; guest-wide account, conversation and provider-data absence is not asserted.'],
    }


def require_root_owned(path, directory=False):
    info = path.lstat()
    expected = stat.S_ISDIR if directory else stat.S_ISREG
    if not expected(info.st_mode) or info.st_uid != 0 or stat.S_IMODE(info.st_mode) & 0o022:
        raise SealError('TEMPLATE_INVENTORY_NOT_ROOT_PROTECTED')
    if path.resolve() != path.absolute():
        raise SealError('TEMPLATE_INVENTORY_PATH_INVALID')


def save_inventory(path, snapshot):
    path.parent.mkdir(mode=0o700, parents=False, exist_ok=True)
    require_root_owned(path.parent, directory=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'w', encoding='utf-8') as stream:
        json.dump(snapshot, stream, sort_keys=True)
        stream.write('\n')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--record-install', action='store_true')
    args = parser.parse_args()
    if os.geteuid() != 0:
        raise SealError('TEMPLATE_SEAL_REQUIRES_ROOT')
    result = subprocess.run(['systemctl', 'is-active', SERVICE], capture_output=True, text=True)
    if result.returncode != 3 or result.stdout.strip() != 'inactive':
        raise SealError('TEMPLATE_RUNTIME_NOT_CONFIRMED_INACTIVE')
    prefix = ('runuser', '-u', 'os-runtime', '--')
    if args.record_install:
        snapshot = record_install(INSTALL, HOME, CONFIG, Path('/etc/skel'), 'inactive', prefix=prefix)
        save_inventory(BASELINE, snapshot)
        print(json.dumps({'installInventoryRecorded': True, 'proof_scope': [str(INSTALL), str(HOME), str(CONFIG)]}))
    else:
        require_root_owned(BASELINE.parent, directory=True)
        require_root_owned(BASELINE)
        baseline = json.loads(BASELINE.read_text(encoding='utf-8'))
        print(json.dumps(verify_install(baseline, INSTALL, HOME, CONFIG, 'inactive', prefix=prefix)))


if __name__ == '__main__':
    try:
        main()
    except (SealError, OSError, ValueError, KeyError):
        # Keep file contents and subprocess stderr (potential private data) out of receipts.
        raise SystemExit('TEMPLATE_SEAL_FAILED') from None
