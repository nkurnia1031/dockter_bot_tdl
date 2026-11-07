import unittest
import threading
import io
import subprocess
import json
from types import SimpleNamespace
from tempfile import TemporaryDirectory
from pathlib import Path
from unittest.mock import patch

from tme3bot.worker.executor import (
    WORKER_JOB_HANDLER_METHODS,
    WorkerJobExecutor,
)
from tme3bot.worker.job_lifecycle import WORKER_JOB_LIFECYCLE, lifecycle_policy
from tme3bot.tdl import SubprocessRunner, preflight_command
from tme3bot.worker.executor_support import (
    JobOwnerCommandCallback,
    ScopedCommandMilestoneRecorder,
    WorkerEventPublisher,
)
from tme3bot.worker.command_store import WorkerCommandStore
from tme3bot.utility import UtilityRunner
from tme3bot.worker import executor_backup_verify


class _BlockingFakeProcess:
    pid = 987654

    def __init__(self, *, binary_output: bool) -> None:
        self.stdout = io.BytesIO() if binary_output else io.StringIO()
        self.stderr = io.BytesIO()
        self.returncode: int | None = None
        self.finished = threading.Event()

    def poll(self):
        return self.returncode

    def wait(self, timeout=None):
        if self.returncode is None and not self.finished.wait(timeout):
            raise subprocess.TimeoutExpired("fake-process", timeout)
        return self.returncode


