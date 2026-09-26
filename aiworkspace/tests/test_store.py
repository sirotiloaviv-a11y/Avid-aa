import sqlite3
import tempfile
import unittest
from pathlib import Path

from aiworkspace.store import Store


class StoreTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "nested" / "db.sqlite3"
        self.store = Store(self.path)

    def tearDown(self):
        self.tmp.cleanup()

    def test_create_list_get(self):
        a = self.store.create_conversation("first")
        b = self.store.create_conversation("second")
        ids = [c.id for c in self.store.list_conversations()]
        self.assertEqual(set(ids), {a.id, b.id})
        self.assertEqual(self.store.get_conversation(a.id).title, "first")
        self.assertIsNone(self.store.get_conversation("0" * 32))

    def test_most_recently_active_first(self):
        a = self.store.create_conversation("a")
        self.store.create_conversation("b")
        self.store.add_message(a.id, "user", "hi")
        self.assertEqual(self.store.list_conversations()[0].id, a.id)

    def test_rename(self):
        c = self.store.create_conversation("old")
        renamed = self.store.rename_conversation(c.id, "חדש")
        self.assertEqual(renamed.title, "חדש")
        self.assertIsNone(self.store.rename_conversation("f" * 32, "x"))

    def test_delete_cascades_to_messages(self):
        c = self.store.create_conversation("c")
        self.store.add_message(c.id, "user", "hello")
        self.assertTrue(self.store.delete_conversation(c.id))
        self.assertFalse(self.store.delete_conversation(c.id))
        self.assertEqual(self.store.list_messages(c.id), [])
        with sqlite3.connect(self.path) as db:
            self.assertEqual(
                db.execute("SELECT COUNT(*) FROM messages").fetchone()[0], 0
            )

    def test_message_lifecycle_and_order(self):
        c = self.store.create_conversation("c")
        u = self.store.add_message(c.id, "user", "question")
        a = self.store.add_message(
            c.id,
            "assistant",
            "",
            status="streaming",
            provider="demo",
            model="demo",
            simulated=True,
        )
        self.store.update_message_content(a.id, "partial")
        final = self.store.finish_message(
            a.id, "full answer", "complete", stop_reason="end_turn"
        )
        self.assertEqual(final.content, "full answer")
        self.assertTrue(final.simulated)
        msgs = self.store.list_messages(c.id)
        self.assertEqual([m.id for m in msgs], [u.id, a.id])
        self.assertEqual(msgs[1].stop_reason, "end_turn")

    def test_rejects_unknown_status_and_role(self):
        c = self.store.create_conversation("c")
        with self.assertRaises(ValueError):
            self.store.add_message(c.id, "user", "x", status="weird")
        with self.assertRaises(sqlite3.IntegrityError):
            self.store.add_message(c.id, "system", "x")

    def test_upgrades_phase1_database(self):
        old = Path(self.tmp.name) / "old.sqlite3"
        with sqlite3.connect(old) as db:
            db.executescript(
                "CREATE TABLE conversations (id TEXT PRIMARY KEY, title TEXT NOT NULL,"
                " created_at REAL NOT NULL, updated_at REAL NOT NULL);"
                "CREATE TABLE messages (id TEXT PRIMARY KEY, conversation_id TEXT NOT NULL"
                " REFERENCES conversations(id) ON DELETE CASCADE, role TEXT NOT NULL,"
                " content TEXT NOT NULL, status TEXT NOT NULL, provider TEXT, model TEXT,"
                " simulated INTEGER NOT NULL DEFAULT 0, error TEXT, stop_reason TEXT,"
                " created_at REAL NOT NULL);"
                "INSERT INTO conversations VALUES ('c1', 'old chat', 1, 1);"
                "INSERT INTO messages (id, conversation_id, role, content, status,"
                " created_at) VALUES ('m1', 'c1', 'user', 'kept', 'complete', 1);"
            )
        store = Store(old)
        msg = store.list_messages("c1")[0]
        self.assertEqual((msg.content, msg.output_tokens), ("kept", None))
        a = store.add_message("c1", "assistant", "", status="streaming")
        done = store.finish_message(
            a.id,
            "x",
            "incomplete",
            stop_reason="max_tokens",
            response_model="m",
            input_tokens=1,
            output_tokens=2,
        )
        self.assertEqual((done.status, done.output_tokens), ("incomplete", 2))

    def test_history_survives_restart(self):
        c = self.store.create_conversation("persisted")
        self.store.add_message(c.id, "user", "remember me")
        a = self.store.add_message(c.id, "assistant", "", status="streaming")
        self.store.update_message_content(a.id, "half a rep")

        reopened = Store(self.path)  # simulates a process restart
        self.assertEqual(reopened.get_conversation(c.id).title, "persisted")
        msgs = reopened.list_messages(c.id)
        self.assertEqual(msgs[0].content, "remember me")
        # A reply cut off by the restart keeps its text and is marked as an error.
        self.assertEqual(msgs[1].status, "error")
        self.assertEqual(msgs[1].content, "half a rep")
        self.assertIn("restart", msgs[1].error)


if __name__ == "__main__":
    unittest.main()
