import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

from tme3bot.tdl import (
    SubprocessRunner,
    TDLClient,
    TDLCommandError,
    TDLStalledError,
    clean_tdl_output_line,
    decode_process_output,
    is_nonsemantic_tdl_output_line,
    parse_tdl_progress_line,
)


class FakeRunner:
    def __init__(self, mode: str) -> None:
        self.mode = mode
        self.commands: list[list[str]] = []
        self.envs: list[dict[str, str] | None] = []
        self.caption_contents: list[str] = []
        self.export_output_modes: list[int] = []
        self.export_calls = 0

    def run(
        self,
        command: list[str],
        env: dict[str, str] | None = None,
        log_prefix: str = "tdl",
        stall_timeout_seconds: int = 0,
        progress_callback=None,
        output_callback=None,
    ) -> subprocess.CompletedProcess[str]:
        self.commands.append(command)
        self.envs.append(env)
        if "--caption" in command:
            self.caption_contents.append(Path(command[command.index("--caption") + 1]).read_text(encoding="utf-8"))

        if "chat" in command and "export" in command:
            if self.mode == "export_failure":
                return subprocess.CompletedProcess(command, 1, "", "export failed")

            output_path = Path(command[command.index("-o") + 1])
            if output_path.exists():
                self.export_output_modes.append(output_path.stat().st_mode & 0o777)
            payload = {"messages": []}
            if self.mode in {"success", "download_failure"}:
                payload = {
                    "messages": [
                        {
                            "id": 7,
                            "type": "document",
                            "file_name": "sample.txt",
                        }
                    ]
                }
            if self.mode == "delayed_upload" and self.export_calls >= 2:
                payload = {
                    "messages": [
                        {
                            "id": 4321,
                            "type": "document",
                            "caption": "Backup node=local run=abc Part: backup.7z.001",
                        }
                    ]
                }
            self.export_calls += 1
            output_path.write_text(json.dumps(payload), encoding="utf-8")
            return subprocess.CompletedProcess(command, 0, "ok", "")

        if "dl" in command:
            if self.mode == "download_failure":
                return subprocess.CompletedProcess(command, 1, "", "download failed")
            return subprocess.CompletedProcess(command, 0, "ok", "")

        if "up" in command:
            if self.mode == "delayed_upload":
                return subprocess.CompletedProcess(command, 0, "... done! [394.96 KB]", "")
            return subprocess.CompletedProcess(command, 0, "Upload File(1):987 -> /tmp/a.pdf ... done!", "")

        raise AssertionError(f"Unexpected command: {command}")


