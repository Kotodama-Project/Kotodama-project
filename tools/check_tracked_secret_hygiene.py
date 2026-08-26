#!/usr/bin/env python3
"""Detect likely live credentials in the current Git-tracked tree."""

from __future__ import annotations

import argparse
import codecs
from collections import deque
import json
import re
import subprocess
import sys
from pathlib import Path


MAX_TEXT_BYTES = 8 * 1024 * 1024
ALLOWED_ENV = {
    ".dev.vars.example",
    ".env.example",
    ".env.sample",
    ".env.template",
}
SENSITIVE_EXACT = {".env", "credentials.json", "id_ed25519", "id_rsa"}
SENSITIVE_SUFFIXES = {".key", ".p12", ".pem", ".pfx", ".ppk"}
TEXT_FILENAMES = {".dev.vars", ".env", "dockerfile", "makefile"}
TEXT_SUFFIXES = {
    ".c", ".cfg", ".cmd", ".conf", ".cpp", ".cs", ".css", ".csv",
    ".env", ".go", ".gradle", ".graphql", ".h", ".hcl", ".hh", ".hpp",
    ".html", ".hxx",
    ".ini", ".java", ".js", ".json", ".kt", ".kts", ".lock", ".md",
    ".php", ".properties", ".ps1", ".py", ".rb", ".rs", ".sh",
    ".sql", ".swift", ".tf", ".toml", ".ts", ".txt", ".xml", ".yaml",
    ".yml",
}

TOKEN_PATTERNS = (
    ("GitHub token", re.compile(r"(?<![A-Za-z0-9_])gh[pousr]_[A-Za-z0-9]{36,255}(?![A-Za-z0-9_])")),
    ("GitHub fine-grained token", re.compile(r"(?<![A-Za-z0-9_])github_pat_[A-Za-z0-9_]{60,255}(?![A-Za-z0-9_])")),
    ("AWS access key ID", re.compile(r"(?<![A-Z0-9])(?:AKIA|ASIA)[A-Z0-9]{16}(?![A-Z0-9])")),
    ("Google API key", re.compile(r"(?<![A-Za-z0-9_-])AIza[0-9A-Za-z_-]{35}(?![A-Za-z0-9_-])")),
    ("Slack token", re.compile(r"(?<![A-Za-z0-9-])xox[baprs]-[A-Za-z0-9-]{20,255}")),
    ("Stripe live key", re.compile(r"(?<![A-Za-z0-9_])(?:sk|rk)_live_[A-Za-z0-9]{20,255}")),
    ("Anthropic API key", re.compile(r"(?<![A-Za-z0-9_-])sk-ant-[A-Za-z0-9_-]{40,255}")),
    ("OpenAI API key", re.compile(r"(?<![A-Za-z0-9_-])sk-(?:proj-)?[A-Za-z0-9_-]{48,255}")),
)

ASSIGNMENT_NAMES = (
    "ANTHROPIC_API_KEY", "AWS_SECRET_ACCESS_KEY", "CF_API_KEY", "CF_API_TOKEN",
    "CLOUDFLARE_API_TOKEN", "DATABASE_URL", "DISCORD_TOKEN", "GEMINI_API_KEY",
    "GITHUB_TOKEN", "GH_TOKEN", "GOOGLE_API_KEY", "N8N_ENCRYPTION_KEY",
    "KOTODAMA_COMPANY_DB_PASSWORD", "KOTODAMA_EVIDENCE_DB_PASSWORD",
    "OPENAI_API_KEY", "POSTGRES_PASSWORD", "SLACK_BOT_TOKEN",
)
ASSIGNMENT_OPERATOR = (
    r"(?:\?\?=|\?=|\|\|=|&&=|\*\*=|//=|<<=|>>>=|>>=|"
    r"[+\-*/%@|&^]?=(?![=>~]))"
)
ASSIGNMENT = re.compile(
    r"^\s*(?:-\s*|ARG\s+|export\s+|\$env:|ENV\s+|setx?\s+)?[\"']?(?P<name>"
    + "|".join(map(re.escape, ASSIGNMENT_NAMES))
    + r")[\"']?\s*(?::|"
    + ASSIGNMENT_OPERATOR
    + r")\s*(?P<value>.+?)\s*$",
    re.IGNORECASE,
)
SPACE_ASSIGNMENT = re.compile(
    r"^\s*(?:ENV\s+|setx?\s+)[\"']?(?P<name>"
    + "|".join(map(re.escape, ASSIGNMENT_NAMES))
    + r")[\"']?\s+(?P<value>.+?)\s*$",
    re.IGNORECASE,
)
BARE_SPACE_ASSIGNMENT = re.compile(
    r"^\s*[\"']?(?P<name>"
    + "|".join(map(re.escape, ASSIGNMENT_NAMES))
    + r")[\"']?\s+(?P<value>.+?)\s*$",
    re.IGNORECASE,
)
STRUCTURED_ASSIGNMENT = re.compile(
    r"(?<![A-Za-z0-9_])[\"']?(?P<name>"
    + "|".join(map(re.escape, ASSIGNMENT_NAMES))
    + r")[\"']?\s*:\s*(?P<value>(?:"
    + r"\$\{\{[^{}\r\n]+\}\}|\$\{[^{}\r\n]+\}|"
    + r"\{[A-Za-z_][A-Za-z0-9_]*\}|<[^<>\r\n]+>|"
    + r'"(?:\\.|[^"\\])*"'
    + r"|'(?:\\.|[^'\\])*'|[^,}\]])+)",
    re.IGNORECASE,
)
INLINE_ASSIGNMENT = re.compile(
    r"(?<![A-Za-z0-9_])[\"']?(?P<name>"
    + "|".join(map(re.escape, ASSIGNMENT_NAMES))
    + r")[\"']?\s*"
    + ASSIGNMENT_OPERATOR
    + r"\s*(?P<value>(?:"
    + r"\$\{\{[^{}\r\n]+\}\}|\$\{[^{}\r\n]+\}|"
    + r"\{[A-Za-z_][A-Za-z0-9_]*\}|<[^<>\r\n]+>|"
    + r'"(?:\\.|[^"\\])*"'
    + r"|'(?:\\.|[^'\\])*'|[^,;}\r\n]+)+)",
    re.IGNORECASE,
)
BRACKETED_ASSIGNMENT = re.compile(
    r"\[\s*[\"'`](?P<name>"
    + "|".join(map(re.escape, ASSIGNMENT_NAMES))
    + r")[\"'`]\s*\]\s*"
    + ASSIGNMENT_OPERATOR
    + r"\s*(?P<value>(?:"
    + r"\$\{\{[^{}\r\n]+\}\}|\$\{[^{}\r\n]+\}|"
    + r"\{[A-Za-z_][A-Za-z0-9_]*\}|<[^<>\r\n]+>|"
    + r'"(?:\\.|[^"\\])*"'
    + r"|'(?:\\.|[^'\\])*'|[^,;}\r\n]+)+)",
    re.IGNORECASE,
)
MULTILINE_ASSIGNMENT_START = re.compile(
    r"(?<![A-Za-z0-9_])[\"'`]?(?P<name>"
    + "|".join(map(re.escape, ASSIGNMENT_NAMES))
    + r")[\"'`]?(?:\s*\])?\s*(?::|"
    + ASSIGNMENT_OPERATOR
    + r")\s*"
    + r"(?:(?P<block>[|>](?:[1-9][+-]?|[+-][1-9]?)?"
    + r"(?:\s+#.*)?)|#.*)?$",
    re.IGNORECASE,
)
MULTILINE_ASSIGNMENT_NAME_ONLY = re.compile(
    r"(?<![A-Za-z0-9_])[\"'`]?(?P<name>"
    + "|".join(map(re.escape, ASSIGNMENT_NAMES))
    + r")[\"'`]?(?:\s*\])?\s*$",
    re.IGNORECASE,
)
MULTILINE_OPERATOR = re.compile(
    r"^[ \t]*(?::|" + ASSIGNMENT_OPERATOR + r")[ \t]*(?P<value>.*)$"
)
MAKE_DEFINE_START = re.compile(
    r"^[ \t]*(?:override[ \t]+)?define[ \t]+(?P<name>"
    + "|".join(map(re.escape, ASSIGNMENT_NAMES))
    + r")(?:[ \t]+(?:\?=|\+=|!=|:::=|::=|:=|=))?[ \t]*$",
    re.IGNORECASE,
)
MAKE_ANY_DEFINE = re.compile(r"^[ \t]*(?:override[ \t]+)?define(?:[ \t]|$)")
MAKE_DEFINE_END = re.compile(r"^[ \t]*endef[ \t]*(?:#.*)?$")
SIBLING_ASSIGNMENT_START = re.compile(
    r"^[ \t]*(?:[\"'][^\"']+[\"']|[A-Za-z_][A-Za-z0-9_.-]*)\s*[:=]"
)
JSON_STRING_TOKEN = re.compile(r'"(?:\\.|[^"\\])*"')
JSON_KEY_SEPARATOR = re.compile(r"\s*:")
YAML_DOUBLE_QUOTED_KEY = re.compile(
    r'"(?P<key>(?:\\.|[^"\\])*)"(?=\s*:)', re.MULTILINE
)
TOML_DOUBLE_QUOTED_KEY = re.compile(
    r'"(?P<key>(?:\\.|[^"\\])*)"(?=\s*=)', re.MULTILINE
)
YAML_HEX_ESCAPE = re.compile(
    r"\\(?:x(?P<x>[0-9A-Fa-f]{2})|u(?P<u>[0-9A-Fa-f]{4})|"
    r"U(?P<U>[0-9A-Fa-f]{8}))"
)
BRACKETED_QUOTED_KEY = re.compile(
    r"\[\s*(?P<quote>[\"'`])(?P<key>(?:\\.|(?!(?P=quote)).)*)"
    r"(?P=quote)\s*\](?=\s*=)",
    re.MULTILINE,
)
JAVASCRIPT_CONST_DECLARATION = re.compile(
    r"(?:^|[;{}])[ \t]*(?:export[ \t]+)?const[ \t]+"
    r"(?P<name>[A-Za-z_$][A-Za-z0-9_$]*)"
    r"(?:\s*:\s*[^=;\r\n]+)?\s*=",
    re.MULTILINE,
)
JAVASCRIPT_COMPUTED_KEY = re.compile(
    r"(?P<prefix>(?:[A-Za-z_$][A-Za-z0-9_$]*\.)*"
    r"[A-Za-z_$][A-Za-z0-9_$]*)\[(?P<expression>[^\]]{1,512})\]",
    re.DOTALL,
)
MAX_JAVASCRIPT_CONSTANT_DEPTH = 8
MAX_JAVASCRIPT_CONSTANT_PARTS = 32
BRACED_UNICODE_ESCAPE = re.compile(
    r"\\u\{(?P<digits>[0-9A-Fa-f]{1,6})\}"
)
ESCAPED_IDENTIFIER_TOKEN = re.compile(
    r"(?:[A-Za-z0-9_$]|"
    r"\\(?:x[0-9A-Fa-f]{2}|u\{[0-9A-Fa-f]{1,6}\}|"
    r"u[0-9A-Fa-f]{4}|U[0-9A-Fa-f]{8}))+"
)
POSTGRES_DOLLAR_QUOTE = re.compile(
    r"\$(?:[A-Za-z_][A-Za-z0-9_]*)?\$"
)
RUST_RAW_STRING_START = re.compile(
    r"(?:br|r)(?P<hashes>#{0,255})\""
)
SWIFT_RAW_STRING_START = re.compile(
    r"(?P<hashes>#{1,255})\""
)
CPP_RAW_STRING_START = re.compile(
    r"(?:u8|u|U|L)?R\"(?P<delimiter>[^ ()\\\t\r\n]{0,16})\("
)
HCL_HEREDOC_START = re.compile(
    r"<<-?(?P<delimiter>[A-Za-z_][A-Za-z0-9_]*)"
)
PHP_HEREDOC_START = re.compile(
    r"<<<[ \t]*(?P<quote>['\"]?)(?P<delimiter>"
    r"[A-Za-z_][A-Za-z0-9_]*)(?P=quote)"
)
JAVA_UNICODE_ESCAPE = re.compile(
    r"\\u+(?P<digits>[0-9A-Fa-f]{4})"
)
FLOW_SCALAR_ANCHOR = re.compile(
    r"&(?P<anchor>[A-Za-z_][A-Za-z0-9_-]*)\s+(?P<value>"
    r'"(?:\\.|[^"\\])*"'
    r"|'(?:\\.|[^'\\])*'|[^\s,\]\}\r\n]+)"
)
YAML_BLOCK_SCALAR = re.compile(
    r"[|>](?:[1-9][+-]?|[+-][1-9]?)?(?:\s+#.*)?$"
)
YAML_SCALAR_PROPERTIES = re.compile(
    r"^(?:(?:&[A-Za-z_][A-Za-z0-9_-]*|!![^\s]+|![^\s]+)(?:\s+|$))+"
)
YAML_ANY_BLOCK_SCALAR_START = re.compile(
    r"^(?P<indent>[ \t]*)(?P<item>-\s*)?(?:.*?:[ \t]*)?"
    r"[|>](?:[1-9][+-]?|[+-][1-9]?)?(?:[ \t]+#.*)?$"
)
YAML_ENV_FIELD = re.compile(
    r"^(?P<indent>[ \t]*)(?P<item>-\s*)?"
    r"[\"']?(?P<field>name|valueFrom|value)[\"']?\s*:\s*"
    r"(?P<value>.*?)\s*$",
    re.IGNORECASE,
)
YAML_MERGE_FIELD = re.compile(
    r"^(?P<indent>[ \t]*)(?P<item>-\s*)?[\"']?<<[\"']?\s*:\s*"
    r"(?P<value>.+?)\s*$"
)
YAML_ANCHOR_DECLARATION = re.compile(
    r"^(?P<indent>[ \t]*)(?P<item>-\s*)?.+?:[ \t]*"
    r"&(?P<anchor>[A-Za-z_][A-Za-z0-9_-]*)"
    r"(?:[ \t]+(?P<value>.*?))?[ \t]*$"
)
YAML_ENV_NAME_VALUE = re.compile(
    r"(?P<prefix>[\"']?name[\"']?\s*:\s*)"
    r'"(?P<key>(?:\\.|[^"\\])*)"',
    re.IGNORECASE,
)
PRIVATE_BEGIN = re.compile(
    r"(?:-----BEGIN (?:(?:(?:ENCRYPTED|RSA|DSA|EC|OPENSSH) )?PRIVATE KEY|"
    r"PGP PRIVATE KEY BLOCK)-----|PuTTY-User-Key-File-[23]:)"
)
HASH_COMMENT_SUFFIXES = {
    ".cfg", ".conf", ".env", ".hcl", ".ini", ".md", ".properties",
    ".ps1", ".py", ".rb", ".sh", ".tf", ".toml", ".yaml", ".yml",
}
SLASH_COMMENT_SUFFIXES = {
    ".c", ".cpp", ".cs", ".go", ".h", ".hcl", ".hh", ".hpp",
    ".hxx", ".java", ".js", ".kt", ".kts", ".php", ".rs", ".swift",
    ".tf", ".ts",
}
BLOCK_COMMENT_SUFFIXES = SLASH_COMMENT_SUFFIXES | {".css", ".sql"}
NESTED_BLOCK_COMMENT_SUFFIXES = {".rs", ".sql", ".swift"}
TRIPLE_QUOTE_SUFFIXES = {".cs", ".java", ".kt", ".kts", ".swift"}
CPP_SOURCE_SUFFIXES = {".cpp", ".h", ".hh", ".hpp", ".hxx"}
C_SOURCE_SUFFIXES = {".c"} | CPP_SOURCE_SUFFIXES
JAVASCRIPT_SOURCE_SUFFIXES = {".js", ".ts"}
JAVA_TEXT_BLOCK_SENTINEL = "<java-text-block>"
SOURCE_CODE_SUFFIXES = {
    ".c", ".cpp", ".cs", ".go", ".h", ".hh", ".hpp", ".hxx",
    ".java", ".js", ".kt", ".kts", ".php", ".ps1", ".py", ".rb",
    ".rs", ".swift", ".ts",
}
CODE_REFERENCE_VALUE = re.compile(
    r"[A-Za-z_$][A-Za-z0-9_$]*"
    r"(?:(?:\.[A-Za-z_$][A-Za-z0-9_$]*)|(?:\[[^\]\r\n]+\]))*"
)
LOOKUP_CALL_VALUE = re.compile(
    r"(?:os\.getenv|os\.environ\.get|os\.Getenv|System\.getenv|"
    r"Environment\.GetEnvironmentVariable|getenv|std::env::var)"
    r"\(\s*[\"'](?:"
    + "|".join(map(re.escape, ASSIGNMENT_NAMES))
    + r")[\"']\s*\)"
)


