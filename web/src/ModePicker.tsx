import { useEffect, useRef, useState } from 'react'
import { Bus, Check, ChevronDown, TrainFront } from 'lucide-react'
import { MODES, useModes, type Mode } from './modes'

const ICON = { bus: Bus, train: TrainFront }

/**
 * Regions in the order they first appear in MODES, so Cape Town leads.
 *
 * Keyed rather than run-length grouped: Gauteng appears either side of the two
 * Johannesburg services, and merging only neighbours listed it twice.
 */
function byRegion(modes: Mode[]): [string, Mode[]][] {
  const groups = new Map<string, Mode[]>()
  for (const m of modes) {
    const existing = groups.get(m.region)
    if (existing) existing.push(m)
    else groups.set(m.region, [m])
  }
  return [...groups]
}

function Chip({ mode, on, onToggle }: { mode: Mode; on: boolean; onToggle: () => void }) {
  const Icon = ICON[mode.kind]
  return (
    <button
      className={[
        'inline-flex items-center gap-1.5 rounded-full border px-[11px] py-1',
        'text-xs font-semibold',
        on ? 'border-ink bg-ink text-white' : 'border-line bg-panel text-ink',
        // Listed but not selectable. Dimmed and not-allowed rather than hidden, so a
        // rider looking for a train learns the app has none yet instead of doubting
        // their search.
        mode.available ? 'cursor-pointer hover:border-accent' : 'cursor-not-allowed opacity-55',
      ].join(' ')}
      onClick={onToggle}
      disabled={!mode.available}
      aria-pressed={mode.available ? on : undefined}
      title={mode.available ? `${mode.note} (${mode.region})`
                            : `${mode.note} (${mode.region}) - not yet available`}
    >
      {on ? <Check size={13} aria-hidden="true" /> : <Icon size={13} aria-hidden="true" />}
      <span>{mode.name}</span>
      {!mode.available && (
        <span className="rounded border border-line px-1 text-[9.5px] font-bold tracking-[.06em] text-muted uppercase">
          soon
        </span>
      )}
    </button>
  )
}

/**
 * Which transport to plan with.
 *
 * The ones with no data behind them are shown greyed rather than hidden, so a rider
 * looking for a train can see the app does not have trains yet instead of assuming they
 * searched wrongly. They are real buttons but disabled, which is what tells a screen
 * reader the same thing.
 *
 * The list of what is still to come opens as a panel over the page rather than inside
 * the row. Opening it used to grow the row from one line to two and push everything
 * below it - the results, the map - down the screen, which is a jarring thing to happen
 * because you glanced at a roadmap. Overlaying costs the layout nothing.
 */
export default function ModePicker() {
  const modes = useModes()
  const [showAll, setShowAll] = useState(false)
  const box = useRef<HTMLDivElement>(null)
  const ready = MODES.filter((m) => m.available)

  // A panel over the page has to be dismissable the ways a reader expects.
  useEffect(() => {
    if (!showAll) return
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') setShowAll(false) }
    const onDown = (e: MouseEvent) => {
      if (box.current && !box.current.contains(e.target as Node)) setShowAll(false)
    }
    document.addEventListener('keydown', onKey)
    document.addEventListener('mousedown', onDown)
    return () => {
      document.removeEventListener('keydown', onKey)
      document.removeEventListener('mousedown', onDown)
    }
  }, [showAll])

  return (
    <div className="modepicker relative flex flex-wrap items-center gap-1.5" ref={box}>
      <div className="flex min-w-0 flex-1 flex-wrap items-center gap-1.5">
        {ready.map((m) => (
          <Chip key={m.id} mode={m} on={modes.has(m.id)} onToggle={() => modes.toggle(m.id)} />
        ))}
        <button
          className="inline-flex cursor-pointer items-center gap-1 rounded-full border border-dashed border-line bg-transparent px-[11px] py-1 text-[11.5px] font-bold text-muted hover:border-accent hover:text-accent"
          onClick={() => setShowAll(!showAll)}
          aria-expanded={showAll}
        >
          <ChevronDown size={13} aria-hidden="true"
            className={`transition-transform ${showAll ? 'rotate-180' : ''}`} />
          {showAll ? 'Hide' : 'More transport soon'}
        </button>
      </div>

      {showAll && (
        <div className="absolute top-full left-0 z-30 mt-2 max-h-[60vh] w-full max-w-3xl overflow-y-auto rounded-xl border border-line bg-panel p-3 shadow-lg">
          <div className="mb-2 text-[11px] font-bold tracking-[.05em] text-muted uppercase">
            Coming to these cities
          </div>
          <div className="flex flex-wrap gap-4">
            {byRegion(MODES.filter((m) => !m.available)).map(([region, group]) => (
              <div className="flex flex-col gap-1" key={region}>
                <span className="text-[10px] font-bold tracking-[.06em] text-muted uppercase">
                  {region}
                </span>
                <div className="flex min-w-0 flex-wrap gap-1.5">
                  {group.map((m) => (
                    <Chip key={m.id} mode={m} on={false} onToggle={() => modes.toggle(m.id)} />
                  ))}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
