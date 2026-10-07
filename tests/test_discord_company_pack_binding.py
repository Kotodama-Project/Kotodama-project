"""Synthetic SQLite contract tests; the Node runtime owns the actual Task state."""
import copy
from contextlib import closing
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import run_company_pack_task as executor


class DiscordCompanyPackBindingTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name).resolve()
        self.output = self.base / "outputs"
        self.output.mkdir()
        self.database = self.base / "owner.sqlite"
        self.binding_path = self.base / "binding.json"
        self.task_id = "task-00000000-0000-4000-8000-000000000001"
        self.source_key, self.intent_id = "a" * 64, "b" * 64
        actor, guild, channel = ("100000000000000002", "100000000000000001", "100000000000000003")
        self.source = {"key": self.source_key, "provider": "discord", "guildId": guild, "channelId": channel,
            "sourceId": "100000000000000020", "actorId": actor, "readers": [actor], "revision": 100,
            "final": True, "text": "fixture-company", "metadata": {"kind": "trusted_cli", "command": {
                "request": "fixture-company", "action": "create_company_pack"}}}
        self.task = {"id": self.task_id, "actor": actor, "room": f"discord:{guild}:{channel}",
            "source_key": self.source_key, "source_revision": 100, "request": "fixture-company",
            "action": "create_company_pack", "requiredActions": ["create_company_pack"], "intentIds": [self.intent_id]}
        self.intent = {"kind": "request", "explicit": True, "complete": True, "origin": "explicit_command",
            "source_key": self.source_key, "source_revision": 100, "action": "create_company_pack", "request": "fixture-company"}
        with closing(sqlite3.connect(self.database)) as connection, connection:
            connection.executescript("""
                CREATE TABLE tasks(id TEXT PRIMARY KEY,actor TEXT,room TEXT,source_key TEXT,revision INTEGER,state TEXT,body TEXT);
                CREATE TABLE sources(key TEXT PRIMARY KEY,revision INTEGER,fingerprint TEXT,body TEXT);
                CREATE TABLE intents(id TEXT PRIMARY KEY,source_key TEXT,revision INTEGER,body TEXT);
            """)
            connection.execute("INSERT INTO tasks VALUES(?,?,?,?,?,?,?)", (self.task_id, actor, self.task["room"], self.source_key, 1, "running", json.dumps(self.task)))
            connection.execute("INSERT INTO sources VALUES(?,?,?,?)", (self.source_key, 100, "c" * 64, json.dumps(self.source)))
            connection.execute("INSERT INTO intents VALUES(?,?,?,?)", (self.intent_id, self.source_key, 100, json.dumps(self.intent)))
        self.request = {"kind": "company_pack_task_request", "operation": "CREATE_COMPANY_PACK",
            "operation_key": self.task_id + "-r1", "task_ref": "task:" + self.task_id,
            "work_order_ref": "work-order:synthetic-caller", "capability_ref": "capability:synthetic-caller",
            "authorized_output_root": str(self.output), "source": executor.source_binding(),
            "pack_id": "fixture-company", "human_intent_ref": "human-intent:" + self.intent_id,
            "authority_expires_at": (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(),
            "retention_policy_ref": "retention-policy:synthetic-caller"}
        self.binding = {"kind": "company_pack_discord_task_binding", "version": "1.0", "owner_kind": "local",
            "owner_ref": "ref/local/discord-owner", "database_path": str(self.database), "task_id": self.task_id,
            "task_revision": 1, "source_key": self.source_key, "source_revision": 100,
            "required_actions": ["create_company_pack"], "request_sha256": executor.digest(self.request)}
        self.save_binding()

    def save_binding(self):
        self.binding_path.write_bytes(executor.canonical(self.binding))

    def update_document(self, table, value):
        self.assertIn(table, ("tasks", "sources", "intents"))
        with closing(sqlite3.connect(self.database)) as connection, connection:
            connection.execute(f"UPDATE {table} SET body=?", (json.dumps(value),))

    def execute(self):
        return executor.execute(self.request, self.output, self.binding_path)

    def assert_refused(self, code):
        with self.assertRaises(executor.Refused) as caught:
            self.execute()
        self.assertEqual(code, str(caught.exception))
        self.assertFalse((self.output / self.request["operation_key"]).exists())

    def test_real_pack_and_receipt_readback_preserve_one_owner_and_original_rows(self):
        before = self.database.read_bytes()
        receipt = self.execute()
        self.assertEqual("LOCAL_PASS", receipt["status"])
        self.assertFalse(receipt["task_state_changed"])
        self.assertFalse(receipt["record_binding"]["authority_verified"])
        self.assertEqual(1, receipt["record_binding"]["task_revision"])
        self.assertEqual(before, self.database.read_bytes())
        self.assertEqual(receipt, self.execute())
        with closing(sqlite3.connect(self.database)) as connection, connection:
            self.assertEqual([(self.task_id, 1, "running")], connection.execute("SELECT id,revision,state FROM tasks").fetchall())
        self.assertTrue((self.output / self.request["operation_key"] / "pack" / "manifest.json").is_file())
        self.assertFalse((self.base / "task.json").exists())

    def test_unknown_field_remote_owner_and_boolean_revision_are_refused(self):
        original = copy.deepcopy(self.binding)
        for change, code in [({"task_state_change": True}, "DISCORD_BINDING_INVALID"), ({"owner_kind": "remote"}, "DISCORD_LOCAL_OWNER_REQUIRED"), ({"task_revision": True}, "DISCORD_REVISION_INVALID")]:
            self.binding = {**original, **change}
            self.save_binding()
            self.assert_refused(code)

    def test_current_task_and_source_revisions_and_running_state_are_required(self):
        for field, value, code in [("task_revision", 2, "DISCORD_TASK_NOT_RUNNING"), ("source_revision", 101, "DISCORD_SOURCE_CHANGED")]:
            old = self.binding[field]
            self.binding[field] = value
            self.save_binding()
            self.assert_refused(code)
            self.binding[field] = old
        self.save_binding()
        with closing(sqlite3.connect(self.database)) as connection, connection:
            connection.execute("UPDATE tasks SET state='uncertain'")
        self.assert_refused("DISCORD_TASK_NOT_RUNNING")

    def test_model_intent_and_access_revocation_never_create_a_pack(self):
        self.update_document("intents", {**self.intent, "origin": "model"})
        self.assert_refused("DISCORD_EXPLICIT_COMMAND_REQUIRED")
        self.update_document("intents", self.intent)
        self.update_document("sources", {**self.source, "readers": []})
        self.assert_refused("DISCORD_SOURCE_ACCESS_DENIED")

    def test_request_capability_change_requires_a_matching_binding(self):
        self.request["capability_ref"] = "capability:different-caller"
        self.assert_refused("DISCORD_REQUEST_MISMATCH")

    def test_same_operation_key_with_another_task_revision_cannot_borrow_the_result(self):
        self.execute()
        with closing(sqlite3.connect(self.database)) as connection, connection:
            connection.execute("UPDATE tasks SET revision=2")
        self.binding["task_revision"] = 2
        self.save_binding()
        with self.assertRaisesRegex(executor.Refused, "OPERATION_KEY_OR_OWNERSHIP_MISMATCH"):
            self.execute()

    def test_source_or_task_change_during_creation_preserves_incomplete_candidate(self):
        create = executor.create_company_pack
        def changed(*args, **kwargs):
            result = create(*args, **kwargs)
            with closing(sqlite3.connect(self.database)) as connection, connection:
                connection.execute("UPDATE tasks SET revision=2,state='stopping'")
            return result
        with patch.object(executor, "create_company_pack", side_effect=changed):
            with self.assertRaisesRegex(executor.Refused, "DISCORD_TASK_NOT_RUNNING"):
                self.execute()
        operation = self.output / self.request["operation_key"]
        self.assertTrue((operation / "pack").is_dir())
        self.assertFalse((operation / "receipt.json").exists())

    def test_real_cli_refuses_without_explicit_output_authorization_then_returns_bound_receipt(self):
        path = self.base / "request.json"
        path.write_bytes(executor.canonical(self.request))
        command = [sys.executable, "-B", str(ROOT / "tools/run_company_pack_task.py"), str(path), "--record-binding", str(self.binding_path)]
        refused = subprocess.run(command, capture_output=True, check=False)
        self.assertEqual("EXPLICIT_LOCAL_AUTHORIZATION_REQUIRED", json.loads(refused.stdout)["error"])
        completed = subprocess.run([*command, "--authorize-local-output-root", str(self.output)], capture_output=True, check=False)
        self.assertEqual(0, completed.returncode, completed.stdout.decode("utf-8"))
        self.assertEqual(self.task_id, json.loads(completed.stdout)["task_ref"].removeprefix("task:"))

    def test_readonly_owner_lookup_observes_the_live_wal_revision(self):
        connection = sqlite3.connect(self.database)
        self.addCleanup(connection.close)
        self.assertEqual("wal", connection.execute("PRAGMA journal_mode=WAL").fetchone()[0])
        connection.execute("UPDATE tasks SET revision=2")
        connection.commit()
        self.assertTrue(Path(str(self.database) + "-wal").is_file())
        self.binding["task_revision"] = 2
        self.save_binding()
        self.assertEqual(2, self.execute()["record_binding"]["task_revision"])

    def test_receipt_contains_binding_digests_but_not_private_source_metadata(self):
        self.source["metadata"]["internalNote"] = "synthetic-private-source-note"
        self.update_document("sources", self.source)
        receipt = self.execute()
        self.assertNotIn("synthetic-private-source-note", json.dumps(receipt))
        self.assertEqual(64, len(receipt["record_binding"]["owner_snapshot_sha256"]))


if __name__ == "__main__":
    unittest.main()
