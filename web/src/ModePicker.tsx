import { Bus, Check, TrainFront } from 'lucide-react'
import { MODES, useModes } from './modes'

const ICON: Record<string, typeof Bus> = {
  gabs: Bus,
  myciti: Bus,
  metrorail: TrainFront,
}

/**
 * Which transport to plan with.
 *
 * The ones with no data behind them are shown greyed rather than hidden, so a rider
 * looking for a train can see the app does not have trains yet instead of assuming they
 * searched wrongly. They are real buttons but disabled, which is what tells a screen
 * reader the same thing.
 */
export default function ModePicker() {
  const modes = useModes()
  return (
    <div className="modepicker">
      <span className="modelbl">Transport</span>
      <div className="modelist">
        {MODES.map((m) => {
          const Icon = ICON[m.id] ?? Bus
          const on = modes.has(m.id)
          return (
            <button
              key={m.id}
              className={`modechip ${on ? 'on' : ''} ${m.available ? '' : 'soon'}`}
              onClick={() => modes.toggle(m.id)}
              disabled={!m.available}
              aria-pressed={m.available ? on : undefined}
              title={m.note}
            >
              {on ? <Check size={13} aria-hidden="true" /> : <Icon size={13} aria-hidden="true" />}
              <span>{m.name}</span>
              {!m.available && <span className="modesoon">soon</span>}
            </button>
          )
        })}
      </div>
    </div>
  )
}
