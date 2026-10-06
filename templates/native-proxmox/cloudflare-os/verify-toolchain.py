#!/usr/bin/python3
"""Verify pinned public archive digests before extraction or package execution.

Pins came from official HTTPS distribution metadata observed on 2026-09-06.
This is artifact integrity against the reviewed pins, not independent registry
key/provenance trust or production adoption.
"""
import hashlib
import json
from pathlib import Path

PINS = {
    'node.tar.xz': {
        'algorithm': 'sha256',
        'digest': '14b342e71204f811bde6153be8e04b62aef63c236fef92b55f9c83154b409647',
        'url': 'https://nodejs.org/dist/v24.19.0/node-v24.19.0-linux-x64.tar.xz',
        'metadata_url': 'https://nodejs.org/dist/v24.19.0/SHASUMS256.txt',
        'metadata_sha256': 'be0629ee2bcd8e40bb856abdd3407f0762101b76bd60a36b8867f637733631c0',
    },
    'pnpm.tgz': {
        'algorithm': 'sha512',
        'digest': 'cca3cea332ad254bb84145f966d19f4879615210346fc92c79a047f23a0d7b3cca3c3792f0076ba1f1831d277efbcf0a9119b31a9a60eca7fb3d6231f331ef72',
        'url': 'https://registry.npmjs.org/pnpm/-/pnpm-11.17.0.tgz',
        'metadata_url': 'https://registry.npmjs.org/pnpm/11.17.0',
        'metadata_sha256': 'eec829422e0250c5f66dcdd7591598086c1604ac3fb15fe32c52b50a174e7744',
    },
}


def verify_archive(path: Path, algorithm: str, digest: str):
    if path.is_symlink() or not path.is_file():
        raise ValueError('archive is not a regular file')
    with path.open('rb') as stream:
        observed = hashlib.file_digest(stream, algorithm).hexdigest()
    if observed != digest:
        raise ValueError('archive digest mismatch')
    return observed


def main():
    results = {}
    try:
        for name, pin in PINS.items():
            results[name] = verify_archive(Path(name), pin['algorithm'], pin['digest'])
    except (OSError, ValueError):
        raise SystemExit('TOOLCHAIN_ARCHIVE_REFUSED')
    print(json.dumps({'verified_archives': results, 'signature_trust_verified': False, 'extracted': False}))


if __name__ == '__main__':
    main()
