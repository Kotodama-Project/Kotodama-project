from pathlib import Path
import unittest

ROOT=Path(__file__).resolve().parents[1]


class RetentionRuntimeSchemaTests(unittest.TestCase):
    def test_independent_template_ships_the_canonical_receipt_schema_bytes(self):
        self.assertEqual((ROOT/'schemas/retention-deletion-receipt.schema.json').read_bytes(),
            (ROOT/'runtime/discord-template/src/retention-deletion-receipt.schema.json').read_bytes())
