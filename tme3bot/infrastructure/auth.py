from __future__ import annotations

import hashlib
import secrets
import sqlite3
import threading
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

import jwt

from tme3bot.domain.models import AuthChallengeStatus, DomainError


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _hash_secret(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class TokenPair:
    access_token: str
    refresh_token: str
    token_type: str
    expires_in: int


class SqliteAuthRepository:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(str(self.path), timeout=30)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA journal_mode=WAL")
        return db

    @contextmanager
    def _db(self):
        with self._lock:
            db = self._connect()
            try:
                yield db
                db.commit()
            finally:
                db.close()

    def _initialize(self) -> None:
        with self._db() as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS auth_challenges (
                    id TEXT PRIMARY KEY,
                    code TEXT NOT NULL UNIQUE,
                    poll_token_hash TEXT NOT NULL,
                    status TEXT NOT NULL,
                    telegram_user_id INTEGER,
                    created_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    approved_at TEXT,
                    consumed_at TEXT
                );
                CREATE INDEX IF NOT EXISTS auth_challenges_code
                    ON auth_challenges(code);
                CREATE TABLE IF NOT EXISTS auth_sessions (
                    id TEXT PRIMARY KEY,
                    telegram_user_id INTEGER NOT NULL,
                    refresh_token_hash TEXT NOT NULL UNIQUE,
                    created_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    last_used_at TEXT NOT NULL,
                    revoked_at TEXT
                );
                CREATE INDEX IF NOT EXISTS auth_sessions_user
                    ON auth_sessions(telegram_user_id, created_at DESC);
                """
            )

    def create_challenge(
        self, challenge_id: str, code: str, poll_token_hash: str, expires_at: datetime
    ) -> None:
        now = _now().isoformat()
        with self._db() as db:
            db.execute(
                """
                INSERT INTO auth_challenges(
                    id, code, poll_token_hash, status, created_at, expires_at
                ) VALUES(?, ?, ?, ?, ?, ?)
                """,
                (
                    challenge_id,
                    code,
                    poll_token_hash,
                    AuthChallengeStatus.PENDING.value,
                    now,
                    expires_at.isoformat(),
                ),
            )

    def challenge_by_id(self, challenge_id: str) -> dict[str, Any] | None:
        return self._challenge("id", challenge_id)

    def challenge_by_code(self, code: str) -> dict[str, Any] | None:
        return self._challenge("code", code)

    def _challenge(self, column: str, value: str) -> dict[str, Any] | None:
        if column not in {"id", "code"}:
            raise ValueError("Invalid challenge lookup.")
        with self._db() as db:
            row = db.execute(
                f"SELECT * FROM auth_challenges WHERE {column} = ?", (value,)
            ).fetchone()
        if row is None:
            return None
        return dict(row)

    def mark_challenge_expired(self, challenge_id: str) -> None:
        with self._db() as db:
            db.execute(
                """
                UPDATE auth_challenges SET status = ?
                WHERE id = ? AND status = ?
                """,
                (
                    AuthChallengeStatus.EXPIRED.value,
                    challenge_id,
                    AuthChallengeStatus.PENDING.value,
                ),
            )

    def approve_challenge(self, code: str, telegram_user_id: int) -> bool:
        with self._db() as db:
            cursor = db.execute(
                """
                UPDATE auth_challenges
                SET status = ?, telegram_user_id = ?, approved_at = ?
                WHERE code = ? AND status = ? AND expires_at > ?
                """,
                (
                    AuthChallengeStatus.APPROVED.value,
                    int(telegram_user_id),
                    _now().isoformat(),
                    code,
                    AuthChallengeStatus.PENDING.value,
                    _now().isoformat(),
                ),
            )
            return cursor.rowcount > 0

    def consume_challenge(self, challenge_id: str) -> bool:
        with self._db() as db:
            cursor = db.execute(
                """
                UPDATE auth_challenges
                SET status = ?, consumed_at = ?
                WHERE id = ? AND status = ?
                """,
                (
                    AuthChallengeStatus.CONSUMED.value,
                    _now().isoformat(),
                    challenge_id,
                    AuthChallengeStatus.APPROVED.value,
                ),
            )
            return cursor.rowcount > 0

    def create_single_session(
        self,
        telegram_user_id: int,
        refresh_token_hash: str,
        expires_at: datetime,
    ) -> str:
        session_id = str(uuid.uuid4())
        now = _now().isoformat()
        with self._db() as db:
            db.execute(
                """
                UPDATE auth_sessions SET revoked_at = ?
                WHERE telegram_user_id = ? AND revoked_at IS NULL
                """,
                (now, int(telegram_user_id)),
            )
            db.execute(
                """
                INSERT INTO auth_sessions(
                    id, telegram_user_id, refresh_token_hash, created_at,
                    expires_at, last_used_at
                ) VALUES(?, ?, ?, ?, ?, ?)
                """,
                (
                    session_id,
                    int(telegram_user_id),
                    refresh_token_hash,
                    now,
                    expires_at.isoformat(),
                    now,
                ),
            )
        return session_id

    def active_session_by_refresh_hash(
        self, refresh_token_hash: str
    ) -> dict[str, Any] | None:
        with self._db() as db:
            row = db.execute(
                """
                SELECT * FROM auth_sessions
                WHERE refresh_token_hash = ? AND revoked_at IS NULL AND expires_at > ?
                """,
                (refresh_token_hash, _now().isoformat()),
            ).fetchone()
        return dict(row) if row is not None else None

    def active_session_by_id(self, session_id: str) -> dict[str, Any] | None:
        with self._db() as db:
            row = db.execute(
                """
                SELECT * FROM auth_sessions
                WHERE id = ? AND revoked_at IS NULL AND expires_at > ?
                """,
                (session_id, _now().isoformat()),
            ).fetchone()
        return dict(row) if row is not None else None

    def rotate_refresh(
        self, session_id: str, old_hash: str, new_hash: str
    ) -> bool:
        with self._db() as db:
            cursor = db.execute(
                """
                UPDATE auth_sessions
                SET refresh_token_hash = ?, last_used_at = ?
                WHERE id = ? AND refresh_token_hash = ? AND revoked_at IS NULL
                """,
                (new_hash, _now().isoformat(), session_id, old_hash),
            )
            return cursor.rowcount > 0

    def revoke_refresh_hash(self, refresh_token_hash: str) -> bool:
        with self._db() as db:
            cursor = db.execute(
                """
                UPDATE auth_sessions SET revoked_at = ?
                WHERE refresh_token_hash = ? AND revoked_at IS NULL
                """,
                (_now().isoformat(), refresh_token_hash),
            )
            return cursor.rowcount > 0


class BotAuthService:
    def __init__(
        self,
        repository: SqliteAuthRepository,
        actor_resolver: Callable[[int], Any],
        jwt_secret: str,
        bot_username: str,
        *,
        access_minutes: int = 15,
        refresh_days: int = 30,
        challenge_minutes: int = 5,
    ) -> None:
        if not jwt_secret:
            raise ValueError("AUTH_JWT_SECRET wajib diisi.")
        self.repository = repository
        self.actor_resolver = actor_resolver
        self.jwt_secret = jwt_secret
        self.bot_username = bot_username.lstrip("@")
        self.access_seconds = max(60, int(access_minutes) * 60)
        self.refresh_days = max(1, int(refresh_days))
        self.challenge_minutes = max(1, int(challenge_minutes))

    def create_challenge(self) -> dict[str, Any]:
        challenge_id = str(uuid.uuid4())
        code = secrets.token_urlsafe(18)
        poll_token = secrets.token_urlsafe(32)
        expires_at = _now() + timedelta(minutes=self.challenge_minutes)
        self.repository.create_challenge(
            challenge_id, code, _hash_secret(poll_token), expires_at
        )
        return {
            "challenge_id": challenge_id,
            "poll_token": poll_token,
            "verification_uri": f"https://t.me/{self.bot_username}?start=login_{code}",
            "expires_at": expires_at.isoformat(),
            "interval": 2,
        }

    def approve(self, code: str, telegram_user_id: int) -> dict[str, Any]:
        actor = self.actor_resolver(int(telegram_user_id))
        if not getattr(actor, "authorized", True):
            raise DomainError(
                "UNAUTHORIZED_ACTOR",
                "Telegram user belum memiliki identity TDL.",
                status_code=403,
            )
        if not self.repository.approve_challenge(code, int(telegram_user_id)):
            raise DomainError(
                "CHALLENGE_INVALID",
                "Challenge tidak ditemukan, kedaluwarsa, atau sudah digunakan.",
                status_code=404,
            )
        return {"approved": True, "telegram_user_id": int(telegram_user_id)}

    def exchange_challenge(
        self, challenge_id: str, poll_token: str
    ) -> TokenPair | None:
        challenge = self.repository.challenge_by_id(challenge_id)
        if challenge is None or not secrets.compare_digest(
            str(challenge["poll_token_hash"]), _hash_secret(poll_token)
        ):
            raise DomainError(
                "CHALLENGE_INVALID", "Challenge atau poll token tidak valid.", status_code=404
            )
        if datetime.fromisoformat(str(challenge["expires_at"])) <= _now():
            self.repository.mark_challenge_expired(challenge_id)
            raise DomainError(
                "CHALLENGE_EXPIRED", "Challenge login telah kedaluwarsa.", status_code=410
            )
        status = AuthChallengeStatus(str(challenge["status"]))
        if status == AuthChallengeStatus.PENDING:
            return None
        if status != AuthChallengeStatus.APPROVED:
            raise DomainError(
                "CHALLENGE_CONSUMED",
                "Challenge login sudah digunakan.",
                status_code=409,
            )
        if not self.repository.consume_challenge(challenge_id):
            raise DomainError(
                "CHALLENGE_CONSUMED",
                "Challenge login sudah digunakan.",
                status_code=409,
            )
        return self._new_web_session(int(challenge["telegram_user_id"]))

    def service_exchange(self, telegram_user_id: int) -> dict[str, Any]:
        actor = self.actor_resolver(int(telegram_user_id))
        return {
            "access_token": self._access_token(
                int(telegram_user_id), getattr(actor, "profile", ""), session_id="bot"
            ),
            "token_type": "bearer",
            "expires_in": self.access_seconds,
        }

    def refresh(self, refresh_token: str) -> TokenPair:
        old_hash = _hash_secret(refresh_token)
        session = self.repository.active_session_by_refresh_hash(old_hash)
        if session is None:
            raise DomainError(
                "REFRESH_INVALID",
                "Refresh token tidak valid atau sudah dicabut.",
                status_code=401,
            )
        user_id = int(session["telegram_user_id"])
        actor = self.actor_resolver(user_id)
        new_refresh = secrets.token_urlsafe(48)
        if not self.repository.rotate_refresh(
            str(session["id"]), old_hash, _hash_secret(new_refresh)
        ):
            raise DomainError(
                "REFRESH_REUSED",
                "Refresh token sudah digunakan.",
                status_code=401,
            )
        return TokenPair(
            access_token=self._access_token(
                user_id, getattr(actor, "profile", ""), str(session["id"])
            ),
            refresh_token=new_refresh,
            token_type="bearer",
            expires_in=self.access_seconds,
        )

    def logout(self, refresh_token: str) -> bool:
        return self.repository.revoke_refresh_hash(_hash_secret(refresh_token))

    def decode_access(self, token: str) -> dict[str, Any]:
        try:
            payload = jwt.decode(token, self.jwt_secret, algorithms=["HS256"])
        except jwt.PyJWTError as exc:
            raise DomainError(
                "TOKEN_INVALID", "Access token tidak valid.", status_code=401
            ) from exc
        if payload.get("typ") != "access":
            raise DomainError(
                "TOKEN_INVALID", "Jenis token tidak valid.", status_code=401
            )
        session_id = str(payload.get("sid", ""))
        if session_id != "bot" and self.repository.active_session_by_id(session_id) is None:
            raise DomainError(
                "SESSION_REVOKED",
                "Sesi web sudah dicabut atau kedaluwarsa.",
                status_code=401,
            )
        return payload

    def _new_web_session(self, telegram_user_id: int) -> TokenPair:
        actor = self.actor_resolver(telegram_user_id)
        refresh = secrets.token_urlsafe(48)
        session_id = self.repository.create_single_session(
            telegram_user_id,
            _hash_secret(refresh),
            _now() + timedelta(days=self.refresh_days),
        )
        return TokenPair(
            access_token=self._access_token(
                telegram_user_id, getattr(actor, "profile", ""), session_id
            ),
            refresh_token=refresh,
            token_type="bearer",
            expires_in=self.access_seconds,
        )

    def _access_token(
        self, telegram_user_id: int, profile: str, session_id: str
    ) -> str:
        now = _now()
        return jwt.encode(
            {
                "sub": str(int(telegram_user_id)),
                "telegram_user_id": int(telegram_user_id),
                "profile": profile,
                "sid": session_id,
                "typ": "access",
                "jti": str(uuid.uuid4()),
                "iat": int(now.timestamp()),
                "exp": int((now + timedelta(seconds=self.access_seconds)).timestamp()),
            },
            self.jwt_secret,
            algorithm="HS256",
        )
