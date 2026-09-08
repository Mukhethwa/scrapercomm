/**
 * Light, dark, or whatever the phone is set to.
 *
 * Three states rather than two. A plain toggle has to start somewhere, and starting it on
 * "light" ignores a phone that is already in dark mode, while starting it on "dark"
 * ignores one that is not. "System" is the honest default and the other two are an
 * override for somebody who wants this app to differ from the rest of their phone.
 *
 * The choice is written to the root element rather than held in React, because the CSS has
 * to answer for the whole document - including the classic view, which is styled by a
 * stylesheet React knows nothing about.
 */
import { useCallback, useEffect, useState } from 'react'

export type Theme = 'system' | 'light' | 'dark'

/**
 * What somebody gets before they have chosen anything.
 *
 * Light rather than "system". Following the phone sounds like the respectful default, but
 * it means a rider on a dark phone meets the app in a theme nobody has looked at as hard
 * as the light one - and the first impression is the one that decides whether they trust
 * it. Anyone who prefers dark is two taps away, and their choice then outranks this.
 */
const DEFAULT: Theme = 'light'

const STORAGE_KEY = 'commuttr:theme'
const CHANGED = 'commuttr:theme-changed'

export function readTheme(): Theme {
  try {
    const saved = localStorage.getItem(STORAGE_KEY)
    if (saved === 'light' || saved === 'dark' || saved === 'system') return saved
  } catch {
    // A private window can refuse to read; the default applies for this visit.
  }
  return DEFAULT
}

/**
 * Put the choice on <html>, where the stylesheet can see it.
 *
 * "system" removes the attribute rather than setting it to anything, which hands the
 * decision back to the prefers-color-scheme rule in the stylesheet. Note that the stored
 * value still says "system" - only the attribute is absent - because an absent stored
 * value means the rider has not chosen at all, and that gets light.
 */
export function applyTheme(theme: Theme) {
  const root = document.documentElement
  if (theme === 'system') root.removeAttribute('data-theme')
  else root.setAttribute('data-theme', theme)
}

/** Read the theme and change it, shared across every component that shows the control. */
export function useTheme() {
  const [theme, setThemeState] = useState<Theme>(readTheme)

  useEffect(() => {
    const sync = () => setThemeState(readTheme())
    window.addEventListener(CHANGED, sync)
    window.addEventListener('storage', sync)
    return () => {
      window.removeEventListener(CHANGED, sync)
      window.removeEventListener('storage', sync)
    }
  }, [])

  const setTheme = useCallback((next: Theme) => {
    try {
      // Stored even for "system": absence of a key now means light, so choosing to
      // follow the phone has to be recorded rather than implied.
      localStorage.setItem(STORAGE_KEY, next)
    } catch {
      // Storage refused; the choice still applies for this visit.
    }
    applyTheme(next)
    setThemeState(next)
    window.dispatchEvent(new Event(CHANGED))
  }, [])

  return { theme, setTheme }
}

/**
 * Hold the document at one theme for as long as a view is mounted.
 *
 * The classic layout is styled by a stylesheet with 84 hard-coded whites in it, written
 * when there was only one theme. Under the dark tokens those turn into white cards
 * carrying white text, which is not a style problem but an unreadable screen. Rather than
 * rewrite a stylesheet that is due to be deleted, that view pins itself to light and
 * releases the pin when it unmounts.
 */
export function usePinnedTheme(pin: Theme | null) {
  const { theme } = useTheme()
  useEffect(() => {
    if (!pin) return
    applyTheme(pin)
    return () => applyTheme(readTheme())
  }, [pin, theme])
}
