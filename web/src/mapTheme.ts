import { useCallback, useEffect, useState } from 'react'

export type MapTheme = 'light' | 'dark'

const STORAGE_KEY = 'commuttr:map-theme'
const CHANGED = 'commuttr:map-theme-changed'

/**
 * Light or dark basemap, chosen by the rider rather than by their operating system.
 *
 * mapcn falls back to the system preference, which meant somebody whose laptop is in
 * dark mode got a near-black map under an otherwise light app - and a route drawn in
 * orange over it is far harder to follow than the same line over a pale street map.
 * Light is the default here for that reason; the choice is remembered.
 */
export function useMapTheme() {
  const [theme, setTheme] = useState<MapTheme>(() => {
    try {
      return localStorage.getItem(STORAGE_KEY) === 'dark' ? 'dark' : 'light'
    } catch {
      return 'light'
    }
  })

  useEffect(() => {
    const sync = () => {
      try {
        setTheme(localStorage.getItem(STORAGE_KEY) === 'dark' ? 'dark' : 'light')
      } catch {
        // A private window can refuse to read; the current choice still stands.
      }
    }
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
