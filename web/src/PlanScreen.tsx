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
  ArrowsDownUp, CaretDown, XCircle, Info, Lightbulb, MapTrifold, Warning, X,
} from '@phosphor-icons/react'
import { usePlanSearch, type Hit } from './usePlanSearch'
import type { Connection } from './api'
import type { Pt } from './PlanMap'
import { MODES, useLoadedOperators } from './modes'
import {
  groupByOperator, fromTime, alightOrNone, blockKey, DAY_LABEL, type DepartureBlock,
} from './results'
import { pinEnd } from './pins'
import { stopLabel } from './stops'
import { clockFace, shortTime } from './times'
import OperatorCard from './OperatorCard'
import LeaveAt, { hhmm, nowMinutes } from './LeaveAt'
import PlanMap from './PlanMap'
import TripStrip from './TripStrip'
import FarePanel from './FarePanel'
import { plural } from './money'
import ConnectionsCard, { connectionsFrom } from './ConnectionsCard'
import { PinIcon } from './icons'

/**
 * What a rider is looking for as the vehicle arrives.
 *
 * On a bus that is the destination on the front, which is the last place its route names.
 * A train is not signed that way - PRASA labels a service by its line and direction, and
 * the platform indicator shows the line - so the line is what to look for.
 */
function vehicleSign(routeLabel: string, kind?: string): string {
  if (kind === 'train') {
    const line = routeLabel.replace(/\b(INBOUND|OUTBOUND)\b/i, '').trim()
    return line ? line.replace(/\s+/g, ' ') : routeLabel
  }
  // "T01 to Civic Centre" already says where it is going, and has no dash to split on.
  const own = routeLabel.match(/^(\S+) to (.+)$/)
  if (own) return routeLabel

  const parts = routeLabel.split(' - ').map((x) => x.trim()).filter(Boolean)
  return parts[parts.length - 1] ?? routeLabel
}

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
    <div className={`flex items-start gap-2 px-3 py-2.5 text-[13px] ${skin}`}>
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
function NearbyBox({ title, tone, stops, onPick, vehicle = 'bus' }: {
  title: React.ReactNode
  tone: 'suggest' | 'plain'
  stops: NearStop[]
  onPick: (s: NearStop) => void
  /** Bus or train, so a train rider is not offered "2 buses" to a station. */
  vehicle?: 'bus' | 'train'
}) {
  return (
    <div className={`p-4 ${tone === 'suggest' ? 'bg-accent text-white' : 'bg-panel shadow-sm'}`}>
      <div className="mb-3 flex items-start gap-2 text-[13px]">
        {tone === 'suggest' && <Lightbulb size={16} weight="fill" aria-hidden="true" className="mt-px shrink-0" />}
        <span>{title}</span>
      </div>
      <div className="grid gap-2 sm:grid-cols-2">
        {stops.map((r) => (
          <button
            key={r.id}
            className="flex cursor-pointer flex-col items-start gap-0.5 bg-panel px-3 py-2.5 text-left hover:ring-1 hover:ring-accent"
            onClick={() => onPick(r)}
          >
            <span className="text-[13px] font-bold text-ink">{r.name}</span>
            <span className="text-[11px] text-sub">
              {away(r.km)} away - {r.change ? `2 ${plural(vehicle)}` : 'direct'}
            </span>
          </button>
        ))}
      </div>
    </div>
  )
}

/** How many departures the carousel holds before the rest go behind "View full day". */
const CAROUSEL = 8

/**
 * A walk, as somebody would say it.
 *
 * Rounded to the nearest fifty metres under a kilometre and one decimal above, because a
 * distance measured straight-line to the nearest metre is precision the number does not
 * have - the pavement is longer than the crow flies.
 */