def index_blobs(root: Path) -> dict[Path, str]:
    output = subprocess.run(
        ["git", "ls-files", "-s", "-z"],
        cwd=root,
        capture_output=True,
        check=True,
    ).stdout
    result: dict[Path, str] = {}
    for raw in output.split(b"\0"):
        if not raw:
            continue
        metadata, raw_path = raw.split(b"\t", 1)
        _mode, oid, stage = metadata.decode("ascii").split()
        if stage != "0":
            raise ValueError("unmerged index entry")
        result[Path(raw_path.decode("utf-8", errors="strict"))] = oid
    return result


def head_blobs(root: Path) -> dict[Path, str]:
    head = subprocess.run(
        ["git", "rev-parse", "--verify", "HEAD"],
        cwd=root,
        capture_output=True,
        check=False,
    )
    if head.returncode != 0:
        return {}
    output = subprocess.run(
        ["git", "ls-tree", "-r", "-z", "HEAD"],
        cwd=root,
        capture_output=True,
        check=True,
    ).stdout
    result: dict[Path, str] = {}
    for raw in output.split(b"\0"):
        if not raw:
            continue
        metadata, raw_path = raw.split(b"\t", 1)
        _mode, object_type, oid = metadata.decode("ascii").split()
        if object_type == "blob":
            result[Path(raw_path.decode("utf-8", errors="strict"))] = oid
    return result


def blob_sizes(root: Path, oids: set[str]) -> dict[str, int]:
    if not oids:
        return {}
    output = subprocess.run(
        [
            "git",
            "cat-file",
            "--batch-check=%(objectname) %(objecttype) %(objectsize)",
        ],
        cwd=root,
        input=("\n".join(sorted(oids)) + "\n").encode("ascii"),
        capture_output=True,
        check=True,
    ).stdout
    result: dict[str, int] = {}
    for line in output.decode("ascii").splitlines():
        oid, object_type, size = line.split()
        if object_type != "blob":
            raise ValueError("tracked Git object is not a blob")
        result[oid] = int(size)
    return result


def read_blobs(root: Path, oids: set[str]) -> dict[str, bytes]:
    if not oids:
        return {}
    output = subprocess.run(
        ["git", "cat-file", "--batch"],
        cwd=root,
        input=("\n".join(sorted(oids)) + "\n").encode("ascii"),
        capture_output=True,
        check=True,
    ).stdout
    result: dict[str, bytes] = {}
    offset = 0
    while offset < len(output):
        end = output.index(b"\n", offset)
        oid, object_type, raw_size = output[offset:end].decode("ascii").split()
        if object_type != "blob":
            raise ValueError("tracked Git object is not a blob")
        size = int(raw_size)
        start = end + 1
        result[oid] = output[start:start + size]
        offset = start + size + 1
    return result


def text_like_path(path: Path) -> bool:
    return path.name.lower() in TEXT_FILENAMES or path.suffix.lower() in TEXT_SUFFIXES


