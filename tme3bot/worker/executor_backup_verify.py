from __future__ import annotations

import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from tme3bot.profile_backup_verifier import verify_profile_backup
from tme3bot.progress_reporter import ProgressReporter
from tme3bot.worker.backup_channel_download import (
    BackupChannelDownloadError,
    download_backup_parts,
)


class BackupVerificationExecutorMixin:
    def _backup_verify(self, command: dict[str, Any]) -> dict[str, Any]:
        payload = command.get("payload") if isinstance(command.get("payload"), dict) else {}
        profile = str(command.get("profile") or "").strip().lower()
        run_id = str(payload.get("run_id") or "")
        worker = str(payload.get("node_name") or "")
        expected_worker = str(getattr(self.config, "backup_node_name", "") or "").strip()
        parts = payload.get("parts")
        run_record = payload.get("run_record")
        password = str(payload.get("password") or "")
        channel_ref = str(payload.get("channel_ref") or "")
        if (
            not profile
            or not run_id
            or not worker
            or worker != expected_worker
            or not isinstance(parts, list)
            or not isinstance(run_record, dict)
            or not password
            or not channel_ref
        ):
            raise RuntimeError("BACKUP_SELECTION_INVALID")

        reporter = ProgressReporter(self.publisher, str(command["job_id"]))
        reporter.report(
            phase="diagnosing_profile",
            message="Memeriksa sesi TDL profil terpilih",
            overall={"current": 0, "total": len(parts), "unit": "parts"},
            indeterminate=True,
            force=True,
        )
        try:
            diagnostics = self.diagnose_profile_tdl(profile)
        except Exception:
            diagnostics = {
                "ready": False,
                "identity_match": False,
                "reason_codes": ["PROFILE_SESSION_UNAVAILABLE"],
                "sessions": [
                    {
                        "name": name,
                        "ready": False,
                        "code": "PROFILE_SESSION_UNAVAILABLE",
                        "identity_matches_metadata": False,
                    }
                    for name in ("root", "user1")
                ],
            }
        diagnostics = {
            **diagnostics,
            "worker": worker,
            "profile": profile,
            "checked_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        }

        temp_root = Path(getattr(self.config, "temp_root", "/tmp"))
        temp_root.mkdir(parents=True, exist_ok=True)
        download_error = ""
        runtime = self.profile_manager.runtime(profile)
        current_part: dict[str, Any] = {}
        completed_bytes = 0
        expected_total_bytes = sum(
            int(item.get("file_size") or 0)
            for item in parts
            if isinstance(item, dict)
        )

        def report_download(stage: str, index: int, total: int, part_name: str) -> None:
            nonlocal completed_bytes
            current_part.clear()
            row = next((item for item in parts if isinstance(item, dict) and item.get("part_name") == part_name), {})
            current_part.update({"index": index, "total": total, **row})
            if stage == "downloaded":
                completed_bytes += int(row.get("file_size") or 0)
                progress = reporter.report(
                    phase="downloading_backup_parts",
                    message=f"Part {index}/{total} selesai diunduh dari channel backup",
                    overall={
                        "current": index,
                        "total": total,
                        "percent": completed_bytes * 100 / expected_total_bytes if expected_total_bytes else None,
                        "unit": "parts",
                        "bytes_current": completed_bytes,
                        "bytes_total": expected_total_bytes,
                    },
                    item={"name": part_name, "index": index, "total": total},
                    force=True,
                )
                reporter.milestone("backup.verify.part_downloaded", progress=progress)
            else:
                reporter.report(
                    phase="downloading_backup_parts",
                    message=(
                        f"Membaca metadata part {index}/{total} dari channel backup"
                        if stage == "exporting"
                        else f"Mengunduh part {index}/{total} dari channel backup"
                    ),
                    overall={"current": index - 1, "total": total, "unit": "parts"},
                    item={"name": part_name, "index": index, "total": total},
                    indeterminate=stage == "downloading",
                    force=stage == "exporting",
                )

        with tempfile.TemporaryDirectory(prefix="profile-backup-check-", dir=str(temp_root)) as raw_temp:
            parts_dir = Path(raw_temp) / "parts"
            parts_dir.mkdir(mode=0o700)
            try:
                with runtime.export_operation_lock, runtime.download_operation_lock:
                    with self._capture_tdl_progress(
                        runtime.export_tdl_client,
                        lambda value: self._report_backup_download_bytes(
                            reporter,
                            value,
                            current_part,
                            completed_bytes,
                            expected_total_bytes,
                        ),
                    ):
                        download_backup_parts(
                            runtime.export_tdl_client,
                            channel_ref=channel_ref,
                            parts=parts,
                            destination=parts_dir,
                            progress=report_download,
                        )
            except BackupChannelDownloadError as exc:
                download_error = exc.code

            reporter.report(
                phase="verifying_archive",
                message="Memeriksa checksum, password, integritas, dan sesi di arsip",
                overall={"current": len(parts) if not download_error else 0, "total": len(parts), "unit": "parts"},
                indeterminate=True,
                force=True,
            )
            report = verify_profile_backup(
                run_id=run_id,
                node_name=worker,
                profile=profile,
                parts_dir=parts_dir,
                tdl_diagnostics=diagnostics,
                run_record=run_record,
                part_records=parts,
                password=password,
            )
            report["download"] = {
                "status": "failed" if download_error else "complete",
                "reason_code": download_error or None,
            }
            if download_error:
                report["status"] = "failed"
                report["reason_codes"] = [download_error]
                report["checksums_match"] = False
                report["integrity"] = "not_checked"
                report["decryption"] = "not_checked"
                report["canary_evidence_status"] = "tdl_failed" if not diagnostics.get("ready") else "backup_failed"

        reporter.report(
            phase="completed",
            message=(
                "Arsip backup lolos verifikasi"
                if report.get("status") == "verified"
                else "Pemeriksaan selesai; lihat kode alasan pada laporan JSON"
            ),
            overall={"current": len(parts), "total": len(parts), "percent": 100, "unit": "parts"},
            indeterminate=False,
            force=True,
        )
        reporter.milestone("backup.verify.report", result={"report": report})
        return {"report": report}

    @staticmethod
    def _report_backup_download_bytes(
        reporter: ProgressReporter,
        value: Any,
        current_part: dict[str, Any],
        completed_bytes: int,
        total_bytes: int,
    ) -> None:
        index = int(current_part.get("index") or 0)
        total = int(current_part.get("total") or 0)
        name = str(current_part.get("part_name") or "")
        part_size = int(current_part.get("file_size") or 0)
        transfer = reporter.tdl_transfer(value, total_bytes=part_size)
        current_bytes = int(transfer.get("bytes_current") or 0)
        overall_bytes = min(total_bytes, completed_bytes + current_bytes)
        reporter.report(
            phase="downloading_backup_parts",
            message=f"Mengunduh part {index}/{total} dari channel backup",
            overall={
                "current": index - 1,
                "total": total,
                "percent": overall_bytes * 100 / total_bytes if total_bytes else None,
                "unit": "parts",
                "bytes_current": overall_bytes,
                "bytes_total": total_bytes,
            },
            item={"name": name, "index": index, "total": total},
            transfer=transfer,
        )