function walkAway(metres: number): string {
  if (metres >= 1000) return `${(metres / 1000).toFixed(1)} km walk`
  return `${Math.round(metres / 50) * 50} m walk`
}

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
      <div className="flex items-center gap-2 border border-line bg-field px-3 py-2.5">
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
          <button className="shrink-0 cursor-pointer p-0.5 text-sub hover:text-ink"
            onMouseDown={(e) => { e.preventDefault(); onClear() }}
            aria-label={`Clear ${label}`}>
            <X size={15} weight="bold" aria-hidden="true" />
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
        <div className="absolute top-full right-0 left-0 z-40 mt-1 max-h-64 overflow-y-auto border border-line bg-panel py-1 shadow-lg">
          {hits.map((h, i) => (
            <button
              key={`${h.kind}-${h.id ?? h.name}-${i}`}
              className="flex w-full cursor-pointer flex-col items-start gap-0.5 px-3 py-2 text-left hover:bg-line/50"
              onMouseDown={(e) => e.preventDefault()}
              onClick={() => onPick(h)}
              aria-label={h.sub ? `${h.name}, ${h.sub}` : h.name}
            >
              <span className="flex items-center gap-1.5">
                {/* A stop says which mode it is, because two operators can name a place
                    the same way and mean two different corners of it: RETREAT the station
                    and RETREAT the bus stop are 800m apart. */}
                <span className="bg-ink px-1 text-[9px] font-bold tracking-wide text-onink uppercase">
                  {h.kind === 'stop' && h.mode ? h.mode : h.kind}
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
  /**
   * Which operator the screen is narrowed to. Null is "All".
   *
   * Declared before the search because the search takes it: the chip scopes what is
   * offered, not only what is shown. Choosing Metro Rail and still being offered a
   * Golden Arrow stop - whose journeys are then filtered away to an empty screen - is
   * the app disagreeing with itself.
   */
  const [only, setOnly] = useState<string | null>(null)
  const s = usePlanSearch(only)
  /**
   * Departures that have already gone are not choices, so the screen opens on the clock.
   * A rider standing at a stop means "the next bus" by default; somebody planning
   * tomorrow is one tap from "Any time".
   */
  const [leaveAt, setLeaveAt] = useState<number | null>(() => nowMinutes())
  const [showMap, setShowMap] = useState(false)
  /**
   * Which operators the API can plan with right now.
   *
   * The chips are pressable on this rather than on the static list, so Metrorail goes
   * live the moment its timetables load and not before. Nothing has to be redeployed to
   * turn it on, and nothing offers a rider a filter that returns an empty screen.
   */
  const operators = useLoadedOperators()

  /**
   * Bus or train, in the app's own sentences.
   *
   * Taken from where the rider is standing rather than from what came back, because these
   * lines are mostly written for the case where nothing came back. Telling somebody at
   * FISH HOEK station that "no bus goes there" is a true sentence about the wrong network,
   * and it reads as though the app has not understood the question.
   */
  /*
   * Bus or train, in the sentences on this screen.
   *
   * The chip first, then where the rider is standing. A place - "Buh-rein Drive" - is not
   * an operator's stop and carries no mode, so it fell through to bus and the screen said
   * "on one bus" with Metro Rail selected. If somebody has narrowed the screen to one
   * operator, that is the most explicit statement of intent available and it should win.
   */
  const chosen = only ? MODES.find((m) => m.id === only)?.kind : undefined
  const ride = (chosen ?? s.from?.mode) === 'train' ? 'train' : 'bus'
  const rides = plural(ride)

  /*
   * The same thing in a sentence, where nothing narrows it to one network.
   *
   * `ride` has to resolve to a single kind because the cards and icons take one, and it
   * falls back to bus when there is nothing to go on. In prose that fallback is a claim:
   * a place with no chip chosen told a rider "no way to get there by bus" when neither
   * network had been ruled out, and the trains were never mentioned at all.
   */
  const said = chosen ? ride : (s.from?.mode ?? 'bus or train')
  // "bus" pluralises to "buses", not "buss". The template made the plural by adding an
  // s to the kind, which is right for "trains" and wrong for the one it is used for most.
  const saids = chosen ? rides : (s.from?.mode ? plural(s.from.mode) : 'buses or trains')

  /*
   * What the destinations list actually reached, rather than a guess from the origin.
   *
   * The old sentence read the origin's own mode, so a place - which belongs to no
   * operator and carries no mode - always produced "on one bus". That was a guess that
   * happened to be a true sentence about part of the answer, which is the worst kind:
   * standing in Kraaifontein, the Northern Line runs past and the screen said bus, so
   * the trains looked like they did not exist. The rows themselves know, so they are
   * asked instead.
   */
  const reachRide = useMemo(() => {
    const kinds = new Set(s.filteredReach.map((r) => (r.operator_kind === 'train' ? 'train' : 'bus')))
    if (kinds.size > 1) return 'bus or train'
    return kinds.size === 1 ? [...kinds][0] : said
  }, [s.filteredReach, said])

  const groups = useMemo(() => groupByOperator(s.plan ?? []), [s.plan])
  /** The journey-with-changes the map should draw, when there is no direct one. */
  const [chosenConn, setChosenConn] = useState<Connection | null>(null)
  /** Connections whose first bus could still be caught at the chosen time. */
  /**
   * Which network the journey-with-a-change runs on, and whether the chip wants it.
   *
   * No stop in this database is served by both a bus route and a train route, so a
   * journey with a change never mixes them: the stop it changes at belongs to one
   * operator, and so does the whole journey. The API says which stop it resolved the
   * origin to, and that stop knows whose it is.
   *
   * Choosing Golden Arrow used to say "No bus goes from KRAAIFONTEIN" and then list
   * twenty-six Metrorail journeys underneath it, described as "2 buses". Two answers to
   * two different questions, on one screen, contradicting each other.
   */
  const connKind = s.connFrom?.operator_kind ?? ride
  // Whose journey it is, compared with whose chip is pressed. By company, not by kind:
  // MyCiTi and Golden Arrow are both buses, so a kind comparison shows one company's
  // journeys under the other's chip - which is the contradiction this check was added to
  // remove, wearing a third face.
  const connWanted = !only || (s.connFrom?.operator_code ?? 'gabs') === only

  const liveConns = useMemo(
    () => (s.conns ? connectionsFrom(s.conns, leaveAt) : null),
    [s.conns, leaveAt],
  )
  const shownGroups = only ? groups.filter((g) => g.id === only) : groups
  const openKey = s.openDep ? blockKey(s.openDep.oi, s.openDep.di) : null
  const openOption = s.openDep ? s.plan?.[s.openDep.oi] : undefined
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

  /**
   * Where you get on, where you change, and where you get off.
   *
   * A connection has no road geometry, so the map cannot draw the route it takes. It can
   * still draw the places, which is the question a rider actually has about a journey
   * with changes: where am I changing, and how far apart are those points.
   */
  const connSegment: Pt[] | undefined = useMemo(() => {
    if (!chosenConn || (s.plan && s.plan.length > 0)) return undefined
    const pts: Pt[] = chosenConn.legs.map((l, i) => ({
      name: l.from_name, lat: l.from_lat, lon: l.from_lon, stop_sequence: i + 1,
    }))
    const last = chosenConn.legs[chosenConn.legs.length - 1]
    if (last) {
      pts.push({
        name: last.to_name, lat: last.to_lat, lon: last.to_lon,
        stop_sequence: chosenConn.legs.length + 1,
      })
    }
    return pts.filter((p) => p.lat != null && p.lon != null)
  }, [chosenConn, s.plan])

  /** Tapping a time asks "which bus is this, where do I get off" - not "show me a map". */
  function open(b: DepartureBlock) {
    s.selectDep(b.optionIndex, b.departureIndex, b.departure)
  }

  /**
   * The map, declared once because two layouts show it.
   *
   * A phone folds it away behind a toggle, since the screen has room for one thing at a
   * time. A wide screen has room for both and gets it as a standing panel: a 512px column
   * of cards marooned in the middle of a monitor is not a layout, it is a phone screenshot.
   */
  const mapEl = (
    <PlanMap
      from={s.from} to={s.to}
      segment={connSegment ?? s.segment}
      roadPath={connSegment ? undefined : s.roadPath}
      ride={connSegment ? undefined : s.ride}
      onMapClick={s.onMapClick}
    />
  )
  const hasRoute = (s.plan && s.plan.length > 0) || (liveConns && liveConns.length > 0)

  return (
    <div className="mx-auto flex min-h-0 w-full max-w-6xl flex-1 gap-4 p-3">
      <div className={`mx-auto min-h-0 w-full max-w-lg min-w-0 flex-1 space-y-3 overflow-x-hidden overflow-y-auto ${hasRoute ? 'lg:mx-0 lg:max-w-none' : ''}`}>
      {/* Block layout with margins, not a column flex box. As a flex container this
          squashed its own children: flex items shrink by default, so the moment results
          overflowed, the operator chips were crushed to a sliver peeking out under the
          Leave At row instead of keeping their height and scrolling away like the rest. */}
      {/* Search. The swap sits outside the two fields, against their shared left edge,
          because it acts on both of them and belongs to neither. */}
      <div className="flex items-center gap-2">
        <button
          className="shrink-0 cursor-pointer p-2 text-ink hover:bg-line/50 disabled:opacity-35"
          onClick={s.swapEnds}
          disabled={!s.from || !s.to}
          aria-label="Swap starting point and destination"
        >
          <ArrowsDownUp size={20} weight="bold" aria-hidden="true" />
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

      {/* Operator filter. It scrolls inside the column rather than bleeding past it: the
          page padding moved to the outer wrapper when the desktop layout arrived, so the
          negative margin this used to carry had nothing left to bleed into and simply
          overhung the column, clipping the first chip and the Leave At label.

          The ones with no data behind them stay listed and disabled -
          a rider looking for a train should learn the app has none yet, rather than
          assume they searched wrongly. Same reasoning as the old ModePicker. */}
      <div className="flex gap-2 overflow-x-auto pb-1">
        <button
          className={`shrink-0 cursor-pointer border px-4 py-1.5 text-[13px] font-semibold ${
            only === null ? 'border-ink bg-ink text-onink' : 'border-line bg-panel text-ink'
          }`}
          onClick={() => setOnly(null)}
          aria-pressed={only === null}
        >
          All
        </button>
        {/* Only operators with data behind them. MyCiTi sat here greyed out for months
            on the reasoning that a rider should learn the app does not have it yet; that
            reasoning loses to a simpler one - a control that never does anything reads as
            a half-built app, and there is no MyCiTi row in the operator table at all. */}
        {MODES.filter((m) => m.available || m.id === 'metrorail').map((m) => {
          const ready = operators.ready(m.id)
          return (
            <button
              key={m.id}
              className={`shrink-0 border px-4 py-1.5 text-[13px] font-semibold ${
                only === m.id ? 'border-ink bg-ink text-onink' : 'border-line bg-panel text-ink'
              } ${ready ? 'cursor-pointer' : 'cursor-not-allowed opacity-45'}`}
              onClick={() => ready && setOnly(m.id)}
              disabled={!ready}
              aria-pressed={ready ? only === m.id : undefined}
              title={ready ? m.note : `${m.note} - not yet available`}
            >
              {m.name}
            </button>
          )
        })}
      </div>

      {s.pickError && (
        <div className="bg-accent-soft px-3 py-2 text-[13px] text-ink">{s.pickError}</div>
      )}

      {s.loading && <div className="py-8 text-center text-[13px] text-sub">Finding {saids}…</div>}

      {!s.from && !s.loading && !s.typingFrom && (
        <div className="py-8 text-center text-[13px] text-sub">
          Search for a place to start planning.
        </div>
      )}

      {/* Words in a box are not a destination.
          A rider typed "random place" and the screen answered "No direct bus or train
          goes to random place from here" - a statement about the network, about somewhere
          that does not exist. The app can only plan between places it knows, so when the
          text is not one of them it says what to do rather than inventing an answer. */}
      {(s.typingFrom || s.typingTo) && !s.loading && (
        <div className="border border-line bg-panel px-4 py-6 text-center">
          <div className="text-[13px] font-bold text-ink">
            Choose a place from the list
          </div>
          <div className="mt-1 text-[12px] text-sub">
            Commuttr plans between places it knows, so “{(s.typingFrom ? s.fromText : s.toText).trim()}”
            has to be picked from the suggestions as you type
            {only ? <> — and this one is narrowed to {operators.nameOf(only)}</> : null}.
          </div>
        </div>
      )}

      {/*
        * Where you can get to from here, before a destination is chosen.
        *
        * Without it the screen is two empty boxes, and a rider has to already know the
        * name of a stop for anything to happen. This list answers "I am here - where can
        * this take me", which is how somebody who does not know the network starts.
        */}
      {s.stage === 'reachable' && !s.typingTo && (
        <div className="border border-line bg-panel p-4">
          <div className="mb-1 text-[14px] font-bold text-ink">
            {s.reachable == null
              ? 'Finding destinations…'
              : <>You can reach {s.filteredReach.length} stop{s.filteredReach.length === 1 ? '' : 's'} from{' '}
                  <span className="text-accent">{s.from!.name}</span>{' '}
                  on one {reachRide}</>}
          </div>
          <div className="mb-3 text-[12px] text-sub">
            Tap one, or search for a place above.
          </div>
          <div className="flex flex-col gap-1">
            {s.filteredReach.slice(0, 40).map((r) => (
              /* No trip count. It was the number of scheduled journeys that call at the
                 stop, which sounds informative and is not: a rider choosing where to go
                 cannot act on "144" versus "120", and it made every row look like a
                 statistic rather than a destination. */
              <button
                key={r.id}
                className="flex cursor-pointer items-center gap-2 border border-line bg-block px-3 py-2.5 text-left hover:border-accent"
                onClick={() => s.pickTo({ kind: 'stop', id: r.id, name: r.name, lat: r.lat!, lon: r.lon! })}
              >
                {/* Which network gets you there. The list holds both, and two of these
                    rows can carry one name: RETREAT the station and RETREAT the bus stop
                    are 800m apart, exactly as in the search suggestions above. */}
                <span className="shrink-0 bg-ink px-1 text-[9px] font-bold tracking-wide text-onink uppercase">
                  {r.operator_kind === 'train' ? 'train' : 'bus'}
                </span>
                <span className="truncate text-[13px] font-semibold text-ink">{r.name}</span>
              </button>
            ))}
            {s.reachable != null && s.filteredReach.length === 0 && (
              <div className="py-4 text-center text-[13px] text-sub">
                Nothing runs from here on a single {reachRide}. Try a journey with a
                change by choosing a destination above.
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
          title={<><b>Suggestion.</b> {s.to!.name} needs {s.bestLegs} leg
            {s.bestLegs === 1 ? '' : 's'}, but these stops nearby are quicker to reach.</>}
          stops={s.betterNearby as unknown as NearStop[]}
          vehicle={ride}
          onPick={(r) => s.pickTo({ kind: 'stop', id: r.id, name: r.name, lat: r.lat!, lon: r.lon! })}
        />
      )}

      {/* The chosen network does not come near here, so say where it does.
          
          BUH REIN to CAPE TOWN under Metro Rail drew nothing whatever: no station is
          within walking distance of BUH REIN, so the plan held only buses, the chip hid
          those, and the banners below all ask whether the plan is empty - which it was
          not. A blank screen reads as broken rather than as "not from here".
          
          The nearest station is named, with what it actually runs, and tapping it plans
          from there. It is the same answer the destination list already gives for the
          other end of a journey. */}
      {/* Somebody else runs it, so say who.
          
          Upper Long to Camps Bay under Golden Arrow: no Golden Arrow bus goes, and
          MyCiTi runs it. The screen sent the rider hunting for a Golden Arrow stop
          instead - and, asking for the nearest stop of KIND bus, offered MyCiTi's. Tap
          it and the same sentence returned about another MyCiTi stop, and another.
          
          The plan already holds every operator's answer, because the chip filters what
          is drawn and not what is asked for, so this costs nothing to say and is the
          answer a rider can act on in one tap. */}
      {s.plan && !s.loading && only && shownGroups.length === 0
        && s.otherOperators.length > 0 && (
        <div className="bg-accent p-4 text-white">
          <div className="mb-3 flex items-start gap-2 text-[13px]">
            <Lightbulb size={16} weight="fill" aria-hidden="true" className="mt-px shrink-0" />
            <span>
              <b>{operators.nameOf(only)} does not run {s.from!.name} to {s.to!.name}.</b>
              {s.otherOperators.length === 1 ? <> This one does:</> : <> These do:</>}
            </span>
          </div>
          <div className="grid gap-2 sm:grid-cols-2">
            {s.otherOperators.map((x) => (
              <button
                key={x.code}
                className="flex cursor-pointer flex-col items-start gap-0.5 bg-panel px-3 py-2.5 text-left hover:ring-1 hover:ring-accent"
                onClick={() => setOnly(x.code)}
              >
                <span className="text-[13px] font-bold text-ink">
                  {operators.nameOf(x.code)}
                </span>
                <span className="text-[11px] text-sub">
                  {x.departures} {x.departures === 1 ? 'departure' : 'departures'} - direct
                </span>
              </button>
            ))}
          </div>
        </div>
      )}

      {s.plan && !s.loading && only && shownGroups.length === 0
        && s.otherOperators.length === 0 && (
        s.referralLoading ? (
          <Banner tone="info" icon={Info}>
            No {said} from {s.from!.name}. Looking for the nearest one…
          </Banner>
        ) : s.referral ? (
          <NearbyBox
            tone="suggest"
            vehicle={s.referral.kind}
            title={<>
              {/* "to Camps Bay", not "to Quebec". toName is the stop the check used
                  to prove the service exists, which is an implementation detail the
                  rider never typed and cannot place. */}
              <b>No {said} goes from {s.from!.name}.</b> The nearest{' '}
              {s.referral.kind === 'train' ? 'station' : 'stop'} with one to{' '}
              {s.to!.name} is <b>{s.referral.from.name}</b>,{' '}
              {away(s.referral.from.distance_m / 1000)} away
              {s.referral.from.earliest && <> — {s.referral.from.trip_count}{' '}
                {s.referral.kind === 'train' ? 'trains' : 'buses'} a day, first{' '}
                {s.referral.from.earliest}</>}. Tap it to plan from there.
            </>}
            stops={[{
              id: s.referral.from.id, name: s.referral.from.name,
              km: s.referral.from.distance_m / 1000, change: false,
              lat: s.referral.from.lat, lon: s.referral.from.lon,
            }]}
            /* useAlt, not pickFrom: the destination is the half the rider still wants.
               pickFrom clears it, which is right when somebody starts again from
               somewhere else and wrong here - they would have to retype CAPE TOWN to
               see the journey they had just been offered. */
            onPick={() => s.useAlt(s.referral!.from)}
          />
        ) : (
          <Banner tone="bad" icon={XCircle}>
            <b>No {said} goes from {s.from!.name} to {s.to!.name}</b>, and there is
            no {s.plan.length > 0 ? 'nearby ' : ''}
            {chosen === 'train' ? 'station' : 'stop'} that runs one either. Choose
            All to see what does.
          </Banner>
        )
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
              detail={s.openDep && openOption && (
                <>
                  {/* What the block in the carousel had no room for.
                      A 136px tile can carry a time, a price and a stop count; the route
                      the bus actually runs, the timetable it comes from, and the cheaper
                      multi-ride tickets all have to live somewhere, and this is where a
                      rider has asked for more. */}
                  <div className="mb-3 border border-line bg-block p-3">
                    <div className="text-[11px] font-bold tracking-[.06em] text-sub uppercase">
                      {openOption.operator_kind === 'train'
                        ? 'Look for the train on' : 'Look for the bus to'}
                    </div>
                    <div className="text-[15px] font-bold text-ink">
                      {vehicleSign(openOption.route_label, openOption.operator_kind)}
                    </div>
                    {/* Where the ride actually starts.
                        The API has always sent this and nothing ever showed it. It only
                        matters when the rider searched a place rather than a stop - then
                        the journey begins at a stop they did not name, up to a couple of
                        kilometres from where they are, and a departure time means nothing
                        without knowing which platform it leaves. */}
                    {openOption.board_label
                      && s.from?.kind === 'pin'
                      && openOption.board_label !== s.from?.name && (
                      <div className="mt-1 text-[12px] font-semibold text-ink">
                        {/* A station is a place you board AT; a point on a bus route is
                            one you board BETWEEN two stops, and the label already says
                            which. "Board at near X-Y" was both wordings at once. */}
                        Board {openOption.board_label.startsWith('between')
                          ? openOption.board_label
                          : `at ${openOption.board_label}`}
                        {/* And how far that is. "Board at KRAAIFONTEIN" is an instruction
                            only once it says the station is nearly two kilometres away -
                            which is a normal walk to a train, and a thing to know before
                            setting out rather than on arriving. */}
                        {openOption.board_away_m != null && (
                          <span className="font-normal text-sub">
                            {' '}· {walkAway(openOption.board_away_m)}
                          </span>
                        )}
                      </div>
                    )}
                    <div className="mt-1 text-[12px] text-sub">
                      {openOption.operator_kind === 'train' ? 'Service' : 'Route'}{' '}
                      {openOption.route_label}
                      {openOption.timetable_number
                        && <>, timetable #{openOption.timetable_number}</>}
                    </div>
                    <div className="mt-1 text-[12px] text-sub">
                      {DAY_LABEL[openOption.day_type] ?? openOption.day_type}
                      {/* The same mark as the departure chip above it. Printed bare, this
                          line said "05:10 to 06:30" directly over a breakdown reading
                          "before 06:30" - the app disagreeing with itself on one card. */}
                      {openDeparture && <> ·{' '}
                        {shortTime(openDeparture.board_raw, openDeparture.board_approx).text} to{' '}
                        {shortTime(openDeparture.arrive_raw, openDeparture.arrive_approx).text}</>}
                      {openDeparture && stopLabel(openDeparture.stop_count)
                        && <> · {stopLabel(openDeparture.stop_count)}</>}
                    </div>
                  </div>
                  <FarePanel
                    fare={openOption.fare}
                    mode={openOption.operator_kind === 'train' ? 'train' : 'bus'}
                  />
                  {/* A place is a boarding point on a bus and never on a train.
                      A bus is caught where its road passes, so "Kraaifontein High School
                      - get on here" is a real instruction. A train is caught at a station:
                      the school is where the walk starts, not where anybody boards, and
                      listing it among the stops said the train calls there. */}
                  <TripStrip
                    stops={s.tripStops}
                    loading={s.loadingTrip}
                    notes={s.tripNotes}
                    riderFromSeq={openDeparture?.from_seq ?? 0}
                    riderToSeq={openDeparture?.to_seq ?? 9999}
                    boardPin={pinEnd({ end: s.from, label: openOption.board_label,
                      operatorKind: openOption.operator_kind,
                      time: openDeparture?.board_raw,
                      approx: openDeparture?.board_approx })}
                    alightPin={pinEnd({ end: s.to, label: openOption.alight_label,
                      operatorKind: openOption.operator_kind,
                      time: openDeparture?.arrive_raw,
                      approx: openDeparture?.arrive_approx })}
                    boardTime={alightOrNone(openDeparture, 'board')}
                    alightTime={alightOrNone(openDeparture, 'alight')}
                    kind={openOption.operator_kind === 'train' ? 'train' : 'bus'}
                    onClose={() => s.setOpenDep(null)}
                  />
                </>
              )}
            />
          </div>
        )
      })}

      {/* Below the direct journeys, not above them. Something running straight
          through is the better answer and should be read first; a change is the
          alternative, and reading as though it were the only option was the
          previous fault wearing the other face. */}
      {s.plan && !s.loading && s.connLoading && (
        <Banner tone="info" icon={Info}>
          {s.plan.length === 0 ? <>No direct {said}. Looking</> : <>Also looking</>} for a
          journey with a change...
        </Banner>
      )}

      {/* There is a way there, it just takes changes. The panel prices the whole thing and
          shows the wait between each leg, which is what decides whether a three-bus
          journey is worth making at all. */}
      {s.plan && !s.loading && !s.connLoading && connWanted
        && liveConns && liveConns.length > 0 && (
        <>
          {/* A journey with a change is worth showing even when something runs straight
              through. Kraaifontein to Rosebank has one direct bus and sixteen ways to do
              it by train, and hiding all sixteen behind the one bus told a rider looking
              for the train that there wasn't one. */}
          <Banner tone={s.plan.length === 0 ? 'warn' : 'info'}
            icon={s.plan.length === 0 ? Warning : Info}>
            {s.plan.length === 0
              ? <><b>No direct {said}</b> from {s.from!.name} to {s.to!.name}. You can still
                  get there by taking{' '}</>
              : <>You can also get from {s.from!.name} to {s.to!.name} by taking{' '}</>}
            {/* plural(connKind), not the chip's word: a journey of two trains read
                "2 buses" whenever the rider had chosen All, because the fallback for
                "no network chosen" is bus. The journey knows what it is. */}
            <b>{s.connLegs} {plural(connKind)}</b>, changing at{' '}
            <b>{liveConns[0].change_at.join(' then ')}</b>.
          </Banner>
          {/* Headed by the journey, not by what the rider typed. A place carries no
              operator and fell through to Golden Arrow, so a connection made entirely of
              trains was headed Golden Arrow Buses. The API says which stop it resolved
              the place to, and that stop knows whose it is. */}
          <ConnectionsCard connections={liveConns} onChoose={setChosenConn}
            kind={s.connFrom?.operator_kind ?? ride}
            operator={s.connFrom?.operator_code ?? s.from?.operator ?? 'gabs'}
            operatorName={operators.nameOf(
              s.connFrom?.operator_code ?? s.from?.operator ?? 'gabs')} />
        </>
      )}

      {/* There is a way there, but not any more today. Saying so beats both an empty
          screen and a journey whose first bus finished this morning. */}
      {s.plan && !s.loading && s.plan.length === 0 && !s.connLoading
        && s.conns && s.conns.length > 0 && liveConns && liveConns.length === 0 && (
        <Banner tone="warn" icon={Warning}>
          <b>No direct {said}</b> from {s.from!.name} to {s.to!.name}, and the {s.connLegs}-leg
          journey through <b>{s.conns[0].change_at.join(' then ')}</b> has finished for today.
          Choose an earlier time, or “Any time”, to see how it runs.
        </Banner>
      )}

      {s.plan && !s.loading && s.plan.length === 0 && !s.connLoading && s.conns && s.conns.length === 0 && (
        <Banner tone="bad" icon={XCircle}>
          <b>No way to get there by {said}.</b> There is no direct service from {s.from!.name} to{' '}
          {s.to!.name}, and no combination of up to three {saids} connects them either.
        </Banner>
      )}

      {s.plan && !s.loading && s.plan.length === 0 && !s.connLoading && s.conns
        && s.conns.length === 0 && s.nearbyAlternatives.length > 0 && (
        <NearbyBox
          tone="plain"
          title={<>You can reach these stops near <b>{s.to!.name}</b></>}
          stops={s.nearbyAlternatives as unknown as NearStop[]}
          vehicle={ride}
          onPick={(r) => s.pickTo({ kind: 'stop', id: r.id, name: r.name, lat: r.lat!, lon: r.lon! })}
        />
      )}

      {/* A dropped pin has no stop id, and the connections engine can only join named
          stops - so this is a limit of the question, not of the network. */}
      {s.plan && !s.loading && s.plan.length === 0 && !s.connLoading && s.conns === null && (
        <Banner tone="bad" icon={XCircle}>
          <b>No direct {said}.</b> Journeys with a change can only be worked out between named
          stops, not dropped pins.
        </Banner>
      )}


      {/* Nothing runs today, but something runs on Saturday - or from a stop up the road.
          Worth saying: the alternative is a rider concluding the journey is impossible. */}
      {s.plan && !s.loading && s.altDays.length > 0 && (
        <div className="border border-line bg-panel p-4">
          <div className="mb-3 text-[13px] font-bold text-ink">
            {s.plan.length
              ? `On other days, the nearest stop with a direct ${said}:`
              : `Nearest stops with a direct ${said} there:`}
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
                    className="flex cursor-pointer flex-col items-start gap-0.5 border border-line bg-block px-3 py-2.5 text-left hover:border-accent"
                    onClick={() => s.useAlt(o)}
                  >
                    <span className="text-[13px] font-semibold text-ink">{o.name}</span>
                    <span className="text-[11px] text-sub">
                      {(o.distance_m / 1000).toFixed(1)} km away
                      {o.earliest ? `, first departure ${o.earliest}` : ''}, {o.trip_count} trips
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
          No stop within 8 km has a direct {said} there either.
        </div>
      )}

      {/* On a phone the map is something a rider asks for, not something that takes half
          the screen. It matters when deciding where to stand, which is after the bus is
          chosen. On a wide screen it stands permanently in the panel to the right, so
          this whole card is hidden there.

          It is drawn for journeys with a change too. Those carry no road geometry - the
          API sends that only for a direct plan - but the legs do carry the coordinates of
          every place you get on and off, which is the part a rider needs: where the
          changes actually are. */}
      {hasRoute && (
        <div className="border border-line bg-panel p-3 lg:hidden">
          <button
            className="flex w-full cursor-pointer items-center justify-between text-[13px] font-semibold text-ink"
            onClick={() => setShowMap(!showMap)}
            aria-expanded={showMap}
          >
            <span className="flex items-center gap-2">
              <MapTrifold size={18} weight="fill" aria-hidden="true" className="text-accent" />
              {showMap ? 'Hide map' : 'Show map'}
            </span>
            <CaretDown size={16} weight="bold" aria-hidden="true"
              className={`transition-transform ${showMap ? 'rotate-180' : ''}`} />
          </button>
          {showMap && (
            <div className="mappanel mt-3 h-72 overflow-hidden">{mapEl}</div>
          )}
        </div>
      )}
      </div>

      {/* The standing map panel. Only from lg up, and only once there is a route to draw:
          an empty map beside an empty search is decoration. */}
      {hasRoute && (
        <aside className="hidden min-h-0 min-w-0 flex-1 lg:block">
          <div className="mappanel h-full overflow-hidden border border-line">
            {mapEl}
          </div>
        </aside>
      )}
    </div>
  )
}
