from __future__ import annotations

from dataclasses import asdict
from fastapi import Depends, Query
from tme3bot.api.schemas import ItemListResponse, JobResponse, ObjectResponse, StorageBulkActionRequest, StorageDeliveryRequest, StorageFolderRequest, StorageFolderUpdateRequest, StorageItemListResponse, StorageItemResponse, StorageSettingsResponse, StorageUpdateRequest, StorageUploadRequest, TelegramStorageDeliveryRequest
from tme3bot.domain.models import DomainError
from tme3bot.storage_catalog import build_storage_caption, storage_item_dict
from tme3bot.storage_links import sign_storage_item, verify_storage_item
import uuid

def register_storage(app, context, *, _active_storage_item, _deliver_storage_telegram, _model_dict, _require_storage_folders_idle, _storage_item, current_actor, job_dict, require_service, verify_target):

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
        if payload.get("rclone_upload"):
            # Snapshot the destination at enqueue time. The rclone config is
            # never sent through the browser or persisted in the API payload.
            payload["rclone_destination"] = context.utility_settings.get().get(
                "rclone_destination", "googledrive:backup"
            )
        verify_target(actor, "storage", None, payload.get("worker"))
        if payload.get("destination_folder_id") is None and payload.get("folder"):
            folder = context.storage_catalog.ensure_path(
                str(payload["folder"]), actor.telegram_user_id
            )
            payload["destination_folder_id"] = folder.id if folder else None
        destination = payload.get("destination_folder_id")
        if destination is not None:
            selected = context.storage_catalog.get_folder(int(destination))
            if selected is None or selected.status != "active":
                raise DomainError("STORAGE_FOLDER_INVALID", "Folder tujuan tidak aktif.", status_code=409)
        payload["destination_folder_path"] = context.storage_catalog.folder_path(destination)
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
