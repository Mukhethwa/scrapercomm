/**
 * The trip planner, grouped by operator.
 *
 * Same search as the original view - it runs on the same hook - but the answer is drawn
 * differently: one card per operator, departures running sideways inside it. Tapping a
 * departure opens the trip breakdown, which is what a rider wants at that moment; the
 * map is a separate thing they can ask for.
 */
import { useMemo, useState } from 'react'
import {
  ArrowUpDown, ChevronDown, CircleX, Info, Lightbulb, Map as MapIcon, TriangleAlert, X,
} from 'lucide-react'
import { usePlanSearch, type Hit } from './usePlanSearch'
import { MODES } from './modes'
import {
  groupByOperator, fromTime, alightOrNone, DAY_LABEL, type DepartureBlock,
} from './results'
import OperatorCard from './OperatorCard'
import LeaveAt, { hhmm, nowMinutes } from './LeaveAt'
import PlanMap from './PlanMap'
import TripStrip from './TripStrip'
import ConnectionsCard, { connectionsFrom } from './ConnectionsCard'
import { PinIcon } from './icons'

/** "996 m", "3.6 km" - whichever a rider would actually say for that distance. */
function away(km: number): string {
  return km < 1 ? `${Math.round(km * 1000)} m` : `${km.toFixed(1)} km`
}

/** A coloured strip carrying one fact about the search as a whole. */
function Banner({ tone, icon: Icon, children }: {
  tone: 'info' | 'warn' | 'bad'
  icon: typeof Info
  children: React.ReactNode
}) {
  const skin = {
    info: 'bg-panel text-ink shadow-sm',
    warn: 'bg-accent text-white',
    bad: 'bg-bad text-white',
  }[tone]
  return (
    <div className={`flex items-start gap-2 rounded-xl px-3 py-2.5 text-[13px] ${skin}`}>
      <Icon size={16} aria-hidden="true" className="mt-px shrink-0" />
      <span>{children}</span>
    </div>
  )
}

/** A stop near the destination, and how much easier it is to reach. */
interface NearStop { id: number; name: string; km: number; change: boolean; lat: number | null; lon: number | null }

/**
 * Stops near the destination worth going to instead.
 *
 * A stop's name is not its area: somebody who asks for KHAYELITSHA is told it needs three
 * buses, because no route lists a stop by that name - while SITE C, MAKHAZA and HARARE
 * are all Khayelitsha and one bus away. Answering the letter of the question and hiding
 * the better journey helps nobody.
 */
function NearbyBox({ title, tone, stops, onPick }: {
  title: React.ReactNode
  tone: 'suggest' | 'plain'
  stops: NearStop[]
  onPick: (s: NearStop) => void
}) {
  return (
    <div className={`rounded-2xl p-4 ${tone === 'suggest' ? 'bg-accent text-white' : 'bg-panel shadow-sm'}`}>
      <div className="mb-3 flex items-start gap-2 text-[13px]">
        {tone === 'suggest' && <Lightbulb size={15} aria-hidden="true" className="mt-px shrink-0" />}
        <span>{title}</span>
      </div>
      <div className="grid gap-2 sm:grid-cols-2">
        {stops.map((r) => (
          <button
            key={r.id}
            className="flex cursor-pointer flex-col items-start gap-0.5 rounded-xl bg-panel px-3 py-2.5 text-left hover:ring-1 hover:ring-accent"
            onClick={() => onPick(r)}
          >
            <span className="text-[13px] font-bold text-ink">{r.name}</span>
            <span className="text-[11px] text-sub">
              {away(r.km)} away - {r.change ? '2 buses' : 'direct'}
            </span>
          </button>
        ))}
      </div>
    </div>
  )
}

/** How many departures the carousel holds before the rest go behind "View full day". */
const CAROUSEL = 8