def looks_like_text(data: bytes) -> bool:
    sample = data[:8192]
    if not sample:
        return True
    control = sum(
        (byte < 32 and byte not in {8, 9, 10, 12, 13}) or byte == 127
        for byte in sample
    )
    return control / len(sample) <= 0.01


def decode_text_snapshot(path: Path, data: bytes) -> tuple[str | None, str | None]:
    encodings = (
        (codecs.BOM_UTF32_LE, "utf-32"),
        (codecs.BOM_UTF32_BE, "utf-32"),
        (codecs.BOM_UTF16_LE, "utf-16"),
        (codecs.BOM_UTF16_BE, "utf-16"),
        (codecs.BOM_UTF8, "utf-8-sig"),
    )
    for marker, encoding in encodings:
        if data.startswith(marker):
            try:
                return data.decode(encoding), None
            except UnicodeDecodeError:
                return None, "tracked text BOM has invalid encoded content"
    if b"\0" in data[:8192]:
        if text_like_path(path):
            return None, "tracked text-like file contains unrecognized NUL encoding"
        return None, None
    try:
        return data.decode("utf-8"), None
    except UnicodeDecodeError:
        if text_like_path(path) or looks_like_text(data):
            return None, "tracked text-like file is not UTF-8 or BOM-backed Unicode"
        return None, None


def source_label(sources: set[str]) -> str:
    order = {"HEAD": 0, "index": 1, "working tree": 2}
    return "/".join(sorted(sources, key=lambda source: order[source]))


def sensitive_filename(path: Path) -> bool:
    name = path.name.lower()
    parts = tuple(part.lower() for part in path.parts)
    if (bool(parts) and parts[0] == "work") or any(
        part in {".terraform", ".wrangler"} for part in parts
    ):
        return True
    if name in ALLOWED_ENV or (
        name.startswith((".dev.vars.", ".env.")) and name.endswith(".example")
    ):
        return False
    return (
        name in SENSITIVE_EXACT
        or name == ".dev.vars"
        or name.startswith(".dev.vars.")
        or name.startswith(".env.")
        or name.endswith(".tfstate")
        or ".tfstate." in name
        or path.suffix.lower() in SENSITIVE_SUFFIXES
        or re.fullmatch(r"credentials(?:[-_.].+)?\.json", name) is not None
        or re.fullmatch(r"service[-_]account(?:[-_.].+)?\.json", name) is not None
    )


def strip_format_comment(path: Path, raw: str) -> str:
    suffix = path.suffix.lower()
    name = path.name.lower()
    markers: tuple[str, ...] = ()
    if (
        suffix in {
            ".env", ".hcl", ".ps1", ".py", ".rb", ".sh", ".tf",
            ".toml", ".yaml", ".yml",
        }
        or name in {".dev.vars", ".env", "makefile"}
        or name.startswith((".dev.vars.", ".env."))
    ):
        markers += ("#",)
    if suffix in SLASH_COMMENT_SUFFIXES:
        markers += ("//",)
    if suffix == ".sql":
        markers += ("--",)
    if suffix in BLOCK_COMMENT_SUFFIXES:
        markers += ("/*",)

    quote: str | None = None
    escaped = False
    for index, character in enumerate(raw):
        if quote is not None:
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == quote:
                quote = None
            continue
        if character in {"'", '"', "`"}:
            quote = character
            continue
        if index and raw[index - 1] not in " \t\r\n":
            continue
        if any(raw.startswith(marker, index) for marker in markers):
            return raw[:index].rstrip()
    return raw


def assignment_value(
    raw: str, path: Path | None = None, strip_comments: bool = True
) -> str:
    value = raw.strip().rstrip(",").strip()
    if path is not None and strip_comments:
        value = strip_format_comment(path, value).strip().rstrip(",").strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        value = value[1:-1].strip()
    return value


def yaml_scalar_value(
    raw: str,
    path: Path | None = None,
    strip_comments: bool = True,
    strip_properties: bool = False,
) -> str:
    prepared = raw.strip().rstrip(",").strip()
    if path is not None and strip_comments:
        prepared = strip_format_comment(path, prepared).strip().rstrip(",").strip()
    double_quoted = (
        len(prepared) >= 2
        and prepared[0] == prepared[-1] == '"'
    )
    value = assignment_value(prepared)
    if double_quoted:
        value = decode_yaml_key(value)
    if strip_properties:
        value = YAML_SCALAR_PROPERTIES.sub("", value).strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            quoted = value[0] == '"'
            value = value[1:-1].strip()
            if quoted:
                value = decode_yaml_key(value)
    return value


def placeholder(value: str) -> bool:
    stripped = value.strip()
    normalized = stripped.strip("'\"")
    lower = normalized.lower()
    if not lower or lower in {"none", "null", "nil", "undefined"}:
        return True
    if re.fullmatch(
        r"(?:\$\{\{\s*(?:env|secrets|vars)\.[A-Za-z_][A-Za-z0-9_]*\s*\}\}|"
        r"\$\{[A-Za-z_][A-Za-z0-9_]*(?:(?::?\?)[^{}\r\n]*)?\}|"
        r"\{[A-Za-z_][A-Za-z0-9_]*\}|<[^<>\r\n]+>)",
        normalized,
    ):
        return True
    marker = re.fullmatch(
        r"(?:changeme|change-me|dummy|example|fake|not-a-real|placeholder|"
        r"redacted|replace-me|replaceme|sample|synthetic|test-only)"
        r"(?:[._-][a-z0-9._-]+)?",
        lower,
    )
    reference = re.fullmatch(
        r"(?:(?:env|secrets|vars|var)\.[a-z_][a-z0-9_]*|"
        r"process\.env\.[a-z_][a-z0-9_]*|"
        r"os\.environ(?:\[['\"][a-z_][a-z0-9_]*['\"]\]|"
        r"\.get\(['\"][a-z_][a-z0-9_]*['\"]\))|"
        r"your[-_][a-z0-9._-]+)",
        lower,
    )
    return (
        lower == "demo"
        or marker is not None
        or reference is not None
        or re.fullmatch(r"[*xX._-]{8,}", normalized) is not None
    )


def live_assignment(value: str) -> bool:
    return not placeholder(value)


def trim_unmatched_closing_delimiters(value: str) -> str:
    stack: list[str] = []
    matching = {")": "(", "]": "[", "}": "{"}
    quote: str | None = None
    escaped = False
    for index, character in enumerate(value):
        if quote is not None:
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == quote:
                quote = None
            continue
        if character in {"'", '"', "`"}:
            quote = character
        elif character in "([{":
            stack.append(character)
        elif character in matching:
            if not stack or stack[-1] != matching[character]:
                return value[:index].rstrip()
            stack.pop()
    return value


def source_code_reference(path: Path, value: str) -> bool:
    raw = trim_unmatched_closing_delimiters(value.strip())
    if path.suffix.lower() not in SOURCE_CODE_SUFFIXES or not raw:
        return False
    if raw[0] in {"'", '"', "`"}:
        return False
    normalized = assignment_value(raw, path).rstrip(";").rstrip()
    return (
        CODE_REFERENCE_VALUE.fullmatch(normalized) is not None
        or LOOKUP_CALL_VALUE.fullmatch(normalized) is not None
    )


def multiline_code_reference(path: Path, value: str) -> bool:
    return source_code_reference(path, value)


def shell_parameter_assignments(line: str) -> list[tuple[str, str]]:
    """Return sensitive shell default/assignment expansions, including nesting."""

    assignments: list[tuple[str, str]] = []
    stack: list[int] = []
    index = 0
    names = sorted(ASSIGNMENT_NAMES, key=len, reverse=True)
    while index < len(line):
        if line.startswith("${", index):
            stack.append(index)
            index += 2
            continue
        if line[index] == "}" and stack:
            start = stack.pop()
            body = line[start + 2:index]
            upper = body.upper()
            for name in names:
                if not upper.startswith(name):
                    continue
                remainder = body[len(name):]
                for operator in (":-", ":=", ":+", "-", "=", "+"):
                    if remainder.startswith(operator):
                        assignments.append((name, remainder[len(operator):]))
                        break
                break
        index += 1
    return assignments


def shell_heredoc_delimiters(line: str) -> list[tuple[str, bool]]:
    """Find heredoc delimiters without interpreting quoted shell content."""

    delimiters: list[tuple[str, bool]] = []
    quote: str | None = None
    escaped = False
    comment = False
    index = 0
    while index < len(line):
        character = line[index]
        if comment:
            break
        if quote == "'":
            if character == "'":
                quote = None
            index += 1
            continue
        if escaped:
            escaped = False
            index += 1
            continue
        if character == "\\":
            escaped = True
            index += 1
            continue
        if quote is not None:
            if character == quote:
                quote = None
            index += 1
            continue
        if character in {'"', "'", "`"}:
            quote = character
            index += 1
            continue
        if character == "#" and (index == 0 or line[index - 1].isspace()):
            comment = True
            break
        if line.startswith("<<", index) and not line.startswith("<<<", index):
            cursor = index + 2
            strip_tabs = cursor < len(line) and line[cursor] == "-"
            if strip_tabs:
                cursor += 1
            while cursor < len(line) and line[cursor] in " \t":
                cursor += 1
            if cursor >= len(line):
                index = cursor
                continue
            delimiter_quote = line[cursor] if line[cursor] in {"'", '"'} else None
            if delimiter_quote is not None:
                cursor += 1
                end = line.find(delimiter_quote, cursor)
                if end < 0:
                    index = cursor
                    continue
                delimiter = line[cursor:end]
                index = end + 1
            else:
                match = re.match(r"[^\s;&|<>]+", line[cursor:])
                if match is None:
                    index = cursor
                    continue
                delimiter = match.group()
                index = cursor + match.end()
            if delimiter:
                delimiters.append((delimiter, strip_tabs))
            continue
        index += 1
    return delimiters


def shell_heredoc_terminator(
    line: str, delimiter: str, strip_tabs: bool
) -> bool:
    candidate = line.rstrip("\r\n")
    if strip_tabs:
        candidate = candidate.lstrip("\t")
    return candidate == delimiter


