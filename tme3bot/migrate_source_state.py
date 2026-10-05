"""Offline inventory, planning, and migration for legacy source cursors.

The command only reads explicitly-listed JSON/SQLite snapshots. It never opens
TDL session folders and does not contact a worker or a Telegram service.

Input format (all paths are relative to --input-dir):
    {"version": 1, "snapshots": [
      {"origin": "backend", "profile": "default",
       "state_file": "backend/state.json", "max_file": "backend/max.json",
       "database": "backend/storage.db"},
      {"origin": "worker", "worker": "remote-1", "profile": "default",
       "state_file": "workers/remote-1/state.json"}
    ]}

Every path is allowlisted by this manifest, must remain inside input-dir, and
must not name a .tdl session. The operator must create an offline copy first.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
import sys
import uuid
from pathlib import Path
from typing import Any

from tme3bot.chat_refs import canonical_chat_key
from tme3bot.infrastructure.source_store import (
    MigrationPlanConflict,
    SourceRevisionConflict,
    SqliteSourceRepository,
)
from tme3bot.names import normalize_profile_name
from tme3bot.persistence import utc_now_iso


class MigrationError(RuntimeError):
    pass


def _canonical_json(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_json(path: Path, payload: Any, *, exclusive: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if exclusive:
        with path.open("x", encoding="utf-8", newline="\n") as stream:
            stream.write(data)
        return
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(data, encoding="utf-8", newline="\n")
    os.replace(temporary, path)


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise MigrationError(f"JSON snapshot tidak dapat dibaca: {path.name}") from exc


def _profile(value: Any) -> str:
    normalized = normalize_profile_name(str(value or ""))
    if not normalized:
        raise MigrationError("Nama profile snapshot tidak valid.")
    return normalized


def _safe_snapshot_path(root: Path, value: Any) -> Path:
    raw = str(value or "").strip()
    if not raw:
        raise MigrationError("Path snapshot kosong.")
    relative = Path(raw)
    if relative.is_absolute() or any(part.casefold() == ".tdl" for part in relative.parts):
        raise MigrationError("Snapshot harus relatif dan tidak boleh menunjuk sesi .tdl.")
    resolved_root = root.resolve()
    try:
        resolved = (root / relative).resolve(strict=True)
    except OSError as exc:
        raise MigrationError("File snapshot tidak ditemukan atau tidak dapat dibaca.") from exc
    try:
        resolved.relative_to(resolved_root)
    except ValueError as exc:
        raise MigrationError("Path snapshot keluar dari input-dir.") from exc
    if not resolved.is_file():
        raise MigrationError("Path snapshot harus berupa file.")
    return resolved


def _source_record(
    *, origin: str, profile: str, chat_ref: str, last_id: Any,
    payload: dict[str, Any], source_type: str, input_path: str,
    input_sha256: str, worker: str | None = None, revision: int | None = None,
    gate_enabled: bool = False,
) -> dict[str, Any] | None:
    try:
        cursor = int(last_id)
    except (TypeError, ValueError, OverflowError):
        return None
    if isinstance(last_id, bool) or cursor < 0:
        return None
    key = canonical_chat_key(chat_ref)
    if not key:
        return None
    return {
        "origin": origin,
        "worker": worker,
        "profile": profile,
        "chat_ref": key,
        "last_id": cursor,
        "label": payload.get("label"),
        "updated_at": str(payload.get("updated_at") or ""),
        "warmup_url": payload.get("warmup_url"),
        "warmup_done": bool(payload.get("warmup_done", True)),
        "warmup_done_at": payload.get("warmup_done_at"),
        "source_type": source_type,
        "input_path": input_path,
        "input_sha256": input_sha256,
        "revision": int(revision or 0),
        "gate_enabled": bool(gate_enabled),
    }


def _readonly_database(path: Path) -> sqlite3.Connection:
    db = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True, timeout=30)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA query_only=ON")
    return db


def _tables(db: sqlite3.Connection) -> set[str]:
    return {str(row[0]) for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}


def _columns(db: sqlite3.Connection, table: str) -> set[str]:
    return {str(row[1]) for row in db.execute(f"PRAGMA table_info({table})")}


def _int_from(*values: Any) -> int | None:
    for value in values:
        try:
            result = int(value)
        except (TypeError, ValueError, OverflowError):
            continue
        if not isinstance(value, bool) and result >= 0:
            return result
    return None


def _database_snapshot(
    path: Path, *, origin: str, worker: str | None, profile_filter: str | None,
    input_relative: str, input_sha256: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], bool]:
    records: list[dict[str, Any]] = []
    jobs: dict[str, dict[str, Any]] = {}
    artifacts: list[dict[str, Any]] = []
    gate_enabled = False
    db = _readonly_database(path)
    try:
        tables = _tables(db)
        if "source_repository_metadata" in tables:
            row = db.execute(
                "SELECT value FROM source_repository_metadata WHERE key=?",
                (SqliteSourceRepository.FEATURE_KEY,),
            ).fetchone()
            gate_enabled = bool(row and row["value"] == "enabled")
        if "source_records" in tables:
            columns = _columns(db, "source_records")
            if {"profile", "canonical_chat_key", "last_id"}.issubset(columns):
                for row in db.execute("SELECT * FROM source_records ORDER BY profile, canonical_chat_key"):
                    profile = _profile(row["profile"])
                    if profile_filter and profile != profile_filter:
                        continue
                    payload = {key: row[key] for key in (
                        "label", "updated_at", "warmup_url", "warmup_done", "warmup_done_at"
                    ) if key in columns}
                    item = _source_record(
                        origin=origin, worker=worker, profile=profile,
                        chat_ref=str(row["canonical_chat_key"]), last_id=row["last_id"],
                        payload=payload, source_type="sql", input_path=input_relative,
                        input_sha256=input_sha256, revision=(row["revision"] if "revision" in columns else 0),
                        gate_enabled=gate_enabled,
                    )
                    if item:
                        records.append(item)
        if "jobs" in tables:
            columns = _columns(db, "jobs")
            needed = {"id", "kind", "profile", "status"}
            if needed.issubset(columns):
                selected = [name for name in (
                    "id", "kind", "profile", "status", "payload", "progress", "result"
                ) if name in columns]
                query = "SELECT " + ",".join(selected) + " FROM jobs WHERE kind='export'"
                for row in db.execute(query):
                    payload = _safe_json_object(row["payload"] if "payload" in selected else None)
                    progress = _safe_json_object(row["progress"] if "progress" in selected else None)
                    result = _safe_json_object(row["result"] if "result" in selected else None)
                    chat_ref = payload.get("chat_ref") or progress.get("chat_ref") or result.get("chat_ref")
                    start_id = _int_from(
                        result.get("export_start_id"), result.get("start_id"),
                        progress.get("export_start_id"), payload.get("export_start_id"),
                    )
                    end_id = _int_from(
                        result.get("export_end_id"), result.get("end_id"),
                        result.get("max_message_id"), progress.get("export_end_id"),
                    )
                    jobs[str(row["id"])] = {
                        "id": str(row["id"]), "profile": _profile(row["profile"]),
                        "status": str(row["status"]),
                        "chat_ref": canonical_chat_key(str(chat_ref or "")),
                        "start_id": start_id, "end_id": end_id,
                    }
        if "export_artifacts" in tables:
            columns = _columns(db, "export_artifacts")
            needed = {"id", "profile", "export_job_id", "chat_ref", "status"}
            if needed.issubset(columns):
                for row in db.execute(
                    "SELECT id, profile, export_job_id, chat_ref, status FROM export_artifacts"
                ):
                    artifacts.append({
                        "id": str(row["id"]), "profile": _profile(row["profile"]),
                        "export_job_id": str(row["export_job_id"] or ""),
                        "chat_ref": canonical_chat_key(str(row["chat_ref"] or "")),
                        "status": str(row["status"]),
                    })
    finally:
        db.close()
    evidence: list[dict[str, Any]] = []
    for job in jobs.values():
        if job["status"] != "succeeded" or not job["chat_ref"] or job["start_id"] is None or job["end_id"] is None:
            continue
        linked = [artifact for artifact in artifacts if (
            artifact["export_job_id"] == job["id"]
            and artifact["profile"] == job["profile"]
            and artifact["chat_ref"] == job["chat_ref"]
        )]
        if not linked:
            continue
        evidence.append({
            "profile": job["profile"], "chat_ref": job["chat_ref"],
            "job_id": job["id"], "status": job["status"],
            "start_id": job["start_id"], "end_id": job["end_id"],
            "artifacts": [{"id": value["id"], "status": value["status"]} for value in linked],
        })
    return records, evidence, gate_enabled


def _safe_json_object(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            loaded = json.loads(value)
        except json.JSONDecodeError:
            return {}
        return loaded if isinstance(loaded, dict) else {}
    return {}


def inventory(input_dir: Path, output: Path) -> dict[str, Any]:
    root = input_dir.resolve(strict=True)
    if output.resolve() == root or output.resolve().is_relative_to(root):
        raise MigrationError("Output inventory harus disimpan di luar input-dir snapshot.")
    manifest_path = root / "migration-snapshots.json"
    manifest = _read_json(manifest_path)
    if not isinstance(manifest, dict) or manifest.get("version") != 1 or not isinstance(manifest.get("snapshots"), list):
        raise MigrationError("migration-snapshots.json harus memiliki version=1 dan snapshots[].")
    files: dict[str, str] = {manifest_path.name: _sha256_file(manifest_path)}
    records: list[dict[str, Any]] = []
    evidence: list[dict[str, Any]] = []
    database_info: list[dict[str, Any]] = []
    for snapshot in manifest["snapshots"]:
        if not isinstance(snapshot, dict):
            raise MigrationError("Setiap snapshot harus berupa object.")
        origin = str(snapshot.get("origin") or "").strip().lower()
        if origin not in {"backend", "worker"}:
            raise MigrationError("origin snapshot harus backend atau worker.")
        worker = str(snapshot.get("worker") or "").strip() or None
        if origin == "worker" and not worker:
            raise MigrationError("Snapshot worker membutuhkan nama worker.")
        profile_filter = _profile(snapshot["profile"]) if snapshot.get("profile") else None
        state: dict[str, dict[str, Any]] = {}
        state_relative: str | None = None
        state_hash: str | None = None
        state_present = False
        if snapshot.get("state_file"):
            path = _safe_snapshot_path(root, snapshot["state_file"])
            state_present = True
            state_relative = path.relative_to(root).as_posix()
            state_hash = files.setdefault(state_relative, _sha256_file(path))
            payload = _read_json(path)
            sources = payload.get("sources", {}) if isinstance(payload, dict) else None
            if not isinstance(sources, dict):
                raise MigrationError("state.json tidak memiliki object sources.")
            for chat_ref, value in sources.items():
                if not isinstance(value, dict) or "last_id" not in value:
                    continue
                item = _source_record(
                    origin=origin, worker=worker, profile=profile_filter or str(snapshot.get("profile") or "default"),
                    chat_ref=str(chat_ref), last_id=value.get("last_id"), payload=value,
                    source_type="state_json", input_path=state_relative,
                    input_sha256=state_hash,
                )
                if item and (not profile_filter or item["profile"] == profile_filter):
                    state[item["chat_ref"]] = item
        max_values: dict[str, Any] = {}
        max_relative: str | None = None
        max_hash: str | None = None
        if snapshot.get("max_file"):
            path = _safe_snapshot_path(root, snapshot["max_file"])
            max_relative = path.relative_to(root).as_posix()
            max_hash = files.setdefault(max_relative, _sha256_file(path))
            payload = _read_json(path)
            if not isinstance(payload, dict):
                raise MigrationError("max.json harus berupa object JSON.")
            max_values = payload
        if state:
            records.extend(state.values())
        elif not state_present and max_values and max_relative and max_hash:
            for chat_ref, last_id in max_values.items():
                item = _source_record(
                    origin=origin, worker=worker,
                    profile=profile_filter or str(snapshot.get("profile") or "default"),
                    chat_ref=str(chat_ref), last_id=last_id, payload={}, source_type="max_json",
                    input_path=max_relative, input_sha256=max_hash,
                )
                if item and (not profile_filter or item["profile"] == profile_filter):
                    records.append(item)
        if snapshot.get("database"):
            path = _safe_snapshot_path(root, snapshot["database"])
            relative = path.relative_to(root).as_posix()
            digest = files.setdefault(relative, _sha256_file(path))
            wal_path = Path(str(path) + "-wal")
            if wal_path.is_file():
                wal_relative = wal_path.relative_to(root).as_posix()
                files.setdefault(wal_relative, _sha256_file(wal_path))
            sql_records, sql_evidence, gate = _database_snapshot(
                path, origin=origin, worker=worker, profile_filter=profile_filter,
                input_relative=relative, input_sha256=digest,
            )
            records.extend(sql_records)
            evidence.extend(sql_evidence)
            database_info.append({
                "origin": origin, "worker": worker, "profile": profile_filter,
                "path": relative, "sha256": digest, "source_state_enabled": gate,
            })
    inventory_payload = {
        "version": 1,
        "created_at": utc_now_iso(),
        "input_dir": str(root),
        "manifest_sha256": _sha256_file(manifest_path),
        "input_files": [{"path": path, "sha256": digest} for path, digest in sorted(files.items())],
        "records": sorted(records, key=lambda row: (row["profile"], row["chat_ref"], row["origin"], row["worker"] or "", row["source_type"])),
        "evidence": sorted(evidence, key=lambda row: (row["profile"], row["chat_ref"], row["start_id"], row["end_id"])),
        "databases": database_info,
    }
    _write_json(output, inventory_payload)
    return inventory_payload


def _coverage(evidence: list[dict[str, Any]], profile: str, chat_ref: str, before: int, after: int) -> bool:
    if after <= before:
        return False
    intervals = sorted(
        (int(item["start_id"]), int(item["end_id"]))
        for item in evidence
        if item["profile"] == profile and item["chat_ref"] == chat_ref
        and item.get("status") == "succeeded"
        and item.get("artifacts")
    )
    needed = max(1, before + 1) if before else 1
    for start, end in intervals:
        if end < needed or start > needed:
            continue
        needed = max(needed, end + 1)
        if needed > after:
            return True
    return after < needed


def _distinct(records: list[dict[str, Any]], key: str) -> set[str]:
    return {json.dumps(record.get(key), ensure_ascii=False, sort_keys=True) for record in records}


def _parse_decisions(values: list[str]) -> dict[tuple[str, str], dict[str, str]]:
    decisions: dict[tuple[str, str], dict[str, str]] = {}
    for raw in values:
        try:
            selector, decision = raw.split("=", 1)
            profile, chat_ref = selector.split("|", 1)
            category, value = decision.split(":", 1)
        except ValueError as exc:
            raise MigrationError("--decision format: PROFILE|CHAT_REF=cursor:keep_backend atau metadata:keep_backend_metadata/worker:NAME") from exc
        key = (_profile(profile), canonical_chat_key(chat_ref))
        if not key[1] or category not in {"cursor", "metadata"}:
            raise MigrationError("Selector atau kategori --decision tidak valid.")
        if category == "cursor" and value != "keep_backend":
            raise MigrationError("Keputusan cursor yang didukung hanya keep_backend; promosi tetap membutuhkan bukti artifact.")
        if category == "metadata" and value not in {"keep_backend_metadata"} and not value.startswith("worker:"):
            raise MigrationError("Keputusan metadata harus keep_backend_metadata atau worker:NAMA.")
        decisions.setdefault(key, {})[category] = value
    return decisions


def _semantic_metadata(record: dict[str, Any]) -> tuple[str, str, bool, str]:
    return (
        json.dumps(record.get("label"), ensure_ascii=False, sort_keys=True),
        json.dumps(record.get("warmup_url"), ensure_ascii=False, sort_keys=True),
        bool(record.get("warmup_done", True)),
        json.dumps(record.get("warmup_done_at"), ensure_ascii=False, sort_keys=True),
    )


def build_plan(inventory_path: Path, output: Path, decisions: list[str] | None = None, migration_id: str | None = None) -> dict[str, Any]:
    inventory_path = inventory_path.resolve(strict=True)
    if output.resolve() == inventory_path:
        raise MigrationError("Output plan tidak boleh menimpa file inventory.")
    inventory_hash = _sha256_file(inventory_path)
    inv = _read_json(inventory_path)
    if not isinstance(inv, dict) or inv.get("version") != 1:
        raise MigrationError("Format inventory tidak didukung.")
    output_resolved = output.resolve()
    input_root = Path(str(inv.get("input_dir") or "")).resolve()
    if any(output_resolved == (input_root / item["path"]).resolve() for item in inv.get("input_files", [])):
        raise MigrationError("Output plan tidak boleh menimpa file snapshot.")
    explicit = _parse_decisions(decisions or [])
    records = inv.get("records", [])
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for record in records:
        grouped.setdefault((str(record["profile"]), canonical_chat_key(str(record["chat_ref"]))), []).append(record)
    rows: list[dict[str, Any]] = []
    for (profile, chat_ref), variants in sorted(grouped.items()):
        backend = [item for item in variants if item["origin"] == "backend"]
        workers = [item for item in variants if item["origin"] == "worker"]
        backend.sort(key=lambda item: (
            0 if item["source_type"] == "sql" and item.get("gate_enabled") else
            1 if item["source_type"] == "state_json" else
            2 if item["source_type"] == "max_json" else 3,
            str(item.get("input_path") or ""),
        ))
        chosen_backend = backend[0] if backend else None
        worker_latest: dict[str, dict[str, Any]] = {}
        for item in workers:
            name = str(item.get("worker") or "")
            current = worker_latest.get(name)
            if current is None or (item["source_type"] == "sql" and current["source_type"] != "sql") or item["last_id"] > current["last_id"]:
                worker_latest[name] = item
        candidates = ([chosen_backend] if chosen_backend else []) + list(worker_latest.values())
        target_sql = next((item for item in backend if item["source_type"] == "sql"), None)
        expected_revision = int(target_sql["revision"]) if target_sql else 0
        cursor_before = int(chosen_backend["last_id"]) if chosen_backend else None
        observed_cursors = {int(item["last_id"]) for item in candidates}
        cursor_conflict = len(observed_cursors) > 1
        worker_max = max((int(item["last_id"]) for item in worker_latest.values()), default=None)
        evidence_from = int(cursor_before or 0)
        evidence_to = max(observed_cursors) if observed_cursors else 0
        coverage = bool(worker_max is not None and _coverage(inv.get("evidence", []), profile, chat_ref, evidence_from, evidence_to))
        cursor_choice = explicit.get((profile, chat_ref), {}).get("cursor")
        metadata_choice = explicit.get((profile, chat_ref), {}).get("metadata")
        reasons: list[str] = []
        status = "approved"
        decision_parts: list[str] = []

        if target_sql and chosen_backend and int(target_sql["last_id"]) > int(chosen_backend["last_id"]):
            cursor_conflict = True
            reasons.append("target_sql_cursor_ahead")
        if cursor_conflict:
            if coverage:
                cursor_after = max(observed_cursors | {int(target_sql["last_id"]) if target_sql else 0})
                decision_parts.append("cursor=promote_verified_worker")
            elif cursor_choice == "keep_backend" and chosen_backend:
                cursor_after = max(int(chosen_backend["last_id"]), int(target_sql["last_id"]) if target_sql else 0)
                decision_parts.append("cursor=keep_backend")
            else:
                cursor_after = max(int(chosen_backend["last_id"]) if chosen_backend else 0, int(target_sql["last_id"]) if target_sql else 0)
                status = "blocked"
                reasons.append("cursor_conflict_without_complete_export_artifact_coverage")
        elif chosen_backend:
            cursor_after = int(chosen_backend["last_id"])
            decision_parts.append("cursor=keep_backend")
        elif workers:
            cursor_after = int(worker_max or 0)
            if coverage:
                decision_parts.append("cursor=promote_verified_worker")
            else:
                status = "blocked"
                reasons.append("worker_cursor_import_requires_complete_export_artifact_coverage")
        else:
            cursor_after = 0
            decision_parts.append("cursor=empty")

        metadata_records = candidates
        metadata_conflict = len({_semantic_metadata(item) for item in metadata_records}) > 1
        metadata_source = chosen_backend
        if metadata_conflict:
            if metadata_choice == "keep_backend_metadata" and chosen_backend:
                metadata_source = chosen_backend
                decision_parts.append("metadata=keep_backend_metadata")
            elif metadata_choice and metadata_choice.startswith("worker:"):
                selected_worker = worker_latest.get(metadata_choice.split(":", 1)[1])
                if selected_worker is None:
                    status = "blocked"
                    reasons.append("metadata_decision_worker_not_in_inventory")
                else:
                    metadata_source = selected_worker
                    decision_parts.append("metadata=" + metadata_choice)
            else:
                status = "blocked"
                reasons.append("label_or_warmup_metadata_conflict_requires_explicit_decision")
        elif metadata_source is None and worker_latest:
            metadata_source = next(iter(worker_latest.values()))
        if metadata_source is None:
            metadata_source = {"label": None, "warmup_url": None, "warmup_done": True, "warmup_done_at": None, "updated_at": ""}
        if not metadata_conflict:
            decision_parts.append("metadata=consistent")
        rows.append({
            "profile": profile, "chat_ref": chat_ref,
            "status": status, "decision": ";".join(decision_parts) or "unresolved",
            "reasons": reasons,
            "cursor_before": cursor_before,
            "cursor_after": int(cursor_after),
            "expected_revision": expected_revision,
            "label": metadata_source.get("label"),
            "updated_at": metadata_source.get("updated_at"),
            "warmup_url": metadata_source.get("warmup_url"),
            "warmup_done": bool(metadata_source.get("warmup_done", True)),
            "warmup_done_at": metadata_source.get("warmup_done_at"),
            "inputs": [{
                "origin": item["origin"], "worker": item.get("worker"),
                "source_type": item["source_type"], "last_id": item["last_id"],
                "input_path": item["input_path"], "input_sha256": item["input_sha256"],
            } for item in variants],
            "evidence": [item for item in inv.get("evidence", []) if item["profile"] == profile and item["chat_ref"] == chat_ref],
        })
    payload: dict[str, Any] = {
        "version": 1,
        "migration_id": migration_id or str(uuid.uuid4()),
        "created_at": utc_now_iso(),
        "inventory_path": str(inventory_path),
        "inventory_sha256": inventory_hash,
        "input_dir": str(inv.get("input_dir") or ""),
        "input_files": inv.get("input_files", []),
        "rows": rows,
    }
    payload["plan_sha256"] = _sha256_bytes(_canonical_json(payload))
    _write_json(output, payload)
    return payload


def _verify_plan(plan: dict[str, Any]) -> str:
    supplied = str(plan.get("plan_sha256") or "")
    unsigned = dict(plan)
    unsigned.pop("plan_sha256", None)
    expected = _sha256_bytes(_canonical_json(unsigned))
    if supplied != expected:
        raise MigrationError("Checksum plan tidak cocok; buat ulang plan setelah mengubah keputusan.")
    return supplied


def _check_input_hashes(plan: dict[str, Any]) -> None:
    inventory_path = Path(str(plan.get("inventory_path") or ""))
    if not inventory_path.is_file() or _sha256_file(inventory_path) != plan.get("inventory_sha256"):
        raise MigrationError("Inventory berubah sejak plan dibuat.")
    root = Path(str(plan.get("input_dir") or "")).resolve(strict=True)
    for item in plan.get("input_files", []):
        path = _safe_snapshot_path(root, item.get("path"))
        if _sha256_file(path) != item.get("sha256"):
            raise MigrationError(f"Checksum input berubah: {item.get('path')}")


def _target_snapshot(database: Path) -> tuple[dict[tuple[str, str], dict[str, Any]], list[str], dict[str, str], int | None]:
    if not database.exists():
        return {}, [], {}, None
    db = _readonly_database(database)
    try:
        tables = _tables(db)
        current: dict[tuple[str, str], dict[str, Any]] = {}
        if "source_records" in tables:
            for row in db.execute("SELECT profile, canonical_chat_key, last_id, revision FROM source_records"):
                current[(_profile(row["profile"]), canonical_chat_key(row["canonical_chat_key"]))] = {
                    "last_id": int(row["last_id"]), "revision": int(row["revision"]),
                }
        active_profiles: list[str] = []
        if "jobs" in tables:
            for row in db.execute(
                "SELECT DISTINCT profile FROM jobs WHERE kind='export' AND status IN ('queued','dispatched','running','paused')"
            ):
                active_profiles.append(_profile(row["profile"]))
        migration_runs: dict[str, str] = {}
        if "source_migration_runs" in tables:
            migration_runs = {
                str(row["migration_id"]): str(row["plan_sha256"])
                for row in db.execute("SELECT migration_id, plan_sha256 FROM source_migration_runs")
            }
        artifact_count = (
            int(db.execute("SELECT COUNT(*) FROM export_artifacts").fetchone()[0])
            if "export_artifacts" in tables else None
        )
        return current, active_profiles, migration_runs, artifact_count
    finally:
        db.close()


def apply_plan(plan_path: Path, database: Path, *, commit: bool, backup: Path | None, exports_drained: bool) -> dict[str, Any]:
    plan_path = plan_path.resolve(strict=True)
    plan = _read_json(plan_path)
    if not isinstance(plan, dict) or plan.get("version") != 1:
        raise MigrationError("Format plan tidak didukung.")
    plan_hash = _verify_plan(plan)
    rows = plan.get("rows")
    if not isinstance(rows, list):
        raise MigrationError("Plan tidak memiliki rows[].")
    if not rows:
        raise MigrationError("Plan kosong tidak boleh mengaktifkan backend source state.")
    current, active_profiles, migration_runs, artifact_count = _target_snapshot(database)
    prior_plan = migration_runs.get(str(plan.get("migration_id") or ""))
    if prior_plan is not None:
        if prior_plan != plan_hash:
            raise MigrationError("Migration ID sudah digunakan oleh plan berbeda.")
        return {"mode": "commit" if commit else "dry-run", "plan_sha256": plan_hash, "replay": True, "source_count": len(current)}
    _check_input_hashes(plan)
    affected = {str(item["profile"]) for item in rows}
    active = sorted(affected.intersection(active_profiles))
    if active:
        raise MigrationError("Masih ada export aktif untuk profile: " + ", ".join(active))
    if commit:
        if not exports_drained:
            raise MigrationError("Commit membutuhkan --exports-drained setelah admission export dihentikan.")
        if backup is None or not backup.is_file() or backup.stat().st_size <= 0:
            raise MigrationError("Commit membutuhkan --backup yang tersedia dan tidak kosong.")
        if backup.resolve() == database.resolve():
            raise MigrationError("File backup tidak boleh sama dengan database target.")
    for item in rows:
        key = (_profile(item["profile"]), canonical_chat_key(str(item["chat_ref"])))
        actual = int(current.get(key, {}).get("revision", 0))
        expected = int(item["expected_revision"])
        if actual != expected:
            raise MigrationError(f"Revision target berubah untuk {key[0]}:{key[1]} (expected {expected}, actual {actual}).")
    if not commit:
        return {"mode": "dry-run", "plan_sha256": plan_hash, "approved": sum(item["status"] == "approved" for item in rows), "blocked": sum(item["status"] != "approved" for item in rows), "source_count": len(rows)}

    before_count = len(current)
    expected_added = sum(
        1 for item in rows
        if item["status"] == "approved"
        and (_profile(item["profile"]), canonical_chat_key(str(item["chat_ref"]))) not in current
    )
    repository = SqliteSourceRepository(database)
    migration_rows = [{
        **item,
        "expected_revision": int(item["expected_revision"]),
        "input_sha256": plan.get("inventory_sha256", ""),
    } for item in rows]
    try:
        replay = repository.apply_migration_plan(
            migration_id=str(plan["migration_id"]), plan_sha256=plan_hash,
            backup_sha256=_sha256_file(backup), rows=migration_rows,
        )
    except (SourceRevisionConflict, MigrationPlanConflict) as exc:
        raise MigrationError(str(exc)) from exc
    verified = repository.export_database_snapshot(database)
    after_current, _, _, after_artifact_count = _target_snapshot(database)
    if len(verified["sources"]) < before_count + expected_added:
        raise MigrationError("Verifikasi jumlah source setelah commit gagal.")
    if artifact_count is not None and after_artifact_count != artifact_count:
        raise MigrationError("Migrasi mengubah jumlah artifact catalog; periksa database sebelum melanjutkan.")
    if any(
        item["status"] == "approved"
        and int(after_current.get((_profile(item["profile"]), canonical_chat_key(str(item["chat_ref"]))), {}).get("last_id", -1)) < int(item["cursor_after"])
        for item in rows
    ):
        raise MigrationError("Verifikasi cursor source setelah commit gagal.")
    return {"mode": "commit", "plan_sha256": plan_hash, "replay": replay, "source_count": len(verified["sources"]), "ledger_count": len(verified["ledger"])}


def export_legacy(database: Path, output_dir: Path, *, exports_drained: bool) -> dict[str, Any]:
    if not database.is_file():
        raise MigrationError("Database sumber tidak ditemukan.")
    if database.resolve().is_relative_to(output_dir.resolve()):
        raise MigrationError("output-dir tidak boleh berisi database sumber.")
    _, active_profiles, _, _ = _target_snapshot(database)
    if not exports_drained:
        raise MigrationError("Export rollback membutuhkan --exports-drained setelah admission export dihentikan.")
    if active_profiles:
        raise MigrationError("Export rollback ditolak karena masih ada export aktif: " + ", ".join(sorted(set(active_profiles))))
    if output_dir.exists() and any(output_dir.iterdir()):
        raise MigrationError("output-dir harus baru atau kosong; file tidak akan ditimpa.")
    snapshot = SqliteSourceRepository.export_database_snapshot(database)
    root = output_dir.resolve()
    root.mkdir(parents=True, exist_ok=True)
    by_profile: dict[str, dict[str, dict[str, Any]]] = {}
    for record in snapshot["sources"]:
        profile = _profile(record["profile"])
        source = {
            "last_id": int(record["last_id"]), "label": record.get("label"),
            "updated_at": str(record.get("updated_at") or utc_now_iso()),
            "warmup_url": record.get("warmup_url"),
            "warmup_done": bool(record.get("warmup_done", True)),
            "warmup_done_at": record.get("warmup_done_at"),
        }
        by_profile.setdefault(profile, {})[canonical_chat_key(str(record["canonical_chat_key"]))] = source
    output_files: list[dict[str, str]] = []
    for profile, sources in sorted(by_profile.items()):
        relative = Path("state.json") if profile == "default" else Path("profiles") / profile / "state.json"
        path = root / relative
        _write_json(path, {"sources": sources, "migration": {"exported_from_sql": True}}, exclusive=True)
        output_files.append({"path": relative.as_posix(), "sha256": _sha256_file(path)})
    ledger_path = root / "source-migration-ledger.json"
    _write_json(ledger_path, {"version": 1, "runs": snapshot.get("runs", []), "ledger": snapshot["ledger"]}, exclusive=True)
    output_files.append({"path": ledger_path.name, "sha256": _sha256_file(ledger_path)})
    manifest = {"version": 1, "created_at": utc_now_iso(), "database_sha256": _sha256_file(database), "files": output_files}
    _write_json(root / "legacy-export-manifest.json", manifest, exclusive=True)
    return {"profiles": len(by_profile), "sources": len(snapshot["sources"]), "ledger_rows": len(snapshot["ledger"]), "output_files": len(output_files) + 1}


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    inv = commands.add_parser("inventory", help="Inventaris snapshot state secara offline.")
    inv.add_argument("--input-dir", required=True, type=Path)
    inv.add_argument("--output", required=True, type=Path)
    plan = commands.add_parser("plan", help="Buat plan dengan status approved/blocked.")
    plan.add_argument("--inventory", required=True, type=Path)
    plan.add_argument("--output", required=True, type=Path)
    plan.add_argument("--migration-id")
    plan.add_argument("--decision", action="append", default=[], help="PROFILE|CHAT_REF=cursor:keep_backend atau metadata:keep_backend_metadata/worker:NAME; ulangi untuk keputusan terpisah.")
    apply = commands.add_parser("apply", help="Validasi plan; dry-run adalah default.")
    apply.add_argument("--plan", required=True, type=Path)
    apply.add_argument("--database", required=True, type=Path)
    apply.add_argument("--dry-run", action="store_true")
    apply.add_argument("--commit", action="store_true")
    apply.add_argument("--backup", type=Path)
    apply.add_argument("--exports-drained", action="store_true")
    legacy = commands.add_parser("export-legacy", help="Ekspor state SQL dan ledger untuk rollback.")
    legacy.add_argument("--database", required=True, type=Path)
    legacy.add_argument("--output-dir", required=True, type=Path)
    legacy.add_argument("--exports-drained", action="store_true", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "inventory":
            result = inventory(args.input_dir, args.output)
            message = {"records": len(result["records"]), "evidence": len(result["evidence"]), "input_files": len(result["input_files"]), "output": str(args.output)}
        elif args.command == "plan":
            result = build_plan(args.inventory, args.output, args.decision, args.migration_id)
            message = {"migration_id": result["migration_id"], "plan_sha256": result["plan_sha256"], "approved": sum(row["status"] == "approved" for row in result["rows"]), "blocked": sum(row["status"] != "approved" for row in result["rows"]), "output": str(args.output)}
        elif args.command == "apply":
            if args.commit and args.dry_run:
                raise MigrationError("Pilih --commit atau --dry-run, bukan keduanya.")
            result = apply_plan(args.plan, args.database, commit=args.commit, backup=args.backup, exports_drained=args.exports_drained)
            message = result
        else:
            message = export_legacy(args.database, args.output_dir, exports_drained=args.exports_drained)
        print(json.dumps({"ok": True, **message}, ensure_ascii=False))
        return 0
    except (MigrationError, OSError, ValueError, sqlite3.Error) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
