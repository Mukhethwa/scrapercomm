import { useCallback, useEffect, useState } from 'react'

export type MapTheme = 'light' | 'dark'

const STORAGE_KEY = 'commuttr:map-theme'
const CHANGED = 'commuttr:map-theme-changed'

/** The stored choice, or the system's if none has been made. */
function read(): MapTheme {
  try {
    const saved = localStorage.getItem(STORAGE_KEY)
    if (saved === 'dark' || saved === 'light') return saved
  } catch {
    // A private window can refuse to read; fall through to the system preference.
  }
  return window.matchMedia?.('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'
}

/**
 * Light or dark basemap.
 *
 * This used to default to light whatever the system said, because a dark map under a
 * light app was jarring and an orange route over near-black is harder to follow than the
 * same line over a pale street map. The first half of that reasoning has since inverted:
 * the app has a real dark theme, so on a dark phone the light map is now the thing that
 * does not belong.
 *
 * So the default follows the system, and a rider who prefers the pale street map still
 * has the toggle - and their choice, once made, outranks the system.
 */
export function useMapTheme() {
  const [theme, setTheme] = useState<MapTheme>(() => read())

  useEffect(() => {
    const sync = () => setTheme(read())
    window.addEventListener(CHANGED, sync)
    window.addEventListener('storage', sync)
    return () => {
      window.removeEventListener(CHANGED, sync)
      window.removeEventListener('storage', sync)
    }
  }, [])

  // Both maps read the same value, so switching on one is switching on both.
  const toggle = useCallback(() => {
    setTheme((current) => {
      const next: MapTheme = current === 'dark' ? 'light' : 'dark'
      try {
        localStorage.setItem(STORAGE_KEY, next)
      } catch {
        // Storage refused; the choice still applies for this visit.
      }
      window.dispatchEvent(new Event(CHANGED))
      return next
    })
  }, [])

  return { theme, toggle }
}