def normalize_shell_line_continuations(text: str) -> tuple[str, list[int]]:
    """Join shell logical lines while preserving the first physical line."""

    result: list[str] = []
    line_origins = [1]
    heredocs: list[tuple[str, bool]] = []
    logical_line: list[str] = []
    physical_line = 1
    quote: str | None = None
    comment = False
    for raw_line in text.splitlines(keepends=True):
        if heredocs:
            result.extend(raw_line)
            if "\n" in raw_line or "\r" in raw_line:
                line_origins.append(physical_line + 1)
            if shell_heredoc_terminator(raw_line, *heredocs[0]):
                heredocs.pop(0)
            physical_line += 1
            logical_line = []
            continue

        line_ending = ""
        body = raw_line
        if body.endswith("\r\n"):
            line_ending = "\r\n"
            body = body[:-2]
        elif body.endswith(("\n", "\r")):
            line_ending = body[-1]
            body = body[:-1]
        result.extend(body)
        logical_line.extend(body)

        escaped = False
        for index, character in enumerate(body):
            if comment:
                continue
            if quote == "'":
                if character == "'":
                    quote = None
                continue
            if escaped:
                escaped = False
                continue
            if character == "\\":
                escaped = True
                continue
            if quote is not None:
                if character == quote:
                    quote = None
                continue
            if character in {'"', "'", "`"}:
                quote = character
            elif character == "#" and (index == 0 or body[index - 1].isspace()):
                comment = True

        backslashes = 0
        for character in reversed(body):
            if character != "\\":
                break
            backslashes += 1
        continuation = (
            bool(line_ending)
            and backslashes % 2 == 1
        )
        # Quoted literals and comments must not be reinterpreted as assignments.
        if quote is not None or comment:
            continuation = False
        if continuation:
            result.pop()
            logical_line.pop()
            escaped = False
        elif line_ending:
            result.extend(line_ending)
            line_origins.append(physical_line + 1)
            heredocs.extend(shell_heredoc_delimiters("".join(logical_line)))
            logical_line = []
            comment = False
            escaped = False
        physical_line += 1
    if not text:
        line_origins = [1]
    return "".join(result), line_origins


def line_is_comment(path: Path, line: str) -> bool:
    stripped = line.lstrip(" \t")
    suffix = path.suffix.lower()
    if suffix in HASH_COMMENT_SUFFIXES and stripped.startswith("#"):
        return True
    if suffix in SLASH_COMMENT_SUFFIXES and stripped.startswith(("//", "/*", "*")):
        return True
    if suffix == ".sql" and stripped.startswith("--"):
        return True
    return suffix in {".cfg", ".conf", ".ini", ".properties"} and stripped.startswith(";")


def java_delimiter_is_escaped(text: str, index: int) -> bool:
    count = 0
    cursor = index
    while cursor > 0:
        if text[cursor - 1] == "\\":
            count += 1
            cursor -= 1
            continue
        if text[max(0, cursor - 4):cursor].lower() != "005c":
            break
        marker = cursor - 4
        unicode_start = marker
        while unicode_start > 0 and text[unicode_start - 1] == "u":
            unicode_start -= 1
        if unicode_start == marker or unicode_start == 0:
            break
        if text[unicode_start - 1] != "\\":
            break
        count += 1
        cursor = unicode_start - 1
    return count % 2 == 1


def escaped_by_backslash(text: str, index: int) -> bool:
    count = 0
    cursor = index - 1
    while cursor >= 0 and text[cursor] == "\\":
        count += 1
        cursor -= 1
    return count % 2 == 1


def java_quote_token_end(text: str, index: int) -> int | None:
    if index < len(text) and text[index] == '"':
        return index + 1
    if index >= len(text) or text[index] != "\\":
        return None
    cursor = index + 1
    if cursor >= len(text) or text[cursor] != "u":
        return None
    while cursor < len(text) and text[cursor] == "u":
        cursor += 1
    if text[cursor:cursor + 4].lower() != "0022":
        return None
    return cursor + 4


def java_triple_quote_end(text: str, index: int) -> int | None:
    cursor = index
    for _ in range(3):
        token_end = java_quote_token_end(text, cursor)
        if token_end is None:
            return None
        cursor = token_end
    return cursor


def normalize_java_lexical_escapes(text: str) -> str:
    """Translate Java escapes that alter scanner lexical boundaries."""

    def replace(match: re.Match[str]) -> str:
        character = chr(int(match.group("digits"), 16))
        if character in {"\r", "\n", '"', "\\"}:
            return character
        return match.group()

    return JAVA_UNICODE_ESCAPE.sub(replace, text)


def heredoc_end(path: Path, text: str, index: int) -> int | None:
    if text[index] != "<":
        return None
    suffix = path.suffix.lower()
    if suffix in {".hcl", ".tf"}:
        start = HCL_HEREDOC_START.match(text, index)
        allow_semicolon = False
    elif suffix == ".php":
        start = PHP_HEREDOC_START.match(text, index)
        allow_semicolon = True
    else:
        return None
    if start is None:
        return None
    line_break = re.search(r"\r\n|\r|\n", text[start.end():])
    if line_break is None:
        return None
    line_end = start.end() + line_break.end()
    delimiter = re.escape(start.group("delimiter"))
    if allow_semicolon:
        terminator = re.compile(
            rf"(?:(?<=[\r\n])|^)[ \t]*{delimiter}"
            r"(?=$|[ \t\r\n;,)\]])"
            r"[^\r\n]*(?:\r\n|\r|\n|$)",
        )
    else:
        terminator = re.compile(
            rf"(?:(?<=[\r\n])|^)[ \t]*{delimiter}"
            r"[ \t]*(?:\r\n|\r|\n|$)",
        )
    end = terminator.search(text, line_end)
    return end.end() if end is not None else None


def javascript_regex_end(text: str, index: int) -> int | None:
    if index + 1 >= len(text) or text[index] != "/" or text[index + 1] in "/*":
        return None
    previous = index - 1
    while previous >= 0 and text[previous].isspace():
        previous -= 1
    if previous >= 0 and text[previous] not in "=([{,:;!&|?~+-*%^<>":
        return None
    escaped = False
    character_class = False
    cursor = index + 1
    while cursor < len(text):
        character = text[cursor]
        if character in "\r\n":
            return None
        if escaped:
            escaped = False
        elif character == "\\":
            escaped = True
        elif character == "[":
            character_class = True
        elif character == "]":
            character_class = False
        elif character == "/" and not character_class:
            cursor += 1
            while cursor < len(text) and text[cursor].isalpha():
                cursor += 1
            return cursor
        cursor += 1
    return None


def c_spliced_pair_length(
    text: str, index: int, first: str, second: str
) -> int | None:
    if not text.startswith(first, index):
        return None
    cursor = index + 1
    if cursor < len(text) and text[cursor] == second:
        return 2
    if text.startswith("\\\r\n", cursor):
        cursor += 3
    elif text.startswith("\\\n", cursor):
        cursor += 2
    else:
        return None
    return cursor - index + 1 if cursor < len(text) and text[cursor] == second else None


def blank_comment_delimiter(
    result: list[str], text: str, index: int, length: int
) -> None:
    for cursor in range(index, index + length):
        if text[cursor] not in "\r\n":
            result[cursor] = " "


def strip_block_comments(path: Path, text: str) -> str:
    suffix = path.suffix.lower()
    if suffix not in BLOCK_COMMENT_SUFFIXES:
        return text
    result = list(text)
    block_depth = 0
    nested_blocks = path.suffix.lower() in NESTED_BLOCK_COMMENT_SUFFIXES
    quote: str | None = None
    dollar_quote: str | None = None
    raw_quote: str | None = None
    escaped = False
    index = 0
    while index < len(text):
        if block_depth:
            nested_length = (
                c_spliced_pair_length(text, index, "/", "*")
                if suffix in C_SOURCE_SUFFIXES
                else (2 if text.startswith("/*", index) else None)
            )
            if nested_blocks and nested_length is not None:
                blank_comment_delimiter(result, text, index, nested_length)
                block_depth += 1
                index += nested_length
                continue
            end_length = (
                c_spliced_pair_length(text, index, "*", "/")
                if suffix in C_SOURCE_SUFFIXES
                else (2 if text.startswith("*/", index) else None)
            )
            if end_length is not None:
                blank_comment_delimiter(result, text, index, end_length)
                block_depth -= 1
                index += end_length
                continue
            if text[index] not in "\r\n":
                result[index] = " "
            index += 1
            continue
        if dollar_quote is not None:
            if text.startswith(dollar_quote, index):
                index += len(dollar_quote)
                dollar_quote = None
            else:
                index += 1
            continue
        if raw_quote is not None:
            if raw_quote == JAVA_TEXT_BLOCK_SENTINEL:
                quote_end = java_triple_quote_end(text, index)
                if quote_end is not None and not java_delimiter_is_escaped(
                    text, index
                ):
                    index = quote_end
                    raw_quote = None
                else:
                    index += 1
            elif text.startswith(raw_quote, index) and not (
                suffix == ".swift" and escaped_by_backslash(text, index)
            ):
                index += len(raw_quote)
                raw_quote = None
            else:
                index += 1
            continue
        character = text[index]
        if quote is not None:
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == quote:
                quote = None
            elif character in "\r\n" and quote != "`":
                quote = None
            index += 1
            continue
        heredoc_stop = heredoc_end(path, text, index)
        if heredoc_stop is not None:
            index = heredoc_stop
            continue
        if suffix in JAVASCRIPT_SOURCE_SUFFIXES:
            regex_end = javascript_regex_end(text, index)
            if regex_end is not None:
                index = regex_end
                continue
        if suffix in CPP_SOURCE_SUFFIXES:
            raw_start = CPP_RAW_STRING_START.match(text, index)
            if raw_start is not None and (
                index == 0 or not (text[index - 1].isalnum() or text[index - 1] == "_")
            ):
                raw_quote = ")" + raw_start.group("delimiter") + '"'
                index = raw_start.end()
                continue
        if suffix == ".rs":
            raw_start = RUST_RAW_STRING_START.match(text, index)
            if raw_start is not None and (
                index == 0 or not (text[index - 1].isalnum() or text[index - 1] == "_")
            ):
                raw_quote = '"' + raw_start.group("hashes")
                index = raw_start.end()
                continue
        elif suffix == ".swift":
            raw_start = SWIFT_RAW_STRING_START.match(text, index)
            if raw_start is not None:
                raw_quote = '"' + raw_start.group("hashes")
                index = raw_start.end()
                continue
        if suffix == ".java":
            quote_end = java_triple_quote_end(text, index)
            if quote_end is not None and not java_delimiter_is_escaped(
                text, index
            ):
                raw_quote = JAVA_TEXT_BLOCK_SENTINEL
                index = quote_end
                continue
        if (
            suffix in TRIPLE_QUOTE_SUFFIXES
            and suffix != ".java"
            and text.startswith('"""', index)
            and not (suffix == ".swift" and escaped_by_backslash(text, index))
        ):
            quote_end = index + 3
            while quote_end < len(text) and text[quote_end] == '"':
                quote_end += 1
            raw_quote = text[index:quote_end]
            index = quote_end
            continue
        if character in {"'", '"', "`"}:
            quote = character
            index += 1
            continue
        if path.suffix.lower() == ".sql" and character == "$":
            delimiter = POSTGRES_DOLLAR_QUOTE.match(text, index)
            if delimiter is not None:
                dollar_quote = delimiter.group()
                index = delimiter.end()
                continue
        if (
            path.suffix.lower() in SLASH_COMMENT_SUFFIXES
            and text.startswith("//", index)
        ) or (
            path.suffix.lower() == ".sql"
            and text.startswith("--", index)
        ):
            newline = text.find("\n", index)
            end = len(text) if newline < 0 else newline
            result[index:end] = [" "] * (end - index)
            index = end
            continue
        start_length = (
            c_spliced_pair_length(text, index, "/", "*")
            if suffix in C_SOURCE_SUFFIXES
            else (2 if text.startswith("/*", index) else None)
        )
        if start_length is not None:
            blank_comment_delimiter(result, text, index, start_length)
            block_depth = 1
            index += start_length
            continue
        index += 1
    return "".join(result)