function Field({ label, value, onChange, onFocus, onBlur, hits, open, onPick, onClear, disabled }: {
  label: string
  value: string
  onChange: (v: string) => void
  onFocus: () => void
  onBlur: () => void
  hits: Hit[]
  open: boolean
  onPick: (h: Hit) => void
  onClear: () => void
  disabled?: boolean
}) {
  return (
    <div className="relative flex-1">
      <div className="flex items-center gap-2 rounded-xl bg-bg px-3 py-2.5">
        <span className="shrink-0"><PinIcon size={15} /></span>
        <input
          className="min-w-0 flex-1 bg-transparent text-[14px] text-ink outline-none placeholder:text-sub disabled:cursor-not-allowed"
          placeholder={label}
          value={value}
          disabled={disabled}
          onChange={(e) => onChange(e.target.value)}
          onFocus={onFocus}
          onBlur={onBlur}
          onKeyDown={(e) => { if (e.key === 'Escape') (e.target as HTMLInputElement).blur() }}
          aria-label={label}
        />
        {value && !disabled && (
          <button className="shrink-0 cursor-pointer rounded p-0.5 text-sub hover:text-ink"
            onMouseDown={(e) => { e.preventDefault(); onClear() }}
            aria-label={`Clear ${label}`}>
            <X size={15} aria-hidden="true" />
          </button>
        )}
      </div>

      {/* Rendered only while the field has focus, so a search that resolves after the
          rider has moved on cannot pop the menu open again.
          
          mousedown only calls preventDefault - that stops the field blurring, which is
          what would otherwise unmount this menu before the click landed. Choosing then
          happens on click, so Enter and Space work too. Picking on mousedown instead
          left the list dead to anyone not using a mouse. */}
      {open && hits.length > 0 && (
        <div className="absolute top-full right-0 left-0 z-40 mt-1 max-h-64 overflow-y-auto rounded-xl border border-line bg-panel py-1 shadow-lg">
          {hits.map((h, i) => (
            <button
              key={`${h.kind}-${h.id ?? h.name}-${i}`}
              className="flex w-full cursor-pointer flex-col items-start gap-0.5 px-3 py-2 text-left hover:bg-black/5"
              onMouseDown={(e) => e.preventDefault()}
              onClick={() => onPick(h)}
              aria-label={h.sub ? `${h.name}, ${h.sub}` : h.name}
            >
              <span className="flex items-center gap-1.5">
                <span className="rounded bg-ink px-1 text-[9px] font-bold tracking-wide text-white uppercase">
                  {h.kind}
                </span>
                <span className="text-[13px] font-semibold text-ink">{h.name}</span>
              </span>
              {h.sub && <span className="line-clamp-1 text-[11px] text-sub">{h.sub}</span>}
            </button>
          ))}
        </div>
      )}
    </div>
  )
}