class WorkerJobLifecycleContractTests(unittest.TestCase):
    def _active_cancel_executor(self, kind, payload, profiles, runtimes):
        calls = []
        emitted = []
        executor = object.__new__(WorkerJobExecutor)
        executor._durable_admission_lock = threading.RLock()
        executor.command_store = SimpleNamespace(
            request_cancel_by_job=lambda job_id, **_kwargs: (
                calls.append(job_id)
                or {"command_id": "command-1", "status": "cancelling"}
            )
        )
        executor._lock = threading.RLock()
        executor._active = {"job-1": ("default", kind)}
        executor._active_commands = {
            "job-1": {"kind": kind, "profile": "default", "payload": payload}
        }
        executor._utility_runners = {}
        executor._rclone_runners = {}
        executor._quick_export_clients = {}
        executor._quick_download_clients = {}
        executor._quick_active = set()
        executor._quick_thumbnail_builders = {}
        executor._pause_events = {}
        executor._paused_pending_ids = set()
        executor._cancel_requested = set()
        executor._finalizing = set()
        executor._jobs = SimpleNamespace(cancel_pending=lambda _job_id: False)
        executor.publisher = SimpleNamespace(
            emit=lambda *args, **kwargs: emitted.append((args, kwargs))
        )
        executor.profile_manager = SimpleNamespace(
            runtime=lambda profile: runtimes[profile],
            list_profiles=lambda: list(profiles),
        )
        executor.available_storage_profiles = lambda: list(profiles)
        executor._write_quick_log_line = lambda *_args: None
        return executor, calls, emitted

    def test_every_registered_handler_has_a_complete_lifecycle_policy(self):
        self.assertEqual(set(WORKER_JOB_HANDLER_METHODS), set(WORKER_JOB_LIFECYCLE))

        for kind, method_name in WORKER_JOB_HANDLER_METHODS.items():
            with self.subTest(kind=kind):
                policy = lifecycle_policy(kind)
                self.assertTrue(callable(getattr(WorkerJobExecutor, method_name)))
                self.assertTrue(policy.cooperative_checkpoint)
                self.assertTrue(policy.external_effects)
                self.assertTrue(policy.restart_policy)
                self.assertIn("succeeded", policy.terminal_events)
                self.assertIn("failed", policy.terminal_events)
                if policy.cancel_supported:
                    self.assertTrue(policy.cancel_resources)
                    self.assertIn("cancelled", policy.terminal_events)
                else:
                    self.assertFalse(policy.cancel_resources)
                    self.assertNotIn("cancelled", policy.terminal_events)

    def test_unregistered_job_kind_cannot_silently_inherit_a_policy(self):
        with self.assertRaisesRegex(ValueError, "Lifecycle policy tidak terdaftar"):
            lifecycle_policy("new_worker_handler")

    def test_worker_fallback_queue_fences_artifact_delete_with_download(self):
        executor = object.__new__(WorkerJobExecutor)
        executor.config = SimpleNamespace(backup_node_name="local")
        executor.profile_manager = SimpleNamespace(list_profiles=lambda: ["default"])
        delete_keys = executor._resource_keys_for_command(
            {
                "kind": "artifact_delete",
                "profile": "default",
                "worker": "local",
                "payload": {"artifact_keys": ["export.json"]},
            }
        )
        download_keys = executor._resource_keys_for_command(
            {
                "kind": "download",
                "profile": "default",
                "worker": "local",
                "payload": {"artifact_keys": ["export.json"]},
            }
        )
        self.assertEqual(
            delete_keys & download_keys,
            {"worker:local:artifact:export.json"},
        )

    def test_subprocess_cancel_only_interrupts_the_requested_job_owner(self):
        runner = SubprocessRunner()

        class RunningProcess:
            def poll(self):
                return None

        runner._current_process = RunningProcess()
        runner._current_owner = "other-job"
        with patch.object(SubprocessRunner, "_interrupt_process") as interrupt:
            self.assertFalse(runner.interrupt_current("target-job"))
            interrupt.assert_not_called()

            runner._current_owner = "target-job"
            self.assertTrue(runner.interrupt_current("target-job"))
            interrupt.assert_called_once_with(runner._current_process)

    def test_tdl_cancel_cannot_miss_process_between_spawn_and_owner_registration(self):
        spawn_started = threading.Event()
        allow_spawn = threading.Event()
        interrupted = threading.Event()
        cancel_done = threading.Event()
        process = _BlockingFakeProcess(binary_output=True)
        run_errors = []
        cancel_results = []
        runner = SubprocessRunner()

        def fake_popen(*_args, **_kwargs):
            spawn_started.set()
            self.assertTrue(allow_spawn.wait(3))
            return process

        def fake_interrupt(target):
            self.assertIs(target, process)
            target.returncode = -2
            target.finished.set()
            interrupted.set()

        def run():
            try:
                runner.run(
                    ["fake-tdl"],
                    command_callback=JobOwnerCommandCallback("job-race"),
                    quiet_output=True,
                )
            except Exception as exc:  # pragma: no cover - asserted below
                run_errors.append(exc)

        with patch("tme3bot.tdl.subprocess.Popen", side_effect=fake_popen), patch.object(
            SubprocessRunner, "_interrupt_process", side_effect=fake_interrupt
        ):
            run_thread = threading.Thread(target=run)
            run_thread.start()
            self.assertTrue(spawn_started.wait(2))
            cancel_thread = threading.Thread(
                target=lambda: (
                    cancel_results.append(runner.interrupt_current("job-race")),
                    cancel_done.set(),
                )
            )
            cancel_thread.start()
            self.assertFalse(cancel_done.wait(0.05))
            allow_spawn.set()
            run_thread.join(3)
            cancel_thread.join(3)

        self.assertFalse(run_thread.is_alive())
        self.assertFalse(cancel_thread.is_alive())
        self.assertEqual(cancel_results, [True])
        self.assertTrue(interrupted.is_set())
        self.assertEqual(run_errors, [])

    def test_utility_cancel_cannot_miss_process_between_spawn_and_registration(self):
        spawn_started = threading.Event()
        allow_spawn = threading.Event()
        interrupted = threading.Event()
        cancel_done = threading.Event()
        process = _BlockingFakeProcess(binary_output=False)
        runner = UtilityRunner(Path("utility"), command_callback=JobOwnerCommandCallback("utility-race"))
        run_errors = []
        cancel_results = []

        def fake_popen(*_args, **_kwargs):
            spawn_started.set()
            self.assertTrue(allow_spawn.wait(3))
            return process

        def fake_terminate(target):
            self.assertIs(target, process)
            target.returncode = -2
            target.finished.set()
            interrupted.set()

        def run():
            try:
                runner._command(["fake-utility"], Path("/var/tmp"), "utility-race")
            except Exception as exc:
                run_errors.append(exc)

        def fake_killpg(_process_group, _signal):
            fake_terminate(process)

        with patch("tme3bot.utility.subprocess.Popen", side_effect=fake_popen), patch(
            "tme3bot.utility.os.getpgid", return_value=123
        ), patch("tme3bot.utility.os.killpg", side_effect=fake_killpg):
            run_thread = threading.Thread(target=run)
            run_thread.start()
            self.assertTrue(spawn_started.wait(2))
            cancel_thread = threading.Thread(
                target=lambda: (
                    cancel_results.append(runner.cancel_current("utility-race")),
                    cancel_done.set(),
                )
            )
            cancel_thread.start()
            self.assertFalse(cancel_done.wait(0.05))
            allow_spawn.set()
            run_thread.join(3)
            cancel_thread.join(3)

        self.assertFalse(run_thread.is_alive())
        self.assertFalse(cancel_thread.is_alive())
        self.assertEqual(cancel_results, [True])
        self.assertTrue(interrupted.is_set())
        self.assertEqual(len(run_errors), 1)
        self.assertIn("exit code -2", str(run_errors[0]))

    def test_durable_handoff_does_not_cancel_a_non_cancellable_running_kind(self):
        with TemporaryDirectory(prefix="lifecycle-cancel-handoff-", dir="/var/tmp") as root:
            store = WorkerCommandStore(Path(root) / "commands.sqlite3")
            envelope = {
                "command_id": "clear-failed-command",
                "operation_id": "operation-1",
                "job_id": "clear-failed-job",
                "attempt": 1,
                "dispatch_token": "private-token",
                "job": {
                    "kind": "download_clear_failed",
                    "profile": "default",
                    "worker": "local",
                    "actor_user_id": 1,
                    "payload": {},
                },
            }
            store.accept(envelope)
            store.set_status("clear-failed-command", "running", only_from=("accepted",))
            executor = object.__new__(WorkerJobExecutor)
            executor._durable_admission_lock = threading.RLock()
            executor.command_store = store
            executor._lock = threading.RLock()
            executor._active = {}
            executor._active_commands = {}
            executor._utility_runners = {}
            executor._rclone_runners = {}
            executor._quick_export_clients = {}
            executor._quick_download_clients = {}
            executor._pause_events = {}
            executor._paused_pending_ids = set()
            executor._cancel_requested = set()
            executor._jobs = SimpleNamespace(cancel_pending=lambda _job_id: False)

            self.assertFalse(executor.cancel("clear-failed-job"))
            self.assertEqual(store.get("clear-failed-command")["status"], "running")
            self.assertNotIn("clear-failed-job", executor._cancel_requested)

    def test_cancel_is_rejected_after_worker_enters_finalization(self):
        executor, cancel_calls, _emitted = self._active_cancel_executor(
            "storage_upload", {}, ["default"],
            {"default": SimpleNamespace(upload_tdl_client=SimpleNamespace())},
        )
        executor._finalizing.add("job-1")

        self.assertFalse(executor.cancel("job-1"))
        self.assertEqual(cancel_calls, [])
        self.assertNotIn("job-1", executor._cancel_requested)

    def test_unobserved_cancel_racing_with_handler_return_does_not_override_success(self):
        executor = object.__new__(WorkerJobExecutor)
        executor._lock = threading.RLock()
        executor._cancel_requested = {"job-1"}
        executor._cancel_observed = set()
        executor._cancel_confirmed = set()
        executor._finalizing = set()

        self.assertFalse(executor._cancellation_was_effective("job-1"))
        executor._finalizing.add("job-1")
        self.assertFalse(executor._cancellation_was_effective("job-1"))

    def test_worker_checkpoint_makes_cancel_effective_for_terminal_status(self):
        executor = object.__new__(WorkerJobExecutor)
        executor._lock = threading.RLock()
        executor._cancel_requested = {"job-1"}
        executor._cancel_observed = set()
        executor._cancel_confirmed = set()
        executor._finalizing = set()

        self.assertTrue(executor._job_cancelled("job-1"))
        self.assertTrue(executor._cancellation_was_effective("job-1"))

    def test_failed_export_cleanup_emits_durable_per_file_outcomes(self):
        emitted = []
        service = SimpleNamespace(
            clear_failed_exports=lambda on_item: (
                on_item("started", "one.json"),
                on_item("deleted", "one.json"),
                on_item("started", "two.json"),
                on_item("missing", "two.json"),
                1,
            )[-1]
        )
        executor = object.__new__(WorkerJobExecutor)
        executor.profile_manager = SimpleNamespace(
            runtime=lambda _profile: SimpleNamespace(download_service=service)
        )
        executor.publisher = SimpleNamespace(
            emit=lambda *args, **kwargs: emitted.append((args, kwargs))
        )

        result = executor._download_clear_failed(
            {"job_id": "clear-job", "profile": "default"}
        )

        self.assertEqual(result, {"deleted": 1})
        self.assertEqual(
            [(event[0][2], event[1]["result"]["artifact_key"]) for event in emitted],
            [
                ("artifact.clear_failed.started", "one.json"),
                ("artifact.clear_failed.deleted", "one.json"),
                ("artifact.clear_failed.started", "two.json"),
                ("artifact.clear_failed.missing", "two.json"),
            ],
        )

    def test_artifact_delete_outcomes_survive_restart_before_reconciliation_terminal(self):
        with TemporaryDirectory(prefix="artifact-recovery-", dir="/var/tmp") as root:
            root_path = Path(root)
            pending = root_path / "pending"
            failed = root_path / "failed"
            pending.mkdir()
            failed.mkdir()
            (pending / "one.json").write_text("{}", encoding="utf-8")
            (pending / "two.json").write_text("{}", encoding="utf-8")
            (pending / "three.json").write_text("{}", encoding="utf-8")

            store = WorkerCommandStore(root_path / "commands.sqlite3")
            envelope = {
                "command_id": "artifact-delete-command",
                "operation_id": "operation-1",
                "job_id": "artifact-delete-job",
                "attempt": 1,
                "dispatch_token": "private-dispatch-token",
                "event_sequence_start": 1,
                "job": {
                    "kind": "artifact_delete",
                    "profile": "default",
                    "worker": "local",
                    "actor_user_id": 1,
                    "payload": {"artifact_keys": ["one.json", "two.json", "three.json"]},
                },
            }
            store.accept(envelope)
            store.set_status(
                "artifact-delete-command", "running", only_from=("accepted",)
            )
            publisher = WorkerEventPublisher("http://unused", "unused")
            publisher.attach_outbox(store)
            publisher.begin("artifact-delete-job", 1)
            publisher.bind_command(
                "artifact-delete-job", "artifact-delete-command", 1, "private-dispatch-token"
            )
            publisher.bind_job_worker("artifact-delete-job", "local")
            executor = object.__new__(WorkerJobExecutor)
            executor.command_store = store
            executor.publisher = publisher
            executor.profile_manager = SimpleNamespace(
                runtime=lambda _profile: SimpleNamespace(
                    config=SimpleNamespace(
                        export_pending_dir=pending,
                        export_failed_dir=failed,
                    )
                )
            )
            executor._job_cancelled = lambda _job_id: False

            result = executor._artifact_delete(
                {
                    "job_id": "artifact-delete-job",
                    "profile": "default",
                    "payload": {"artifact_keys": ["one.json"]},
                }
            )
            self.assertEqual(
                result, {"deleted": ["one.json"], "missing": [], "failed": []}
            )
            self.assertFalse((pending / "one.json").exists())

            # This is the durable intent for the next item when the process
            # disappears between unlink and its completion event.
            publisher.emit(
                "artifact-delete-job",
                "running",
                "artifact.delete.started",
                result={"artifact_key": "two.json"},
            )
            publisher.emit(
                "artifact-delete-job",
                "running",
                "artifact.delete.started",
                result={"artifact_key": "three.json"},
            )
            # Simulate a worker restart after unlink committed but before the
            # corresponding completion event reached the durable outbox.
            (pending / "three.json").unlink()
            store.recover_startup()
            executor._publish_command_recoveries()
            # A process restart in the old emit→mark gap used to append a
            # second terminal event. The recovery outbox/fence now commit as
            # one SQLite transaction, so another startup is a no-op.
            executor._publish_command_recoveries()

            with store._db() as db:
                rows = db.execute(
                    "SELECT sequence,event_json FROM worker_event_outbox "
                    "WHERE job_id=? ORDER BY sequence",
                    ("artifact-delete-job",),
                ).fetchall()
            events = [json.loads(row["event_json"]) for row in rows]
            event_types = [event["event_type"] for event in events]
            self.assertEqual(
                event_types,
                [
                    "artifact.delete.started",
                    "artifact.delete.completed",
                    "artifact.delete.started",
                    "artifact.delete.started",
                    "artifact.delete.missing",
                    "worker.restart_interrupted",
                ],
            )
            self.assertEqual(events[1]["result"]["artifact_key"], "one.json")
            self.assertEqual(events[2]["result"]["artifact_key"], "two.json")
            self.assertEqual(events[3]["result"]["artifact_key"], "three.json")
            self.assertEqual(events[4]["result"]["artifact_key"], "three.json")
            recovered_items = events[-1]["result"]["value"]["artifact_delete_recovery"]["items"]
            self.assertEqual(
                recovered_items,
                [
                    {"artifact_key": "two.json", "status": "present"},
                    {"artifact_key": "three.json", "status": "missing"},
                ],
            )
            self.assertEqual(
                events[-1]["progress"]["restart_recovery"]["status"],
                "needs_reconciliation",
            )

    def test_artifact_delete_reports_unlink_failure_without_hiding_catalog_item(self):
        with TemporaryDirectory(prefix="artifact-delete-failure-", dir="/var/tmp") as root:
            root_path = Path(root)
            pending = root_path / "pending"
            failed = root_path / "failed"
            pending.mkdir()
            failed.mkdir()
            (pending / "blocked.json").write_text("{}", encoding="utf-8")
            emitted = []
            executor = object.__new__(WorkerJobExecutor)
            executor.profile_manager = SimpleNamespace(
                runtime=lambda _profile: SimpleNamespace(
                    config=SimpleNamespace(
                        export_pending_dir=pending,
                        export_failed_dir=failed,
                    )
                )
            )
            executor.publisher = SimpleNamespace(
                emit=lambda *args, **kwargs: emitted.append((args, kwargs))
            )
            executor._job_cancelled = lambda _job_id: False
            original_unlink = Path.unlink

            def deny_one_file(path, *args, **kwargs):
                if path.name == "blocked.json":
                    raise PermissionError("do not expose this filesystem detail")
                return original_unlink(path, *args, **kwargs)

            with patch.object(Path, "unlink", deny_one_file):
                result = executor._artifact_delete(
                    {
                        "job_id": "delete-job",
                        "profile": "default",
                        "payload": {"artifact_key": "blocked.json"},
                    }
                )

            self.assertEqual(
                result,
                {
                    "deleted": [],
                    "missing": [],
                    "failed": [
                        {"artifact_key": "blocked.json", "reason_code": "UNLINK_FAILED"}
                    ],
                },
            )
            self.assertTrue((pending / "blocked.json").is_file())
            self.assertEqual(
                [call[0][2] for call in emitted],
                ["artifact.delete.started", "artifact.delete.failed"],
            )
            self.assertNotIn("do not expose", str(emitted))

    def test_storage_recovery_batches_and_terminal_event_are_fenced_together(self):
        with TemporaryDirectory(prefix="storage-recovery-fence-", dir="/var/tmp") as root:
            store = WorkerCommandStore(Path(root) / "commands.sqlite3")
            envelope = {
                "command_id": "storage-recovery-command",
                "operation_id": "operation-1",
                "job_id": "storage-recovery-job",
                "attempt": 1,
                "dispatch_token": "private-token",
                "event_sequence_start": 5,
                "job": {
                    "kind": "storage_upload",
                    "profile": "default",
                    "worker": "local",
                    "actor_user_id": 1,
                    "payload": {
                        "provider": "telegram",
                        "transfer_mode": "copy",
                        "folder_path": "batch",
                    },
                },
            }
            store.accept(envelope)
            store.set_status(
                "storage-recovery-command", "running", only_from=("accepted",)
            )
            store.record_storage_upload_item(
                "storage-recovery-command",
                "one.bin",
                file_name="one.bin",
                status="succeeded",
                attempt=1,
                profile="default",
                result_item={"provider": "telegram", "channel_message_id": 71},
            )
            store.recover_startup()
            publisher = WorkerEventPublisher("http://unused", "unused")
            publisher.attach_outbox(store)
            executor = object.__new__(WorkerJobExecutor)
            executor.command_store = store
            executor.publisher = publisher

            executor._publish_storage_upload_recoveries()
            executor._publish_storage_upload_recoveries()

            with store._db() as db:
                rows = db.execute(
                    "SELECT sequence,event_json FROM worker_event_outbox "
                    "WHERE job_id=? ORDER BY sequence",
                    ("storage-recovery-job",),
                ).fetchall()
                command = db.execute(
                    "SELECT phase FROM worker_commands WHERE command_id=?",
                    ("storage-recovery-command",),
                ).fetchone()
            events = [json.loads(row["event_json"]) for row in rows]
            self.assertEqual(
                [event["event_type"] for event in events],
                ["storage.recovery_batch", "storage.batch_interrupted"],
            )
            self.assertEqual([row["sequence"] for row in rows], [6, 7])
            self.assertEqual(command["phase"], "reconciliation_reported")

    def test_storage_upload_cancel_targets_upload_clients_of_local_senders(self):
        calls = {"default": [], "ruth2": []}
        emitted = []

        class TdlClient:
            def __init__(self, profile):
                self.profile = profile

            def interrupt_current(self, owner_job_id=None):
                calls[self.profile].append(owner_job_id)
                return self.profile == "ruth2"

        runtimes = {
            profile: SimpleNamespace(
                upload_tdl_client=TdlClient(profile),
                export_tdl_client=SimpleNamespace(
                    interrupt_current=lambda *_args: self.fail("export lane must not be interrupted")
                ),
            )
            for profile in calls
        }
        executor = object.__new__(WorkerJobExecutor)
        executor._durable_admission_lock = threading.RLock()
        executor.command_store = SimpleNamespace(
            request_cancel_by_job=lambda job_id, **_kwargs: {
                "command_id": "command-1",
                "status": "cancelling",
            }
        )
        executor._lock = threading.RLock()
        executor._active = {"job-1": ("default", "storage_upload")}
        executor._active_commands = {
            "job-1": {
                "kind": "storage_upload",
                "payload": {"_tdl_sender_profiles": ["ruth2", "default"]},
            }
        }
        executor._utility_runners = {}
        executor._rclone_runners = {}
        executor._quick_export_clients = {}
        executor._quick_download_clients = {}
        executor._quick_active = set()
        executor._quick_thumbnail_builders = {}
        executor._pause_events = {}
        executor._paused_pending_ids = set()
        executor._cancel_requested = set()
        executor._jobs = SimpleNamespace(cancel_pending=lambda _job_id: False)
        executor.publisher = SimpleNamespace(
            emit=lambda *args, **kwargs: emitted.append((args, kwargs))
        )
        executor.profile_manager = SimpleNamespace(runtime=lambda profile: runtimes[profile])
        executor.available_storage_profiles = lambda: ["default", "ruth2"]
        executor._write_quick_log_line = lambda *_args: None
        executor._pause_events = {}
        executor._paused_pending_ids = set()

        self.assertTrue(executor.cancel("job-1"))
        self.assertEqual(calls, {"default": ["job-1"], "ruth2": ["job-1"]})
        self.assertEqual(emitted[0][0][2], "cancel.requested")

    def test_non_cancellable_active_job_is_not_marked_cancelling(self):
        requested = []
        executor = object.__new__(WorkerJobExecutor)
        executor._lock = threading.RLock()
        executor._active = {"job-1": ("default", "download_clear_failed")}
        executor._active_commands = {}
        executor._pause_events = {}
        executor._paused_pending_ids = set()
        executor.command_store = SimpleNamespace(
            request_cancel_by_job=lambda job_id: requested.append(job_id)
        )
        executor._durable_admission_lock = threading.RLock()

        self.assertFalse(executor.cancel("job-1"))
        self.assertEqual(requested, [])

    def test_late_cancel_for_old_attempt_does_not_interrupt_active_retry(self):
        with TemporaryDirectory() as folder:
            store = WorkerCommandStore(Path(folder) / "commands.db")
            first = {
                "command_id": "retry-command-1",
                "job_id": "retry-job",
                "attempt": 1,
                "dispatch_token": "token-1",
                "job": {
                    "kind": "export",
                    "profile": "default",
                    "worker": "local",
                    "actor_user_id": 42,
                    "payload": {},
                },
            }
            store.accept(first)
            store.finish("retry-command-1", "cancelled")
            second = {**first, "command_id": "retry-command-2", "attempt": 2, "dispatch_token": "token-2"}
            store.accept(second)

            executor = object.__new__(WorkerJobExecutor)
            executor._durable_admission_lock = threading.RLock()
            executor.command_store = store
            executor._lock = threading.RLock()
            executor._active = {"retry-job": ("default", "export")}
            executor._active_commands = {"retry-job": {"kind": "export", "attempt": 2}}
            executor._finalizing = set()
            executor._cancel_requested = set()

            self.assertFalse(executor.cancel("retry-job", attempt=1))
            self.assertNotIn("retry-job", executor._cancel_requested)
            self.assertEqual(store.get("retry-command-2")["status"], "accepted")

    def test_late_cancel_for_old_attempt_does_not_remove_queued_or_paused_retry(self):
        for paused in (False, True):
            with self.subTest(paused=paused), TemporaryDirectory() as folder:
                store = WorkerCommandStore(Path(folder) / "commands.db")
                first = {
                    "command_id": "retry-command-1",
                    "job_id": "retry-job",
                    "attempt": 1,
                    "dispatch_token": "token-1",
                    "job": {
                        "kind": "export",
                        "profile": "default",
                        "worker": "local",
                        "actor_user_id": 42,
                        "payload": {},
                    },
                }
                store.accept(first)
                store.finish("retry-command-1", "cancelled")
                store.accept({
                    **first,
                    "command_id": "retry-command-2",
                    "attempt": 2,
                    "dispatch_token": "token-2",
                })
                pending_cancel_calls = []
                pause_event = threading.Event()
                if paused:
                    pause_event.set()
                executor = object.__new__(WorkerJobExecutor)
                executor._durable_admission_lock = threading.RLock()
                executor.command_store = store
                executor._lock = threading.RLock()
                executor._active = {}
                executor._active_commands = {}
                executor._finalizing = set()
                executor._cancel_requested = set()
                executor._pause_events = {"retry-job": pause_event} if paused else {}
                executor._paused_pending_ids = {"retry-job"} if paused else set()
                executor._jobs = SimpleNamespace(
                    cancel_pending=lambda job_id: pending_cancel_calls.append(job_id) or True
                )

                self.assertFalse(executor.cancel("retry-job", attempt=1))
                self.assertEqual(pending_cancel_calls, [])
                self.assertEqual(store.get("retry-command-2")["status"], "accepted")
                if paused:
                    self.assertTrue(pause_event.is_set())
                    self.assertIn("retry-job", executor._paused_pending_ids)

    def test_tts_cancel_targets_selected_and_fallback_export_clients(self):
        calls = {"default": [], "archive": []}

        class TdlClient:
            def __init__(self, profile):
                self.profile = profile

            def interrupt_current(self, owner_job_id=None):
                calls[self.profile].append(owner_job_id)
                return self.profile == "archive"

        runtimes = {
            profile: SimpleNamespace(export_tdl_client=TdlClient(profile))
            for profile in calls
        }
        executor, _, emitted = self._active_cancel_executor(
            "tts", {"_tdl_sender_profiles": ["archive"]}, ["default", "archive"], runtimes
        )

        self.assertTrue(executor.cancel("job-1"))
        self.assertEqual(calls, {"default": ["job-1"], "archive": ["job-1"]})
        self.assertEqual(emitted[0][0][2], "cancel.requested")

    def test_backup_node_cancel_targets_the_actual_sorted_uploader(self):
        calls = {"default": [], "archive": []}
        archive_calls = []

        class TdlClient:
            def __init__(self, profile):
                self.profile = profile

            def interrupt_current(self, owner_job_id=None):
                calls[self.profile].append(owner_job_id)
                return True

        runtimes = {
            profile: SimpleNamespace(export_tdl_client=TdlClient(profile))
            for profile in calls
        }
        executor, _, emitted = self._active_cancel_executor(
            "backup_node", {}, ["default", "archive"], runtimes
        )
        executor._backup_services = {
            "job-1": SimpleNamespace(
                cancel_current=lambda owner_job_id: archive_calls.append(owner_job_id) or True
            )
        }

        self.assertTrue(executor.cancel("job-1"))
        self.assertEqual(calls, {"default": [], "archive": ["job-1"]})
        self.assertEqual(archive_calls, ["job-1"])
        self.assertEqual(emitted[0][0][2], "cancel.requested")

    def test_backup_verify_binds_tdl_process_to_job_and_preflight(self):
        observed = []

        class Recorder:
            job_id = "backup-verify-job"

            def preflight(self):
                observed.append("preflight")

            def command_started(self, command, log_prefix, context=None):
                observed.append(("started", command, context))
                return "command-1"

            def command_completed(self, *args, **kwargs):
                return None

        class Client:
            output_callback = None
            command_callback = None
            progress_callback = None

        with TemporaryDirectory(prefix="backup-verify-test-", dir="/var/tmp") as root:
            client = Client()
            runtime = SimpleNamespace(
                export_operation_lock=threading.RLock(),
                download_operation_lock=threading.RLock(),
                export_tdl_client=client,
            )
            emitted = []
            executor = object.__new__(WorkerJobExecutor)
            executor.config = SimpleNamespace(backup_node_name="local", temp_root=root)
            executor.profile_manager = SimpleNamespace(runtime=lambda _profile: runtime)
            executor.publisher = SimpleNamespace(
                emit=lambda *args, **kwargs: emitted.append((args, kwargs))
            )
            executor._job_log = SimpleNamespace(audit=Recorder())
            executor._append_job_log = lambda *_args: None
            executor.diagnose_profile_tdl = lambda _profile: {"ready": True}
            executor._profile_sessions = SimpleNamespace(test_backup_session=lambda *_args: True)

            def fake_download(active_client, **_kwargs):
                callback = active_client.command_callback
                self.assertEqual(callback.job_id, "backup-verify-job")
                callback.preflight()
                callback.command_started(["tdl", "export"], "backup verification")

            command = {
                "job_id": "backup-verify-job",
                "profile": "default",
                "payload": {
                    "run_id": "run-1",
                    "node_name": "local",
                    "parts": [],
                    "run_record": {},
                    "password": "temporary",
                    "channel_ref": "-1001",
                },
            }
            with (
                patch.object(executor_backup_verify, "download_backup_parts", fake_download),
                patch.object(
                    executor_backup_verify,
                    "verify_profile_backup",
                    return_value={"status": "verified", "part_count": 0},
                ),
            ):
                result = executor._backup_verify(command)

        self.assertEqual(result["report"]["status"], "verified")
        self.assertEqual(observed[0], "preflight")
        self.assertEqual(observed[1][0], "started")
        self.assertEqual(observed[1][2], {"profile": "default", "runtime": "backup_verify"})

    def test_scoped_command_callback_preserves_job_owner_and_preflight(self):
        calls = []

        class Recorder:
            job_id = "job-owner"

            def preflight(self):
                calls.append("preflight")

            def command_started(self, command, log_prefix, context=None):
                return None

            def command_completed(self, *args, **kwargs):
                return None

        callback = ScopedCommandMilestoneRecorder(Recorder(), runtime="download")
        self.assertEqual(callback.job_id, "job-owner")
        preflight_command(callback)
        self.assertEqual(calls, ["preflight"])

    def test_cancel_checkpoint_prevents_a_following_subprocess_from_spawning(self):
        class CancelledBeforeCommand:
            job_id = "job-owner"

            def preflight(self):
                raise RuntimeError("cancelled before next command")

        with patch("tme3bot.tdl.subprocess.Popen") as spawn:
            with self.assertRaisesRegex(RuntimeError, "before next command"):
                SubprocessRunner().run(
                    ["example-command"],
                    command_callback=CancelledBeforeCommand(),
                )
        spawn.assert_not_called()

    def test_recovery_publishes_one_failed_worker_outcome_without_replaying_command(self):
        emitted = []
        marked = []
        command = {
            "command_id": "command-1",
            "job_id": "job-1",
            "attempt": 2,
            "dispatch_token": "private-dispatch-token",
            "event_sequence_start": 41,
            "kind": "storage_download",
            "worker": "remote-1",
            "phase": "needs_reconciliation",
            "checkpoint": {"progress": {"phase": "downloading"}},
        }
        executor = object.__new__(WorkerJobExecutor)
        executor.command_store = SimpleNamespace(
            list_recovery_commands=lambda: [command],
            mark_recovery_reported=lambda command_id: marked.append(command_id) or True,
        )
        executor.publisher = SimpleNamespace(
            begin=lambda *args: emitted.append(("begin", args)),
            bind_command=lambda *args: emitted.append(("bind", args)),
            bind_job_worker=lambda *args: emitted.append(("worker", args)),
            emit=lambda *args, **kwargs: emitted.append(("emit", args, kwargs)),
        )

        executor._publish_command_recoveries()

        event = next(item for item in emitted if item[0] == "emit")
        self.assertIn(("begin", ("job-1", 41)), emitted)
        self.assertEqual(event[1][1], "failed")
        self.assertEqual(event[1][2], "worker.restart_interrupted")
        self.assertEqual(event[2]["progress"]["previous_phase"], "downloading")
        self.assertEqual(
            event[2]["error"]["code"], "WORKER_RESTART_RECONCILIATION_REQUIRED"
        )
        self.assertNotIn("private-dispatch-token", str(event))
        self.assertEqual(marked, ["command-1"])


if __name__ == "__main__":
    unittest.main()
