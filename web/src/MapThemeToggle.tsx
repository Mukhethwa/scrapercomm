import { Moon, Sun } from 'lucide-react'
import type { MapTheme } from './mapTheme'

/**
 * Light/dark switch for the basemap.
 *
 * Sits opposite the zoom controls so the two never collide, and names the state it will
 * move to rather than the one it is in - a button that says "Dark map" is one you press
 * to get a dark map.
 */
export default function MapThemeToggle(
  { theme, onToggle }: { theme: MapTheme; onToggle: () => void },
) {
  const next = theme === 'dark' ? 'light' : 'dark'
  return (
    <button
      type="button"
      onClick={onToggle}
      title={`Switch to the ${next} map`}
      aria-label={`Switch to the ${next} map`}
      className="absolute top-2.5 right-2.5 z-10 inline-flex cursor-pointer items-center gap-1.5
                 rounded-lg border border-line bg-panel px-2.5 py-1.5 text-[11px] font-bold
                 text-ink shadow-sm hover:border-accent hover:text-accent"
    >
      {theme === 'dark'
        ? <Sun size={13} aria-hidden="true" />
        : <Moon size={13} aria-hidden="true" />}
      <span>{next === 'dark' ? 'Dark map' : 'Light map'}</span>
    </button>
  )
}
