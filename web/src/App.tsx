import { useState } from 'react'
import PlanView from './PlanView'
import PlannerView from './PlannerView'
import RouteBrowser from './RouteBrowser'
import { usePlanner } from './planner'

type Tab = 'plan' | 'planner' | 'browse'

export default function App() {
  const [tab, setTab] = useState<Tab>('plan')
  // Read here purely for the badge; the count updates the moment a journey is added
  // on the search tab, because usePlanner listens for the change event.
  const { journeys } = usePlanner()

  return (
    <div className="app">
      <header className="topbar">
        <div className="brand" aria-label="commuttr">
          commuttr<span className="flare">.</span>
        </div>
        <nav className="tabs">
          <button className={`tab ${tab === 'plan' ? 'active' : ''}`} onClick={() => setTab('plan')}>
            Plan a trip
          </button>
          <button className={`tab ${tab === 'planner' ? 'active' : ''}`} onClick={() => setTab('planner')}>
            Planner
            {journeys.length > 0 && <span className="tabbadge">{journeys.length}</span>}
          </button>
          <button className={`tab ${tab === 'browse' ? 'active' : ''}`} onClick={() => setTab('browse')}>
            Browse routes
          </button>
        </nav>
        <div className="sub">Cape Town bus timetables and trip planner</div>
      </header>
      {/*
        * PlanView stays mounted and is hidden with CSS rather than unmounted. The whole
        * point of the planner is to bounce between searching and reviewing, and
        * unmounting threw away the search — the stops, the results, the map — every
        * time. The other two views are cheap to rebuild and read their state fresh.
        */}
      <div className={tab === 'plan' ? 'viewhost' : 'viewhost hiddenview'}>
        <PlanView />
      </div>
      {tab === 'planner' && <PlannerView onBrowse={() => setTab('plan')} />}
      {tab === 'browse' && <RouteBrowser />}
    </div>
  )
}
