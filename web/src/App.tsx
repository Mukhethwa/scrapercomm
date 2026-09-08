import { useEffect, useRef, useState } from 'react'
import { Menu, X } from 'lucide-react'
import PlanView from './PlanView'
import PlannerView from './PlannerView'
import RouteBrowser from './RouteBrowser'
import { usePlanner } from './planner'
import NewApp from './NewApp'
import { usePinnedTheme } from './theme'

/**
 * Which layout to run.
 *
 * Two results layouts exist while the operator-grouped one is being judged against the
 * original. The choice is remembered so a reload does not throw the reviewer back to the
 * other one mid-comparison. When the new layout wins, this and the old view go together.
 */
const SHELL_KEY = 'commuttr:shell'

function readShell(): 'classic' | 'grouped' {
  try {
    return localStorage.getItem(SHELL_KEY) === 'grouped' ? 'grouped' : 'classic'
  } catch {
    return 'classic'
  }
}

type Tab = 'plan' | 'planner' | 'browse'

const TABS: { id: Tab; label: string }[] = [
  { id: 'plan', label: 'Plan a trip' },
  { id: 'planner', label: 'Planner' },
  { id: 'browse', label: 'Browse routes' },
]

/** The planner count, shown on a tab. */
function Badge({ n }: { n: number }) {
  if (!n) return null
  return (
    <span className="ml-1.5 rounded-full bg-white px-[7px] py-px text-[11px] font-bold text-accent">
      {n}
    </span>
  )
}

