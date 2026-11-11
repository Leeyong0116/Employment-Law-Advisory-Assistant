// Light or dark theme (author's decision 2026-11-12). The choice is stored in this browser;
// with no stored choice the system setting is used. index.html applies the same rule before
// React starts, so the page never flashes the wrong colours.
export type Theme = 'light' | 'dark'

export const THEME_KEY = 'getright.theme.v1'

export function initialTheme(): Theme {
  try {
    const stored = localStorage.getItem(THEME_KEY)
    if (stored === 'light' || stored === 'dark') return stored
  } catch {
    // storage blocked: fall back to the system setting
  }
  return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'
}

export function applyTheme(theme: Theme): void {
  document.documentElement.classList.toggle('dark', theme === 'dark')
  try {
    localStorage.setItem(THEME_KEY, theme)
  } catch {
    // storage blocked: the choice lasts until the page closes
  }
}