def next_content_line(
    path: Path, lines: list[str], start: int
) -> tuple[int, str] | None:
    index = start
    while index < len(lines):
        stripped = lines[index].strip()
        if stripped and not line_is_comment(path, lines[index]):
            return index, lines[index]
        index += 1
    return None


def yaml_document_boundary(value: str) -> bool:
    if value.startswith((" ", "\t")):
        return False
    marker = value.split("#", 1)[0].strip()
    return marker in {"---", "..."}


def expression_continues(previous: str, current: str) -> bool:
    leading_operators = (
        "+", ".", "||", "&&", "??", "|", "&", "?", ":", ","
    )
    trailing_operators = (
        "+", ".", "||", "&&", "??", "|", "&", "?", ":", ",", "\\"
    )
    if current.startswith(leading_operators):
        return True
    if previous.rstrip().endswith(trailing_operators):
        return True
    return (
        current.startswith(("'", '"'))
        and previous.lstrip().startswith(("'", '"'))
    )


def continuation_value(
    path: Path,
    lines: list[str],
    start: int,
    key_indent: int,
    include_indented: bool,
) -> str | None:
    located = next_content_line(path, lines, start)
    if located is None:
        return None
    value_index, candidate = located
    stripped = candidate.strip()
    if stripped in {"}", "},", "]", "],"} or yaml_document_boundary(candidate):
        return None
    value_indent = len(candidate) - len(candidate.lstrip(" \t"))
    if (
        value_indent <= key_indent
        and not candidate.lstrip().startswith("-")
        and SIBLING_ASSIGNMENT_START.match(candidate) is not None
    ):
        return None

    return accumulate_continuation(
        path,
        lines,
        value_index,
        stripped,
        key_indent,
        include_indented,
    )


def accumulate_continuation(
    path: Path,
    lines: list[str],
    value_index: int,
    initial_value: str,
    key_indent: int,
    include_indented: bool,
) -> str:
    parts = [initial_value]
    next_index = value_index + 1
    while True:
        following = next_content_line(path, lines, next_index)
        if following is None:
            break
        following_index, following_line = following
        following_value = following_line.strip()
        if (
            following_value in {"}", "},", "]", "],"}
            or yaml_document_boundary(following_line)
        ):
            break
        following_indent = len(following_line) - len(
            following_line.lstrip(" \t")
        )
        if (
            following_indent <= key_indent
            and not following_line.lstrip().startswith("-")
            and SIBLING_ASSIGNMENT_START.match(following_line) is not None
        ):
            break
        if not (
            expression_continues(parts[-1], following_value)
            or (include_indented and following_indent > key_indent)
        ):
            break
        parts.append(following_value)
        next_index = following_index + 1
    return " ".join(parts)


def yaml_block_scalar_value(
    lines: list[str], start: int, key_indent: int
) -> str:
    parts: list[str] = []
    for line in lines[start:]:
        stripped = line.strip()
        if not stripped:
            if parts:
                parts.append("")
            continue
        indent = len(line) - len(line.lstrip(" \t"))
        if indent <= key_indent:
            break
        parts.append(stripped)
    return " ".join(parts)


def multiline_assignments(
    path: Path, text: str
) -> list[tuple[str, int, str, bool]]:
    """Find named assignments whose operator or value crosses a line."""

    lines = strip_block_comments(path, text).splitlines()
    assignments: list[tuple[str, int, str, bool]] = []
    include_indented = path.suffix.lower() in {".yml", ".yaml"}
    if path.name.lower() == "makefile" or path.suffix.lower() == ".mk":
        for index, line in enumerate(lines):
            define = MAKE_DEFINE_START.match(line)
            if define is None:
                continue
            depth = 1
            body: list[str] = []
            for candidate in lines[index + 1:]:
                if MAKE_ANY_DEFINE.match(candidate) is not None:
                    depth += 1
                elif MAKE_DEFINE_END.match(candidate) is not None:
                    depth -= 1
                    if depth == 0:
                        break
                if depth:
                    body.append(candidate.strip())
            if depth == 0:
                assignments.append((
                    define.group("name"), index + 1, " ".join(body), False
                ))
    for index, line in enumerate(lines):
        if line_is_comment(path, line):
            continue
        key_indent = len(line) - len(line.lstrip(" \t"))
        match = MULTILINE_ASSIGNMENT_START.search(line)
        if match is not None:
            block_scalar = include_indented and match.group("block") is not None
            if block_scalar:
                value = yaml_block_scalar_value(lines, index + 1, key_indent)
            else:
                value = continuation_value(
                    path, lines, index + 1, key_indent, include_indented
                )
            if value is not None:
                assignments.append((
                    match.group("name"), index + 1, value, not block_scalar
                ))
            continue

        match = MULTILINE_ASSIGNMENT_NAME_ONLY.search(line)
        if match is None:
            continue
        located = next_content_line(path, lines, index + 1)
        if located is None:
            continue
        operator_index, operator_line = located
        operator = MULTILINE_OPERATOR.match(operator_line)
        if operator is None:
            continue
        value = operator.group("value").strip()
        block_scalar = (
            include_indented
            and YAML_BLOCK_SCALAR.fullmatch(value) is not None
        )
        if block_scalar:
            operator_indent = len(operator_line) - len(
                operator_line.lstrip(" \t")
            )
            value = yaml_block_scalar_value(
                lines, operator_index + 1, operator_indent
            )
        elif not value or value.startswith("#"):
            value = continuation_value(
                path,
                lines,
                operator_index + 1,
                key_indent,
                include_indented,
            )
        else:
            value = accumulate_continuation(
                path,
                lines,
                operator_index,
                value,
                key_indent,
                include_indented,
            )
        if value is not None:
            assignments.append((
                match.group("name"), index + 1, value, not block_scalar
            ))
    return assignments


def yaml_quote_can_start(text: str, index: int) -> bool:
    if index == 0 or text[index - 1] in " \t\r\n[{,:":
        return True
    if text[index - 1] not in "-?":
        return False
    return index == 1 or text[index - 2] in " \t\r\n[{,:"


def flow_mapping_bodies(text: str) -> list[tuple[str, int, str | None]]:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    bodies: list[tuple[str, int, str | None]] = []
    stack: list[tuple[int, int, str | None]] = []
    sanitized = list(text)
    quote: str | None = None
    comment = False
    escaped = False
    line_number = 1
    index = 0
    while index < len(text):
        character = text[index]
        if comment:
            if character == "\n":
                comment = False
                line_number += 1
            else:
                sanitized[index] = " "
            index += 1
            continue
        if quote is not None:
            if escaped:
                escaped = False
            elif quote == "'" and text.startswith("''", index):
                index += 2
                continue
            elif character == "\\" and quote == '"':
                escaped = True
            elif character == quote:
                quote = None
            if character == "\n":
                line_number += 1
            index += 1
            continue
        if character == "#" and (
            index == 0 or text[index - 1] in " \t\n"
        ):
            sanitized[index] = " "
            comment = True
        elif character in {"'", '"'} and yaml_quote_can_start(text, index):
            quote = character
        elif character == "{":
            prefix = text[max(0, index - 256):index]
            anchor_match = re.search(
                r"&(?P<anchor>[A-Za-z_][A-Za-z0-9_-]*)\s*$", prefix
            )
            anchor = (
                anchor_match.group("anchor")
                if anchor_match is not None
                else None
            )
            stack.append((index, line_number, anchor))
        elif character == "}" and stack:
            start, start_line, anchor = stack.pop()
            bodies.append((
                "".join(sanitized[start + 1:index]), start_line, anchor
            ))
        if character == "\n":
            line_number += 1
        index += 1
    return bodies


