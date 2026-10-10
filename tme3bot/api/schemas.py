from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class ApiResponse(BaseModel):
    """Base response DTO that remains forward-compatible with added fields."""

    model_config = ConfigDict(extra="allow")


class ErrorBody(ApiResponse):
    code: str
    message: str
    details: dict[str, Any] = Field(default_factory=dict)
    request_id: str


class ErrorResponse(ApiResponse):
    error: ErrorBody


class ChallengeResponse(ApiResponse):
    challenge_id: str
    poll_token: str
    verification_uri: str
    expires_at: datetime
    interval: int


class BrowserChallengeResponse(ApiResponse):
    """Safe browser login response; the poll token stays in an HttpOnly cookie."""

    challenge_id: str
    verification_uri: str
    expires_at: datetime
    interval: int


class BrowserSessionResponse(ApiResponse):
    authenticated: bool
    actor: ActorResponse | None = None
    profiles: list[str] = Field(default_factory=list)


class BrowserProfileRequest(BaseModel):
    profile: str


class DeviceRegistrationRequest(BaseModel):
    device_id: str = Field(min_length=36, max_length=36)
    name: str = Field(min_length=1, max_length=80)
    algorithm: str = Field(min_length=1, max_length=16)
    public_key: str = Field(min_length=40, max_length=64)
    origin: str = Field(min_length=8, max_length=300)


class DeviceRenameRequest(BaseModel):
    name: str = Field(min_length=1, max_length=80)


class DeviceChallengeRequest(BaseModel):
    device_id: str = Field(min_length=36, max_length=36)


class DeviceExchangeRequest(BaseModel):
    device_id: str = Field(min_length=36, max_length=36)
    challenge_id: str = Field(min_length=36, max_length=36)
    signature: str = Field(min_length=80, max_length=100)


class ChallengeExchangeResponse(ApiResponse):
    status: str | None = None
    access_token: str | None = None
    refresh_token: str | None = None
    token_type: str | None = None
    expires_in: int | None = None


class TokenPairResponse(ApiResponse):
    access_token: str
    refresh_token: str
    token_type: str
    expires_in: int


class LogoutResponse(ApiResponse):
    revoked: bool


class ActorResponse(ApiResponse):
    telegram_user_id: int
    profile: str
    authorized: bool
    worker_route: str
    download_mode: str


class JobResponse(ApiResponse):
    id: str
    kind: str
    profile: str
    actor_user_id: int
    worker: str
    status: str
    payload: dict[str, Any] = Field(default_factory=dict)
    progress: dict[str, Any] = Field(default_factory=dict)
    result: dict[str, Any] | None = None
    error: dict[str, Any] | None = None
    archived_at: datetime | None = None
    queue_position: int | None = None
    retryable: bool = False
    retry_of: str | None = None
    retry_phase: str | None = None
    export_start_id: int | None = None
    export_end_id: int | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class JobListResponse(ApiResponse):
    items: list[JobResponse]
    total: int | None = None
    next_offset: int | None = None


class JobEventResponse(ApiResponse):
    job_id: str
    sequence: int
    status: str
    event_type: str
    progress: dict[str, Any] = Field(default_factory=dict)
    result: dict[str, Any] | None = None
    error: dict[str, Any] | None = None
    created_at: datetime


class JobEventListResponse(ApiResponse):
    items: list[JobEventResponse]


class SourceResponse(ApiResponse):
    chat_ref: str
    last_id: int
    label: str | None = None
    updated_at: datetime
    warmup_url: str | None = None
    warmup_done: bool
    warmup_done_at: datetime | None = None


class SourceListResponse(ApiResponse):
    items: list[SourceResponse]


class WorkerResponse(ApiResponse):
    name: str
    url: str
    selected: bool = False
    enabled: bool = True


class WorkerListResponse(ApiResponse):
    items: list[WorkerResponse]


class TtsHelperHealthItem(ApiResponse):
    slot: int = Field(ge=1, le=3)
    status: str
    bootstrap_percent: int | None = Field(default=None, ge=0, le=100)
    checked_at: str | None = None


