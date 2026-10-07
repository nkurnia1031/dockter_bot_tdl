from __future__ import annotations

from fastapi import Depends
from tme3bot.api.schemas import (
    ObjectResponse,
    WorkerEnabledRequest,
    WorkerListResponse,
    WorkerRequest,
    WorkerRouteRequest,
    WorkerRuntimeSettingsRequest,
    WorkerTtsHealthResponse,
    WorkerTtsRecoveryResponse,
    WorkerUpdateRequest,
)
from tme3bot.domain.models import DomainError
from tme3bot.infrastructure.http_client import JsonHttpError

def register_workers(app, context, *, current_actor):

    @app.get("/api/v1/workers", response_model=WorkerListResponse)
    def list_workers(actor=Depends(current_actor)):
        return {
            "items": [
                {
                    "name": name,
                    "url": value["url"],
                    "enabled": bool(value.get("enabled", True)),
                    "selected": name
                    == context.profile_manager.worker_route(actor.profile),
                }
                for name, value in context.worker_registry.list().items()
            ]
        }

    @app.post("/api/v1/workers", response_model=ObjectResponse)
    def add_worker(body: WorkerRequest, actor=Depends(current_actor)):
        del actor
        name = context.worker_registry.upsert(
            body.name, body.url, body.token, enabled=body.enabled
        )
        return {"name": name}

    @app.put("/api/v1/workers/{name}", response_model=ObjectResponse)
    def update_worker(
        name: str, body: WorkerUpdateRequest, actor=Depends(current_actor)
    ):
        del actor
        current = context.worker_registry.get(name)
        if current is None:
            raise DomainError(
                "WORKER_NOT_FOUND", "Worker tidak ditemukan.", status_code=404
            )
        new_token = str(body.token or "").strip()
        same_endpoint = body.url.rstrip("/") == str(current.get("url") or "").rstrip("/")
        if new_token and same_endpoint and new_token != str(current.get("token") or ""):
            update_settings = getattr(context.worker_dispatcher, "update_worker_settings", None)
            if not callable(update_settings):
                raise DomainError(
                    "WORKER_TOKEN_ROTATION_UNAVAILABLE",
                    "Worker belum mendukung rotasi token langsung; perbarui worker terlebih dahulu.",
                    status_code=409,
                )
            try:
                update_settings(name, {"worker_api_token": new_token})
            except JsonHttpError as exc:
                if exc.status == 404:
                    raise DomainError(
                        "WORKER_UPDATE_REQUIRED",
                        "Perbarui aplikasi worker agar token dapat dirotasi dari Web.",
                        status_code=409,
                    ) from exc
                raise DomainError(
                    "WORKER_TOKEN_ROTATION_FAILED",
                    "Worker menolak rotasi token. Token gateway belum diubah.",
                    status_code=502,
                ) from exc
            except Exception as exc:
                raise DomainError(
                    "WORKER_UNAVAILABLE",
                    "Worker tidak dapat dihubungi; token gateway belum diubah.",
                    status_code=502,
                ) from exc
        token = new_token or str(current.get("token") or "")
        return {
            "name": context.worker_registry.upsert(
                name, body.url, token, enabled=body.enabled
            )
        }

    @app.patch("/api/v1/workers/{name}", response_model=ObjectResponse)
    def set_worker_enabled(
        name: str, body: WorkerEnabledRequest, actor=Depends(current_actor)
    ):
        del actor
        if context.worker_registry.get(name) is None:
            raise DomainError(
                "WORKER_NOT_FOUND", "Worker tidak ditemukan.", status_code=404
            )
        context.worker_registry.set_enabled(name, body.enabled)
        return {"name": name, "enabled": bool(body.enabled)}

    def tts_worker_error(name: str, exc: Exception) -> DomainError:
        if isinstance(exc, JsonHttpError):
            if exc.status == 404:
                return DomainError(
                    "WORKER_UPDATE_REQUIRED",
                    "Perbarui worker agar diagnosis dan pemulihan TTS tersedia.",
                    status_code=409,
                    details={"worker": name},
                )
            error_payload = exc.payload.get("error")
            error = error_payload if isinstance(error_payload, dict) else {}
            code = str(error.get("code") or "")
            safe_codes = {
                "TTS_HELPER_BUSY", "TTS_HELPER_ALREADY_READY", "TTS_RECOVERY_COOLDOWN",
                "TTS_HELPER_RECOVERING", "TTS_HELPER_UNAVAILABLE", "TTS_HELPER_SLOT_INVALID",
                "TTS_RECOVERY_REJECTED",
            }
            if code in safe_codes and 400 <= exc.status < 500:
                messages = {
                    "TTS_HELPER_BUSY": "Helper sedang memproses sintesis; coba lagi setelah selesai.",
                    "TTS_HELPER_ALREADY_READY": "Helper TTS sudah siap.",
                    "TTS_RECOVERY_COOLDOWN": "Tunggu sebentar sebelum meminta pemulihan lagi.",
                    "TTS_HELPER_RECOVERING": "Pemulihan helper TTS sedang berlangsung.",
                    "TTS_HELPER_UNAVAILABLE": "Helper TTS tidak dapat dihubungi.",
                    "TTS_HELPER_SLOT_INVALID": "Slot helper TTS tidak valid.",
                    "TTS_RECOVERY_REJECTED": "Helper TTS menolak permintaan pemulihan.",
                }
                return DomainError(
                    code,
                    messages.get(code, "Permintaan pemulihan TTS ditolak."),
                    status_code=exc.status,
                    details={
                        key: value for key, value in dict(error.get("details") or {}).items()
                        if key == "retry_after_seconds" and isinstance(value, int)
                    },
                )
            return DomainError(
                "WORKER_UNAVAILABLE",
                f"Worker {name} tidak dapat dihubungi untuk diagnosis TTS.",
                status_code=503 if exc.status >= 500 else 502,
                details={"worker": name},
            )
        return DomainError(
            "WORKER_UNAVAILABLE",
            f"Worker {name} tidak dapat dihubungi untuk diagnosis TTS.",
            status_code=503,
            details={"worker": name},
        )

    @app.get("/api/v1/workers/{name}/tts/health", response_model=WorkerTtsHealthResponse)
    def worker_tts_health(name: str, actor=Depends(current_actor)):
        if context.worker_registry.get(name) is None:
            raise DomainError("WORKER_NOT_FOUND", "Worker tidak ditemukan.", status_code=404)
        get_health = getattr(context.worker_dispatcher, "tts_health", None)
        if not callable(get_health):
            raise DomainError("WORKER_UPDATE_REQUIRED", "Backend belum mendukung diagnosis TTS worker.", status_code=409)
        try:
            result = get_health(name)
        except Exception as exc:
            raise tts_worker_error(name, exc) from None
        helpers = result.get("helpers") if isinstance(result, dict) else []
        helpers_ready = bool(result.get("helpers_ready")) if isinstance(result, dict) else False
        available_profiles = result.get("available_profiles") if isinstance(result, dict) else []
        if not isinstance(available_profiles, list):
            available_profiles = []
        safe_helpers = []
        allowed_statuses = {"ready", "bootstrapping", "tor_unreachable", "helper_unreachable"}
        for helper in helpers if isinstance(helpers, list) else []:
            if not isinstance(helper, dict):
                continue
            status = str(helper.get("status") or "helper_unreachable")
            if status not in allowed_statuses:
                status = "helper_unreachable"
            slot = helper.get("slot")
            if isinstance(slot, bool) or not isinstance(slot, int) or slot < 1 or slot > 3:
                continue
            percent = helper.get("bootstrap_percent")
            if isinstance(percent, bool) or not isinstance(percent, int) or not 0 <= percent <= 100:
                percent = None
            if status in {"tor_unreachable", "helper_unreachable"}:
                percent = None
            safe_helpers.append({
                "slot": slot,
                "status": status,
                "bootstrap_percent": percent,
                "checked_at": str(helper.get("checked_at") or "") or None,
            })
        safe_helpers.sort(key=lambda item: item["slot"])
        profile_session_ready = str(actor.profile) in {str(item) for item in available_profiles}
        helpers_ready = helpers_ready and len(safe_helpers) == 3 and all(item["status"] == "ready" for item in safe_helpers)
        return {
            "worker": name,
            "ready": helpers_ready and profile_session_ready,
            "helpers_ready": helpers_ready,
            "profile_session_ready": profile_session_ready,
            "helpers": safe_helpers,
        }

    @app.post(
        "/api/v1/workers/{name}/tts/helpers/{slot}/recover",
        response_model=WorkerTtsRecoveryResponse,
        status_code=202,
    )
    def recover_worker_tts_helper(name: str, slot: int, actor=Depends(current_actor)):
        del actor
        if slot < 1 or slot > 3:
            raise DomainError("TTS_HELPER_SLOT_INVALID", "Slot helper TTS harus 1, 2, atau 3.", status_code=422)
        if context.worker_registry.get(name) is None:
            raise DomainError("WORKER_NOT_FOUND", "Worker tidak ditemukan.", status_code=404)
        recover = getattr(context.worker_dispatcher, "recover_tts_helper", None)
        if not callable(recover):
            raise DomainError("WORKER_UPDATE_REQUIRED", "Backend belum mendukung pemulihan helper TTS.", status_code=409)
        try:
            result = recover(name, slot)
        except Exception as exc:
            raise tts_worker_error(name, exc) from None
        return {"worker": name, "slot": slot, "accepted": bool(result.get("accepted", True)), "status": str(result.get("status") or "restarting")}

    @app.get("/api/v1/workers/{name}/settings", response_model=ObjectResponse)
    def worker_settings(name: str, actor=Depends(current_actor)):
        del actor
        if context.worker_registry.get(name) is None:
            raise DomainError(
                "WORKER_NOT_FOUND", "Worker tidak ditemukan.", status_code=404
            )
        get_settings = getattr(context.worker_dispatcher, "worker_settings", None)
        if not callable(get_settings):
            raise DomainError(
                "WORKER_SETTINGS_UNAVAILABLE",
                "Backend belum mendukung pengaturan runtime worker.",
                status_code=503,
            )
        try:
            values = get_settings(name)
            settings_store = getattr(context, "runtime_settings_store", None)
            if settings_store is not None:
                try:
                    settings_store.seed_worker_once(
                        name, values, source="legacy-worker-settings"
                    )
                    snapshot = settings_store.snapshot("worker", worker=name)
                    return {
                        "worker": name,
                        **values,
                        "desired_version": snapshot["desired_version"],
                        "applied_version": snapshot["applied_version"],
                        "settings_status": snapshot["status"],
                    }
                except (TypeError, ValueError):
                    # Keep the old endpoint readable if a legacy worker reports
                    # a setting that no longer passes the current registry.
                    pass
            return {"worker": name, **values}
        except JsonHttpError as exc:
            if exc.status == 404:
                raise DomainError(
                    "WORKER_UPDATE_REQUIRED",
                    "Perbarui aplikasi worker agar pengaturan lewat Web tersedia.",
                    status_code=409,
                    details={"worker": name},
                ) from exc
            if 400 <= exc.status < 500:
                error_payload = exc.payload.get("error")
                error = error_payload if isinstance(error_payload, dict) else {}
                raise DomainError(
                    str(error.get("code") or "WORKER_SETTINGS_REJECTED"),
                    str(error.get("message") or "Worker menolak permintaan pengaturan."),
                    status_code=exc.status,
                    details={"worker": name},
                ) from exc
            raise DomainError(
                "WORKER_UNAVAILABLE",
                f"Worker {name} tidak dapat dihubungi.",
                status_code=502,
                details={"worker": name},
            ) from exc
        except Exception as exc:
            raise DomainError(
                "WORKER_UNAVAILABLE",
                f"Pengaturan worker {name} gagal dimuat.",
                status_code=502,
                details={"worker": name},
            ) from exc

    @app.put("/api/v1/workers/{name}/settings", response_model=ObjectResponse)
    def update_worker_settings(
        name: str, body: WorkerRuntimeSettingsRequest, actor=Depends(current_actor)
    ):
        if context.worker_registry.get(name) is None:
            raise DomainError(
                "WORKER_NOT_FOUND", "Worker tidak ditemukan.", status_code=404
            )
        update_settings = getattr(context.worker_dispatcher, "update_worker_settings", None)
        if not callable(update_settings):
            raise DomainError(
                "WORKER_SETTINGS_UNAVAILABLE",
                "Backend belum mendukung pengaturan runtime worker.",
                status_code=503,
            )
        try:
            payload = body.model_dump(exclude_unset=True) if hasattr(body, "model_dump") else body.dict(exclude_unset=True)
            applied = update_settings(name, payload)
            settings_store = getattr(context, "runtime_settings_store", None)
            if settings_store is not None:
                desired = {
                    key: value for key, value in payload.items()
                    if key in {
                        "job_stall_timeout_seconds", "tdl_export_stall_timeout_seconds",
                        "tdl_download_stall_timeout_seconds", "storage_profile", "tts_helper_urls",
                        "tts_tor_control_hosts", "tts_tor_control_ports", "tts_part_retries",
                        "tts_retry_base_seconds", "tts_newnym_after_retries",
                    }
                }
                if desired:
                    if "job_stall_timeout_seconds" in desired:
                        desired["worker_job_stall_timeout_seconds"] = desired.pop(
                            "job_stall_timeout_seconds"
                        )
                    snapshot = settings_store.snapshot("worker", worker=name)
                    saved = settings_store.update(
                        "worker", desired,
                        expected_version=int(snapshot["desired_version"]),
                        worker=name,
                        actor_user_id=int(actor.telegram_user_id),
                        source="legacy-worker-settings",
                    )
                    saved = settings_store.acknowledge(
                        "worker", name, int(saved["desired_version"])
                    )
                    applied.update({
                        "desired_version": saved["desired_version"],
                        "applied_version": saved["applied_version"],
                        "settings_status": saved["status"],
                    })
            return {"worker": name, **applied}
        except JsonHttpError as exc:
            if exc.status == 404:
                raise DomainError(
                    "WORKER_UPDATE_REQUIRED",
                    "Perbarui aplikasi worker agar pengaturan lewat Web tersedia.",
                    status_code=409,
                    details={"worker": name},
                ) from exc
            if 400 <= exc.status < 500:
                error_payload = exc.payload.get("error")
                error = error_payload if isinstance(error_payload, dict) else {}
                raise DomainError(
                    str(error.get("code") or "WORKER_SETTINGS_REJECTED"),
                    str(error.get("message") or "Worker menolak pengaturan tersebut."),
                    status_code=exc.status,
                    details={"worker": name},
                ) from exc
            raise DomainError(
                "WORKER_UNAVAILABLE",
                f"Worker {name} tidak dapat dihubungi.",
                status_code=502,
                details={"worker": name},
            ) from exc
        except Exception as exc:
            raise DomainError(
                "WORKER_UNAVAILABLE",
                f"Pengaturan worker {name} gagal disimpan.",
                status_code=502,
                details={"worker": name},
            ) from exc

    @app.delete("/api/v1/workers/{name}", response_model=ObjectResponse)
    def remove_worker(name: str, actor=Depends(current_actor)):
        del actor
        if any(
            context.profile_manager.worker_route(profile) == name
            for profile in context.profile_manager.list_profiles()
        ):
            raise DomainError(
                "WORKER_IN_USE",
                "Worker masih digunakan oleh profile.",
                status_code=409,
            )
        return {"removed": context.worker_registry.remove(name)}

    @app.put("/api/v1/me/worker-route", response_model=ObjectResponse)
    def set_worker_route(body: WorkerRouteRequest, actor=Depends(current_actor)):
        return {"route": context.control_plane.set_worker_route(actor, body.route)}