def split_flow_segments(text: str, delimiter: str) -> list[str]:
    segments: list[str] = []
    stack: list[str] = []
    matching = {"}": "{", "]": "[", ")": "("}
    quote: str | None = None
    escaped = False
    start = 0
    index = 0
    while index < len(text):
        character = text[index]
        if quote is not None:
            if escaped:
                escaped = False
            elif quote == "'" and text.startswith("''", index):
                index += 2
                continue
            elif character == "\\" and quote == '"':
                escaped = True
            elif character == quote:
                quote = None
            index += 1
            continue
        if character in {"'", '"'}:
            quote = character
        elif character in "{[(":
            stack.append(character)
        elif character in matching and stack and stack[-1] == matching[character]:
            stack.pop()
        elif character == delimiter and not stack:
            segments.append(text[start:index])
            start = index + 1
        index += 1
    segments.append(text[start:])
    return segments


def mask_yaml_block_scalar_contents(text: str) -> str:
    masked: list[str] = []
    active_indent: int | None = None
    for line in text.splitlines(keepends=True):
        content = line.rstrip("\r\n")
        ending = line[len(content):]
        stripped = content.strip()
        indent = len(content) - len(content.lstrip(" \t"))
        if active_indent is not None:
            if not stripped or indent > active_indent:
                masked.append(" " * len(content) + ending)
                continue
            active_indent = None
        marker = YAML_ANY_BLOCK_SCALAR_START.match(content)
        if marker is not None:
            active_indent = len(marker.group("indent"))
        masked.append(line)
    return "".join(masked)


def parsed_flow_fields(body: str) -> dict[str, str]:
    fields: dict[str, str] = {}
    for raw_field in split_flow_segments(body, ","):
        pair = split_flow_segments(raw_field, ":")
        if len(pair) < 2:
            continue
        key = yaml_scalar_value(pair[0]).lower()
        fields[key] = ":".join(pair[1:]).strip()
    return fields


def resolve_flow_fields(
    fields: dict[str, str],
    anchors: dict[str, dict[str, str]],
    seen: frozenset[str] = frozenset(),
) -> dict[str, str]:
    resolved: dict[str, str] = {}
    for alias in re.findall(
        r"\*(?P<alias>[A-Za-z_][A-Za-z0-9_-]*)", fields.get("<<", "")
    ):
        if alias in seen or alias not in anchors:
            continue
        inherited = resolve_flow_fields(
            anchors[alias], anchors, seen | {alias}
        )
        for key, value in inherited.items():
            resolved.setdefault(key, value)
    for key, value in fields.items():
        if key != "<<":
            resolved[key] = value
    return resolved


def yaml_structured_field(line: str) -> re.Match[str] | None:
    return YAML_ENV_FIELD.match(line) or YAML_MERGE_FIELD.match(line)


def yaml_mapping_span(
    lines: list[str], index: int, field: re.Match[str]
) -> tuple[int, int, int]:
    field_indent = len(field.group("indent")) + len(field.group("item") or "")
    boundary_indent = -1
    start = 0
    if field.group("item") is not None:
        boundary_indent = len(field.group("indent"))
        start = index
    else:
        for previous_index in range(index - 1, -1, -1):
            previous = lines[previous_index]
            stripped = previous.strip()
            if not stripped or stripped.startswith("#"):
                continue
            if yaml_document_boundary(previous):
                start = previous_index + 1
                break
            previous_indent = len(previous) - len(previous.lstrip(" \t"))
            if previous_indent >= field_indent:
                continue
            previous_field = yaml_structured_field(previous)
            boundary_indent = previous_indent
            if (
                previous_field is not None
                and previous_field.group("item") is not None
                and previous_indent + len(previous_field.group("item") or "")
                == field_indent
            ):
                start = previous_index
            else:
                start = previous_index + 1
            break

    end = len(lines)
    for following_index in range(index + 1, len(lines)):
        following = lines[following_index]
        stripped = following.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if yaml_document_boundary(following):
            end = following_index
            break
        following_indent = len(following) - len(following.lstrip(" \t"))
        if following_indent <= boundary_indent:
            end = following_index
            break
    return start, end, field_indent


def continued_yaml_scalar(
    lines: list[str], start: int, field_indent: int
) -> str:
    for line in lines[start:]:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        indent = len(line) - len(line.lstrip(" \t"))
        if indent <= field_indent:
            break
        return stripped
    return ""


def block_yaml_anchors(
    path: Path, lines: list[str]
) -> tuple[dict[str, dict[str, str]], dict[str, str]]:
    mappings: dict[str, dict[str, str]] = {}
    scalars: dict[str, str] = {}
    for index, line in enumerate(lines):
        declaration = YAML_ANCHOR_DECLARATION.match(line)
        if declaration is None:
            continue
        anchor = declaration.group("anchor")
        raw_value = strip_format_comment(
            path, declaration.group("value") or ""
        ).strip()
        if raw_value and not raw_value.startswith(("{", "[")):
            scalars[anchor] = yaml_scalar_value(
                raw_value, path, strip_properties=True
            )
            continue
        if raw_value:
            continue
        base_indent = len(declaration.group("indent")) + len(
            declaration.group("item") or ""
        )
        continuation = continued_yaml_scalar(lines, index + 1, base_indent)
        if continuation and yaml_structured_field(continuation) is None:
            scalars[anchor] = yaml_scalar_value(
                continuation, path, strip_properties=True
            )
            continue
        fields: dict[str, str] = {}
        child_indent: int | None = None
        for candidate_line in lines[index + 1:]:
            stripped = candidate_line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            indent = len(candidate_line) - len(
                candidate_line.lstrip(" \t")
            )
            if indent <= base_indent:
                break
            candidate = yaml_structured_field(candidate_line)
            if candidate is None:
                continue
            candidate_indent = len(candidate.group("indent")) + len(
                candidate.group("item") or ""
            )
            if child_indent is None:
                child_indent = candidate_indent
            if candidate_indent != child_indent:
                continue
            if candidate.re is YAML_MERGE_FIELD:
                fields["<<"] = candidate.group("value")
            else:
                fields[candidate.group("field").lower()] = candidate.group("value")
        if fields:
            mappings[anchor] = fields
    return mappings, scalars


def resolve_yaml_name(
    raw: str,
    path: Path,
    scalar_anchors: dict[str, str],
) -> str:
    value = yaml_scalar_value(raw, path, strip_properties=True)
    seen: set[str] = set()
    while value.startswith("*"):
        alias = value[1:].strip()
        if alias in seen or alias not in scalar_anchors:
            break
        seen.add(alias)
        value = yaml_scalar_value(
            scalar_anchors[alias], path, strip_properties=True
        )
    return value


def structured_environment_assignments(
    path: Path, text: str
) -> list[tuple[str, int, str, bool]]:
    if path.suffix.lower() not in {".json", ".yaml", ".yml"}:
        return []
    assignments: list[tuple[str, int, str, bool]] = []
    lines = text.splitlines()
    block_anchors, scalar_anchors = block_yaml_anchors(path, lines)
    flow_text = (
        mask_yaml_block_scalar_contents(text)
        if path.suffix.lower() in {".yaml", ".yml"}
        else text
    )
    flow_records = [
        (parsed_flow_fields(body), number, anchor)
        for body, number, anchor in flow_mapping_bodies(flow_text)
    ]
    for scalar in FLOW_SCALAR_ANCHOR.finditer(flow_text):
        raw_value = scalar.group("value")
        if raw_value.startswith(("{", "[")):
            continue
        scalar_anchors.setdefault(
            scalar.group("anchor"),
            yaml_scalar_value(raw_value, path, strip_properties=True),
        )
    flow_anchors = {
        anchor: fields
        for fields, _number, anchor in flow_records
        if anchor is not None
    }
    anchors = {**block_anchors, **flow_anchors}
    for fields, number, _anchor in flow_records:
        resolved = resolve_flow_fields(fields, anchors)
        if "name" not in resolved or "value" not in resolved:
            continue
        name = resolve_yaml_name(
            resolved["name"], path, scalar_anchors
        ).upper()
        if name in ASSIGNMENT_NAMES:
            assignments.append((name, number, resolved["value"], True))
    for index, line in enumerate(lines):
        name_field = YAML_ENV_FIELD.match(line)
        if name_field is None or name_field.group("field").lower() != "name":
            continue
        name = resolve_yaml_name(
            name_field.group("value"), path, scalar_anchors
        ).upper()
        if not name:
            field_indent = len(name_field.group("indent")) + len(
                name_field.group("item") or ""
            )
            name = resolve_yaml_name(
                continued_yaml_scalar(lines, index + 1, field_indent),
                path,
                scalar_anchors,
            ).upper()
        if name not in ASSIGNMENT_NAMES:
            continue

        start, end, field_indent = yaml_mapping_span(
            lines, index, name_field
        )

        values: list[tuple[str, bool]] = []
        value_from = False
        for candidate_index in range(start, end):
            candidate = YAML_ENV_FIELD.match(lines[candidate_index])
            if candidate is None:
                continue
            candidate_indent = len(candidate.group("indent")) + len(
                candidate.group("item") or ""
            )
            if candidate_indent != field_indent:
                continue
            field = candidate.group("field").lower()
            if field == "valuefrom":
                value_from = True
                continue
            if field != "value":
                continue
            raw_value = candidate.group("value")
            strip_comments = True
            if YAML_BLOCK_SCALAR.fullmatch(raw_value.strip()) is not None:
                raw_value = yaml_block_scalar_value(
                    lines, candidate_index + 1, candidate_indent
                )
                strip_comments = False
            values.append((raw_value, strip_comments))
        if not values and value_from:
            continue
        assignments.extend(
            (name, index + 1, value, strip_comments)
            for value, strip_comments in values
        )

    for index, line in enumerate(lines):
        merge_field = YAML_MERGE_FIELD.match(line)
        if merge_field is None:
            continue
        start, end, field_indent = yaml_mapping_span(
            lines, index, merge_field
        )
        fields: dict[str, str] = {"<<": merge_field.group("value")}
        strip_value_comments = True
        for candidate_index in range(start, end):
            candidate = yaml_structured_field(lines[candidate_index])
            if candidate is None:
                continue
            candidate_indent = len(candidate.group("indent")) + len(
                candidate.group("item") or ""
            )
            if candidate_indent != field_indent:
                continue
            if candidate.re is YAML_MERGE_FIELD:
                fields["<<"] = candidate.group("value")
                continue
            field_name = candidate.group("field").lower()
            raw_value = candidate.group("value")
            if (
                field_name == "value"
                and YAML_BLOCK_SCALAR.fullmatch(raw_value.strip()) is not None
            ):
                raw_value = yaml_block_scalar_value(
                    lines, candidate_index + 1, candidate_indent
                )
                strip_value_comments = False
            fields[field_name] = raw_value
        resolved = resolve_flow_fields(fields, anchors)
        if "name" not in resolved or "value" not in resolved:
            continue
        name = resolve_yaml_name(
            resolved["name"], path, scalar_anchors
        ).upper()
        if name in ASSIGNMENT_NAMES:
            assignments.append((
                name,
                index + 1,
                resolved["value"],
                strip_value_comments,
            ))
    return assignments


