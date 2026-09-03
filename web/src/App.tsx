import { useState } from 'react'
import PlanView from './PlanView'
import PlannerView from './PlannerView'
import RouteBrowser from './RouteBrowser'
import { usePlanner } from './planner'

type Tab = 'plan' | 'planner' | 'browse'

const TABS: { id: Tab; label: string }[] = [
  { id: 'plan', label: 'Plan a trip' },
  { id: 'planner', label: 'Planner' },
  { id: 'browse', label: 'Browse routes' },
]

export default function App() {
  const [tab, setTab] = useState<Tab>('plan')
  // Read here purely for the badge; the count updates the moment a journey is added
  // on the search tab, because usePlanner listens for the change event.
  const { journeys } = usePlanner()

  return (
    <div className="flex h-full flex-col">
      <header className="flex items-baseline gap-4 bg-black px-5 py-3 text-white">
        {/* commuttr. wordmark: all-lowercase, heavy, tight, with the orange period.
            font-size and weight are set here rather than inherited, because a button
            that only inherits its family shrinks to the surrounding text. */}
        <button
          className="group inline-flex cursor-pointer items-baseline text-[22px] leading-none font-bold tracking-[-0.03em] lowercase text-white"
          onClick={() => setTab('plan')}
          aria-label="commuttr home"
        >
          commuttr
          <span className="text-accent transition-transform group-hover:scale-135">.</span>
        </button>
        <nav className="ml-2 flex gap-1">
          {TABS.map((t) => (
            <button
              key={t.id}
              className={`cursor-pointer rounded-lg px-3.5 py-1.5 text-sm font-semibold text-white ${
                tab === t.id ? 'bg-accent-fill' : 'hover:bg-white/12'
              }`}
              onClick={() => setTab(t.id)}
            >
              {t.label}
              {t.id === 'planner' && journeys.length > 0 && (
                <span className="ml-1.5 rounded-full bg-white px-[7px] py-px text-[11px] font-bold text-accent">
                  {journeys.length}
                </span>
              )}
            </button>
          ))}
        </nav>
      </header>
      {/*
        * PlanView stays mounted and is hidden with CSS rather than unmounted. The whole
        * point of the planner is to bounce between searching and reviewing, and
        * unmounting threw away the search — the stops, the results, the map — every
        * time. The other two views are cheap to rebuild and read their state fresh.
        */}
      <div className={tab === 'plan' ? 'flex min-h-0 flex-1 flex-col' : 'hidden'}>
        <PlanView />
      </div>
      {tab === 'planner' && <PlannerView onBrowse={() => setTab('plan')} />}
      {tab === 'browse' && <RouteBrowser />}
    </div>
  )
}
