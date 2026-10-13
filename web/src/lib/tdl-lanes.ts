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
  return value
    .replace(/(^|[\\/])root(?=[\\/]\.tdl(?:[\\/]|$))/g, '$1Download')
    .replace(/(^|[\\/])user1(?=[\\/]\.tdl(?:[\\/]|$))/g, '$1Export');
}
