from __future__ import annotations

import hashlib
import json
import logging
import tempfile
from pathlib import Path
from urllib.parse import quote

from tme3bot.infrastructure.http_client import request_json
from tme3bot.progress_reporter import ProgressReporter
from tme3bot.tdl import tdl_write_denial_code

LOGGER = logging.getLogger(__name__)

_SAFE_TDL_COMMAND_TEMPLATE = (
    "tdl --storage type=bolt,path=<session-database> -n <export-namespace> "
    "up -p <temporary-test-file> -c <configured-destination> "
    "--caption <temporary-caption-file>"
)

_TDL_ACCESS_ERROR_MESSAGES = {
    "TDL_SESSION_DIRECTORY_MISSING": "Folder sesi export profil ini tidak ditemukan pada worker.",
    "TDL_SESSION_DATABASE_MISSING": "Database sesi TDL export profil ini tidak ditemukan pada worker.",
    "TDL_SESSION_DATABASE_EMPTY": "Database sesi TDL export profil ini kosong.",
    "TDL_SESSION_DATABASE_INVALID": "Database sesi TDL export profil ini bukan file yang valid.",
    "TDL_SESSION_UNREADABLE": "Worker tidak dapat membaca database sesi TDL export profil ini.",
    "TDL_SESSION_UNAVAILABLE": "Sesi TDL export profil ini tidak tersedia untuk diuji.",
    "CHAT_WRITE_FORBIDDEN": "Telegram menolak pengiriman karena akun tidak diizinkan mengirim ke tujuan.",
    "CHAT_ADMIN_REQUIRED": "Telegram mensyaratkan hak admin untuk mengirim ke tujuan.",
    "USER_BANNED_IN_CHANNEL": "Akun diblokir dari channel tujuan.",
    "CHANNEL_PRIVATE": "Akun tidak memiliki akses ke channel tujuan.",
    "CHAT_RESTRICTED": "Telegram membatasi akun untuk mengirim ke tujuan.",
    "USER_RESTRICTED": "Telegram membatasi akun untuk mengirim ke tujuan.",
    "VERIFICATION_FAILED": "Perintah TDL gagal. Buka log diagnosis worker untuk detail teknis yang aman.",
}