export default function PlanScreen() {
  const s = usePlanSearch()
  /**
   * Departures that have already gone are not choices, so the screen opens on the clock.
   * A rider standing at a stop means "the next bus" by default; somebody planning
   * tomorrow is one tap from "Any time".
   */
  const [leaveAt, setLeaveAt] = useState<number | null>(() => nowMinutes())
  const [showMap, setShowMap] = useState(false)
  /** Which operator's card to show. Null is "All". */
  const [only, setOnly] = useState<string | null>(null)

  const groups = useMemo(() => groupByOperator(s.plan ?? []), [s.plan])
  /** Connections whose first bus could still be caught at the chosen time. */
  const liveConns = useMemo(
    () => (s.conns ? connectionsFrom(s.conns, leaveAt) : null),
    [s.conns, leaveAt],
  )
  const shownGroups = only ? groups.filter((g) => g.id === only) : groups
  const openKey = s.openDep ? `${s.openDep.oi}-${s.openDep.di}` : null
  const openDeparture = s.openDep ? s.plan?.[s.openDep.oi]?.departures[s.openDep.di] : undefined

  function isPlanned(b: DepartureBlock) {
    const d = b.departure
    return s.planner.has({
      scheduleId: d.schedule_id, tripIndex: d.trip_index,
      fromSeq: d.from_seq, toSeq: d.to_seq,
    })
  }

  function add(b: DepartureBlock) {
    const option = s.plan?.[b.optionIndex]
    if (option) s.togglePlanned(option, b.departure)
  }

  /** Tapping a time asks "which bus is this, where do I get off" - not "show me a map". */
  function open(b: DepartureBlock) {
    s.selectDep(b.optionIndex, b.departureIndex, b.departure)
  }

  return (
    <div className="mx-auto flex w-full max-w-lg flex-1 flex-col gap-3 overflow-y-auto p-3">
      {/* Search. The swap sits outside the two fields, against their shared left edge,
          because it acts on both of them and belongs to neither. */}
      <div className="flex items-center gap-2">
        <button
          className="shrink-0 cursor-pointer rounded-lg p-2 text-ink hover:bg-black/5 disabled:opacity-35"
          onClick={s.swapEnds}
          disabled={!s.from || !s.to}
          aria-label="Swap starting point and destination"
        >
          <ArrowUpDown size={18} aria-hidden="true" />
        </button>
        <div className="flex min-w-0 flex-1 flex-col gap-2">
          <Field
            label="Starting point"
            value={s.fromText}
            onChange={s.setFromText}
            onFocus={() => s.setFromOpen(true)}
            onBlur={() => s.setFromOpen(false)}
            hits={s.fromHits}
            open={s.fromOpen}
            onPick={(h) => s.choose(h, s.pickFrom)}
            onClear={s.clearFrom}
          />
          <Field
            label={s.from ? 'Destination' : 'Choose a starting point first'}
            value={s.toText}
            onChange={s.setToText}
            onFocus={() => s.setToOpen(true)}
            onBlur={() => s.setToOpen(false)}
            hits={s.toHits}
            open={s.toOpen}
            onPick={(h) => s.choose(h, s.pickTo)}
            onClear={s.clearTo}
            disabled={!s.from}
          />
        </div>
      </div>

      <LeaveAt value={leaveAt} onChange={setLeaveAt} />

      {/* Operator filter. The ones with no data behind them stay listed and disabled -
          a rider looking for a train should learn the app has none yet, rather than
          assume they searched wrongly. Same reasoning as the old ModePicker. */}
      <div className="-mx-3 flex gap-2 overflow-x-auto px-3 pb-1">
        <button
          className={`shrink-0 cursor-pointer rounded-full border px-4 py-1.5 text-[13px] font-semibold ${
            only === null ? 'border-ink bg-ink text-white' : 'border-line bg-panel text-ink'
          }`}
          onClick={() => setOnly(null)}
          aria-pressed={only === null}
        >
          All
        </button>
        {MODES.filter((m) => m.available || m.id === 'myciti' || m.id === 'metrorail').map((m) => (
          <button
            key={m.id}
            className={`shrink-0 rounded-full border px-4 py-1.5 text-[13px] font-semibold ${
              only === m.id ? 'border-ink bg-ink text-white' : 'border-line bg-panel text-ink'
            } ${m.available ? 'cursor-pointer' : 'cursor-not-allowed opacity-45'}`}
            onClick={() => m.available && setOnly(m.id)}
            disabled={!m.available}
            aria-pressed={m.available ? only === m.id : undefined}
            title={m.available ? m.note : `${m.note} - not yet available`}
          >
            {m.name}
          </button>
        ))}
      </div>

      {s.pickError && (
        <div className="rounded-xl bg-accent-soft px-3 py-2 text-[13px] text-ink">{s.pickError}</div>
      )}

      {s.loading && <div className="py-8 text-center text-[13px] text-sub">Finding buses…</div>}

      {!s.from && !s.loading && (
        <div className="py-8 text-center text-[13px] text-sub">
          Search a stop or place to start planning.
        </div>
      )}

      {/*
        * Where you can get to from here, before a destination is chosen.
        *
        * Without it the screen is two empty boxes, and a rider has to already know the
        * name of a stop for anything to happen. This list answers "I am here - where can
        * this take me", which is how somebody who does not know the network starts.
        */}
      {s.stage === 'reachable' && (
        <div className="rounded-2xl bg-panel p-4 shadow-sm">
          <div className="mb-1 text-[14px] font-bold text-ink">
            {s.reachable == null
              ? 'Finding destinations…'
              : <>You can reach {s.filteredReach.length} stop{s.filteredReach.length === 1 ? '' : 's'} from{' '}
                  <span className="text-accent">{s.from!.name}</span> on one bus</>}
          </div>
          <div className="mb-3 text-[12px] text-sub">
            Tap one, or type any stop or place above.
          </div>
          <div className="flex flex-col gap-1">
            {s.filteredReach.slice(0, 40).map((r) => (
              <button
                key={r.id}
                className="flex cursor-pointer items-center justify-between gap-2 rounded-xl bg-bg px-3 py-2.5 text-left hover:bg-accent-soft"
                onClick={() => s.pickTo({ kind: 'stop', id: r.id, name: r.name, lat: r.lat!, lon: r.lon! })}
              >
                <span className="truncate text-[13px] font-semibold text-ink">{r.name}</span>
                <span className="shrink-0 text-[11px] text-sub">{r.trip_count} trips</span>
              </button>
            ))}
            {s.reachable != null && s.filteredReach.length === 0 && (
              <div className="py-4 text-center text-[13px] text-sub">
                No direct bus goes to “{s.toText}” from here.
              </div>
            )}
          </div>
        </div>
      )}

      {/* Above the results, not below them. A shorter journey is only useful before the
          rider has read and chosen from the long one. */}
      {!s.loading && !s.connLoading && s.betterNearby.length > 0 && s.bestLegs < Infinity && (
        <NearbyBox
          tone="suggest"
          title={<><b>Suggestion.</b> {s.to!.name} needs {s.bestLegs} bus{s.bestLegs === 1 ? '' : 'es'}, but these stops nearby are quicker to reach.</>}
          stops={s.betterNearby as unknown as NearStop[]}
          onPick={(r) => s.pickTo({ kind: 'stop', id: r.id, name: r.name, lat: r.lat!, lon: r.lon! })}
        />
      )}

      {s.plan && !s.loading && s.plan.length === 0 && s.connLoading && (
        <Banner tone="info" icon={Info}>
          No direct bus. Looking for a journey with a change...
        </Banner>
      )}

      {/* There is a way there, it just takes changes. The panel prices the whole thing and
          shows the wait between each leg, which is what decides whether a three-bus
          journey is worth making at all. */}
      {s.plan && !s.loading && s.plan.length === 0 && !s.connLoading && liveConns && liveConns.length > 0 && (
        <>
          <Banner tone="warn" icon={TriangleAlert}>
            <b>No direct bus</b> from {s.from!.name} to {s.to!.name}. You can still get there by taking{' '}
            <b>{s.connLegs} buses</b>, changing at <b>{liveConns[0].change_at.join(' then ')}</b>.
          </Banner>
          <ConnectionsCard connections={liveConns} legsRequired={s.connLegs} />
        </>
      )}

      {/* There is a way there, but not any more today. Saying so beats both an empty
          screen and a journey whose first bus finished this morning. */}
      {s.plan && !s.loading && s.plan.length === 0 && !s.connLoading
        && s.conns && s.conns.length > 0 && liveConns && liveConns.length === 0 && (
        <Banner tone="warn" icon={TriangleAlert}>
          <b>No direct bus</b> from {s.from!.name} to {s.to!.name}, and the {s.connLegs}-bus
          journey through <b>{s.conns[0].change_at.join(' then ')}</b> has finished for today.
          Choose an earlier time, or “Any time”, to see how it runs.
        </Banner>
      )}

      {s.plan && !s.loading && s.plan.length === 0 && !s.connLoading && s.conns && s.conns.length === 0 && (
        <Banner tone="bad" icon={CircleX}>
          <b>No way to get there by bus.</b> There is no direct service from {s.from!.name} to{' '}
          {s.to!.name}, and no combination of up to three buses connects them either.
        </Banner>
      )}

      {s.plan && !s.loading && s.plan.length === 0 && !s.connLoading && s.conns
        && s.conns.length === 0 && s.nearbyAlternatives.length > 0 && (
        <NearbyBox
          tone="plain"
          title={<>You can reach these stops near <b>{s.to!.name}</b></>}
          stops={s.nearbyAlternatives as unknown as NearStop[]}
          onPick={(r) => s.pickTo({ kind: 'stop', id: r.id, name: r.name, lat: r.lat!, lon: r.lon! })}
        />
      )}

      {/* A dropped pin has no stop id, and the connections engine can only join named
          stops - so this is a limit of the question, not of the network. */}
      {s.plan && !s.loading && s.plan.length === 0 && !s.connLoading && s.conns === null && (
        <Banner tone="bad" icon={CircleX}>
          <b>No direct bus.</b> Journeys with a change can only be worked out between named
          bus stops, not dropped pins.
        </Banner>
      )}

      {shownGroups.map((g) => {
        const still = fromTime(g.blocks, leaveAt)
        return (
          <div key={g.id} className="flex flex-col gap-1">
            {leaveAt != null && still.length === 0 && (
              <div className="px-1 text-[12px] text-sub">
                Nothing leaves after {hhmm(leaveAt)} today. Pick an earlier time, or “Any
                time”, to see the rest of the day.
              </div>
            )}
            <OperatorCard
              group={g}
              shown={still.slice(0, CAROUSEL)}
              all={still}
              openKey={openKey}
              isPlanned={isPlanned}
              onAdd={add}
              onOpen={open}
            />
          </div>
        )
      })}

      {/* Nothing runs today, but something runs on Saturday - or from a stop up the road.
          Worth saying: the alternative is a rider concluding the journey is impossible. */}
      {s.plan && !s.loading && s.altDays.length > 0 && (
        <div className="rounded-2xl bg-panel p-4 shadow-sm">
          <div className="mb-3 text-[13px] font-bold text-ink">
            {s.plan.length
              ? 'On other days, the nearest stop with a direct bus:'
              : 'Nearest stops with a direct bus there:'}
          </div>
          {s.altDays.map((d) => (
            <div key={d} className="mb-3 last:mb-0">
              <div className="mb-1.5 text-[11px] font-bold tracking-[.05em] text-sub uppercase">
                {DAY_LABEL[d] ?? d}
              </div>
              <div className="flex flex-col gap-1">
                {s.dayAlts[d].map((o) => (
                  <button
                    key={o.id}
                    className="flex cursor-pointer flex-col items-start gap-0.5 rounded-xl bg-bg px-3 py-2.5 text-left hover:bg-accent-soft"
                    onClick={() => s.useAlt(o)}
                  >
                    <span className="text-[13px] font-semibold text-ink">{o.name}</span>
                    <span className="text-[11px] text-sub">
                      {(o.distance_m / 1000).toFixed(1)} km away
                      {o.earliest ? `, first bus ${o.earliest}` : ''}, {o.trip_count} trips
                    </span>
                  </button>
                ))}
              </div>
            </div>
          ))}
        </div>
      )}

      {s.plan && !s.loading && s.plan.length === 0 && s.altDays.length === 0 && !s.connLoading && (
        <div className="px-1 text-[12px] text-sub">
          No stop within 8 km has a direct bus there either.
        </div>
      )}

      {/* The trip breakdown: the whole bus run, the rider's own part picked out. */}
      {s.openDep && (
        <div className="rounded-2xl bg-panel p-3 shadow-sm">
          <TripStrip
            stops={s.tripStops}
            loading={s.loadingTrip}
            notes={s.tripNotes}
            riderFromSeq={openDeparture?.from_seq ?? 0}
            riderToSeq={openDeparture?.to_seq ?? 9999}
            boardPin={s.from?.kind === 'pin'
              ? { name: s.from.name, time: openDeparture?.board_raw } : null}
            alightPin={s.to?.kind === 'pin'
              ? { name: s.to.name, time: openDeparture?.arrive_raw } : null}
            boardTime={alightOrNone(openDeparture, 'board')}
            alightTime={alightOrNone(openDeparture, 'alight')}
            onClose={() => s.setOpenDep(null)}
          />
        </div>
      )}

      {/* The map is something a rider asks for, not something that takes half the screen.
          It matters when deciding where to stand, which is after the bus is chosen. */}
      {s.plan && s.plan.length > 0 && (
        <div className="rounded-2xl bg-panel p-3 shadow-sm">
          <button
            className="flex w-full cursor-pointer items-center justify-between text-[13px] font-semibold text-ink"
            onClick={() => setShowMap(!showMap)}
            aria-expanded={showMap}
          >
            <span className="flex items-center gap-2">
              <MapIcon size={16} aria-hidden="true" className="text-accent" />
              {showMap ? 'Hide map' : 'Show map'}
            </span>
            <ChevronDown size={16} aria-hidden="true"
              className={`transition-transform ${showMap ? 'rotate-180' : ''}`} />
          </button>
          {showMap && (
            <div className="mt-3 h-72 overflow-hidden rounded-xl">
              <PlanMap
                from={s.from} to={s.to} segment={s.segment} roadPath={s.roadPath}
                ride={s.ride} onMapClick={s.onMapClick}
              />
            </div>
          )}
        </div>
      )}
    </div>
  )
}
