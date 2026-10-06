#!/usr/bin/env python3
"""Inspect public-safe lineage metadata; no persistence or provider access."""
import argparse
import json
from pathlib import Path

from kotodama_kb.foundation import KnowledgeBaseError
from kotodama_kb.lineage_contract import read_snapshot, digest, validate_public_bytes
from kotodama_kb.lineage_impact import project_lineage, compare_lineage


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('validate', 'readback', 'index', 'impact'))
    parser.add_argument('--snapshot', type=Path, required=True)
    parser.add_argument('--root', type=Path)
    parser.add_argument('--before', type=Path)
    parser.add_argument('--invalidation-key', action='append', default=[])
    args = parser.parse_args(argv)
    try:
        snapshot = read_snapshot(args.snapshot)
        if args.command == 'readback':
            if args.root is None:
                raise KnowledgeBaseError('LINEAGE_ROOT_REQUIRED')
            result = validate_public_bytes(snapshot, repository_root=args.root)
            successful = result['local_bytes_match'] and not result['opaque_unverified_revision_refs']
        elif args.command in {'index', 'impact'}:
            if args.command == 'impact':
                if args.before is None:
                    raise KnowledgeBaseError('LINEAGE_PREVIOUS_SNAPSHOT_REQUIRED')
                projection = compare_lineage(read_snapshot(args.before), snapshot, invalidation_keys=args.invalidation_key)
            else:
                projection = project_lineage(snapshot)
            successful = projection['complete'] and not projection['quarantine_revision_refs']
            result = {'projection': projection}
        else:
            successful = True
            result = {'snapshot_sha256': digest(snapshot), 'authority': 'projection_only',
                      'source_count': len(snapshot['sources']), 'concept_count': len(snapshot['concepts']),
                      'access_authenticated': False, 'current_pointer_verified': False}
        print(json.dumps({'status': 'LOCAL_METADATA_PASS' if successful else 'NEEDS_RESOLUTION', **result}, sort_keys=True))
        return 0 if successful else 1
    except (KnowledgeBaseError, OSError, ValueError):
        print(json.dumps({'status': 'REFUSED', 'code': 'LINEAGE_INPUT_OR_BINDING_INVALID'}))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