class TDLClientTests(unittest.TestCase):
    def test_decodes_invalid_utf8_without_losing_surrounding_output(self) -> None:
        self.assertEqual(
            decode_process_output(b"before \xa8 after\n"),
            "before \\xa8 after\n",
        )

    def test_runner_preserves_and_logs_full_non_utf8_failure_output(self) -> None:
        env = dict(os.environ)
        env["TDL_FORCE_PTY"] = "0"
        command = [
            sys.executable,
            "-c",
            (
                "import sys; "
                "sys.stdout.buffer.write(b'before \\xa8 after\\n'); "
                "sys.stderr.buffer.write(b'fatal \\xff detail\\n'); "
                "raise SystemExit(2)"
            ),
        ]

        with self.assertLogs("tme3bot.tdl", level="ERROR") as captured:
            result = SubprocessRunner().run(command, env=env, log_prefix="tdl-test")

        self.assertEqual(result.returncode, 2)
        self.assertIn("before \\xa8 after", result.stdout)
        self.assertIn("fatal \\xff detail", result.stderr)
        logs = "\n".join(captured.output)
        self.assertIn("complete captured output follows", logs)
        self.assertIn("before \\xa8 after", logs)
        self.assertIn("fatal \\xff detail", logs)

    def test_runner_forwards_raw_output_to_snapshot_callback(self) -> None:
        env = dict(os.environ)
        env["TDL_FORCE_PTY"] = "0"
        captured: list[str] = []
        result = SubprocessRunner().run(
            [sys.executable, "-c", "print('raw worker output')"],
            env=env,
            log_prefix="tdl-test",
            output_callback=captured.append,
        )

        self.assertEqual(result.returncode, 0)
        self.assertTrue(any("raw worker output" in line for line in captured))
        self.assertTrue(any("process exited with code 0" in line for line in captured))

    def test_export_handles_empty_result(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            client = TDLClient(root / "export", "export", runner=FakeRunner("empty"))
            result = client.export_messages("@bot", 1, root / "out.json")

            self.assertEqual(result.exported_count, 0)
            self.assertIsNone(result.max_message_id)
            self.assertFalse(result.has_media)

    def test_export_can_use_explicit_message_id_end_for_retry(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            runner = FakeRunner("empty")
            client = TDLClient(root / "export", "export", runner=runner)

            client.export_messages("@bot", 100, root / "out.json", end_id=500)

            command = runner.commands[0]
            self.assertIn("chat", command)
            self.assertIn("export", command)
            self.assertEqual(command[command.index("-i") + 1], "100,500")

    def test_export_failure_raises(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            client = TDLClient(
                root / "export", "export", runner=FakeRunner("export_failure")
            )
            with self.assertRaises(TDLCommandError):
                client.export_messages("@bot", 1, root / "out.json")

    def test_download_failure_raises(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            client = TDLClient(
                root / "download", "download", runner=FakeRunner("download_failure")
            )
            result = client.export_messages("@bot", 1, root / "out.json")

            with self.assertRaises(TDLCommandError):
                client.download(result.export_path, root / "downloaded")

    def test_uses_separate_storage_root_and_namespace(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            runner = FakeRunner("empty")
            client = TDLClient(root / "export", "export", runner=runner)
            client.export_messages("@bot", 1, root / "out.json")

            command = runner.commands[0]
            self.assertIn(f"type=bolt,path={root / 'export' / 'data'}", command)
            self.assertIn("export", command)

    def test_can_wrap_export_command_as_linux_user(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            runner = FakeRunner("empty")
            client = TDLClient(
                root / "user1" / ".tdl",
                "default",
                runner=runner,
                run_as_user="user1",
                home=root / "user1",
            )
            client.export_messages("@bot", 1, root / "out.json")

            command = runner.commands[0]
            self.assertEqual(command[:4], ["runuser", "-u", "user1", "--"])
            self.assertIn(f"type=bolt,path={root / 'user1' / '.tdl' / 'data'}", command)
            self.assertEqual(runner.envs[0]["HOME"], str(root / "user1"))

    def test_parses_tdl_progress_line(self) -> None:
        progress = parse_tdl_progress_line("3/12 sample.mp4 45.5% 1.2MiB/s", "stdout")

        self.assertEqual(progress.fraction_current, 3)
        self.assertEqual(progress.fraction_total, 12)
        self.assertEqual(progress.file_name, "sample.mp4")
        self.assertEqual(progress.percent, 45.5)
        self.assertEqual(progress.speed, "1.2MiB/s")

    def test_parses_tdl_done_line_message_id_and_speed(self) -> None:
        progress = parse_tdl_progress_line(
            "Up Talent / Alter(3714353316):15562 -> ... done! [54.32 MB in 18.005s, 3.02 MB/s]",
            "stdout",
        )

        self.assertEqual(progress.message_id, 15562)
        self.assertEqual(progress.speed, "3.02 MB/s")

    def test_cleans_ansi_cursor_output_from_docker_logs(self) -> None:
        raw = "\x1b[A\x1b[K\x1b[34mFile Total(8777367678):2~\x1b[0m\x1b[34m ... \x1b[0m\x1b[91m99.8%\x1b[0m\x1b[90m [\x1b[36m137.00 MB\x1b[0m\x1b[90m in \x1b[32m37.427s\x1b[0m\x1b[90m; \x1b[35m3.66 MB\x1b[0m\x1b[90m/s]\x1b[0m"

        cleaned = clean_tdl_output_line(raw)
        progress = parse_tdl_progress_line(raw, "stdout")

        self.assertEqual(
            cleaned,
            "File Total(8777367678):2~ ... 99.8% [137.00 MB in 37.427s; 3.66 MB/s]",
        )
        self.assertIsNone(progress.message_id)
        self.assertEqual(progress.percent, 99.8)
        self.assertEqual(progress.speed, "3.66 MB/s")

    def test_identifies_tdl_nonsemantic_status_lines(self) -> None:
        self.assertTrue(
            is_nonsemantic_tdl_output_line("CPU: 1.00% Memory: 32.54 MB Goroutines: 32")
        )
        self.assertTrue(
            is_nonsemantic_tdl_output_line(
                "[################################################################################################################################################################################################################.] [45s; 1.17 MB/s]"
            )
        )
        self.assertTrue(
            is_nonsemantic_tdl_output_line(
                "Another collection-1588718424 ... [<#>.............................................] [0 in 201ms; 0/s]"
            )
        )
        self.assertFalse(
            is_nonsemantic_tdl_output_line(
                "File Total(8777367678):2539 -> /data/download/file.mp4 ... 87.5% [7.02 MB in 6.011s; 1.17 MB/s]"
            )
        )

    def test_runner_cancels_when_only_standstill_progress_bars_repeat(self) -> None:
        command = [
            sys.executable,
            "-c",
            (
                "import time; "
                "print('[>................................] [0 in 1s; 0/s]', flush=True); "
                "time.sleep(10)"
            ),
        ]
        started = time.monotonic()
        with self.assertRaises(TDLStalledError) as raised:
            SubprocessRunner().run(
                command,
                env={**os.environ, "TDL_FORCE_PTY": "0"},
                stall_timeout_seconds=1,
            )

        self.assertEqual(raised.exception.timeout_seconds, 1)
        self.assertLess(time.monotonic() - started, 5)

    def test_parses_full_upload_progress_line(self) -> None:
        progress = parse_tdl_progress_line(
            "Upload File(8543289192):339183 -> /www~ ... 4.8% [29.00 MB in 16.801s; ~ETA: 6m43s; 1.73 MB/s]",
            "stdout",
        )

        self.assertEqual(progress.message_id, 339183)
        self.assertEqual(progress.percent, 4.8)
        self.assertEqual(progress.speed, "1.73 MB/s")
        self.assertEqual(progress.speed_bps, 1814036.48)
        self.assertEqual(progress.eta_seconds, 403)
        self.assertEqual(progress.elapsed_seconds, 16.801)
        self.assertEqual(progress.transferred_bytes, 29 * 1024 * 1024)

    def test_upload_builds_one_file_command_and_returns_message_id(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "a.pdf"
            source.write_bytes(b"a")
            runner = FakeRunner("empty")
            result = TDLClient(root / "tdl", "default", runner=runner).upload(
                source, "-100123", "caption"
            )
        self.assertEqual(result.message_id, 987)
        command = runner.commands[0]
        self.assertEqual(command[command.index("up") : command.index("up") + 7], [
            "up", "-p", str(source), "-c", "-100123", "--caption", command[-1]
        ])
        self.assertTrue(command[-1].endswith(".txt"))
        self.assertEqual(json.loads(runner.caption_contents[0]), "caption")

    def test_upload_waits_for_delayed_message_id(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "backup.7z.001"
            source.write_bytes(b"backup")
            runner = FakeRunner("delayed_upload")
            client = TDLClient(
                root / "tdl",
                "default",
                runner=runner,
                upload_resolve_timeout_seconds=1,
                upload_resolve_interval_seconds=0,
            )
            result = client.upload(
                source,
                "1511596877",
                "Backup node=local run=abc\nPart: backup.7z.001",
            )

        self.assertEqual(result.message_id, 4321)
        self.assertGreaterEqual(runner.export_calls, 2)
        self.assertTrue(all(mode & 0o222 for mode in runner.export_output_modes))
        resolve_command = next(command for command in runner.commands if "export" in command)
        self.assertIn("--with-content", resolve_command)
        self.assertIn("last", resolve_command)

    def test_upload_can_force_image_as_telegram_photo(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "thumbnail.png"
            source.write_bytes(b"png")
            runner = FakeRunner("empty")
            result = TDLClient(root / "tdl", "default", runner=runner).upload(
                source, "-100123", "caption", as_photo=True
            )

        self.assertEqual(result.message_id, 987)
        command = runner.commands[0]
        self.assertIn("--photo", command)
        self.assertLess(command.index("--photo"), command.index("--caption"))


if __name__ == "__main__":
    unittest.main()