class TdlAccessExecutorMixin:
    def _tdl_access_verify(self, command: dict) -> dict:
        job_id = str(command["job_id"])
        worker = str(command.get("worker") or self.config.backup_node_name).strip().lower()
        payload = command.get("payload") if isinstance(command.get("payload"), dict) else {}
        purpose = str(payload.get("purpose") or "").strip().lower()
        if purpose not in {"tts", "storage"}:
            raise RuntimeError("TDL_ACCESS_PURPOSE_INVALID: tujuan verifikasi tidak valid.")

        target = request_json(
            self.config.backend_api_url,
            self.config.backend_internal_token,
            "GET",
            f"/internal/v1/tdl-access/jobs/{quote(job_id, safe='')}/target?worker={quote(worker, safe='')}",
            timeout=15,
        )
        destination = str(target.get("target") or "").strip() if isinstance(target, dict) else ""
        if not destination:
            raise RuntimeError("TDL_ACCESS_TARGET_UNAVAILABLE: tujuan verifikasi tidak tersedia.")

        secrets = getattr(self._job_log, "secrets", None)
        if isinstance(secrets, list) and destination not in secrets:
            secrets.append(destination)

        available_profiles = {
            str(item).strip().lower()
            for item in self.available_storage_profiles()
            if str(item).strip()
        }
        list_profiles = getattr(self.profile_manager, "list_profiles", None)
        if callable(list_profiles):
            local_profiles = sorted(
                {str(item).strip().lower() for item in list_profiles() if str(item).strip()}
            )
        else:
            local_profiles = sorted(available_profiles)
        session_diagnostic = getattr(self.profile_manager, "tdl_session_diagnostic", None)
        diagnostics: dict[str, dict[str, object]] = {}
        if callable(session_diagnostic):
            for profile in local_profiles:
                value = session_diagnostic(profile, "export")
                if isinstance(value, dict):
                    diagnostics[profile] = value
        normalized_profiles = sorted(
            profile
            for profile in available_profiles
            if not diagnostics or diagnostics.get(profile, {}).get("available") is True
        )
        inventory_hash = hashlib.sha256(
            json.dumps(normalized_profiles, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        reporter = ProgressReporter(self.publisher, job_id)
        outcomes: list[dict[str, object]] = []
        if not local_profiles:
            reporter.report(
                phase="tdl_access_verify",
                message="Worker tidak menemukan profil lokal untuk diperiksa.",
                overall={"current": 0, "total": 0, "unit": "profiles", "percent": 100},
                force=True,
            )
            return {
                "purpose": purpose,
                "session": "export",
                "command_template": _SAFE_TDL_COMMAND_TEMPLATE,
                "inventory_hash": inventory_hash,
                "profiles": outcomes,
                "summary": {"total": 0, "tested": 0, "ready": 0, "failed": 0},
            }

        marker_context = tempfile.TemporaryDirectory(prefix="tme3bot-tdl-verify-")
        try:
            marker = Path(marker_context.name) / f"tdl-access-check-{job_id[:8]}.txt"
            tested_profiles = set(normalized_profiles)
            for index, profile in enumerate(local_profiles, start=1):
                if self._job_cancelled(job_id):
                    raise RuntimeError("TDL_ACCESS_VERIFICATION_CANCELLED: verifikasi dibatalkan.")
                reporter.report(
                    phase="tdl_access_verify",
                    message=f"Memeriksa sesi profil {profile} ({index}/{len(local_profiles)}).",
                    overall={
                        "current": index - 1,
                        "total": len(local_profiles),
                        "unit": "profiles",
                        "percent": round((index - 1) * 100 / len(local_profiles)),
                    },
                    force=True,
                )
                diagnostic = diagnostics.get(profile, {})
                is_available = profile in tested_profiles
                error_code = str(diagnostic.get("error_code") or "TDL_SESSION_UNAVAILABLE")
                outcome: dict[str, object] = {
                    "profile": profile,
                    "ready": False,
                    "session": "export",
                    "session_status": "ready" if is_available else "unavailable",
                    "command_attempted": False,
                }
                if not is_available:
                    outcome["error_code"] = error_code
                    outcome["error_message"] = _TDL_ACCESS_ERROR_MESSAGES.get(
                        error_code, _TDL_ACCESS_ERROR_MESSAGES["TDL_SESSION_UNAVAILABLE"]
                    )
                    outcomes.append(outcome)
                    reporter.report(
                        phase="tdl_access_verify",
                        message=f"Profil {profile} dilewati ({error_code}); perintah TDL tidak dijalankan.",
                        overall={
                            "current": index,
                            "total": len(local_profiles),
                            "unit": "profiles",
                            "percent": round(index * 100 / len(local_profiles)),
                        },
                        counters={
                            "succeeded": sum(item.get("ready") is True for item in outcomes),
                            "failed": sum(item.get("ready") is not True for item in outcomes),
                        },
                        force=True,
                    )
                    continue

                outcome["command_attempted"] = True
                try:
                    runtime = self.profile_manager.runtime(profile)
                    with runtime.export_operation_lock:
                        marker.write_text(
                            "Pesan uji akses TDL. Pesan ini dapat dihapus manual setelah verifikasi.",
                            encoding="utf-8",
                        )
                        runtime.export_tdl_client.upload(
                            marker,
                            destination,
                            f"[TME3BOT TEST] Verifikasi akses kirim {purpose.upper()} - pesan uji, boleh dihapus.",
                        )
                    outcome["ready"] = True
                    LOGGER.info("TDL access verification succeeded job=%s purpose=%s profile=%s", job_id, purpose, profile)
                except Exception as exc:
                    denial = tdl_write_denial_code(exc)
                    outcome["error_code"] = denial or "VERIFICATION_FAILED"
                    outcome["error_message"] = _TDL_ACCESS_ERROR_MESSAGES.get(
                        str(outcome["error_code"]),
                        _TDL_ACCESS_ERROR_MESSAGES["VERIFICATION_FAILED"],
                    )
                    LOGGER.warning(
                        "TDL access verification failed job=%s purpose=%s profile=%s code=%s exception=%s",
                        job_id,
                        purpose,
                        profile,
                        outcome["error_code"],
                        type(exc).__name__,
                    )
                outcomes.append(outcome)
                result_message = (
                    f"siap" if outcome.get("ready") is True
                    else f"gagal ({outcome.get('error_code', 'VERIFICATION_FAILED')})"
                )
                reporter.report(
                    phase="tdl_access_verify",
                    message=f"Profil {profile}: {result_message} ({index}/{len(local_profiles)}).",
                    overall={
                        "current": index,
                        "total": len(local_profiles),
                        "unit": "profiles",
                        "percent": round(index * 100 / len(local_profiles)),
                    },
                    counters={
                        "succeeded": sum(item.get("ready") is True for item in outcomes),
                        "failed": sum(item.get("ready") is not True for item in outcomes),
                    },
                    force=True,
                )
        finally:
            marker_context.cleanup()
        return {
            "purpose": purpose,
            "session": "export",
            "command_template": _SAFE_TDL_COMMAND_TEMPLATE,
            "inventory_hash": inventory_hash,
            "profiles": outcomes,
            "summary": {
                "total": len(outcomes),
                "tested": sum(item.get("command_attempted") is True for item in outcomes),
                "ready": sum(item.get("ready") is True for item in outcomes),
                "failed": sum(item.get("ready") is not True for item in outcomes),
            },
        }
