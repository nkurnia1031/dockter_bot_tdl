"""Declared cancellation and restart contracts for worker job handlers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


RestartPolicy = Literal[
    "resume_export_cursor_commit",
    "resume_tts_synthesis",
    "report_reconciliation",
    "report_failure",
]


@dataclass(frozen=True)
class JobLifecyclePolicy:
    cancel_supported: bool
    cancel_resources: tuple[str, ...]
    cooperative_checkpoint: str
    external_effects: tuple[str, ...]
    restart_policy: RestartPolicy
    terminal_events: tuple[str, ...]


# This mapping documents runtime behavior, not UI readiness. Keep it in sync
# with WORKER_JOB_HANDLER_METHODS in executor.py; the contract test enforces it.
WORKER_JOB_LIFECYCLE: dict[str, JobLifecyclePolicy] = {
    "export": JobLifecyclePolicy(
        True, ("export_tdl_client", "quick_mode_phase_resources"),
        "before_each_export_or_quick_mode_phase",
        ("telegram_export", "local_json", "shared_cursor_commit"),
        "resume_export_cursor_commit", ("succeeded", "failed", "cancelled"),
    ),
    "leave": JobLifecyclePolicy(
        True, ("leave_service_runner",), "before_each_chat",
        ("telegram_membership_change",), "report_reconciliation",
        ("succeeded", "failed", "cancelled"),
    ),
    "download": JobLifecyclePolicy(
        True, ("download_tdl_client",), "between_export_files_and_downloads",
        ("local_filesystem_write",), "report_reconciliation",
        ("succeeded", "failed", "cancelled"),
    ),
    "download_clear_failed": JobLifecyclePolicy(
        False, (), "single_local_cleanup_call",
        ("local_file_delete",), "report_reconciliation",
        ("succeeded", "failed"),
    ),
    "artifact_inventory": JobLifecyclePolicy(
        True, ("worker_cancel_token",), "between_artifact_files",
        ("local_artifact_cleanup", "catalog_inventory_events"), "report_failure",
        ("succeeded", "failed", "cancelled"),
    ),
    "artifact_delete": JobLifecyclePolicy(
        True, ("worker_cancel_token",), "between_artifact_files",
        ("local_file_delete",), "report_reconciliation",
        ("succeeded", "failed", "cancelled"),
    ),
    "utility": JobLifecyclePolicy(
        True, ("utility_runner",), "between_folders_and_items",
        ("workspace_mutation",), "report_reconciliation",
        ("succeeded", "failed", "cancelled"),
    ),
    "storage_upload": JobLifecyclePolicy(
        True, ("active_sender_upload_tdl_clients", "rclone_runner"),
        "between_files_and_after_current_transfer",
        ("telegram_or_rclone_upload", "move_source_cleanup", "storage_catalog"),
        "report_reconciliation", ("succeeded", "failed", "cancelled"),
    ),
    "chat_send": JobLifecyclePolicy(
        True, ("selected_profile_upload_tdl_client",), "between_files",
        ("telegram_chat_send",), "report_reconciliation",
        ("succeeded", "failed", "cancelled"),
    ),
    "storage_download": JobLifecyclePolicy(
        True, ("download_tdl_client", "rclone_runner"),
        "between_files_and_download_phases",
        ("workspace_file_write", "public_link_registration"),
        "report_reconciliation", ("succeeded", "failed", "cancelled"),
    ),
    "storage_rclone_manage": JobLifecyclePolicy(
        True, ("rclone_runner",), "between_selected_items",
        ("remote_rclone_mutation",), "report_reconciliation",
        ("succeeded", "failed", "cancelled"),
    ),
    "storage_reconcile": JobLifecyclePolicy(
        True, ("active_sender_upload_tdl_clients",), "between_sender_profiles_and_items",
        ("telegram_history_read", "source_cleanup_after_proof"),
        "report_reconciliation", ("succeeded", "failed", "cancelled"),
    ),
    "storage_sync": JobLifecyclePolicy(
        True, ("active_profile_upload_tdl_client",), "before_export_and_between_apply_batches",
        ("telegram_history_read", "storage_catalog_write"),
        "report_reconciliation", ("succeeded", "failed", "cancelled"),
    ),
    "backup_node": JobLifecyclePolicy(
        True, ("backup_archive_runner", "first_sorted_profile_export_tdl_client"), "between_archive_parts",
        ("local_backup_write", "telegram_upload"), "report_reconciliation",
        ("succeeded", "failed", "cancelled"),
    ),
    "backup_verify": JobLifecyclePolicy(
        True, ("profile_export_tdl_client",), "between_channel_parts_and_verification",
        ("telegram_history_read", "temporary_file_write"), "report_reconciliation",
        ("succeeded", "failed", "cancelled"),
    ),
    "tts": JobLifecyclePolicy(
        True, ("tts_cooperative_cancel", "active_sender_export_tdl_client"),
        "between_synthesis_parts_and_delivery_parts",
        ("helper_synthesis", "telegram_audio_delivery", "tts_artifact_write"),
        "resume_tts_synthesis", ("succeeded", "failed", "cancelled"),
    ),
    "tdl_access_verify": JobLifecyclePolicy(
        True, ("active_profile_upload_or_export_tdl_client",), "between_profiles",
        ("telegram_test_message", "readiness_snapshot_write"),
        "report_reconciliation", ("succeeded", "failed", "cancelled"),
    ),
    "safelink_resolve": JobLifecyclePolicy(
        True, ("resolver_cooperative_cancel",), "between_redirect_steps",
        ("external_http_read",), "report_failure",
        ("succeeded", "failed", "cancelled"),
    ),
}


def lifecycle_policy(job_kind: str) -> JobLifecyclePolicy:
    """Return the required contract for one registered worker job kind."""
    try:
        return WORKER_JOB_LIFECYCLE[str(job_kind)]
    except KeyError as exc:
        raise ValueError(f"Lifecycle policy tidak terdaftar untuk {job_kind!r}.") from exc
