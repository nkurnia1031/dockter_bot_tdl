const sessionLaneLabels: Record<string, string> = {
  root: 'Download',
  user1: 'Export'
};

const diagnosticLaneLabels: Record<string, string> = {
  identity: 'Identitas',
  root_session: 'Download',
  user1_session: 'Export'
};

export function tdlLaneLabel(identifier: string): string {
  return Object.prototype.hasOwnProperty.call(sessionLaneLabels, identifier)
    ? sessionLaneLabels[identifier]
    : identifier;
}

export function profileDiagnosticLabel(identifier: string): string {
  return Object.prototype.hasOwnProperty.call(diagnosticLaneLabels, identifier)
    ? diagnosticLaneLabels[identifier]
    : identifier;
}

export function operatorTdlLogText(value: string): string {
  const lanes = new Set<string>();
  const storagePath = /(?:^|[\\/])(root|user1)(?=[\\/]\.tdl(?:[\\/]|$))/g;

  for (const match of value.matchAll(storagePath)) {
    lanes.add(tdlLaneLabel(match[1]));
  }

  return lanes.size > 0 ? `[lane ${[...lanes].join(', ')}] ${value}` : value;
}
