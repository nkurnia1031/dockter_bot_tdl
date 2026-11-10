from __future__ import annotations

import unittest
from types import SimpleNamespace

from tme3bot.chat_send import safe_chat_send_retry_paths


class ChatSendApiTests(unittest.TestCase):
    def test_retry_includes_only_confirmed_failed_paths_within_selected_roots(self):
        job = SimpleNamespace(
            payload={"folders": ["/workspace/books"]},
            result={"value": {"items": [
                {"path": "books/retry.txt", "status": "failed", "retryable": True},
                {"path": "books/ambiguous.txt", "status": "ambiguous", "retryable": False},
                {"path": "books/sent.txt", "status": "succeeded", "retryable": False},
                {"path": "other/outside.txt", "status": "failed", "retryable": True},
                {"path": "books/../escape.txt", "status": "failed", "retryable": True},
            ]}},
        )

        self.assertEqual(safe_chat_send_retry_paths(job), ["books/retry.txt"])

    def test_retry_allows_selected_workspace_root_and_rejects_paths_outside_it(self):
        job = SimpleNamespace(
            payload={"folders": ["/workspace"]},
            result={"items": [
                {"path": "root.txt", "status": "failed", "retryable": True},
                {"path": "../outside.txt", "status": "failed", "retryable": True},
            ]},
        )

        self.assertEqual(safe_chat_send_retry_paths(job), ["root.txt"])

    def test_retry_preserves_backslash_in_a_linux_filename(self):
        job = SimpleNamespace(
            payload={"folders": ["/workspace"]},
            result={"value": {"items": [
                {"path": r"folder\literal\name.txt", "status": "failed", "retryable": True},
            ]}},
        )

        self.assertEqual(
            safe_chat_send_retry_paths(job),
            [r"folder\literal\name.txt"],
        )


if __name__ == "__main__":
    unittest.main()
