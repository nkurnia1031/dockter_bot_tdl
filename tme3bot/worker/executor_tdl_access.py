from __future__ import annotations

import logging
import tempfile
from pathlib import Path
from urllib.parse import quote

from tme3bot.infrastructure.http_client import request_json
from tme3bot.progress_reporter import ProgressReporter
from tme3bot.tdl_access_fingerprint import tdl_access_inventory_fingerprint
from tme3bot.tdl import tdl_session_denial_code, tdl_write_denial_code

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
    "TDL_ACCESS_MARKER_PERMISSION_FAILED": "Worker tidak dapat menyiapkan file uji TDL.",
    "TDL_SESSION_UNAUTHORIZED": "Sesi TDL untuk profil ini belum terotorisasi. Periksa atau login ulang sesi export pada worker.",
    "CHAT_WRITE_FORBIDDEN": "Telegram menolak pengiriman karena akun tidak diizinkan mengirim ke tujuan.",
    "CHAT_ADMIN_REQUIRED": "Telegram mensyaratkan hak admin untuk mengirim ke tujuan.",
    "USER_BANNED_IN_CHANNEL": "Akun diblokir dari channel tujuan.",
    "CHANNEL_PRIVATE": "Akun tidak memiliki akses ke channel tujuan.",
    "CHAT_RESTRICTED": "Telegram membatasi akun untuk mengirim ke tujuan.",
    "USER_RESTRICTED": "Telegram membatasi akun untuk mengirim ke tujuan.",
    "VERIFICATION_FAILED": "Perintah TDL gagal. Buka log diagnosis worker untuk detail teknis yang aman.",
}

_UPLOAD_ACCESS_ERROR_MESSAGES = {
    "TDL_SESSION_DIRECTORY_MISSING": "Folder lane Upload profil ini belum tersedia pada worker.",
    "TDL_SESSION_DATABASE_MISSING": "Database lane Upload profil ini belum tersedia pada worker.",
    "TDL_SESSION_DATABASE_EMPTY": "Database lane Upload profil ini kosong.",
    "TDL_SESSION_DATABASE_INVALID": "Database lane Upload profil ini bukan file yang valid.",
    "TDL_SESSION_UNREADABLE": "Worker tidak dapat membaca database lane Upload profil ini.",
    "TDL_SESSION_UNAVAILABLE": "Lane Upload profil ini tidak tersedia untuk diuji.",
    "TDL_SESSION_UNAUTHORIZED": "Sesi pada lane Upload profil ini belum terotorisasi. Jalankan scan profil untuk menyiapkan ulang lane dari sesi Export.",
    "PROFILE_UPLOAD_LANE_NOT_READY": "Lane Upload profil ini belum siap. Jalankan scan profil lalu ulangi verifikasi.",
}


class TdlAccessMarkerPermissionError(RuntimeError):
    """Raised when the configured TDL process cannot read its test marker."""


def _tdl_access_error_code(exc: BaseException) -> str:
    denial = tdl_write_denial_code(exc)
    if denial:
        return denial

    session_denial = tdl_session_denial_code(exc)
    if session_denial:
        return session_denial
    return "VERIFICATION_FAILED"


def _prepare_tdl_access_marker(marker: Path) -> None:
    """Keep the test marker private for the root-run TDL process."""
    try:
        marker.parent.chmod(0o700)
        marker.chmod(0o600)
    except (AttributeError, ImportError, KeyError, OSError):
        raise TdlAccessMarkerPermissionError(
            "TDL_ACCESS_MARKER_PERMISSION_FAILED"
        ) from None


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

        list_profiles = getattr(self.profile_manager, "list_profiles", None)
        if callable(list_profiles):
            local_profiles = sorted(
                {str(item).strip().lower() for item in list_profiles() if str(item).strip()}
            )
        else:
            local_profiles = []
        normalized_profiles = list(local_profiles)
        session_fingerprints: dict[str, str] = {}
        inventory_hash = tdl_access_inventory_fingerprint(normalized_profiles, None)
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
                "session": "upload" if purpose == "storage" else "export",
                "command_template": _SAFE_TDL_COMMAND_TEMPLATE,
                "inventory_hash": inventory_hash,
                "session_fingerprints": session_fingerprints,
                "profiles": outcomes,
                "summary": {"total": 0, "tested": 0, "ready": 0, "failed": 0},
            }

        marker_context = tempfile.TemporaryDirectory(prefix="tme3bot-tdl-verify-")
        try:
            marker = Path(marker_context.name) / f"tdl-access-check-{job_id[:8]}.txt"
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
                outcome: dict[str, object] = {
                    "profile": profile,
                    "ready": False,
                    "session": "upload" if purpose == "storage" else "export",
                    "session_status": "not_checked",
                    "command_attempted": False,
                }
                try:
                    runtime = self.profile_manager.runtime(profile)
                    if purpose == "storage":
                        tdl_client = runtime.upload_tdl_client
                        operation_lock = runtime.upload_operation_lock
                    else:
                        tdl_client = runtime.export_tdl_client
                        operation_lock = runtime.export_operation_lock
                    with operation_lock:
                        marker.write_text(
                            "Pesan uji akses TDL. Pesan ini dapat dihapus manual setelah verifikasi.",
                            encoding="utf-8",
                        )
                        _prepare_tdl_access_marker(marker)
                        outcome["command_attempted"] = True
                        with self._capture_tdl_output(
                            tdl_client,
                            command_callback=self._command_callback(
                                profile=profile,
                                runtime="upload" if purpose == "storage" else "tts",
                            ),
                        ):
                            tdl_client.upload(
                                marker,
                                destination,
                                f"[TME3BOT TEST] Verifikasi akses kirim {purpose.upper()} - pesan uji, boleh dihapus.",
                            )
                    outcome["ready"] = True
                    LOGGER.info("TDL access verification succeeded job=%s purpose=%s profile=%s", job_id, purpose, profile)
                except TdlAccessMarkerPermissionError:
                    outcome["error_code"] = "TDL_ACCESS_MARKER_PERMISSION_FAILED"
                    outcome["error_message"] = _TDL_ACCESS_ERROR_MESSAGES[
                        "TDL_ACCESS_MARKER_PERMISSION_FAILED"
                    ]
                except Exception as exc:
                    outcome["error_code"] = _tdl_access_error_code(exc)
                    messages = (
                        {**_TDL_ACCESS_ERROR_MESSAGES, **_UPLOAD_ACCESS_ERROR_MESSAGES}
                        if purpose == "storage"
                        else _TDL_ACCESS_ERROR_MESSAGES
                    )
                    outcome["error_message"] = messages.get(
                        str(outcome["error_code"]),
                        messages["VERIFICATION_FAILED"],
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
            "session": "upload" if purpose == "storage" else "export",
            "command_template": _SAFE_TDL_COMMAND_TEMPLATE,
            "inventory_hash": inventory_hash,
            "session_fingerprints": session_fingerprints,
            "profiles": outcomes,
            "summary": {
                "total": len(outcomes),
                "tested": sum(item.get("command_attempted") is True for item in outcomes),
                "ready": sum(item.get("ready") is True for item in outcomes),
                "failed": sum(item.get("ready") is not True for item in outcomes),
            },
        }
