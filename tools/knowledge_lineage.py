#!/usr/bin/env python3
"""Inspect public-safe lineage metadata; no persistence or provider access."""
import argparse
import json
from pathlib import Path

from kotodama_kb.foundation import KnowledgeBaseError
from kotodama_kb.lineage_contract import read_snapshot, digest, validate_public_bytes, unresolved_parent_refs


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('validate', 'readback'))
    parser.add_argument('--snapshot', type=Path, required=True)
    parser.add_argument('--root', type=Path)
    args = parser.parse_args(argv)
    try:
        snapshot = read_snapshot(args.snapshot)
        if args.command == 'readback':
            if args.root is None:
                raise KnowledgeBaseError('LINEAGE_ROOT_REQUIRED')
            result = validate_public_bytes(snapshot, repository_root=args.root)
            successful = result['local_bytes_match'] and not result['opaque_unverified_revision_refs'] and not result['unresolved_parent_revision_refs']
        else:
            parents = unresolved_parent_refs(snapshot)
            successful = not parents
            result = {'snapshot_sha256': digest(snapshot), 'authority': 'projection_only',
                      'source_count': len(snapshot['sources']), 'concept_count': len(snapshot['concepts']),
                      'unresolved_parent_revision_refs': parents,
                      'access_authenticated': False, 'current_pointer_verified': False}
        print(json.dumps({'status': 'LOCAL_METADATA_PASS' if successful else 'NEEDS_RESOLUTION', **result}, sort_keys=True))
        return 0 if successful else 1
    except (KnowledgeBaseError, OSError, ValueError):
        print(json.dumps({'status': 'REFUSED', 'code': 'LINEAGE_INPUT_OR_BINDING_INVALID'}))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
