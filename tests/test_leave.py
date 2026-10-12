from pathlib import Path
from types import SimpleNamespace
import unittest

from tme3bot.leave import LeaveService


class RecordingRunner:
    def __init__(self):
        self.command = None
        self.options = None

    def run(self, command, **kwargs):
        self.command = command
        self.options = kwargs
        return SimpleNamespace(returncode=0, stdout='{"chat_ref":"@channel","ok":true}\n', stderr="")


class LeaveServiceTests(unittest.TestCase):
    def test_leave_runs_directly_with_export_lane_storage_and_home(self):
        runner = RecordingRunner()
        home = Path("/data/user1")
        service = LeaveService(
            SimpleNamespace(
                leave_helper_binary="/usr/local/bin/tdl-leave",
                tdl_export_storage=home / ".tdl",
                tdl_export_namespace="export-lane",
                tdl_export_home=home,
            ),
            runner,
        )

        result = service.leave(["@channel"])

        self.assertEqual(result.succeeded, ["@channel"])
        self.assertEqual(runner.command[0], "/usr/local/bin/tdl-leave")
        self.assertNotIn("runuser", runner.command)
        self.assertEqual(
            runner.command[runner.command.index("--storage") + 1],
            str(home / ".tdl" / "data"),
        )
        self.assertEqual(
            runner.command[runner.command.index("--namespace") + 1],
            "export-lane",
        )
        self.assertEqual(runner.options["env"]["HOME"], str(home))


if __name__ == "__main__":
    unittest.main()
