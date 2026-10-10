"""Generate the standalone Node runtime's copy of the canonical public schema."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
source = ROOT / "schemas/surface-event-envelope.schema.json"
target = ROOT / "runtime/discord-template/schemas/surface-event-envelope.schema.json"
target.parent.mkdir(parents=True, exist_ok=True)
target.write_bytes(source.read_bytes())
print("Updated runtime surface schema from the canonical schema")
