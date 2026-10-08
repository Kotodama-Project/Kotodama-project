"""Offline, content-free package diagnostic; no Task or provider operations."""
import argparse
import json

from . import __version__, digest


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", action="version", version=__version__)
    parser.parse_args(argv)
    print(json.dumps({"distribution": "kotodama-core", "version": __version__,
                      "status": "CANDIDATE_IMPORT_OK", "api": ["canonical", "digest", "SwarmError"],
                      "self_check": digest({"kotodama": "core"}) == "294978066d8269b9ec2b07723e5ffb0f6f8e1b53db0b1029e21ea4944a467082",
                      "provider_verified": False, "public_beta": "NO_GO_UNPUBLISHED"}))
    return 0
