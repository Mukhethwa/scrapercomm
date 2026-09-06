/**
 * When the rider wants to leave.
 *
 * This filters nothing away. It reorders: departures at or after the chosen time come
 * first, the rest follow behind. A rider who picks 17:00 and is shown an empty card
 * cannot tell whether the buses have stopped for the day or the app has hidden them,
 * and the second is a far more common reason for an empty screen than the first.
 *
 * The time is the rider's own clock, not the server's. Timetables are published in local
 * time and the app is used in the city it describes, so "now" is the browser's now.
 */
import { useEffect, useRef, useState } from 'react'
import { ChevronDown } from 'lucide-react'

/** Minutes past midnight, as the timetable counts them. */
export function nowMinutes(): number {
  const d = new Date()
  return d.getHours() * 60 + d.getMinutes()
}

export function hhmm(minutes: number): string {
  const h = Math.floor(minutes / 60) % 24
  const m = minutes % 60
  return `${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}`
}

/** Half-hours across the service day. Buses run from before 05:00 to after 22:00. */
const CHOICES = Array.from({ length: 40 }, (_, i) => 4 * 60 + i * 30)

export default function LeaveAt({ value, onChange }:
  { value: number | null; onChange: (m: number | null) => void }) {
  const [open, setOpen] = useState(false)
  const box = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!open) return
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') setOpen(false) }
    const onDown = (e: MouseEvent) => {
      if (box.current && !box.current.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener('keydown', onKey)
    document.addEventListener('mousedown', onDown)
    return () => {
      document.removeEventListener('keydown', onKey)
      document.removeEventListener('mousedown', onDown)
    }
  }, [open])

  const label = value == null ? 'Any time' : `${hhmm(value)} (Today)`

  return (
    <div className="flex items-center justify-between gap-3" ref={box}>
      <span className="text-[13px] font-medium text-sub">Leave At</span>
      <div className="relative">
        <button
          className="inline-flex cursor-pointer items-center gap-1 rounded-full bg-accent-soft px-3.5 py-1.5 text-[13px] font-semibold text-accent"
          onClick={() => setOpen(!open)}
          aria-expanded={open}
          aria-haspopup="listbox"
        >
          {label}
          <ChevronDown size={14} aria-hidden="true"
            className={`transition-transform ${open ? 'rotate-180' : ''}`} />
        </button>

        {open && (
          <div
            className="absolute right-0 z-40 mt-2 max-h-72 w-44 overflow-y-auto rounded-xl border border-line bg-panel py-1 shadow-lg"
            role="listbox"
          >
            <button
              role="option"
              aria-selected={value == null}
              className={`w-full cursor-pointer px-4 py-2 text-left text-[13px] font-semibold ${
                value == null ? 'text-accent' : 'text-ink hover:bg-black/5'}`}
              onClick={() => { onChange(null); setOpen(false) }}
            >
              Any time
            </button>
            <button
              role="option"
              aria-selected={false}
              className="w-full cursor-pointer px-4 py-2 text-left text-[13px] font-semibold text-ink hover:bg-black/5"
              onClick={() => { onChange(nowMinutes()); setOpen(false) }}
            >
              Leave now
            </button>
            <div className="my-1 border-t border-line" />
            {CHOICES.map((m) => (
              <button
                key={m}
                role="option"
                aria-selected={value === m}
                className={`w-full cursor-pointer px-4 py-2 text-left text-[13px] ${
                  value === m ? 'font-bold text-accent' : 'text-ink hover:bg-black/5'}`}
                onClick={() => { onChange(m); setOpen(false) }}
              >
                {hhmm(m)}
              </button>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
