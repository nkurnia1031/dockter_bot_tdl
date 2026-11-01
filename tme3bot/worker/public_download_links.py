from __future__ import annotations

import secrets
import sqlite3
import threading
import uuid
import os
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit


class PublicDownloadLinks:
    """Worker-local registry for explicit, revocable Workspace download links."""

    def __init__(self, database_path: Path, workspace_root: Path) -> None:
        self.database_path = Path(database_path)
        self.workspace_root = Path(workspace_root).resolve()
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        descriptor = os.open(self.database_path, os.O_CREAT | os.O_RDWR, 0o600)
        os.close(descriptor)
        self._restrict_database_permissions()
        with self._db() as db:
            db.executescript(
                """
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS public_download_links (
                    id TEXT PRIMARY KEY,
                    token TEXT NOT NULL UNIQUE,
                    file_path TEXT NOT NULL,
                    file_name TEXT NOT NULL,
                    public_base_url TEXT NOT NULL,
                    job_id TEXT NOT NULL,
                    provider TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    revoked_at TEXT,
                    cleanup_status TEXT NOT NULL DEFAULT ''
                );
                CREATE INDEX IF NOT EXISTS idx_public_download_active
                    ON public_download_links(revoked_at, created_at);
                """
            )
        self._restrict_database_permissions()

    def _restrict_database_permissions(self) -> None:
        for path in (
            self.database_path,
            Path(f"{self.database_path}-wal"),
            Path(f"{self.database_path}-shm"),
        ):
            try:
                if path.exists():
                    os.chmod(path, 0o600)
            except OSError:
                pass

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.database_path, timeout=30)
        db.row_factory = sqlite3.Row
        return db

    @contextmanager
    def _db(self):
        db = self._connect()
        try:
            with db:
                yield db
        finally:
            db.close()

    @staticmethod
    def normalize_public_base_url(value: str) -> str:
        raw = str(value or "").strip().rstrip("/")
        try:
            parsed = urlsplit(raw)
            port = parsed.port
        except ValueError as exc:
            raise ValueError("Public worker URL harus berupa origin HTTPS.") from exc
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or port == 0
            or any(char.isspace() or ord(char) < 32 for char in raw)
            or parsed.username
            or parsed.password
            or parsed.path not in {"", "/"}
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("Public worker URL harus berupa origin HTTPS.")
        return f"https://{parsed.netloc}"

    def create(
        self,
        file_path: str | Path,
        *,
        public_base_url: str,
        job_id: str,
        provider: str,
    ) -> dict[str, str]:
        path = Path(file_path)
        if path.is_symlink() or not path.is_file():
            raise ValueError("File Workspace tidak tersedia untuk link publik.")
        if self._has_symlink_ancestor(path):
            raise ValueError("Path file link tidak aman.")
        resolved = path.resolve(strict=True)
        try:
            relative = resolved.relative_to(self.workspace_root)
        except ValueError as exc:
            raise ValueError("File link harus berada di dalam Workspace.") from exc
        if any(part in {"", ".", ".."} for part in relative.parts):
            raise ValueError("Path file link tidak valid.")
        base_url = self.normalize_public_base_url(public_base_url)
        normalized_job_id = str(job_id or "").strip()
        normalized_provider = str(provider or "").strip().lower()
        if not normalized_job_id or len(normalized_job_id) > 200:
            raise ValueError("Job unduhan tidak valid untuk link publik.")
        if normalized_provider not in {"telegram", "rclone"}:
            raise ValueError("Sumber unduhan tidak valid untuk link publik.")
        with self._lock, self._db() as db:
            existing = db.execute(
                """SELECT id,token,file_name,public_base_url,created_at
                   FROM public_download_links
                   WHERE job_id=? AND provider=? AND file_path=? AND revoked_at IS NULL
                   ORDER BY created_at DESC LIMIT 1""",
                (normalized_job_id, normalized_provider, relative.as_posix()),
            ).fetchone()
            if existing is not None:
                return {
                    "id": str(existing["id"]),
                    "token": str(existing["token"]),
                    "file_name": str(existing["file_name"]),
                    "public_base_url": str(existing["public_base_url"]),
                    "created_at": str(existing["created_at"]),
                }
            token = secrets.token_urlsafe(32)
            link_id = str(uuid.uuid4())
            created_at = datetime.now(timezone.utc).isoformat()
            db.execute(
                """INSERT INTO public_download_links
                   (id,token,file_path,file_name,public_base_url,job_id,provider,created_at)
                   VALUES (?,?,?,?,?,?,?,?)""",
                (
                    link_id,
                    token,
                    relative.as_posix(),
                    path.name,
                    base_url,
                    normalized_job_id,
                    normalized_provider,
                    created_at,
                ),
            )
        return {
            "id": link_id,
            "token": token,
            "file_name": path.name,
            "public_base_url": base_url,
            "created_at": created_at,
        }

    def active_links(self) -> list[dict[str, str]]:
        with self._lock, self._db() as db:
            rows = db.execute(
                """SELECT id,token,file_path AS relative_path,file_name,public_base_url,job_id,provider,created_at
                   FROM public_download_links WHERE revoked_at IS NULL
                   ORDER BY created_at DESC,id DESC"""
            ).fetchall()
        return [dict(row) for row in rows]

    def public_file(self, token: str) -> dict[str, str] | None:
        if not token or len(token) > 100:
            return None
        with self._lock, self._db() as db:
            row = db.execute(
                """SELECT file_path,file_name FROM public_download_links
                   WHERE token=? AND revoked_at IS NULL""",
                (token,),
            ).fetchone()
        if row is None:
            return None
        candidate = self.workspace_root / str(row["file_path"])
        if candidate.is_symlink() or not candidate.is_file():
            return None
        if self._has_symlink_ancestor(candidate):
            return None
        try:
            resolved = candidate.resolve(strict=True)
            resolved.relative_to(self.workspace_root)
        except (OSError, ValueError):
            return None
        return {"path": str(resolved), "file_name": str(row["file_name"])}

    def revoke(self, link_id: str) -> dict[str, str | bool]:
        with self._lock:
            with self._db() as db:
                row = db.execute(
                    "SELECT file_path,revoked_at,cleanup_status FROM public_download_links WHERE id=?",
                    (str(link_id),),
                ).fetchone()
                if row is None:
                    return {"revoked": False, "cleanup_status": "not_found"}
                relative_path = str(row["file_path"])
                if row["revoked_at"] is None:
                    now = datetime.now(timezone.utc).isoformat()
                    db.execute(
                        """UPDATE public_download_links SET revoked_at=?,cleanup_status='pending'
                           WHERE file_path=? AND revoked_at IS NULL""",
                        (now, relative_path),
                    )
                else:
                    return {
                        "revoked": True,
                        "cleanup_status": str(row["cleanup_status"] or "unknown"),
                    }

            candidate = self.workspace_root / relative_path
            try:
                if candidate.is_symlink() or self._has_symlink_ancestor(candidate):
                    status = "failed_unsafe_path"
                else:
                    resolved = candidate.resolve(strict=False)
                    resolved.relative_to(self.workspace_root)
                    if resolved.exists():
                        if not resolved.is_file():
                            status = "failed_not_file"
                        else:
                            resolved.unlink()
                            status = "deleted"
                    else:
                        status = "already_missing"
            except (OSError, ValueError):
                status = "failed"
            with self._db() as db:
                db.execute(
                    "UPDATE public_download_links SET cleanup_status=? WHERE file_path=?",
                    (status, relative_path),
                )
            return {"revoked": True, "cleanup_status": status}

    def _has_symlink_ancestor(self, path: Path) -> bool:
        absolute = Path(os.path.abspath(path))
        try:
            relative = absolute.relative_to(self.workspace_root)
        except ValueError:
            return True
        current = self.workspace_root
        if current.is_symlink():
            return True
        for part in relative.parts:
            current = current / part
            if current.is_symlink():
                return True
        return False