class JsonObject(list[tuple[str, object]]):
    """JSON object that preserves duplicate keys and document order."""


def reject_json_constant(value: str) -> None:
    raise ValueError(f"unsupported JSON constant: {value}")


def json_key_lines(text: str) -> dict[str, deque[int]]:
    locations: dict[str, deque[int]] = {}
    line = 1
    cursor = 0
    for token in JSON_STRING_TOKEN.finditer(text):
        line += text.count("\n", cursor, token.start())
        try:
            decoded = json.loads(token.group())
        except ValueError:
            line += text.count("\n", token.start(), token.end())
            cursor = token.end()
            continue
        if isinstance(decoded, str):
            upper = decoded.upper()
            if (
                upper in ASSIGNMENT_NAMES
                and JSON_KEY_SEPARATOR.match(text, token.end()) is not None
            ):
                locations.setdefault(upper, deque()).append(line)
        line += text.count("\n", token.start(), token.end())
        cursor = token.end()
    return locations


def json_assignments(path: Path, text: str) -> list[tuple[str, int]]:
    if path.suffix.lower() != ".json":
        return []
    locations = json_key_lines(text)
    try:
        document = json.loads(
            text,
            object_pairs_hook=JsonObject,
            parse_constant=reject_json_constant,
        )
    except (ValueError, RecursionError):
        return [
            (name, line)
            for name, lines in locations.items()
            for line in lines
        ]

    findings: list[tuple[str, int]] = []
    stack: list[tuple[str, object, object | None]] = [
        ("value", document, None)
    ]
    while stack:
        kind, value, child = stack.pop()
        if kind == "pair":
            key = value
            if not isinstance(key, str):
                continue
            upper = key.upper()
            queue = locations.get(upper)
            line = queue.popleft() if queue else 1
            if upper in ASSIGNMENT_NAMES and (
                child is not None
                and (
                    not isinstance(child, str)
                    or live_assignment(child)
                )
            ):
                findings.append((upper, line))
            stack.append(("value", child, None))
        elif isinstance(value, JsonObject):
            environment_names = [
                child.upper()
                for key, child in value
                if key.lower() == "name"
                and isinstance(child, str)
                and child.upper() in ASSIGNMENT_NAMES
            ]
            environment_values = [
                child for key, child in value if key.lower() == "value"
            ]
            for name in environment_names:
                if any(
                    child is not None
                    and (
                        not isinstance(child, str)
                        or live_assignment(child)
                    )
                    for child in environment_values
                ):
                    findings.append((name, 1))
            for key, nested in reversed(value):
                stack.append(("pair", key, nested))
        elif isinstance(value, list):
            for nested in reversed(value):
                stack.append(("value", nested, None))
    return findings


def decode_yaml_key(raw: str) -> str:
    def replace(match: re.Match[str]) -> str:
        digits = match.group("x") or match.group("u") or match.group("U")
        return chr(int(digits, 16))

    decoded = YAML_HEX_ESCAPE.sub(replace, raw)
    return BRACED_UNICODE_ESCAPE.sub(
        lambda match: chr(int(match.group("digits"), 16)), decoded
    )


def decode_javascript_string_contents(raw: str, quote: str) -> str | None:
    """Decode only JavaScript string escapes; never execute source text."""

    result: list[str] = []
    index = 0
    escapes = {
        "0": "\0",
        "b": "\b",
        "f": "\f",
        "n": "\n",
        "r": "\r",
        "t": "\t",
        "v": "\v",
        "\\": "\\",
        "'": "'",
        '"': '"',
        "`": "`",
    }
    while index < len(raw):
        character = raw[index]
        if character != "\\":
            if quote != "`" and character in "\r\n":
                return None
            result.append(character)
            index += 1
            continue
        index += 1
        if index >= len(raw):
            return None
        escaped = raw[index]
        if escaped == "\r":
            index += 1
            if index < len(raw) and raw[index] == "\n":
                index += 1
            continue
        if escaped == "\n":
            index += 1
            continue
        if escaped in escapes:
            result.append(escapes[escaped])
            index += 1
            continue
        if escaped == "x" and index + 2 < len(raw):
            digits = raw[index + 1:index + 3]
            if re.fullmatch(r"[0-9A-Fa-f]{2}", digits) is None:
                return None
            result.append(chr(int(digits, 16)))
            index += 3
            continue
        if escaped == "u":
            if index + 1 < len(raw) and raw[index + 1] == "{":
                end = raw.find("}", index + 2)
                if end < 0:
                    return None
                digits = raw[index + 2:end]
                if re.fullmatch(r"[0-9A-Fa-f]{1,6}", digits) is None:
                    return None
                codepoint = int(digits, 16)
                if codepoint > 0x10FFFF:
                    return None
                result.append(chr(codepoint))
                index = end + 1
                continue
            digits = raw[index + 1:index + 5]
            if len(digits) != 4 or re.fullmatch(r"[0-9A-Fa-f]{4}", digits) is None:
                return None
            result.append(chr(int(digits, 16)))
            index += 5
            continue
        return None
    return "".join(result)


def javascript_literal_end(expression: str) -> int | None:
    if not expression or expression[0] not in {"'", '"', "`"}:
        return None
    quote = expression[0]
    escaped = False
    for index, character in enumerate(expression[1:], 1):
        if escaped:
            escaped = False
        elif character == "\\":
            escaped = True
        elif character == quote:
            return index
        elif quote != "`" and character in "\r\n":
            return None
    return None


def split_javascript_concatenation(expression: str) -> list[str] | None:
    if len(expression) > 512:
        return None
    parts: list[str] = []
    start = 0
    quote: str | None = None
    escaped = False
    for index, character in enumerate(expression):
        if quote is not None:
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == quote:
                quote = None
            continue
        if character in {"'", '"', "`"}:
            quote = character
        elif character == "+":
            parts.append(expression[start:index].strip())
            start = index + 1
    if quote is not None:
        return None
    parts.append(expression[start:].strip())
    return parts if len(parts) <= MAX_JAVASCRIPT_CONSTANT_PARTS else None


def resolve_javascript_constant(
    expression: str,
    aliases: dict[str, str],
    depth: int = 0,
) -> str | None:
    if depth > MAX_JAVASCRIPT_CONSTANT_DEPTH or len(expression) > 512:
        return None
    expression = expression.strip()
    if not expression:
        return None
    parts = split_javascript_concatenation(expression)
    if parts is None:
        return None
    if len(parts) > 1:
        resolved: list[str] = []
        for part in parts:
            value = resolve_javascript_constant(part, aliases, depth + 1)
            if value is None:
                return None
            resolved.append(value)
        return "".join(resolved)
    expression = parts[0]
    end = javascript_literal_end(expression)
    if end == len(expression) - 1:
        if expression[0] == "`":
            body = expression[1:-1]
            substitutions = re.findall(r"(?<!\\)\$\{([^{}]*)\}", body)
            if "${" in body and len(substitutions) != body.count("${"):
                return None
            for substitution in substitutions:
                value = resolve_javascript_constant(substitution, aliases, depth + 1)
                if value is None:
                    return None
                body = body.replace("${" + substitution + "}", value, 1)
            return decode_javascript_string_contents(body, "`")
        return decode_javascript_string_contents(
            expression[1:-1], expression[0]
        )
    match = re.fullmatch(r"[A-Za-z_$][A-Za-z0-9_$]*", expression)
    return aliases.get(match.group()) if match is not None else None


def javascript_constant_aliases(path: Path, text: str) -> dict[str, str]:
    sanitized = strip_block_comments(path, text)
    aliases: dict[str, str] = {}
    for line in sanitized.splitlines():
        match = JAVASCRIPT_CONST_DECLARATION.search(line)
        if match is None:
            continue
        expression = line[match.end():].split(";", 1)[0].strip()
        expression = re.sub(r"\s+as\s+const\s*$", "", expression)
        value = resolve_javascript_constant(expression, aliases)
        if value is not None:
            aliases[match.group("name")] = value
    return aliases


def normalize_javascript_computed_keys(path: Path, text: str) -> str:
    if path.suffix.lower() not in JAVASCRIPT_SOURCE_SUFFIXES:
        return text
    sanitized = strip_block_comments(path, text)
    aliases = javascript_constant_aliases(path, sanitized)

    def replace(match: re.Match[str]) -> str:
        value = resolve_javascript_constant(match.group("expression"), aliases)
        canonical = value.upper() if value is not None else None
        if canonical not in ASSIGNMENT_NAMES:
            return match.group()
        return f'{match.group("prefix")}["{canonical}"]'

    normalized = JAVASCRIPT_COMPUTED_KEY.sub(replace, sanitized)
    return normalized if normalized != text else text


