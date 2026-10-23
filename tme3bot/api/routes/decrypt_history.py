from __future__ import annotations

from fastapi import Depends, Query

from tme3bot.api.schemas import DecryptHistoryCreateRequest
from tme3bot.domain.models import DomainError


def register_decrypt_history(app, context, *, current_actor) -> None:
    @app.get("/api/v1/decrypt/history")
    def list_decrypt_history(
        limit: int = Query(50, ge=1, le=100),
        offset: int = Query(0, ge=0),
        actor=Depends(current_actor),
    ):
        store = context.decrypt_history_store
        if store is None:
            raise DomainError(
                "DECRYPT_HISTORY_UNAVAILABLE",
                "Penyimpanan riwayat dekripsi belum tersedia.",
                status_code=503,
            )
        items = store.list_for_actor(actor.telegram_user_id, limit=limit, offset=offset)
        total = store.count_for_actor(actor.telegram_user_id)
        next_offset = offset + len(items) if offset + len(items) < total else None
        return {"items": items, "total": total, "next_offset": next_offset}

    @app.post("/api/v1/decrypt/history", status_code=201)
    def save_decrypt_history(
        body: DecryptHistoryCreateRequest,
        actor=Depends(current_actor),
    ):
        store = context.decrypt_history_store
        if store is None:
            raise DomainError(
                "DECRYPT_HISTORY_UNAVAILABLE",
                "Penyimpanan riwayat dekripsi belum tersedia.",
                status_code=503,
            )
        result = body.result
        if not result or len(result) > 65536:
            raise DomainError(
                "DECRYPT_HISTORY_INVALID",
                "Hasil dekripsi kosong atau terlalu panjang untuk disimpan.",
                status_code=422,
            )
        try:
            item = store.add(actor.telegram_user_id, result)
        except ValueError as exc:
            raise DomainError(
                "DECRYPT_HISTORY_INVALID",
                "Hasil dekripsi tidak dapat disimpan.",
                status_code=422,
            ) from exc
        return {"item": item}
