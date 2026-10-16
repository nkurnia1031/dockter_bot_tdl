export type LocalProfileOption = {
  name: string;
  workers: string[];
  exclusive_worker: string;
};

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
