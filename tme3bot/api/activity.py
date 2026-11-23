from __future__ import annotations

from typing import Any


def track_activity_jobs(request: Any, jobs: Any) -> None:
    """Associate newly-created durable jobs with the current API request audit."""
    if jobs is None:
        return
    if not isinstance(jobs, (list, tuple, set)):
        jobs = (jobs,)
    tracked = list(getattr(request.state, "activity_jobs", ()) or ())
    known = {str(item.get("job_id") or "") for item in tracked if isinstance(item, dict)}
    for job in jobs:
        if isinstance(job, dict):
            job_id = str(job.get("job_id") or job.get("id") or "").strip()
            profile = str(job.get("profile") or "")
            worker = str(job.get("worker") or "")
        else:
            job_id = str(getattr(job, "id", "") or "").strip()
            profile = str(getattr(job, "profile", "") or "")
            worker = str(getattr(job, "worker", "") or "")
        if not job_id or job_id in known:
            continue
        tracked.append(
            {
                "job_id": job_id,
                "profile": profile,
                "worker": worker,
            }
        )
        known.add(job_id)
    request.state.activity_jobs = tracked


def track_activity_operation(request: Any, operation: Any) -> None:
    """Associate an operation-backed job submission with its API request."""
    job_id = str(getattr(operation, "job_id", "") or "").strip()
    if not job_id:
        return
    target = getattr(operation, "target", {})
    target = target if isinstance(target, dict) else {}
    request.state.activity_operation_id = str(getattr(operation, "id", "") or "")
    track_activity_jobs(
        request,
        {
            "job_id": job_id,
            "profile": str(getattr(operation, "profile", "") or ""),
            "worker": str(target.get("worker") or ""),
        },
    )