def normalize_yaml_sensitive_keys(path: Path, text: str) -> str:
    if path.suffix.lower() not in {".yml", ".yaml"}:
        return text

    def replace(match: re.Match[str]) -> str:
        decoded = decode_yaml_key(match.group("key"))
        if (
            decoded.upper() in ASSIGNMENT_NAMES
            or decoded.lower() in {"name", "value", "valuefrom"}
        ):
            return decoded
        return match.group()

    normalized = YAML_DOUBLE_QUOTED_KEY.sub(replace, text)

    def replace_environment_name(match: re.Match[str]) -> str:
        decoded = decode_yaml_key(match.group("key"))
        if decoded.upper() not in ASSIGNMENT_NAMES:
            return match.group()
        return match.group("prefix") + decoded

    return YAML_ENV_NAME_VALUE.sub(replace_environment_name, normalized)


def normalize_toml_sensitive_keys(path: Path, text: str) -> str:
    if path.suffix.lower() != ".toml":
        return text

    def replace(match: re.Match[str]) -> str:
        decoded = decode_yaml_key(match.group("key"))
        return decoded if decoded.upper() in ASSIGNMENT_NAMES else match.group()

    return TOML_DOUBLE_QUOTED_KEY.sub(replace, text)


def normalize_bracketed_sensitive_keys(path: Path, text: str) -> str:
    if path.suffix.lower() not in SOURCE_CODE_SUFFIXES:
        return text
    sanitized = strip_block_comments(path, text)
    changed = False

    def replace(match: re.Match[str]) -> str:
        nonlocal changed
        decoded = decode_yaml_key(match.group("key"))
        if decoded.upper() not in ASSIGNMENT_NAMES:
            return match.group()
        changed = True
        quote = match.group("quote")
        return f"[{quote}{decoded}{quote}]"

    normalized = BRACKETED_QUOTED_KEY.sub(replace, sanitized)
    return normalized if changed else text


def normalize_source_sensitive_identifiers(path: Path, text: str) -> str:
    if path.suffix.lower() not in SOURCE_CODE_SUFFIXES:
        return text
    sanitized = strip_block_comments(path, text)
    changed = False

    def replace(match: re.Match[str]) -> str:
        nonlocal changed
        raw = match.group()
        if "\\" not in raw:
            return raw
        decoded = decode_yaml_key(raw)
        if decoded.upper() not in ASSIGNMENT_NAMES:
            return raw
        changed = True
        return decoded

    normalized = ESCAPED_IDENTIFIER_TOKEN.sub(replace, sanitized)
    return normalized if changed else text


def scan_text(
    path: Path, text: str, _normalize_shell: bool = True
) -> list[tuple[str, int, str]]:
    if _normalize_shell and path.suffix.lower() == ".sh":
        normalized_shell, line_origins = normalize_shell_line_continuations(text)
        if normalized_shell != text:
            findings = scan_text(path, normalized_shell, False)
            remapped = [
                (
                    reported_path,
                    line_origins[line - 1] if 0 < line <= len(line_origins) else line,
                    detector,
                )
                for reported_path, line, detector in findings
            ]
            return list(dict.fromkeys(remapped))
    if path.suffix.lower() == ".java":
        text = normalize_java_lexical_escapes(text)
    findings: list[tuple[str, int, str]] = []
    lines = text.splitlines()
    for number, line in enumerate(lines, 1):
        for detector, pattern in TOKEN_PATTERNS:
            if pattern.search(line):
                findings.append((path.as_posix(), number, detector))
        matches = []
        patterns = [ASSIGNMENT, SPACE_ASSIGNMENT]
        if path.suffix.lower() == ".properties":
            patterns.append(BARE_SPACE_ASSIGNMENT)
        for pattern in patterns:
            match = pattern.match(line)
            if match is not None:
                matches.append(match)
        name_spans = {candidate.span("name") for candidate in matches}
        for candidate in (
            *STRUCTURED_ASSIGNMENT.finditer(line),
            *INLINE_ASSIGNMENT.finditer(line),
            *BRACKETED_ASSIGNMENT.finditer(line),
        ):
            name_start = candidate.start("name")
            if name_start >= 2 and line[name_start - 2:name_start] == "${":
                continue
            if candidate.span("name") not in name_spans:
                matches.append(candidate)
                name_spans.add(candidate.span("name"))
        reported_assignments: set[str] = set()
        for match in matches:
            name = match.group("name").upper()
            raw_value = match.group("value")
            if (
                path.suffix.lower() in {".yml", ".yaml"}
                and (
                    raw_value.lstrip().startswith("#")
                    or YAML_BLOCK_SCALAR.fullmatch(raw_value.strip()) is not None
                )
            ):
                continue
            if (
                name not in reported_assignments
                and live_assignment(assignment_value(raw_value, path))
                and not source_code_reference(path, raw_value)
            ):
                findings.append((
                    path.as_posix(),
                    number,
                    f"live-looking value assigned to {name}",
                ))
                reported_assignments.add(name)
        for name, value in shell_parameter_assignments(line):
            name = name.upper()
            if name not in reported_assignments and live_assignment(value):
                findings.append((
                    path.as_posix(),
                    number,
                    f"live-looking value assigned to {name}",
                ))
                reported_assignments.add(name)
        if PRIVATE_BEGIN.search(line):
            findings.append((path.as_posix(), number, "private key block"))
    for name, number, value, strip_comments in multiline_assignments(path, text):
        if (
            live_assignment(assignment_value(value, path, strip_comments))
            and not multiline_code_reference(path, value)
        ):
            findings.append((
                path.as_posix(),
                number,
                f"live-looking value assigned to {name.upper()}",
            ))
    for name, number in json_assignments(path, text):
        findings.append((
            path.as_posix(),
            number,
            f"live-looking value assigned to {name}",
        ))
    for name, number, value, strip_comments in structured_environment_assignments(
        path, text
    ):
        if live_assignment(assignment_value(value, path, strip_comments)):
            findings.append((
                path.as_posix(),
                number,
                f"live-looking value assigned to {name.upper()}",
            ))
    normalized_yaml = normalize_yaml_sensitive_keys(path, text)
    if normalized_yaml != text:
        findings.extend(scan_text(path, normalized_yaml))
    normalized_toml = normalize_toml_sensitive_keys(path, text)
    if normalized_toml != text:
        findings.extend(scan_text(path, normalized_toml))
    normalized_brackets = normalize_bracketed_sensitive_keys(path, text)
    if normalized_brackets != text:
        findings.extend(scan_text(path, normalized_brackets))
    normalized_computed = normalize_javascript_computed_keys(path, text)
    if normalized_computed != text:
        findings.extend(scan_text(path, normalized_computed))
    normalized_source = normalize_source_sensitive_identifiers(path, text)
    if normalized_source != text:
        findings.extend(scan_text(path, normalized_source))
    return list(dict.fromkeys(findings))


def scan_repository(root: Path) -> tuple[list[tuple[str, int, str]], int, int]:
    root = root.resolve()
    findings: list[tuple[str, int, str]] = []
    index = index_blobs(root)
    head = head_blobs(root)
    paths = set(index) | set(head)
    oids = set(index.values()) | set(head.values())
    sizes = blob_sizes(root, oids)
    readable_oids = {oid for oid, size in sizes.items() if size <= MAX_TEXT_BYTES}
    contents = read_blobs(root, readable_oids)
    text_files = 0

    for relative in sorted(paths, key=lambda path: path.as_posix()):
        if sensitive_filename(relative):
            findings.append((relative.as_posix(), 0, "sensitive tracked filename"))

        snapshots: dict[bytes, set[str]] = {}
        for source, oid in (("HEAD", head.get(relative)), ("index", index.get(relative))):
            if oid is None:
                continue
            if sizes[oid] > MAX_TEXT_BYTES:
                findings.append((
                    relative.as_posix(),
                    0,
                    f"tracked file exceeds scan size limit [{source}]",
                ))
                continue
            snapshots.setdefault(contents[oid], set()).add(source)

        path = root / relative
        try:
            if path.is_symlink():
                data = path.readlink().as_posix().encode()
            elif path.exists():
                size = path.stat().st_size
                if size > MAX_TEXT_BYTES:
                    findings.append((
                        relative.as_posix(),
                        0,
                        "tracked file exceeds scan size limit [working tree]",
                    ))
                    data = None
                else:
                    data = path.read_bytes()
            else:
                data = None
        except (OSError, ValueError) as error:
            findings.append((
                relative.as_posix(),
                0,
                f"working-tree inspection failed ({type(error).__name__})",
            ))
            continue
        if data is not None:
            snapshots.setdefault(data, set()).add("working tree")

        for snapshot, sources in snapshots.items():
            text, decode_error = decode_text_snapshot(relative, snapshot)
            label = source_label(sources)
            if decode_error is not None:
                findings.append((
                    relative.as_posix(), 0, f"{decode_error} [{label}]"
                ))
                continue
            if text is None:
                continue
            text_files += 1
            for reported_path, line, detector in scan_text(relative, text):
                findings.append((reported_path, line, f"{detector} [{label}]"))
    return sorted(set(findings)), len(paths), text_files


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    root = parser.parse_args().root
    try:
        findings, tracked, text_files = scan_repository(root)
    except (OSError, subprocess.CalledProcessError, UnicodeError, ValueError) as error:
        print(f"Tracked credential hygiene: ERROR ({type(error).__name__})", file=sys.stderr)
        return 2
    if findings:
        print("Tracked credential hygiene: FAIL", file=sys.stderr)
        for path, line, detector in findings:
            location = f"{path}:{line}" if line else path
            print(f"  - {location}: {detector}", file=sys.stderr)
        print(
            f"Inspected {tracked} tracked paths ({text_files} decoded text snapshots "
            "across HEAD, index, and working tree). "
            "Secret values were not printed.",
            file=sys.stderr,
        )
        return 1
    print(
        f"Tracked credential hygiene: PASS ({tracked} tracked paths; "
        f"{text_files} decoded text snapshots across HEAD, index, and working tree)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