class WorkerTtsHealthResponse(ApiResponse):
    worker: str
    settings_version: int = 0
    ready: bool
    helpers_ready: bool
    capability_ready: bool = False
    profile_session_ready: bool
    profile_sync_ready: bool = False
    reason_code: str = "unknown"
    helpers: list[TtsHelperHealthItem]


class WorkerTtsRecoveryResponse(ApiResponse):
    worker: str
    slot: int = Field(ge=1, le=3)
    accepted: bool
    status: str


class StorageItemResponse(ApiResponse):
    id: int
    upload_id: str
    owner_user_id: int
    owner_profile: str
    channel_id: int
    channel_message_id: int
    original_name: str
    display_name: str
    folder: str
    keywords: str
    caption: str
    file_size: int | None = None
    mime_type: str
    sha256: str
    uploaded_at: datetime
    updated_at: datetime
    status: str
    folder_id: int | None = None
    trashed_at: datetime | None = None
    trashed_by: int | None = None
    caption_sync_status: str = "synced"
    purge_error: str | None = None
    folder_path: str = ""
    purge_at: datetime | None = None


class StorageItemListResponse(ApiResponse):
    items: list[StorageItemResponse]
    total: int | None = None


class StorageSettingsResponse(ApiResponse):
    channel: str
    channel_id: int
    title: str


class ItemListResponse(ApiResponse):
    items: list[Any]


class ObjectResponse(ApiResponse):
    """Typed object envelope for small mutation/settings responses."""

    model_config = ConfigDict(extra="allow")


class ChallengeTokenRequest(BaseModel):
    poll_token: str


class RefreshRequest(BaseModel):
    refresh_token: str


class ApproveChallengeRequest(BaseModel):
    telegram_user_id: int


class ServiceExchangeRequest(BaseModel):
    telegram_user_id: int


class SubmitJobRequest(BaseModel):
    profile: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)


class OperationSubmitRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: str = Field(min_length=1, max_length=64)
    target: dict[str, Any]
    input: dict[str, Any]


class OperationVisibilityRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    dismissed: bool


class OperationResponse(ApiResponse):
    operation_id: str
    kind: str
    profile: str
    target: dict[str, Any]
    status: str
    phase: str
    revision: int
    attempt: int
    progress: dict[str, Any]
    job_id: str | None = None
    error: dict[str, str] | None = None
    created_at: datetime
    updated_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None
    dismissed: bool = False
    status_url: str | None = None


class OperationListResponse(ApiResponse):
    items: list[OperationResponse]
    next_cursor: str | None = None


class ExportRequest(BaseModel):
    url: str | None = None
    chat_ref: str | None = None
    start_id: int | None = Field(default=None, ge=1)
    label: str | None = None
    use_url_message_id: bool = False
    save_source: bool | None = None
    profile: str | None = None
    worker: str | None = None
    quick_mode: bool = False


class DownloadRequest(BaseModel):
    artifact_ids: list[str] = Field(default_factory=list)
    priority: str = "normal"


class DownloadBatchRequest(DownloadRequest):
    pass


class ContextVerifyRequest(BaseModel):
    purpose: str
    profile: str | None = None
    worker: str | None = None
    quick_mode: bool = False


class BatchSourcesRequest(BaseModel):
    chat_refs: list[str]


class SourceUpdateRequest(BaseModel):
    label: str | None = None


class UtilityJobRequest(BaseModel):
    utility: str
    folders: list[str]
    password: str | None = None
    worker: str | None = None


class UtilityFolderRequest(BaseModel):
    path: str


class SettingRequest(BaseModel):
    value: str


class BackupRuntimeSettingsRequest(BaseModel):
    enabled: bool
    schedule: str = Field(min_length=5, max_length=5)
    timezone: str = Field(min_length=1, max_length=80)
    retention: int = Field(ge=1, le=3650)
    volume_size: str = Field(min_length=2, max_length=32)
    channel: str = Field(default="", max_length=200)
    storage_trash_retention_days: int = Field(ge=1, le=3650)
    job_stall_timeout_seconds: int = Field(ge=0, le=86400)
    job_cancel_grace_seconds: int = Field(ge=0, le=3600)


class RuntimeSecretsRequest(BaseModel):
    bot_token: str | None = Field(default=None, min_length=20, max_length=256)
    telegram_tts_chat_id: str | None = Field(default=None, max_length=128)


class RuntimeSettingsPutRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_version: int = Field(ge=0)
    values: dict[str, Any] = Field(default_factory=dict)
    clear: list[str] = Field(default_factory=list, max_length=32)


class RuntimeSettingsAckRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    worker: str = Field(min_length=1, max_length=48)
    scope: str = Field(min_length=1, max_length=24)
    applied_version: int = Field(ge=0)
    success: bool = True
    error_code: str = Field(default="", max_length=80)


class LabelRequest(BaseModel):
    label: str


class WorkerRequest(BaseModel):
    name: str
    url: str
    token: str
    enabled: bool = True


class WorkerUpdateRequest(BaseModel):
    url: str
    token: str | None = None
    enabled: bool | None = None


class WorkerEnabledRequest(BaseModel):
    enabled: bool


class WorkerRuntimeSettingsRequest(BaseModel):
    worker_api_token: str | None = Field(default=None, min_length=16, max_length=512)
    job_stall_timeout_seconds: int | None = Field(default=None, ge=0, le=86400)
    tdl_export_stall_timeout_seconds: int | None = Field(default=None, ge=0, le=86400)
    tdl_download_stall_timeout_seconds: int | None = Field(default=None, ge=0, le=86400)
    storage_profile: str | None = Field(default=None, min_length=1, max_length=48)
    tts_helper_urls: list[str] | None = Field(default=None, min_length=3, max_length=3)
    tts_tor_control_hosts: list[str] | None = Field(default=None, min_length=3, max_length=3)
    tts_tor_control_ports: list[int] | None = Field(default=None, min_length=3, max_length=3)
    tts_part_retries: int | None = Field(default=None, ge=0, le=10)
    tts_retry_base_seconds: float | None = Field(default=None, ge=0.1, le=60)
    tts_newnym_after_retries: int | None = Field(default=None, ge=1, le=20)


class WorkerRouteRequest(BaseModel):
    route: str


class StorageUploadRequest(BaseModel):
    folder_path: str
    folder: str = ""
    destination_folder_id: int | None = None
    preserve_structure: bool = True
    keywords: str = ""
    worker: str | None = None
    rclone_upload: bool = False


class StorageUpdateRequest(BaseModel):
    display_name: str | None = None
    folder: str | None = None
    keywords: str | None = None


class StorageFolderRequest(BaseModel):
    name: str
    parent_id: int | None = None


class StorageFolderUpdateRequest(BaseModel):
    name: str | None = None
    parent_id: int | None = None


class StorageBulkActionRequest(BaseModel):
    item_ids: list[int] = Field(default_factory=list)
    folder_ids: list[int] = Field(default_factory=list)
    destination_folder_id: int | None = None


class StorageDeliveryRequest(BaseModel):
    method: str = "telegram"


class TelegramStorageDeliveryRequest(BaseModel):
    telegram_user_id: int


class WorkerJobRequest(BaseModel):
    job_id: str
    kind: str
    profile: str
    actor_user_id: int
    worker: str | None = None
    # Backend dispatches start numbering because a retry reuses the same job
    # ID and therefore retains its previous event history.  This field must
    # reach the worker; dropping it makes every worker event look stale.
    event_sequence_start: int | None = None
    # Retry attempt binds internal shared-cursor operations to the current
    # backend execution and rejects requests from an older attempt.
    attempt: int | None = None
    execution: dict[str, Any] = Field(default_factory=dict)
    payload: dict[str, Any] = Field(default_factory=dict)


class TtsJobRequest(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    text: str = Field(min_length=1, max_length=100_000)
    worker: str | None = Field(default=None, min_length=1, max_length=48)


class TdlAccessVerificationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    purpose: Literal["tts", "storage"]
    worker: str = Field(min_length=1, max_length=48)


class SafelinkJobRequest(BaseModel):
    # Validate length in the domain layer so FastAPI's validation response
    # never echoes a caller-supplied shortlink in its error details.
    url: str


class WorkerEventRequest(BaseModel):
    sequence: int
    status: str
    event_type: str
    worker: str | None = None
    sent_at: datetime | None = None
    transient: bool = False
    progress: dict[str, Any] = Field(default_factory=dict)
    result: dict[str, Any] | None = None
    error: dict[str, Any] | None = None
