from __future__ import annotations

import threading
import time
from typing import Any
from urllib.parse import quote, urlencode

from tme3bot.infrastructure.http_client import request_json


class BackendApiClient:
    def __init__(self, base_url: str, frontend_service_token: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.frontend_service_token = frontend_service_token
        self._tokens: dict[int, tuple[str, float]] = {}
        self._lock = threading.RLock()

    def approve_login(self, code: str, telegram_user_id: int) -> dict[str, Any]:
        return request_json(
            self.base_url,
            self.frontend_service_token,
            "POST",
            f"/internal/v1/auth/telegram/challenges/{quote(code, safe='')}/approve",
            {"telegram_user_id": int(telegram_user_id)},
        )

    def deliver_storage_link(
        self, token: str, telegram_user_id: int
    ) -> dict[str, Any]:
        """Redeem a signed capability link without creating an actor JWT."""
        return request_json(
            self.base_url,
            self.frontend_service_token,
            "POST",
            f"/internal/v1/storage/deep-links/{quote(token, safe='.')}/deliver",
            {"telegram_user_id": int(telegram_user_id)},
        )

    def register_job_notification(
        self, job_id: str, telegram_user_id: int, telegram_chat_id: int
    ) -> dict[str, Any]:
        return request_json(
            self.base_url,
            self.frontend_service_token,
            "POST",
            f"/internal/v1/jobs/{quote(job_id, safe='')}/telegram-notifications",
            {
                "telegram_user_id": int(telegram_user_id),
                "telegram_chat_id": int(telegram_chat_id),
            },
        )

    def pending_job_notifications(self, limit: int = 100) -> dict[str, Any]:
        return request_json(
            self.base_url,
            self.frontend_service_token,
            "GET",
            f"/internal/v1/telegram-notifications/pending?limit={int(limit)}",
        )

    def update_job_notification(
        self, notification_id: int, values: dict[str, Any]
    ) -> dict[str, Any]:
        return request_json(
            self.base_url,
            self.frontend_service_token,
            "PATCH",
            f"/internal/v1/telegram-notifications/{int(notification_id)}",
            values,
        )

    def me(self, telegram_user_id: int) -> dict[str, Any]:
        return self.get(telegram_user_id, "/api/v1/me")

    def get(
        self,
        telegram_user_id: int,
        path: str,
        query: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if query:
            path += ("&" if "?" in path else "?") + urlencode(
                {key: value for key, value in query.items() if value is not None}
            )
        return request_json(
            self.base_url, self._actor_token(telegram_user_id), "GET", path
        )

    def post(
        self,
        telegram_user_id: int,
        path: str,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return request_json(
            self.base_url,
            self._actor_token(telegram_user_id),
            "POST",
            path,
            payload or {},
        )

    def put(
        self, telegram_user_id: int, path: str, payload: dict[str, Any]
    ) -> dict[str, Any]:
        return request_json(
            self.base_url,
            self._actor_token(telegram_user_id),
            "PUT",
            path,
            payload,
        )

    def patch(
        self, telegram_user_id: int, path: str, payload: dict[str, Any]
    ) -> dict[str, Any]:
        return request_json(
            self.base_url,
            self._actor_token(telegram_user_id),
            "PATCH",
            path,
            payload,
        )

    def delete(
        self,
        telegram_user_id: int,
        path: str,
        query: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if query:
            path += ("&" if "?" in path else "?") + urlencode(query)
        return request_json(
            self.base_url,
            self._actor_token(telegram_user_id),
            "DELETE",
            path,
            {},
        )

    def _actor_token(self, telegram_user_id: int) -> str:
        now = time.monotonic()
        with self._lock:
            cached = self._tokens.get(int(telegram_user_id))
            if cached is not None and cached[1] > now + 10:
                return cached[0]
        response = request_json(
            self.base_url,
            self.frontend_service_token,
            "POST",
            "/internal/v1/auth/telegram/exchange",
            {"telegram_user_id": int(telegram_user_id)},
        )
        token = str(response["access_token"])
        expires_in = max(30, int(response.get("expires_in", 900)))
        with self._lock:
            self._tokens[int(telegram_user_id)] = (token, now + expires_in)
        return token
