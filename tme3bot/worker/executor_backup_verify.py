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
        matched_parts: list[dict[str, Any]] = []
        completed_bytes = 0
        expected_total_bytes = sum(
            int(item.get("file_size") or 0)
            for item in parts
            if isinstance(item, dict)
        )

        parts_dir: Path | None = None

        def report_download(
            stage: str,
            index: int,
            total: int,
            part_name: str,
            message_id: int | None = None,
        ) -> None:
            nonlocal completed_bytes
            current_part.clear()
            row = next((item for item in parts if isinstance(item, dict) and item.get("part_name") == part_name), {})
            current_part.update({"index": index, "total": total, **row})
            if stage == "matched" and message_id is not None:
                matched_parts.append({"name": part_name, "message_id": message_id})
                reporter.report(
                    phase="matching_backup_parts",
                    message=f"Part {index}/{total} cocok dengan worker dan run yang dipilih",
                    overall={"current": index, "total": total, "unit": "parts"},
                    item={"name": part_name, "index": index, "total": total},
                    force=True,
                )
                return
            if stage == "scanning":
                reporter.report(
                    phase="scanning_backup_channel",
                    message="Mengekspor JSON channel backup untuk mencari caption worker dan run",
                    overall={"current": 0, "total": 0, "unit": "messages"},
                    indeterminate=True,
                    force=True,
                )
                return
            if stage == "downloaded":
                downloaded_path = parts_dir / part_name if parts_dir is not None else None
                downloaded_size = (
                    downloaded_path.stat().st_size
                    if downloaded_path is not None and downloaded_path.is_file()
                    else int(row.get("file_size") or 0)
                )
                completed_bytes += downloaded_size
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
                    message=f"Mengunduh part {index}/{total} berdasarkan message ID hasil pencocokan",
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
                            node_name=worker,
                            run_id=run_id,
                            parts=parts,
                            destination=parts_dir,
                            progress=report_download,
                        )
            except BackupChannelDownloadError as exc:
                download_error = exc.code

            downloaded_files = sorted(
                path
                for path in parts_dir.iterdir()
                if path.is_file() and not path.is_symlink()
            )
            catalog_parts_by_name = {
                str(item.get("part_name") or ""): item
                for item in parts
                if isinstance(item, dict)
            }
            verification_parts: list[dict[str, Any]] = []
            for path in downloaded_files:
                record: dict[str, Any] = {"part_name": path.name}
                catalog_part = catalog_parts_by_name.get(path.name, {})
                size = catalog_part.get("file_size")
                digest = str(catalog_part.get("sha256") or "").lower()
                if type(size) is int and size > 0:
                    record["file_size"] = size
                if len(digest) == 64 and all(char in "0123456789abcdef" for char in digest):
                    record["sha256"] = digest
                verification_parts.append(record)

            reporter.report(
                phase="verifying_archive",
                message="Memeriksa checksum, password, integritas, dan sesi di arsip",
                overall={"current": len(downloaded_files), "total": len(downloaded_files), "unit": "parts"},
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
                part_records=verification_parts,
                password=password,
            )
            report["download"] = {
                "status": "failed" if download_error else "complete",
                "reason_code": download_error or None,
                "source": "tdl_export_json_with_content",
                "matched_parts": matched_parts,
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
            overall={
                "current": int(report.get("part_count") or 0),
                "total": int(report.get("part_count") or 0),
                "percent": 100 if report.get("status") == "verified" else None,
                "unit": "parts",
            },
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
