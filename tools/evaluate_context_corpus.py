#!/usr/bin/env python3
"""Evaluate a frozen synthetic corpus; no models, providers, or persistence."""
import argparse
import json
from pathlib import Path

from kotodama_kb.foundation import KnowledgeBaseError, _read_json
from kotodama_kb.retrieval_corpus import load_corpus
from kotodama_kb.retrieval_baselines import MODES
from kotodama_kb.retrieval_evaluation import evaluate_corpus, attest_evaluation


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--corpus', type=Path, required=True)
    parser.add_argument('--mode', choices=MODES, action='append')
    parser.add_argument('--attest', type=Path)
    args = parser.parse_args(argv)
    try:
        if args.attest:
            if args.mode: raise KnowledgeBaseError('ATTEST_MODES_ARE_RECEIPT_BOUND')
            result = attest_evaluation(load_corpus(args.corpus), _read_json(args.attest))
            print(json.dumps(result, ensure_ascii=False, sort_keys=True)); return 0
        result = evaluate_corpus(load_corpus(args.corpus), modes=tuple(args.mode or MODES))
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 0 if all(row['verdict'] == 'PASS_SYNTHETIC' for row in result['results']) and result['latency_budgets_met'] else 1
    except (KnowledgeBaseError, OSError, ValueError):
        print(json.dumps({'status': 'REFUSED', 'code': 'FROZEN_CORPUS_INPUT_INVALID'}))
        return 2


if __name__ == '__main__': raise SystemExit(main())
