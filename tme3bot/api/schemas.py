from __future__ import annotations

from datetime import datetime
from typing import Any

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
    # Backend dispatches start numbering because a retry reuses the same job
    # ID and therefore retains its previous event history.  This field must
    # reach the worker; dropping it makes every worker event look stale.
    event_sequence_start: int | None = None
    execution: dict[str, Any] = Field(default_factory=dict)
    payload: dict[str, Any] = Field(default_factory=dict)


class WorkerEventRequest(BaseModel):
    sequence: int
    status: str
    event_type: str
    transient: bool = False
    progress: dict[str, Any] = Field(default_factory=dict)
    result: dict[str, Any] | None = None
    error: dict[str, Any] | None = None
