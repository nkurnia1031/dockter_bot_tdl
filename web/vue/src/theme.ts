export type ThemePreference = 'light' | 'dark' | 'system';

export function resolveTheme(value: string | null): ThemePreference {
  return value === 'light' || value === 'dark' || value === 'system' ? value : 'dark';
}

export function applyTheme(value: ThemePreference, systemDark = window.matchMedia('(prefers-color-scheme: dark)').matches): void {
  const isDark = value === 'dark' || (value === 'system' && systemDark);
  document.documentElement.dataset.theme = isDark ? 'dark' : 'light';
  document.documentElement.classList.toggle('dark', isDark);
}
