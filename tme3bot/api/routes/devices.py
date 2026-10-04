from __future__ import annotations

from fastapi import Depends, Request, Response

from tme3bot.api.schemas import (
    BrowserSessionResponse,
    DeviceChallengeRequest,
    DeviceExchangeRequest,
    DeviceRegistrationRequest,
    DeviceRenameRequest,
)
from tme3bot.domain.models import Actor, DomainError


def register_device_routes(
    app,
    context,
    *,
    current_actor,
    set_session,
    browser_actor_dict,
):
    service = getattr(context, "device_auth", None)

    def require_browser_actor(request: Request, actor: Actor) -> Actor:
        if not getattr(request.state, "cookie_auth", False):
            raise DomainError(
                "BROWSER_SESSION_REQUIRED",
                "Sesi Web diperlukan untuk mengelola perangkat tepercaya.",
                status_code=401,
            )
        return actor

    def require_expected_origin(request: Request) -> None:
        if service is None or not service.origin:
            raise DomainError("DEVICE_AUTH_UNAVAILABLE", "Autentikasi perangkat belum dikonfigurasi.", status_code=503)
        if request.headers.get("origin", "").rstrip("/") != service.origin:
            raise DomainError("DEVICE_ORIGIN_INVALID", "Origin autentikasi perangkat tidak cocok.", status_code=403)

    def remote_key(request: Request) -> str:
        # X-Forwarded-For is deliberately ignored unless a trusted-proxy model is added.
        return str(request.client.host if request.client is not None else "unknown")[:128]

    @app.post("/api/v1/auth/devices", status_code=201)
    def register_device(
        body: DeviceRegistrationRequest,
        request: Request,
        actor: Actor = Depends(current_actor),
    ):
        if service is None:
            raise DomainError("DEVICE_AUTH_UNAVAILABLE", "Autentikasi perangkat belum dikonfigurasi.", status_code=503)
        owner = require_browser_actor(request, actor)
        item, created = service.register(
            owner.telegram_user_id,
            device_id=body.device_id,
            name=body.name,
            algorithm=body.algorithm,
            public_key=body.public_key,
            origin=body.origin,
        )
        return {"device": item, "created": created}

    @app.get("/api/v1/auth/devices")
    def list_devices(request: Request, actor: Actor = Depends(current_actor)):
        if service is None:
            raise DomainError("DEVICE_AUTH_UNAVAILABLE", "Autentikasi perangkat belum dikonfigurasi.", status_code=503)
        owner = require_browser_actor(request, actor)
        return {"items": service.list_for_actor(owner.telegram_user_id)}

    @app.patch("/api/v1/auth/devices/{device_id}")
    def rename_device(
        device_id: str,
        body: DeviceRenameRequest,
        request: Request,
        actor: Actor = Depends(current_actor),
    ):
        if service is None:
            raise DomainError("DEVICE_AUTH_UNAVAILABLE", "Autentikasi perangkat belum dikonfigurasi.", status_code=503)
        owner = require_browser_actor(request, actor)
        return {"device": service.rename(owner.telegram_user_id, device_id, body.name)}

    @app.delete("/api/v1/auth/devices/{device_id}")
    def revoke_device(device_id: str, request: Request, actor: Actor = Depends(current_actor)):
        if service is None:
            raise DomainError("DEVICE_AUTH_UNAVAILABLE", "Autentikasi perangkat belum dikonfigurasi.", status_code=503)
        owner = require_browser_actor(request, actor)
        service.revoke(owner.telegram_user_id, device_id)
        return {"revoked": True}

    @app.post("/api/v1/auth/device/challenge")
    def device_challenge(body: DeviceChallengeRequest, request: Request):
        if service is None:
            raise DomainError("DEVICE_AUTH_UNAVAILABLE", "Autentikasi perangkat belum dikonfigurasi.", status_code=503)
        require_expected_origin(request)
        return service.create_challenge(body.device_id, remote_key(request))

    @app.post(
        "/api/v1/auth/device/exchange",
        response_model=BrowserSessionResponse,
    )
    def device_exchange(
        body: DeviceExchangeRequest,
        request: Request,
        response: Response,
    ):
        if service is None:
            raise DomainError("DEVICE_AUTH_UNAVAILABLE", "Autentikasi perangkat belum dikonfigurasi.", status_code=503)
        require_expected_origin(request)
        pair = service.exchange(
            body.device_id, body.challenge_id, body.signature, remote_key(request)
        )
        set_session(response, pair)
        payload = context.auth.decode_access(pair.access_token)
        actor = context.control_plane.actor(int(payload["telegram_user_id"]))
        return {
            "authenticated": True,
            "actor": browser_actor_dict(actor),
            "profiles": context.profile_manager.list_profiles(),
        }

