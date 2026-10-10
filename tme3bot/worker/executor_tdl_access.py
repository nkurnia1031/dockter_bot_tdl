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

        profiles = self.available_storage_profiles()
        normalized_profiles = sorted({str(item).strip().lower() for item in profiles if str(item).strip()})
        inventory_hash = hashlib.sha256(
            json.dumps(normalized_profiles, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        reporter = ProgressReporter(self.publisher, job_id)
        outcomes: list[dict[str, object]] = []
        if not normalized_profiles:
            reporter.report(
                phase="tdl_access_verify",
                message="Worker tidak memiliki sesi TDL export yang dapat diuji.",
                overall={"current": 0, "total": 0, "unit": "profiles", "percent": 100},
                force=True,
            )
            return {"purpose": purpose, "inventory_hash": inventory_hash, "profiles": outcomes}

        with tempfile.TemporaryDirectory(prefix="tme3bot-tdl-verify-") as temp_root:
            marker = Path(temp_root) / f"tdl-access-check-{job_id[:8]}.txt"
            marker.write_text(
                "Pesan uji akses TDL. Pesan ini dapat dihapus manual setelah verifikasi.",
                encoding="utf-8",
            )
            for index, profile in enumerate(normalized_profiles, start=1):
                if self._job_cancelled(job_id):
                    raise RuntimeError("TDL_ACCESS_VERIFICATION_CANCELLED: verifikasi dibatalkan.")
                reporter.report(
                    phase="tdl_access_verify",
                    message=f"Menguji akses kirim profil {profile} ({index}/{len(normalized_profiles)}).",
                    overall={
                        "current": index - 1,
                        "total": len(normalized_profiles),
                        "unit": "profiles",
                        "percent": round((index - 1) * 100 / len(normalized_profiles)),
                    },
                    force=True,
                )
                outcome: dict[str, object] = {"profile": profile, "ready": False}
                try:
                    runtime = self.profile_manager.runtime(profile)
                    with runtime.export_operation_lock:
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
                    LOGGER.warning(
                        "TDL access verification failed job=%s purpose=%s profile=%s code=%s",
                        job_id,
                        purpose,
                        profile,
                        outcome["error_code"],
                    )
                outcomes.append(outcome)
                reporter.report(
                    phase="tdl_access_verify",
                    message=f"Pemeriksaan profil {profile} selesai ({index}/{len(normalized_profiles)}).",
                    overall={
                        "current": index,
                        "total": len(normalized_profiles),
                        "unit": "profiles",
                        "percent": round(index * 100 / len(normalized_profiles)),
                    },
                    counters={
                        "succeeded": sum(item.get("ready") is True for item in outcomes),
                        "failed": sum(item.get("ready") is not True for item in outcomes),
                    },
                    force=True,
                )
        return {"purpose": purpose, "inventory_hash": inventory_hash, "profiles": outcomes}