export default function App() {
  const [shell, setShell] = useState<'classic' | 'grouped'>(readShell)
  /**
   * The classic layout is held at light whatever the rider chose.
   *
   * Its stylesheet was written when there was one theme and carries 84 hard-coded whites,
   * so under the dark tokens it renders white cards with white text on them - not merely
   * off-brand, unreadable. Rewriting a stylesheet that is due to be deleted is the wrong
   * work; pinning the view is honest and costs nothing, and the pin lifts the moment the
   * new layout is showing.
   */
  usePinnedTheme(shell === 'classic' ? 'light' : null)
  const [tab, setTab] = useState<Tab>('plan')
  const [menuOpen, setMenuOpen] = useState(false)
  const menuBox = useRef<HTMLDivElement>(null)
  // Read here purely for the badge; the count updates the moment a journey is added
  // on the search tab, because usePlanner listens for the change event.
  const { journeys } = usePlanner()

  // A menu over the page has to close the ways a reader expects it to.
  useEffect(() => {
    if (!menuOpen) return
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') setMenuOpen(false) }
    const onDown = (e: MouseEvent) => {
      if (menuBox.current && !menuBox.current.contains(e.target as Node)) setMenuOpen(false)
    }
    document.addEventListener('keydown', onKey)
    document.addEventListener('mousedown', onDown)
    return () => {
      document.removeEventListener('keydown', onKey)
      document.removeEventListener('mousedown', onDown)
    }
  }, [menuOpen])

  function switchTo(next: 'classic' | 'grouped') {
    try { localStorage.setItem(SHELL_KEY, next) } catch { /* private window; this visit only */ }
    setShell(next)
  }

  if (shell === 'grouped') return <NewApp onLeave={() => switchTo('classic')} />

  return (
    <div className="flex h-full flex-col">
      <header className="flex items-baseline gap-2 bg-black px-3 py-2.5 text-white sm:gap-4 sm:px-5 sm:py-3">
        {/* commuttr. wordmark: all-lowercase, heavy, tight, with the orange period.
            font-size and weight are set here rather than inherited, because a button
            that only inherits its family shrinks to the surrounding text.

            It always returned home, but at 88x19 it was too small to hit with a thumb;
            -my-2 py-2 grows the tap target without moving the word. */}
        <button
          className="group -my-2 inline-flex shrink-0 cursor-pointer items-baseline py-2 pr-1 text-[19px] leading-none font-bold tracking-[-0.03em] lowercase text-white sm:text-[22px]"
          onClick={() => setTab('plan')}
          aria-label="commuttr home"
        >
          commuttr
          <span className="text-accent transition-transform group-hover:scale-135">.</span>
        </button>
        {/* Three tabs abreast fit from 640px up. Below that they used to scroll
            sideways, and the moment the planner badge appeared it widened "Planner"
            just enough to push "Browse routes" off the edge - a whole tab hidden
            behind a gesture nobody knows is there. Narrow screens get the menu
            instead, where every tab is visible at once. */}
        <nav className="ml-auto hidden gap-1 sm:ml-2 sm:mr-auto sm:flex">
          {TABS.map((t) => (
            <button
              key={t.id}
              className={`shrink-0 cursor-pointer rounded-lg px-2.5 py-1.5 text-[13px] font-semibold whitespace-nowrap text-white sm:px-3.5 sm:text-sm ${
                tab === t.id ? 'bg-accent-fill' : 'hover:bg-white/12'
              }`}
              onClick={() => setTab(t.id)}
            >
              {t.label}
              <Badge n={t.id === 'planner' ? journeys.length : 0} />
            </button>
          ))}
        </nav>

        <button
          className="ml-auto hidden shrink-0 cursor-pointer rounded-lg border border-white/25 px-2.5 py-1.5 text-[12px] font-semibold whitespace-nowrap text-white hover:bg-white/12 sm:inline-flex"
          onClick={() => switchTo('grouped')}
        >
          Try new layout
        </button>

        <div className="relative ml-auto sm:hidden" ref={menuBox}>
          <button
            className="flex h-11 w-11 shrink-0 cursor-pointer items-center justify-center self-center rounded-lg text-white hover:bg-white/12"
            onClick={() => setMenuOpen(!menuOpen)}
            aria-expanded={menuOpen}
            aria-haspopup="menu"
            aria-label={menuOpen ? 'Close menu' : 'Open menu'}
          >
            {menuOpen ? <X size={22} aria-hidden="true" /> : (
              <>
                <Menu size={22} aria-hidden="true" />
                {/* The badge rides the button while the menu is shut, so a rider who
                    has added journeys can see it without opening anything. */}
                {journeys.length > 0 && (
                  <span className="absolute top-1 right-1 min-w-[17px] rounded-full bg-accent-fill px-1 text-[10px] leading-[17px] font-bold text-white">
                    {journeys.length}
                  </span>
                )}
              </>
            )}
          </button>

          {menuOpen && (
            <div
              className="absolute right-0 z-40 mt-2 w-56 overflow-hidden rounded-xl border border-line bg-panel shadow-lg"
              role="menu"
            >
              {TABS.map((t) => (
                <button
                  key={t.id}
                  role="menuitem"
                  className={`flex w-full cursor-pointer items-center justify-between gap-2 px-4 py-3 text-left text-sm font-semibold ${
                    tab === t.id ? 'bg-accent-fill text-white' : 'text-ink hover:bg-black/5'
                  }`}
                  onClick={() => { setTab(t.id); setMenuOpen(false) }}
                >
                  <span>{t.label}</span>
                  {t.id === 'planner' && journeys.length > 0 && (
                    <span className={`min-w-[20px] rounded-full px-1.5 text-center text-[11px] font-bold ${
                      tab === t.id ? 'bg-white text-accent' : 'bg-ink text-white'
                    }`}>
                      {journeys.length}
                    </span>
                  )}
                </button>
              ))}
              {/* The way across to the other layout. It lives in this menu on a phone
                  for the same reason the tabs do: the header has room for a wordmark and
                  one control, and that control is the menu. Putting it only in the
                  desktop bar left the new layout unreachable on the device it was
                  designed for. */}
              <div className="border-t border-line" />
              <button
                role="menuitem"
                className="flex w-full cursor-pointer items-center justify-between gap-2 px-4 py-3 text-left text-sm font-semibold text-ink hover:bg-black/5"
                onClick={() => { switchTo('grouped'); setMenuOpen(false) }}
              >
                <span>Try new layout</span>
                <span className="rounded-full bg-accent px-1.5 text-[10px] font-bold tracking-wide text-white uppercase">
                  new
                </span>
              </button>
            </div>
          )}
        </div>
      </header>
      {/*
        * PlanView stays mounted and is hidden with CSS rather than unmounted. The whole
        * point of the planner is to bounce between searching and reviewing, and
        * unmounting threw away the search - the stops, the results, the map - every
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
