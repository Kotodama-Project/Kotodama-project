"""Portable depth refusals must not depend on the interpreter's recursion limit."""
import json
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import validate_resolved_compose_candidate as strict


class StrictJsonDepthTests(unittest.TestCase):
    def test_accepts_64_containers_and_rejects_65(self):
        for levels, accepted in [(63, True), (64, True), (65, False), (5000, False)]:
            content = '{"value":' + '[' * (levels - 1) + '0' + ']' * (levels - 1) + '}'
            with self.subTest(levels=levels):
                if accepted:
                    self.assertIsInstance(strict.loads_strict_json(content), dict)
                else:
                    with self.assertRaises(strict.StrictJsonError):
                        strict.loads_strict_json(content)

    def test_overdeep_input_is_rejected_before_the_json_decoder_runs(self):
        content = '{"value":' + '[' * 64 + '0' + ']' * 64 + '}'
        with mock.patch.object(strict.json, "loads") as decoder:
            with self.assertRaises(strict.StrictJsonError):
                strict.loads_strict_json(content)
            decoder.assert_not_called()

    def test_brackets_and_escaped_quotes_inside_strings_do_not_count(self):
        value = {"text": '[{' * 5000 + '\\"quoted\\"' + '}]' * 5000, "escaped": '\\\\"[{'}
        self.assertEqual(strict.loads_strict_json(json.dumps(value)), value)

    def test_existing_strict_boundaries_are_preserved(self):
        for text in ['{"a":1,"a":2}', '{"a":NaN}', '[]', '{"a":[}']:
            with self.subTest(text=text), self.assertRaises(ValueError):
                strict.loads_strict_json(text)
        with self.assertRaises(UnicodeDecodeError):
            strict.load_strict_json_bytes(b'\xff')


if __name__ == "__main__":
    unittest.main()
