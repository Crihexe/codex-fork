"""Pagination, fork boundaries, and previews, without creating real chats."""

from contextlib import contextmanager, redirect_stderr, redirect_stdout
import io
import unittest
from unittest.mock import patch

import codex_fork


def turn(identifier, text="", status="completed"):
    return {"id": identifier, "status": status,
            "items": [{"type": "userMessage", "content": [{"type": "text", "text": text}]}]}


class ForkTests(unittest.TestCase):
    def test_turn_number_includes_inherited_and_interrupted_turns_across_pages(self):
        calls = []

        def rpc(method, params):
            calls.append((method, params))
            if "cursor" not in params:
                return {"data": [turn("inherited-1"), turn("inherited-2", status="interrupted")],
                        "nextCursor": "page-2"}
            return {"data": [turn("local-1", "explain this")], "nextCursor": None}

        selected = codex_fork.select_turn(rpc, "source", 3, "explain")
        self.assertEqual(selected["id"], "local-1")
        self.assertEqual(calls[0][1]["sortDirection"], "asc")
        self.assertEqual(calls[1][1]["cursor"], "page-2")

    def test_missing_turn_and_active_turn_are_rejected(self):
        rpc = lambda method, params: {"data": [turn("active", status="inProgress")], "nextCursor": None}
        with self.assertRaisesRegex(RuntimeError, "still in progress"):
            codex_fork.select_turn(rpc, "source", 1)
        with self.assertRaisesRegex(RuntimeError, "contains 1 turns"):
            codex_fork.select_turn(rpc, "source", 2)

    def test_fork_uses_selected_id_and_checks_new_history(self):
        calls = []

        def rpc(method, params):
            calls.append((method, params))
            if method == "thread/fork":
                return {"thread": {"id": "new-chat"}}
            return {"data": [turn("inherited"), turn("selected")], "nextCursor": None}

        self.assertEqual(codex_fork.create_fork(rpc, "source", turn("selected"), 2), "new-chat")
        self.assertEqual(calls[0], ("thread/fork", {
            "threadId": "source", "lastTurnId": "selected", "excludeTurns": True}))
        self.assertEqual(calls[1][1]["itemsView"], "notLoaded")

    def test_wrong_fork_boundary_is_reported_with_created_id(self):
        def rpc(method, params):
            if method == "thread/fork":
                return {"thread": {"id": "new-chat"}}
            return {"data": [turn("selected"), turn("later")], "nextCursor": None}

        with self.assertRaisesRegex(RuntimeError, "Fork created with ID new-chat"):
            codex_fork.create_fork(rpc, "source", turn("selected"), 1)

    def test_preview_and_prefix_mismatch_never_create_a_fork(self):
        calls = []

        @contextmanager
        def server():
            def rpc(method, params):
                calls.append(method)
                return {"data": [turn("selected", "explain this")], "nextCursor": None}
            yield rpc

        with patch.object(codex_fork, "app_server", server), redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            self.assertEqual(codex_fork.main(["source", "1", "--dry-run"]), 0)
            self.assertEqual(codex_fork.main(["source", "1", "--expect-prefix", "other"]), 1)
        self.assertNotIn("thread/fork", calls)

    def test_failed_verification_retains_created_chat_id(self):
        def rpc(method, params):
            if method == "thread/fork":
                return {"thread": {"id": "new-chat"}}
            return {"data": [{}], "nextCursor": None}

        with self.assertRaisesRegex(RuntimeError, "Fork created with ID new-chat"):
            codex_fork.create_fork(rpc, "source", turn("selected"), 1)

    def test_successful_cli_prints_only_resume_command_to_stdout(self):
        @contextmanager
        def server():
            def rpc(method, params):
                if method == "thread/fork":
                    return {"thread": {"id": "new-chat"}}
                return {"data": [turn("selected", "explain this")], "nextCursor": None}
            yield rpc

        output = io.StringIO()
        with patch.object(codex_fork, "app_server", server), redirect_stdout(output), redirect_stderr(io.StringIO()):
            self.assertEqual(codex_fork.main(["source", "1"]), 0)
        self.assertEqual(output.getvalue(), "codex resume new-chat\n")


if __name__ == "__main__":
    unittest.main()
