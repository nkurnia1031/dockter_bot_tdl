from __future__ import annotations

import re
from dataclasses import asdict
from fastapi import Depends, Query
from tme3bot.api.schemas import ItemListResponse, JobResponse, ObjectResponse, RcloneStorageActionRequest, RcloneStorageManageRequest, StorageBulkActionRequest, StorageDeliveryRequest, StorageDownloadRequest, StorageFolderRequest, StorageFolderUpdateRequest, StorageItemListResponse, StorageItemResponse, StoragePublicLinkRevokeRequest, StorageSettingsResponse, StorageSyncRequest, StorageUpdateRequest, StorageUploadRequest, TelegramStorageDeliveryRequest
from tme3bot.domain.models import DomainError
from tme3bot.storage_catalog import build_storage_caption, storage_item_dict
from tme3bot.storage_links import sign_storage_item, verify_storage_item
import uuid

def register_storage(app, context, *, _active_storage_item, _deliver_storage_telegram, _model_dict, _require_storage_folders_idle, _storage_item, current_actor, job_dict, require_service):

    def _rclone_relative_path(path: str) -> str:
        normalized = str(path or "").replace("\\", "/").strip("/")
        parts = normalized.split("/") if normalized else []
        if (
            len(normalized) > 2048
            or any(ord(char) < 32 for char in normalized)
            or str(path or "").startswith(("/", "\\"))
            or any(not part or part in {".", ".."} or ":" in part for part in parts)
        ):
            raise DomainError(
                "RCLONE_BROWSER_PATH_INVALID",
                "Path rclone harus berada di bawah root yang dikonfigurasi.",
                status_code=422,
            )
        return normalized

    def _rclone_entry_name(name: str) -> str:
        normalized = str(name or "").strip()
        if (
            not normalized
            or len(normalized) > 120
            or normalized in {".", ".."}
            or any(char in normalized for char in ("/", "\\", ":"))
            or any(ord(char) < 32 for char in normalized)
        ):
            raise DomainError(
                "RCLONE_BROWSER_NAME_INVALID",
                "Nama file atau folder rclone tidak valid.",
                status_code=422,
            )
        return normalized

    @app.get("/api/v1/storage/rclone/browser", response_model=ObjectResponse)
    def rclone_storage_browser(
        worker: str,
        path: str = "",
        q: str = "",
        sort: str = Query("name", pattern="^(name|updated_at|size|type)$"),
        order: str = Query("asc", pattern="^(asc|desc)$"),
        limit: int = Query(100, ge=1, le=200),
        offset: int = Query(0, ge=0),
        actor=Depends(current_actor),
    ):
        normalized_path = _rclone_relative_path(path)
        _, selected_worker = context.control_plane.resolve_target(
            actor, worker=worker
        )
        settings = context.utility_settings.get()
        destination = str(settings.get("rclone_destination") or "googledrive:backup").strip()
        gate = getattr(context.control_plane, "runtime_readiness_gate", None)
        browser = getattr(context.worker_dispatcher, "rclone_storage_browse", None)
        if not callable(browser):
            raise DomainError("WORKER_UPDATE_REQUIRED", "Worker belum mendukung browser rclone Storage.", status_code=503)
        try:
            result = browser(
                selected_worker, destination, path=normalized_path, q=q, sort=sort,
                order=order, limit=limit, offset=offset,
            )
            if gate is not None:
                gate.record_command_result(
                    worker=selected_worker, profile=None, runtime="rclone_storage", succeeded=True
                )
            return result
        except Exception as exc:
            code = str(getattr(exc, "code", "") or "")
            if code == "RCLONE_ACCESS_FAILED":
                if gate is not None:
                    gate.record_command_result(
                        worker=selected_worker, profile=None, runtime="rclone_storage",
                        succeeded=False, reason_code=code,
                    )
                raise DomainError("RCLONE_ACCESS_FAILED", "Worker tidak dapat membaca remote rclone.", status_code=503) from exc
            raise DomainError("RCLONE_BROWSER_FAILED", "Worker tidak dapat memuat folder rclone.", status_code=503) from exc

    @app.get("/api/v1/storage/rclone/folder-summaries", response_model=ObjectResponse)
    def rclone_storage_folder_summaries(worker: str, path: str = "", actor=Depends(current_actor)):
        normalized_path = _rclone_relative_path(path)
        _, selected_worker = context.control_plane.resolve_target(
            actor, worker=worker
        )
        settings = context.utility_settings.get()
        destination = str(settings.get("rclone_destination") or "googledrive:backup").strip()
        gate = getattr(context.control_plane, "runtime_readiness_gate", None)
        summarize = getattr(context.worker_dispatcher, "rclone_storage_folder_summaries", None)
        if not callable(summarize):
            raise DomainError("WORKER_UPDATE_REQUIRED", "Worker belum mendukung ringkasan folder rclone.", status_code=503)
        try:
            result = summarize(selected_worker, destination, path=normalized_path)
            if gate is not None:
                gate.record_command_result(
                    worker=selected_worker, profile=None, runtime="rclone_storage", succeeded=True
                )
            return result
        except Exception as exc:
            code = str(getattr(exc, "code", "") or "")
            if code == "RCLONE_ACCESS_FAILED":
                if gate is not None:
                    gate.record_command_result(
                        worker=selected_worker, profile=None, runtime="rclone_storage",
                        succeeded=False, reason_code=code,
                    )
                raise DomainError("RCLONE_ACCESS_FAILED", "Worker tidak dapat membaca remote rclone.", status_code=503) from exc
            raise DomainError("RCLONE_FOLDER_SUMMARY_FAILED", "Worker tidak dapat menghitung isi folder rclone.", status_code=503) from exc

    @app.post("/api/v1/storage/rclone/actions", response_model=ObjectResponse)
    def rclone_storage_action(body: RcloneStorageActionRequest, actor=Depends(current_actor)):
        path = _rclone_relative_path(body.path)
        name = _rclone_entry_name(body.name)
        if body.action == "rename" and not path:
            raise DomainError(
                "RCLONE_BROWSER_PATH_INVALID",
                "Root remote tidak dapat di-rename.",
                status_code=422,
            )
        _, selected_worker = context.control_plane.resolve_target(
            actor, worker=body.worker
        )
        settings = context.utility_settings.get()
        destination = str(settings.get("rclone_destination") or "googledrive:backup").strip()
        mutate = getattr(context.worker_dispatcher, "rclone_storage_mutate", None)
        if not callable(mutate):
            raise DomainError(
                "WORKER_UPDATE_REQUIRED",
                "Worker belum mendukung pengelolaan Storage rclone.",
                status_code=503,
            )
        gate = getattr(context.control_plane, "runtime_readiness_gate", None)
        try:
            result = mutate(
                selected_worker, destination, action=body.action, path=path, name=name
            )
            if gate is not None:
                gate.record_command_result(
                    worker=selected_worker,
                    profile=None,
                    runtime="rclone_storage",
                    succeeded=True,
                )
            return result
        except Exception as exc:
            payload = getattr(exc, "payload", {})
            nested = payload.get("error", {}) if isinstance(payload, dict) else {}
            code = (
                str(getattr(exc, "code", "") or "")
                or (str(nested.get("code", "")) if isinstance(nested, dict) else "")
            )
            status_by_code = {
                "RCLONE_BROWSER_PATH_INVALID": 422,
                "RCLONE_BROWSER_NAME_INVALID": 422,
                "RCLONE_ACTION_REQUEST_INVALID": 422,
                "RCLONE_ACTION_INVALID": 422,
                "RCLONE_PERMANENT_DELETE_UNSUPPORTED": 422,
                "RCLONE_TARGET_EXISTS": 409,
                "RCLONE_SOURCE_NOT_FOUND": 404,
            }
            status = status_by_code.get(
                code, int(getattr(exc, "status", 503) or 503)
            )
            if code == "RCLONE_ACCESS_FAILED" and gate is not None:
                gate.record_command_result(
                    worker=selected_worker,
                    profile=None,
                    runtime="rclone_storage",
                    succeeded=False,
                    reason_code=code,
                )
            message_by_code = {
                "RCLONE_BROWSER_PATH_INVALID": "Path rclone tidak valid.",
                "RCLONE_BROWSER_NAME_INVALID": "Nama file atau folder rclone tidak valid.",
                "RCLONE_TARGET_EXISTS": "Nama tujuan rclone sudah ada.",
                "RCLONE_SOURCE_NOT_FOUND": "File atau folder rclone tidak ditemukan.",
                "RCLONE_PERMANENT_DELETE_UNSUPPORTED": "Backend rclone ini belum dapat dipastikan mendukung hapus permanen; tidak ada perubahan yang dilakukan.",
            }
            raise DomainError(
                code or "RCLONE_ACTION_FAILED",
                message_by_code.get(code, "Worker tidak dapat mengubah remote rclone."),
                status_code=status,
            ) from exc

    @app.get("/api/v1/storage/rclone/trash", response_model=ObjectResponse)
    def rclone_storage_trash(
        worker: str,
        limit: int = Query(100, ge=1, le=200),
        offset: int = Query(0, ge=0),
        actor=Depends(current_actor),
    ):
        _, selected_worker = context.control_plane.resolve_target(
            actor, worker=worker
        )
        settings = context.utility_settings.get()
        destination = str(settings.get("rclone_destination") or "googledrive:backup").strip()
        listing = getattr(context.worker_dispatcher, "rclone_storage_trash", None)
        if not callable(listing):
            raise DomainError(
                "WORKER_UPDATE_REQUIRED",
                "Worker belum mendukung daftar Trash rclone.",
                status_code=503,
            )
        gate = getattr(context.control_plane, "runtime_readiness_gate", None)
        try:
            result = listing(
                selected_worker, destination, limit=limit, offset=offset
            )
            if result.get("supported") is True and gate is not None:
                gate.record_command_result(
                    worker=selected_worker,
                    profile=None,
                    runtime="rclone_storage",
                    succeeded=True,
                )
            return result
        except Exception as exc:
            code = str(getattr(exc, "code", "") or "")
            if code in {"RCLONE_ACCESS_FAILED", "RCLONE_LIST_FAILED", "RCLONE_RUNTIME_UNAVAILABLE"} and gate is not None:
                gate.record_command_result(
                    worker=selected_worker,
                    profile=None,
                    runtime="rclone_storage",
                    succeeded=False,
                    reason_code=code,
                )
            raise DomainError(
                code or "RCLONE_TRASH_LIST_FAILED",
                "Worker tidak dapat memuat Trash rclone.",
                status_code=int(getattr(exc, "status", 0) or 503),
            ) from exc

    @app.post("/api/v1/storage/rclone/jobs", response_model=JobResponse)
    def submit_rclone_storage_job(
        body: RcloneStorageManageRequest, actor=Depends(current_actor)
    ):
        action = body.action
        if action == "purge" and body.confirmed is not True:
            raise DomainError(
                "RCLONE_PURGE_CONFIRMATION_REQUIRED",
                "Penghapusan permanen memerlukan konfirmasi eksplisit.",
                status_code=422,
            )
        sources = []
        for source in body.sources:
            path = _rclone_relative_path(source.path)
            if not path:
                raise DomainError(
                    "RCLONE_BROWSER_PATH_INVALID",
                    "Root rclone tidak dapat dipilih sebagai item.",
                    status_code=422,
                )
            selected = {"path": path, "is_dir": source.is_dir}
            if source.id:
                selected["id"] = source.id
            sources.append(selected)
        destination_path = _rclone_relative_path(body.destination_path)
        if action in {"copy", "move"}:
            if body.trashed:
                raise DomainError(
                    "RCLONE_ACTION_REQUEST_INVALID",
                    "Copy dan move hanya berlaku untuk item aktif.",
                    status_code=422,
                )
        elif action == "restore" and not body.trashed:
            raise DomainError(
                "RCLONE_ACTION_REQUEST_INVALID",
                "Restore hanya berlaku untuk item Trash.",
                status_code=422,
            )
        elif action == "trash" and body.trashed:
            raise DomainError(
                "RCLONE_ACTION_REQUEST_INVALID",
                "Item Trash tidak dapat dipindahkan ke Trash lagi.",
                status_code=422,
            )
        if action not in {"copy", "move"} and destination_path:
            raise DomainError(
                "RCLONE_ACTION_REQUEST_INVALID",
                "Tujuan hanya berlaku untuk copy dan move.",
                status_code=422,
            )
        _, selected_worker = context.control_plane.resolve_target(
            actor, worker=body.worker
        )
        settings = context.utility_settings.get()
        payload = {
            "action": action,
            "sources": sources,
            "destination_path": destination_path,
            "trashed": body.trashed,
            "rclone_destination": str(
                settings.get("rclone_destination") or "googledrive:backup"
            ).strip(),
        }
        return job_dict(
            context.control_plane.submit_job(
                actor,
                "storage_rclone_manage",
                payload,
                profile=actor.profile,
                worker=selected_worker,
            )
        )

    @app.get("/api/v1/storage/items", response_model=StorageItemListResponse)
    def search_storage(
        q: str = "",
        mine: bool = False,
        limit: int = Query(10, ge=1, le=100),
        offset: int = Query(0, ge=0),
        actor=Depends(current_actor),
    ):
        owner = actor.telegram_user_id if mine else None
        items = [
                storage_item_dict(item)
                for item in context.storage_catalog.search(
                    q, owner_user_id=owner, limit=limit, offset=offset
                )
            ]
        return {"items": items, "total": context.storage_catalog.count(q, owner_user_id=owner)}

    @app.get("/api/v1/storage/browser", response_model=ObjectResponse)
    def storage_browser(
        folder_id: str = "root",
        scope: str = Query("current", pattern="^(current|global|recent|trash)$"),
        q: str = "",
        sort: str = Query("name", pattern="^(name|updated_at|size|type)$"),
        order: str = Query("asc", pattern="^(asc|desc)$"),
        limit: int = Query(50, ge=1, le=200),
        offset: int = Query(0, ge=0),
        actor=Depends(current_actor),
    ):
        del actor
        try:
            parsed = None if folder_id in {"", "root", "null"} else int(folder_id)
            return context.storage_catalog.browser(
                parsed, scope=scope, query=q, sort=sort, order=order,
                limit=limit, offset=offset,
                retention_days=getattr(
                    context.config, "storage_trash_retention_days", 30
                ),
            )
        except (ValueError, KeyError) as exc:
            raise DomainError("STORAGE_FOLDER_INVALID", str(exc), status_code=400) from exc

    @app.get("/api/v1/storage/folders/tree", response_model=ItemListResponse)
    def storage_folder_tree(include_trash: bool = False, actor=Depends(current_actor)):
        del actor
        return {"items": context.storage_catalog.folder_tree(include_trash=include_trash)}

    @app.post("/api/v1/storage/folders", response_model=ObjectResponse)
    def create_storage_folder(body: StorageFolderRequest, actor=Depends(current_actor)):
        try:
            folder = context.storage_catalog.create_folder(
                body.name, actor.telegram_user_id, body.parent_id
            )
            return asdict(folder)
        except (ValueError, KeyError) as exc:
            raise DomainError("STORAGE_FOLDER_INVALID", str(exc), status_code=409) from exc

    @app.patch("/api/v1/storage/folders/{folder_id}", response_model=ObjectResponse)
    def update_storage_folder(
        folder_id: int, body: StorageFolderUpdateRequest, actor=Depends(current_actor)
    ):
        del actor
        try:
            values = _model_dict(body)
            folder = context.storage_catalog.move_folder(
                folder_id,
                values.get("parent_id"),
                name=values.get("name"),
                keep_parent="parent_id" not in getattr(body, "model_fields_set", getattr(body, "__fields_set__", set())),
            )
            return asdict(folder)
        except (ValueError, KeyError) as exc:
            raise DomainError("STORAGE_FOLDER_INVALID", str(exc), status_code=409) from exc

    @app.delete("/api/v1/storage/folders/{folder_id}", response_model=ObjectResponse)
    def trash_storage_folder(folder_id: int, actor=Depends(current_actor)):
        _require_storage_folders_idle(context, [folder_id])
        return {"folders": [asdict(item) for item in context.storage_catalog.trash_folders([folder_id], actor.telegram_user_id)]}

    @app.post("/api/v1/storage/folders/{folder_id}/restore", response_model=ObjectResponse)
    def restore_storage_folder(folder_id: int, actor=Depends(current_actor)):
        del actor
        return {"folders": [asdict(item) for item in context.storage_catalog.restore_folders([folder_id])]}

    @app.delete("/api/v1/storage/folders/{folder_id}/purge", response_model=ObjectResponse)
    def purge_storage_folder(folder_id: int, actor=Depends(current_actor)):
        del actor
        _require_storage_folders_idle(context, [folder_id])
        if context.storage_maintenance is None:
            raise DomainError("STORAGE_PURGE_UNAVAILABLE", "Layanan purge belum aktif.", status_code=503)
        return context.storage_maintenance.purge_folders([folder_id])

    @app.post("/api/v1/storage/actions/move", response_model=ObjectResponse)
    def move_storage_entries(body: StorageBulkActionRequest, actor=Depends(current_actor)):
        del actor
        try:
            items = context.storage_catalog.move_items(body.item_ids, body.destination_folder_id)
            folders = [
                context.storage_catalog.move_folder(folder_id, body.destination_folder_id)
                for folder_id in body.folder_ids
            ]
            return {"items": [storage_item_dict(item) for item in items], "folders": [asdict(folder) for folder in folders]}
        except (ValueError, KeyError) as exc:
            raise DomainError("STORAGE_MOVE_INVALID", str(exc), status_code=409) from exc

    @app.post("/api/v1/storage/actions/trash", response_model=ObjectResponse)
    def trash_storage_entries(body: StorageBulkActionRequest, actor=Depends(current_actor)):
        _require_storage_folders_idle(context, body.folder_ids)
        return {
            "items": [storage_item_dict(item) for item in context.storage_catalog.trash_items(body.item_ids, actor.telegram_user_id)],
            "folders": [asdict(folder) for folder in context.storage_catalog.trash_folders(body.folder_ids, actor.telegram_user_id)],
        }

    @app.post("/api/v1/storage/actions/restore", response_model=ObjectResponse)
    def restore_storage_entries(body: StorageBulkActionRequest, actor=Depends(current_actor)):
        del actor
        return {
            "items": [storage_item_dict(item) for item in context.storage_catalog.restore_items(body.item_ids)],
            "folders": [asdict(folder) for folder in context.storage_catalog.restore_folders(body.folder_ids)],
        }

    @app.post("/api/v1/storage/actions/purge", response_model=ObjectResponse)
    def purge_storage_entries(body: StorageBulkActionRequest, actor=Depends(current_actor)):
        del actor
        _require_storage_folders_idle(context, body.folder_ids)
        if context.storage_maintenance is None:
            raise DomainError("STORAGE_PURGE_UNAVAILABLE", "Layanan purge belum aktif.", status_code=503)
        return context.storage_maintenance.purge(body.item_ids, body.folder_ids)

    @app.get("/api/v1/storage/settings", response_model=StorageSettingsResponse)
    def storage_settings(actor=Depends(current_actor)):
        del actor
        title = "-"
        if context.bot is not None and context.config.storage_channel_id:
            try:
                chat = context.bot.get_chat(context.config.storage_channel_id)
                title = str(
                    getattr(chat, "title", None)
                    or getattr(chat, "username", None)
                    or context.config.storage_channel_id
                )
            except Exception:
                title = str(context.config.storage_channel_id)
        return {
            "channel": context.config.storage_channel,
            "channel_id": context.config.storage_channel_id,
            "title": title,
        }

    @app.get("/api/v1/storage/items/{item_id}", response_model=StorageItemResponse)
    def get_storage_item(item_id: int, actor=Depends(current_actor)):
        del actor
        return storage_item_dict(_storage_item(context, item_id))

    @app.post("/api/v1/storage/uploads", response_model=JobResponse)
    def submit_storage_upload(body: StorageUploadRequest, actor=Depends(current_actor)):
        payload = _model_dict(body)
        provider = payload.get("provider", "telegram")
        if provider == "rclone":
            if payload.get("destination_folder_id") is not None or payload.get("folder"):
                raise DomainError("STORAGE_TARGET_INVALID", "Pilih tepat satu tujuan upload.", status_code=422)
            remote_path = str(payload.get("rclone_path") or "").replace("\\", "/").strip("/")
            parts = remote_path.split("/") if remote_path else []
            if len(remote_path) > 2048 or any(ord(char) < 32 for char in remote_path) or str(payload.get("rclone_path") or "").startswith(("/", "\\")) or any(
                not part or part in {".", ".."} or ":" in part for part in parts
            ):
                raise DomainError("RCLONE_BROWSER_PATH_INVALID", "Path rclone harus berada di bawah root yang dikonfigurasi.", status_code=422)
            payload["rclone_path"] = remote_path
            # Snapshot the configured root. Config contents and local path never
            # enter the browser or the job payload.
            payload["rclone_destination"] = context.utility_settings.get().get(
                "rclone_destination", "googledrive:backup"
            )
        elif payload.get("rclone_path"):
            raise DomainError("STORAGE_TARGET_INVALID", "Path rclone hanya berlaku untuk tujuan rclone.", status_code=422)
        if provider == "telegram" and payload.get("destination_folder_id") is None and payload.get("folder"):
            folder = context.storage_catalog.ensure_path(
                str(payload["folder"]), actor.telegram_user_id
            )
            payload["destination_folder_id"] = folder.id if folder else None
        destination = payload.get("destination_folder_id")
        if provider == "telegram" and destination is not None:
            selected = context.storage_catalog.get_folder(int(destination))
            if selected is None or selected.status != "active":
                raise DomainError("STORAGE_FOLDER_INVALID", "Folder tujuan tidak aktif.", status_code=409)
        if provider == "telegram":
            payload["destination_folder_path"] = context.storage_catalog.folder_path(destination)
        if payload.get("transfer_mode") == "move" and payload.get("move_confirmed") is not True:
            raise DomainError("STORAGE_MOVE_CONFIRMATION_REQUIRED", "Move memerlukan konfirmasi eksplisit.", status_code=422)
        _, selected_worker = context.control_plane.resolve_target(actor, worker=payload.get("worker"))
        payload.update(
            {
                "batch_id": str(uuid.uuid4()),
                "owner_user_id": actor.telegram_user_id,
                "owner_profile": actor.profile,
            }
        )
        return job_dict(
            context.control_plane.submit_job(
                actor, "storage_upload", payload, profile=actor.profile, worker=selected_worker
            )
        )

    @app.post("/api/v1/storage/downloads", response_model=JobResponse)
    def submit_storage_download(body: StorageDownloadRequest, actor=Depends(current_actor)):
        payload = {
            "provider": body.provider,
            "item_ids": list(body.item_ids),
            "folder_ids": list(body.folder_ids),
            "rclone_sources": [_model_dict(item) for item in body.rclone_sources],
            "destination_path": body.destination_path,
            "publish_public_links": body.publish_public_links,
        }
        selected_profile = actor.profile
        if body.provider == "telegram":
            if not body.item_ids and not body.folder_ids:
                raise DomainError("STORAGE_SELECTION_REQUIRED", "Pilih file atau folder Telegram untuk diunduh.", status_code=422)
            if body.rclone_sources:
                raise DomainError("STORAGE_SELECTION_INVALID", "Pilihan rclone hanya berlaku untuk provider rclone.", status_code=422)
            profile, selected_worker = context.control_plane.resolve_target(
                actor, profile=body.profile, worker=body.worker
            )
            selected_profile = profile
        else:
            if not body.rclone_sources:
                raise DomainError("STORAGE_SELECTION_REQUIRED", "Pilih file atau folder rclone untuk diunduh.", status_code=422)
            if body.item_ids or body.folder_ids or body.profile is not None:
                raise DomainError("STORAGE_SELECTION_INVALID", "Profil dan pilihan katalog Telegram tidak berlaku untuk provider rclone.", status_code=422)
            _, selected_worker = context.control_plane.resolve_target(
                actor, worker=body.worker
            )
        try:
            return job_dict(
                context.control_plane.submit_job(
                    actor,
                    "storage_download",
                    payload,
                    profile=selected_profile,
                    worker=selected_worker,
                )
            )
        except ValueError as exc:
            raise DomainError("STORAGE_DOWNLOAD_SELECTION_INVALID", "Pilihan file atau folder tidak valid.", status_code=422) from exc

    @app.get("/api/v1/storage/download-links", response_model=ObjectResponse)
    def list_storage_download_links(worker: str, actor=Depends(current_actor)):
        _, selected_worker = context.control_plane.resolve_target(
            actor, worker=worker, allow_disabled_worker=True
        )
        listing = getattr(context.worker_dispatcher, "public_download_links", None)
        if not callable(listing):
            raise DomainError("WORKER_UPDATE_REQUIRED", "Worker belum mendukung daftar link unduhan.", status_code=503)
        try:
            result = listing(selected_worker)
        except Exception as exc:
            raise DomainError("WORKER_UNAVAILABLE", "Daftar link worker tidak dapat dimuat.", status_code=503) from exc
        items = result.get("items") if isinstance(result, dict) else None
        safe_items = []
        for item in items if isinstance(items, list) else []:
            if not isinstance(item, dict):
                continue
            token = str(item.get("token") or "")
            base_url = str(item.get("public_base_url") or "").rstrip("/")
            if not re.fullmatch(r"[A-Za-z0-9_-]{40,80}", token):
                continue
            normalize_public_url = getattr(context.worker_registry, "_normalize_public_url", None)
            if callable(normalize_public_url):
                try:
                    base_url = normalize_public_url(base_url)
                except ValueError:
                    continue
            elif not base_url.startswith("https://"):
                continue
            safe_items.append({
                "id": str(item.get("id") or ""),
                "worker": selected_worker,
                "relative_path": str(item.get("relative_path") or item.get("file_name") or "File"),
                "file_name": str(item.get("file_name") or "File"),
                "provider": str(item.get("provider") or ""),
                "job_id": str(item.get("job_id") or ""),
                "created_at": str(item.get("created_at") or ""),
                "url": f"{base_url}/public/download/{token}",
            })
        return {"items": safe_items}

    @app.post("/api/v1/storage/download-links/{link_id}/revoke", response_model=ObjectResponse)
    def revoke_storage_download_link(
        link_id: str,
        body: StoragePublicLinkRevokeRequest,
        worker: str = Query(..., min_length=1, max_length=48),
        actor=Depends(current_actor),
    ):
        if body.confirmed is not True:
            raise DomainError("PUBLIC_DOWNLOAD_CONFIRMATION_REQUIRED", "Pencabutan link dan penghapusan file perlu dikonfirmasi.", status_code=422)
        _, selected_worker = context.control_plane.resolve_target(
            actor, worker=worker, allow_disabled_worker=True
        )
        revoke = getattr(context.worker_dispatcher, "revoke_public_download_link", None)
        if not callable(revoke):
            raise DomainError("WORKER_UPDATE_REQUIRED", "Worker belum mendukung pencabutan link unduhan.", status_code=503)
        try:
            result = revoke(selected_worker, link_id)
        except Exception as exc:
            raise DomainError("WORKER_UNAVAILABLE", "Worker tidak dapat mencabut link unduhan.", status_code=503) from exc
        if result.get("revoked") is not True:
            raise DomainError("PUBLIC_DOWNLOAD_NOT_FOUND", "Link unduhan tidak ditemukan.", status_code=404)
        return {"worker": selected_worker, **result}

    @app.post("/api/v1/storage/sync", response_model=JobResponse)
    def submit_storage_sync(body: StorageSyncRequest, actor=Depends(current_actor)):
        channel_id = int(getattr(context.config, "storage_channel_id", 0) or 0)
        if channel_id == 0 or not str(getattr(context.config, "storage_channel_ref", "") or "").strip():
            raise DomainError(
                "STORAGE_SYNC_CHANNEL_UNAVAILABLE",
                "Channel Storage belum dikonfigurasi.",
                status_code=503,
            )
        job = context.control_plane.submit_job(
            actor,
            "storage_sync",
            {"channel_id": channel_id},
            profile=body.profile,
            worker=body.worker,
        )
        return job_dict(job)

    @app.patch(
        "/api/v1/storage/items/{item_id}",
        response_model=StorageItemResponse,
    )
    def update_storage_item(
        item_id: int, body: StorageUpdateRequest, actor=Depends(current_actor)
    ):
        values = _model_dict(body)
        item = _storage_item(context, item_id)
        changes_owned_metadata = values.get("folder") is not None or values.get("keywords") is not None
        if values.get("display_name") is not None:
            item = context.storage_catalog.rename(item_id, values["display_name"])
        if changes_owned_metadata:
            item = context.storage_catalog.update_metadata(
                item_id,
                item.owner_user_id,
                folder=values.get("folder"),
                keywords=values.get("keywords"),
            )
        caption = build_storage_caption(item.folder, item.display_name, item.keywords)
        context.storage_catalog.enqueue_caption(item.id, caption)
        return storage_item_dict(item)

    @app.delete(
        "/api/v1/storage/items/{item_id}",
        response_model=StorageItemResponse,
    )
    def delete_storage_item(item_id: int, actor=Depends(current_actor)):
        _storage_item(context, item_id)
        return storage_item_dict(
            context.storage_catalog.trash_items([item_id], actor.telegram_user_id)[0]
        )

    @app.post("/api/v1/storage/items/{item_id}/restore", response_model=StorageItemResponse)
    def restore_storage_item(item_id: int, actor=Depends(current_actor)):
        del actor
        items = context.storage_catalog.restore_items([item_id])
        if not items:
            raise DomainError("STORAGE_ITEM_NOT_FOUND", "Item Trash tidak ditemukan.", status_code=404)
        return storage_item_dict(items[0])

    @app.delete("/api/v1/storage/items/{item_id}/purge", response_model=ObjectResponse)
    def purge_storage_item(item_id: int, actor=Depends(current_actor)):
        del actor
        if context.storage_maintenance is None:
            raise DomainError("STORAGE_PURGE_UNAVAILABLE", "Layanan purge belum aktif.", status_code=503)
        return context.storage_maintenance.purge([item_id], [])

    @app.post(
        "/api/v1/storage/items/{item_id}/deliveries",
        response_model=ObjectResponse,
    )
    def deliver_storage_item(
        item_id: int, body: StorageDeliveryRequest, actor=Depends(current_actor)
    ):
        if body.method != "telegram":
            raise DomainError(
                "DELIVERY_UNSUPPORTED",
                "Metode delivery belum didukung.",
                status_code=400,
            )
        item = _active_storage_item(context, item_id)
        return _deliver_storage_telegram(context, item, actor.telegram_user_id)

    @app.get(
        "/api/v1/storage/items/{item_id}/deep-link",
        response_model=ObjectResponse,
    )
    def storage_deep_link(item_id: int, actor=Depends(current_actor)):
        del actor
        _active_storage_item(context, item_id)
        token = sign_storage_item(item_id, context.config.auth_jwt_secret)
        return {
            "code": token,
            "url": f"https://t.me/{context.config.bot_username}?start=storage_{token}"
        }

    @app.post(
        "/api/v1/storage/deep-links/{token}/deliver",
        response_model=ObjectResponse,
    )
    def deliver_storage_deep_link(token: str, actor=Depends(current_actor)):
        try:
            item_id = verify_storage_item(token, context.config.auth_jwt_secret)
        except ValueError as exc:
            raise DomainError(
                "STORAGE_LINK_INVALID", str(exc), status_code=400
            ) from exc
        item = _active_storage_item(context, item_id)
        return _deliver_storage_telegram(context, item, actor.telegram_user_id)

    @app.post(
        "/internal/v1/storage/deep-links/{token}/deliver",
        include_in_schema=False,
        response_model=ObjectResponse,
        dependencies=[Depends(require_service)],
    )
    def deliver_public_storage_deep_link(
        token: str, body: TelegramStorageDeliveryRequest
    ):
        """Capability-link delivery; does not grant an application actor."""
        try:
            item_id = verify_storage_item(token, context.config.auth_jwt_secret)
        except ValueError as exc:
            raise DomainError(
                "STORAGE_LINK_INVALID", str(exc), status_code=400
            ) from exc
        item = _active_storage_item(context, item_id)
        return _deliver_storage_telegram(context, item, body.telegram_user_id)
