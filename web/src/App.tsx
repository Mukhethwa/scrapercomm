import { useState } from 'react'
import PlanView from './PlanView'
import RouteBrowser from './RouteBrowser'

export default function App() {
  const [tab, setTab] = useState<'plan' | 'browse'>('plan')
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
          <button className={`tab ${tab === 'browse' ? 'active' : ''}`} onClick={() => setTab('browse')}>
            Browse routes
          </button>
        </nav>
        <div className="sub">Cape Town bus timetables and trip planner</div>
      </header>
      {tab === 'plan' ? <PlanView /> : <RouteBrowser />}
    </div>
  )
}
