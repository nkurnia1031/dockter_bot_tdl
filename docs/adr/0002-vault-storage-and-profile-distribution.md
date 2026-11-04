# ADR 0002: Vault stores active profiles and distributes worker copies

- Status: accepted
- Date: 2026-11-04

## Context

Vault profiles are a shared encrypted store for active TDL profile bundles. The
worker-pull implementation added a second lifecycle around manifests, startup
checks, ACKs, revision readiness, and job admission. It made worker availability
and Vault status affect unrelated profile jobs, although the TDL command itself
is the authoritative check that a local session can perform an operation.

## Decision

- Vault stores the active profile bundle and its identity as the shared source
  for distribution.
- Distribution is an install/copy operation to worker-local profile storage.
  Install status and logs are operational information only.
- A saved Vault profile becomes active immediately after validation and storage.
  Offline or failed worker installs do not keep the Vault profile inactive.
- Workers do not pull profile manifests at startup, run a Vault sync command,
  or report Vault readiness as a condition for running jobs.
- Backend job admission does not consult Vault revisions, worker-install
  acknowledgements, profile fingerprints, or Vault distribution status. Existing
  actor authorization, active-worker selection, path checks, and data safety
  guards remain in force. The actual TDL/rclone/TTS command determines whether
  the worker can complete the requested work.
- Distribution progress can be retried and displayed per worker. It must not
  delay unrelated job submissions or job execution.
- Deleting a Vault bundle removes the shared copy only. It does not remove an
  installed worker-local profile.

## Consequences

- Vault profile activation is decoupled from asynchronous worker installation.
- Worker health reports process health, not whether it reached Vault.
- Runtime scan evidence may guide operator choice, but it does not represent a
  Vault synchronization contract or job gate.
- Legacy pull-sync routes, handlers, worker state, and readiness checks are
  removed. Database startup drops retired request/event tables and migrates
  retained installation history to installation-event terminology.
