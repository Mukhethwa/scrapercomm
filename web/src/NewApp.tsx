/**
 * The operator-grouped app: light header, two tabs at the foot, everything else behind
 * the profile menu.
 *
 * Kept beside the original shell rather than replacing it, so the working app stays
 * working while this one is judged against it. App.tsx decides which runs.
 *
 * There is no "Saved" tab. The design has one, but saving a journey to come back to
 * means knowing who is asking, and there are no accounts yet - so it would be a tab that
 * forgets everything the moment the browser does. It arrives with sign-in.
 */
import { useEffect, useRef, useState } from 'react'
import { CalendarDays, MapPin, User } from 'lucide-react'
import PlanScreen from './PlanScreen'
import PlannerView from './PlannerView'
import RouteBrowser from './RouteBrowser'
import ModePicker from './ModePicker'
import { usePlanner } from './planner'

type Tab = 'plan' | 'planner'
type Panel = 'browse' | 'settings' | null

const TABS: { id: Tab; label: string; icon: typeof MapPin }[] = [
  { id: 'plan', label: 'Plan Trip', icon: MapPin },
  { id: 'planner', label: 'Planner', icon: CalendarDays },
]

export default function NewApp({ onLeave }: { onLeave: () => void }) {
  const [tab, setTab] = useState<Tab>('plan')
  const [menu, setMenu] = useState(false)
  const [panel, setPanel] = useState<Panel>(null)
  const menuBox = useRef<HTMLDivElement>(null)
  const { journeys } = usePlanner()

  useEffect(() => {
    if (!menu) return
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') setMenu(false) }
    const onDown = (e: MouseEvent) => {
      if (menuBox.current && !menuBox.current.contains(e.target as Node)) setMenu(false)
    }
    document.addEventListener('keydown', onKey)
    document.addEventListener('mousedown', onDown)
    return () => {
      document.removeEventListener('keydown', onKey)
      document.removeEventListener('mousedown', onDown)
    }
  }, [menu])

  return (
    <div className="flex h-full flex-col bg-bg">
      <header className="flex items-center justify-between bg-black px-4 py-3 text-white">
        <button
          className="group inline-flex cursor-pointer items-baseline text-[20px] leading-none font-bold tracking-[-0.02em] text-white"
          onClick={() => setTab('plan')}
          aria-label="Commuttr home"
        >
          Commuttr
          <span className="ml-0.5 text-accent transition-transform group-hover:scale-135">.</span>
        </button>

        <div className="relative" ref={menuBox}>
          <button
            className="flex h-9 w-9 cursor-pointer items-center justify-center rounded-full bg-white/12 text-white hover:bg-white/20"
            onClick={() => setMenu(!menu)}
            aria-expanded={menu}
            aria-haspopup="menu"
            aria-label="Menu"
          >
            <User size={18} aria-hidden="true" />
          </button>
          {menu && (
            <div className="absolute right-0 z-50 mt-2 w-56 overflow-hidden rounded-xl border border-line bg-panel shadow-lg"
              role="menu">
              <button role="menuitem"
                className="w-full cursor-pointer px-4 py-3 text-left text-[13px] font-semibold text-ink hover:bg-black/5"
                onClick={() => { setPanel('browse'); setMenu(false) }}>
                Browse routes
              </button>
              <button role="menuitem"
                className="w-full cursor-pointer px-4 py-3 text-left text-[13px] font-semibold text-ink hover:bg-black/5"
                onClick={() => { setPanel('settings'); setMenu(false) }}>
                Transport settings
              </button>
              <div className="border-t border-line" />
              {/* The way back to the original layout, while both exist. */}
              <button role="menuitem"
                className="w-full cursor-pointer px-4 py-3 text-left text-[13px] font-semibold text-sub hover:bg-black/5"
                onClick={() => { onLeave(); setMenu(false) }}>
                Switch to classic view
              </button>
            </div>
          )}
        </div>
      </header>

      <div className={tab === 'plan' ? 'flex min-h-0 flex-1 flex-col' : 'hidden'}>
        <PlanScreen />
      </div>
      {tab === 'planner' && (
        <div className="min-h-0 flex-1 overflow-y-auto">
          <PlannerView onBrowse={() => setTab('plan')} />
        </div>
      )}

      {panel && (
        <div className="fixed inset-0 z-50 flex items-end justify-center bg-black/40"
          onClick={() => setPanel(null)} role="dialog" aria-modal="true">
          <div className="max-h-[85vh] w-full max-w-lg overflow-y-auto rounded-t-2xl bg-panel p-4"
            onClick={(e) => e.stopPropagation()}>
            <div className="mb-3 flex items-center justify-between">
              <div className="text-[15px] font-bold text-ink">
                {panel === 'browse' ? 'Browse routes' : 'Transport settings'}
              </div>
              <button className="cursor-pointer text-[13px] font-semibold text-accent"
                onClick={() => setPanel(null)}>Done</button>
            </div>
            {panel === 'browse' ? <RouteBrowser /> : <ModePicker />}
          </div>
        </div>
      )}

      <nav className="flex shrink-0 border-t border-line bg-panel">
        {TABS.map((t) => {
          const Icon = t.icon
          const on = tab === t.id
          return (
            <button
              key={t.id}
              className={`flex flex-1 cursor-pointer flex-col items-center gap-0.5 py-2.5 text-[11px] font-semibold ${
                on ? 'text-accent' : 'text-sub'}`}
              onClick={() => setTab(t.id)}
              aria-current={on ? 'page' : undefined}
            >
              <span className="relative">
                <Icon size={19} aria-hidden="true" />
                {t.id === 'planner' && journeys.length > 0 && (
                  <span className="absolute -top-1.5 -right-2 min-w-[16px] rounded-full bg-accent px-1 text-[10px] leading-4 font-bold text-white">
                    {journeys.length}
                  </span>
                )}
              </span>
              {t.label}
            </button>
          )
        })}
      </nav>
    </div>
  )
}
