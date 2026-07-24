import tempfile
import unittest
from pathlib import Path

from tme3bot.utility import UtilityRunner


class UtilitySummaryTests(unittest.TestCase):
    def test_organizer_log_is_reduced_to_useful_summary(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            folder = Path(temp_dir)
            (folder / "log.txt").write_text(
                "\n".join(
                    [
                        "messages.json | messages.html/message1 | start | bp01",
                        "messages.json | messages.html/message1 | moved 4 items",
                        "messages.json | messages.html/message2 | start | unresolved-messages-html-message2",
                        "messages.json | messages.html/message2 | moved 2 items",
                    ]
                ),
                encoding="utf-8",
            )

            self.assertEqual(
                UtilityRunner._organizer_log_summary(folder),
                {
                    "groups_created": 2,
                    "items_moved": 6,
                    "unresolved_groups": 1,
                    "log_lines": 4,
                },
            )


if __name__ == "__main__":
    unittest.main()
