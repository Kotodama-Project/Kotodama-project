"""Check a proposed ingress policy; do not configure or contact a provider."""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import stat

from jsonschema import Draft202012Validator, FormatChecker

ROOT = Path(__file__).resolve().parents[1]
FORBIDDEN_PORTS = {22, 2375, 2376, 3306, 5432, 5678, 6379, 8006, 11434}


def require(condition, code):
    if not condition:
        raise ValueError(code)


def timestamp(value):
    parsed=datetime.fromisoformat(value.replace("Z","+00:00"))
    require(parsed.utcoffset() is not None, "TIMEZONE_REQUIRED")
    return parsed


def unique(pairs):
    result={}
    for key,value in pairs:
        require(key not in result, "DUPLICATE_FIELD")
        result[key]=value
    return result


def validate(policy, *, now):
    schema=json.loads((ROOT/"schemas/cloudflare-ingress-policy.schema.json").read_text(encoding="utf-8"))
    require(next(Draft202012Validator(schema,format_checker=FormatChecker()).iter_errors(policy),None) is None, "INGRESS_POLICY_REFUSED")
    require(now.utcoffset() is not None, "TIMEZONE_REQUIRED")
    origin=policy["origins"][0]
    require(origin["port"] not in FORBIDDEN_PORTS, "ADMIN_OR_DATA_PORT_REFUSED")
    require(origin["transport"] != "loopback_http" or origin["network"] == "loopback", "ORIGIN_TRANSPORT_REFUSED")
    access=policy["access"]
    require(access["frontend_policy_digest"] != access["gateway_policy_digest"], "ACCESS_PLANES_MUST_DIFFER")
    token=policy["service_token"]
    issued,expires=timestamp(token["issued_at"]),timestamp(token["expires_at"])
    require(issued <= now < expires and 0 < (expires-issued).total_seconds() <= 86400, "TOKEN_WINDOW_REFUSED")
    return {"status":"PROPOSED_INGRESS_POLICY_VALID", "as_of":now.astimezone(timezone.utc).isoformat(),
            "origin_count":1, "configuration_verified":False, "identity_verified":False,
            "direct_origin_closure_verified":False, "token_verified":False,
            "deployment_authorized":False, "public_beta":"NO_GO_UNPUBLISHED"}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input",type=Path)
    parser.add_argument("--at")
    args=parser.parse_args()
    try:
        fd=os.open(args.input,os.O_RDONLY|getattr(os,"O_NONBLOCK",0)|getattr(os,"O_NOFOLLOW",0)|getattr(os,"O_BINARY",0))
        with os.fdopen(fd,"rb") as stream:
            require(stat.S_ISREG(os.fstat(stream.fileno()).st_mode),"REGULAR_FILE_REQUIRED")
            raw=stream.read(65537)
        require(len(raw)<=65536,"INPUT_LIMIT")
        policy=json.loads(raw,object_pairs_hook=unique)
        result=validate(policy,now=timestamp(args.at) if args.at else datetime.now(timezone.utc))
    except (OSError,ValueError,TypeError,KeyError,RecursionError):
        print('{"status":"INGRESS_POLICY_REFUSED","configuration_verified":false}')
        return 1
    print(json.dumps(result,sort_keys=True))
    return 0


if __name__=="__main__":
    raise SystemExit(main())
