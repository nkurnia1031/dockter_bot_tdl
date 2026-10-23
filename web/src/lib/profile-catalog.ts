export type LocalProfileOption = {
  name: string;
  workers: string[];
  exclusive_worker: string;
};

export type RuntimeReadinessCell = {
  worker: string;
  profile: string | null;
  runtime: string;
  status: 'ready' | 'not_ready';
  checked_at: string;
  reason_code: string;
};

export type RuntimeReadinessWorker = {
  name: string;
  status: 'success' | 'failed' | 'disabled';
  checked_at: string;
  reason_code: string;
};

export type RuntimeReadinessSnapshot = {
  checked_at: string;
  workers: RuntimeReadinessWorker[];
  cells: RuntimeReadinessCell[];
};

export type RuntimeReadinessResult = {
  status: 'ready' | 'not_ready' | 'offline' | 'disabled' | 'unscanned';
  checked_at: string;
  reason_code: string;
};

export function normalizeRuntimeReadiness(value: unknown): RuntimeReadinessSnapshot {
  const payload = value && typeof value === 'object' ? value as Record<string, unknown> : {};
  const workers = Array.isArray(payload.workers) ? payload.workers.flatMap((raw) => {
    if (!raw || typeof raw !== 'object') return [];
    const item = raw as Record<string, unknown>;
    const name = String(item.name || '').trim().toLowerCase();
    const status = String(item.status || '');
    if (!name || !['success', 'failed', 'disabled'].includes(status)) return [];
    return [{
      name,
      status: status as RuntimeReadinessWorker['status'],
      checked_at: String(item.checked_at || ''),
      reason_code: String(item.reason_code || '')
    }];
  }) : [];
  const cells = Array.isArray(payload.cells) ? payload.cells.flatMap((raw) => {
    if (!raw || typeof raw !== 'object') return [];
    const item = raw as Record<string, unknown>;
    const worker = String(item.worker || '').trim().toLowerCase();
    const rawProfile = item.profile;
    const profile = rawProfile === null || rawProfile === undefined || !String(rawProfile).trim()
      ? null
      : String(rawProfile).trim().toLowerCase();
    const runtime = String(item.runtime || '').trim().toLowerCase();
    const status = String(item.status || '');
    if (!worker || !runtime || !['ready', 'not_ready'].includes(status)) return [];
    return [{
      worker,
      profile,
      runtime,
      status: status as RuntimeReadinessCell['status'],
      checked_at: String(item.checked_at || ''),
      reason_code: String(item.reason_code || '')
    }];
  }) : [];
  return {
    checked_at: String(payload.checked_at || ''),
    workers,
    cells
  };
}

export function runtimeReadinessFor(
  snapshot: RuntimeReadinessSnapshot,
  profile: string | null,
  worker: string,
  runtime = 'export'
): RuntimeReadinessResult {
  const normalizedProfile = profile === null || !String(profile || '').trim()
    ? null
    : String(profile).trim().toLowerCase();
  const normalizedWorker = String(worker || '').trim().toLowerCase();
  const workerState = snapshot.workers.find((item) => item.name === normalizedWorker);
  if (workerState?.status === 'disabled') {
    return { status: 'disabled', checked_at: workerState.checked_at, reason_code: 'WORKER_DISABLED' };
  }
  if (workerState?.status === 'failed') {
    return { status: 'offline', checked_at: workerState.checked_at, reason_code: workerState.reason_code || 'WORKER_UNAVAILABLE' };
  }
  const cell = snapshot.cells.find((item) =>
    item.worker === normalizedWorker && item.profile === normalizedProfile && item.runtime === runtime
  );
  if (!workerState || !cell) {
    return { status: 'unscanned', checked_at: '', reason_code: 'RUNTIME_NOT_SCANNED' };
  }
  return {
    status: cell.status,
    checked_at: cell.checked_at,
    reason_code: cell.reason_code
  };
}

export function runtimeReadinessForWorker(
  snapshot: RuntimeReadinessSnapshot,
  worker: string,
  runtime: string
): RuntimeReadinessResult {
  const normalizedWorker = String(worker || '').trim().toLowerCase();
  const workerState = snapshot.workers.find((item) => item.name === normalizedWorker);
  if (workerState?.status === 'disabled') {
    return { status: 'disabled', checked_at: workerState.checked_at, reason_code: 'WORKER_DISABLED' };
  }
  if (workerState?.status === 'failed') {
    return { status: 'offline', checked_at: workerState.checked_at, reason_code: workerState.reason_code || 'WORKER_UNAVAILABLE' };
  }
  const cells = snapshot.cells.filter((item) =>
    item.worker === normalizedWorker && item.profile !== null && item.runtime === runtime
  );
  if (!workerState || !cells.length) {
    return { status: 'unscanned', checked_at: '', reason_code: 'RUNTIME_NOT_SCANNED' };
  }
  const ready = cells.find((item) => item.status === 'ready');
  if (ready) {
    return { status: 'ready', checked_at: ready.checked_at, reason_code: '' };
  }
  const latest = cells.reduce((selected, item) =>
    item.checked_at > selected.checked_at ? item : selected
  );
  return {
    status: 'not_ready',
    checked_at: latest.checked_at,
    reason_code: latest.reason_code || 'RUNTIME_NOT_READY'
  };
}

export function profileOptionLabel(profile: LocalProfileOption): string {
  return profile.exclusive_worker
    ? `${profile.name} (${profile.exclusive_worker})`
    : profile.name;
}

export function profileOptionsForWorker(
  profiles: LocalProfileOption[],
  worker: string
): LocalProfileOption[] {
  if (!worker) return profiles;
  return profiles.filter((profile) => profile.workers.includes(worker));
}

export function chooseProfileWorker(
  profile: LocalProfileOption | undefined,
  currentWorker: string,
  fallbackWorker = ''
): string {
  if (!profile) return currentWorker || fallbackWorker;
  if (profile.exclusive_worker) return profile.exclusive_worker;
  if (currentWorker && profile.workers.includes(currentWorker)) return currentWorker;
  return profile.workers[0] || fallbackWorker;
}

export function normalizeLocalProfileCatalog(value: unknown): LocalProfileOption[] {
  if (!value || typeof value !== 'object') return [];
  const raw = (value as { profiles?: unknown }).profiles;
  if (!Array.isArray(raw)) return [];
  const seen = new Set<string>();
  const profiles: LocalProfileOption[] = [];
  for (const item of raw) {
    if (!item || typeof item !== 'object') continue;
    const candidate = item as Partial<LocalProfileOption>;
    const name = String(candidate.name || '').trim().toLowerCase();
    const workers = Array.isArray(candidate.workers)
      ? [...new Set(candidate.workers.map((worker) => String(worker || '').trim().toLowerCase()).filter(Boolean))].sort()
      : [];
    if (!name || !workers.length || seen.has(name)) continue;
    const exclusive = workers.length === 1 ? workers[0] : '';
    seen.add(name);
    profiles.push({ name, workers, exclusive_worker: exclusive });
  }
  return profiles.sort((left, right) => left.name.localeCompare(right.name));
}
