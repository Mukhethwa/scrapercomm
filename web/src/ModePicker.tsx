import { useState } from 'react'
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

/**
 * Which transport to plan with.
 *
 * The ones with no data behind them are shown greyed rather than hidden, so a rider
 * looking for a train can see the app does not have trains yet instead of assuming they
 * searched wrongly. They are real buttons but disabled, which is what tells a screen
 * reader the same thing.
 *
 * Grouped by city rather than repeating the city on every chip. The point of listing
 * services this app does not carry is to show somebody in Durban or Gqeberha that it is
 * coming to them, and a dozen chips say that better under headings than as a dozen
 * labels - which would also have crowded out the "soon" each one needs to carry.
 */
export default function ModePicker() {
  const modes = useModes()
  const [showAll, setShowAll] = useState(false)
  const ready = MODES.filter((m) => m.available)
  const coming = MODES.length - ready.length

  // Listing a dozen services flat took 479px on a phone - more than half the screen
  // before the rider sees a single result. What they can actually use stays visible;
  // the roadmap is one tap away.
  const shown = showAll ? MODES : ready

  return (
    <div className="modepicker">
      <span className="modelbl">Transport</span>
      <div className="moderegions">
        {byRegion(shown).map(([region, group]) => (
          <div className="moderegion" key={region}>
            <span className="moderegionlbl">{region}</span>
            <div className="modelist">
              {group.map((m) => {
                const Icon = ICON[m.kind]
                const on = modes.has(m.id)
                return (
                  <button
                    key={m.id}
                    className={`modechip ${on ? 'on' : ''} ${m.available ? '' : 'soon'}`}
                    onClick={() => modes.toggle(m.id)}
                    disabled={!m.available}
                    aria-pressed={m.available ? on : undefined}
                    title={m.available ? `${m.note} (${m.region})`
                                       : `${m.note} (${m.region}) - not yet available`}
                  >
                    {on ? <Check size={13} aria-hidden="true" />
                        : <Icon size={13} aria-hidden="true" />}
                    <span>{m.name}</span>
                    {!m.available && <span className="modesoon">soon</span>}
                  </button>
                )
              })}
            </div>
          </div>
        ))}
        <button className="modemore" onClick={() => setShowAll(!showAll)} aria-expanded={showAll}>
          <ChevronDown size={13} aria-hidden="true"
            className={`modemorechev ${showAll ? 'up' : ''}`} />
          {showAll ? 'Hide what is coming' : `${coming} more cities coming`}
        </button>
      </div>
    </div>
  )
}
