"""Shared recognizable-credential patterns for payload rejection and logs."""
import re

TOKEN_PATTERN = re.compile(
    r"\b(?:sk-[A-Za-z0-9_-]{8,}|pk-[A-Za-z0-9_-]{8,}|gh[pousr]_[A-Za-z0-9_-]{8,}|"
    r"xox[baprs]-[A-Za-z0-9-]{8,}|AIza[A-Za-z0-9_-]{20,}|ya29\.[A-Za-z0-9._-]{10,}|AKIA[0-9A-Z]{16})\b"
)
KEY_PATTERN = re.compile(
    r'''(?i)["']?\b(?:api[_ -]?key|access[_ -]?token|refresh[_ -]?token|auth[_ -]?token|token|password|passwd|secret|credential|authorization)\b["']?\s*[:=]'''
)
