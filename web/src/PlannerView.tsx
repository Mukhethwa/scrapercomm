import { useEffect, useState } from 'react'
import {
  DndContext, KeyboardSensor, PointerSensor, closestCenter,
  useSensor, useSensors, type DragEndEvent,
} from '@dnd-kit/core'
import {
  SortableContext, sortableKeyboardCoordinates,
  useSortable, verticalListSortingStrategy,
} from '@dnd-kit/sortable'
import { CSS } from '@dnd-kit/utilities'
import { ArrowRight, ArrowUp, ArrowDown, GripVertical } from 'lucide-react'
import { getPlan, getTripStops, type PlanOption, type TripStop } from './api'
import {
  buildJourney, connectionIssues, rideKey, toEndpoint, usePlanner,
  type SavedJourney,
} from './planner'
import TripStrip from './TripStrip'

const DAY_LABEL: Record<string, string> = {
  WEEKDAY: 'Mon-Fri', SATURDAY: 'Saturday', SUNDAY: 'Sunday',
  PUBLIC_HOLIDAY: 'Public Holiday', OTHER: 'Other',
}

/** The bus's front sign: the terminus, read from ORIGIN - VIA - TERMINUS. */
function terminusOf(routeLabel: string) {
  const parts = routeLabel.split(' - ').map((s) => s.trim()).filter(Boolean)
  return parts[parts.length - 1] ?? routeLabel
}

function plural(n: number, one: string, many: string) {
  return `${n} ${n === 1 ? one : many}`
}

export default function PlannerView({ onBrowse }: { onBrowse: () => void }) {
  const { journeys, remove, replace, reorder, clear } = usePlanner()
  const issues = connectionIssues(journeys)

  const [openId, setOpenId] = useState<string | null>(null)
  const [stops, setStops] = useState<TripStop[] | null>(null)
  const [loadingStops, setLoadingStops] = useState(false)

  const [editingId, setEditingId] = useState<string | null>(null)

  const sensors = useSensors(
    // A small distance threshold so tapping a card still opens it on touch screens
    // rather than being swallowed as the start of a drag.
    useSensor(PointerSensor, { activationConstraint: { distance: 6 } }),
    useSensor(KeyboardSensor, { coordinateGetter: sortableKeyboardCoordinates }),
  )

  function toggleDetail(j: SavedJourney) {
    setEditingId(null)
    if (openId === j.id) { setOpenId(null); return }
    setOpenId(j.id)
    setStops(null)
    setLoadingStops(true)
    // The whole trip, origin to terminus, exactly as the search page fetches it.
    getTripStops(j.departure.scheduleId, j.departure.tripIndex, 0, 9999)
      .then((r) => setStops(r.stops))
      .catch(() => setStops([]))
      .finally(() => setLoadingStops(false))
  }

  function onDragEnd(e: DragEndEvent) {
    const { active, over } = e
    if (!over || active.id === over.id) return
    const from = journeys.findIndex((j) => j.id === active.id)
    const to = journeys.findIndex((j) => j.id === over.id)
    if (from >= 0 && to >= 0) reorder(from, to)
  }

  if (journeys.length === 0) {
    return (
      <div className="plannerwrap">
        <div className="plannerempty">
          <h2>Your planner is empty</h2>
          <p>
            Search for a trip, then tap <b>Add to planner</b> on the departure you want.
            Journeys you add show up here, numbered in the order you plan to travel, and
            you can drag them around to change that order.
          </p>
          <button className="primary" onClick={onBrowse}>Plan a trip</button>
        </div>
      </div>
    )
  }

  return (
    <div className="plannerwrap">
      <div className="plannerhead">
        <div>
          <h2>Your journey plan</h2>
          <p className="plannersub">
            {plural(journeys.length, 'journey', 'journeys')}, in the order you will travel.
            Drag a card, or use the arrows, to reorder. Tap one to see the full trip.
          </p>
        </div>
        <button className="link danger" onClick={() => {
          if (confirm('Remove every journey from your planner?')) clear()
        }}>Clear all</button>
      </div>

      <DndContext sensors={sensors} collisionDetection={closestCenter} onDragEnd={onDragEnd}>
        <SortableContext items={journeys.map((j) => j.id)} strategy={verticalListSortingStrategy}>
          <ol className="plannerlist">
            {journeys.map((j, i) => (
              <SortableJourney
                key={j.id}
                journey={j}
                position={i + 1}
                total={journeys.length}
                issue={issues.get(i)}
                open={openId === j.id}
                editing={editingId === j.id}
                stops={openId === j.id ? stops : null}
                loadingStops={openId === j.id && loadingStops}
                onToggleDetail={() => toggleDetail(j)}
                onToggleEdit={() => { setOpenId(null); setEditingId(editingId === j.id ? null : j.id) }}
                onRemove={() => { setOpenId(null); setEditingId(null); remove(j.id) }}
                onMove={(dir) => reorder(i, i + dir)}
                onReplace={(next) => { replace(j.id, next); setEditingId(null) }}
              />
            ))}
          </ol>
        </SortableContext>
      </DndContext>
    </div>
  )
}

function SortableJourney(props: {
  journey: SavedJourney
  position: number
  total: number
  issue?: { minutesShort: number }
  open: boolean
  editing: boolean
  stops: TripStop[] | null
  loadingStops: boolean
  onToggleDetail: () => void
  onToggleEdit: () => void
  onRemove: () => void
  onMove: (dir: 1 | -1) => void
  onReplace: (next: SavedJourney) => void
}) {
  const {
    journey: j, position, total, issue, open, editing, stops, loadingStops,
    onToggleDetail, onToggleEdit, onRemove, onMove, onReplace,
  } = props

  const { attributes, listeners, setNodeRef, transform, transition, isDragging } =
    useSortable({ id: j.id })

  const style = {
    transform: CSS.Transform.toString(transform),
    transition,
    opacity: isDragging ? 0.55 : 1,
  }

  return (
    <li ref={setNodeRef} style={style} className={`plannercard ${isDragging ? 'dragging' : ''} ${issue ? 'clash' : ''}`}>
      {issue && (
        <div className="clashnote">
          This bus leaves {issue.minutesShort} min <b>before</b> you arrive on journey {position - 1}.
          You would not make this connection.
        </div>
      )}

      <div className="plannertop">
        <button
          className="draghandle"
          aria-label={`Reorder journey ${position}`}
          {...attributes}
          {...listeners}
        >
          <span className="posnum">{position}</span>
          <GripVertical size={14} className="dragdots" aria-hidden="true" />
        </button>

        <button className="plannermain" onClick={onToggleDetail} aria-expanded={open}>
          <div className="plannerroute">
            <span className="pfrom">{j.from.name}</span>
            <ArrowRight size={14} className="parrow" aria-hidden="true" />
            <span className="pto">{j.to.name}</span>
          </div>
          <div className="plannertimes">
            <span className="ptime">{j.departure.boardRaw}</span>
            <span className="pdash">to</span>
            <span className="ptime">{j.departure.arriveRaw}</span>
            {(j.approx.board || j.approx.alight) && <span className="approxpill">Approx</span>}
            <span className="daypill">{DAY_LABEL[j.route.dayType] ?? j.route.dayType}</span>
          </div>
          <div className="plannersign">
            Bus to <b>{terminusOf(j.route.label)}</b>
            <span className="plannerttn"> · timetable #{j.route.timetableNumber}</span>
          </div>
        </button>

        <div className="plannerside">
          <div className="movebtns">
            <button className="movebtn" disabled={position === 1}
              onClick={() => onMove(-1)} aria-label="Move up">
              <ArrowUp size={13} aria-hidden="true" />
            </button>
            <button className="movebtn" disabled={position === total}
              onClick={() => onMove(1)} aria-label="Move down">
              <ArrowDown size={13} aria-hidden="true" />
            </button>
          </div>
          <button className="link" onClick={onToggleEdit}>
            {editing ? 'Cancel' : 'Change time'}
          </button>
          <button className="link danger" onClick={onRemove}>Remove</button>
        </div>
      </div>

      {editing && <ChangeTime journey={j} onPick={onReplace} />}

      {open && (
        <TripStrip
          stops={stops}
          loading={loadingStops}
          riderFromSeq={j.departure.fromSeq}
          riderToSeq={j.departure.toSeq}
          boardPin={j.from.kind === 'pin' ? { name: j.from.name, time: j.departure.boardRaw } : null}
          alightPin={j.to.kind === 'pin' ? { name: j.to.name, time: j.departure.arriveRaw } : null}
        />
      )}
    </li>
  )
}

/**
 * Other departures for the same origin and destination, so a commuter who cannot make
 * the time they picked can swap it without losing the journey's place in the plan.
 */
function ChangeTime(
  { journey, onPick }: { journey: SavedJourney; onPick: (next: SavedJourney) => void },
) {
  const [options, setOptions] = useState<PlanOption[] | null>(null)
  const [failed, setFailed] = useState(false)

  useEffect(() => {
    let live = true
    setOptions(null); setFailed(false)
    getPlan(toEndpoint(journey.from), toEndpoint(journey.to))
      .then((r) => { if (live) setOptions(r.options) })
      .catch(() => { if (live) setFailed(true) })
    return () => { live = false }
  }, [journey.from, journey.to])

  if (failed) return <div className="changebox"><div className="empty">Could not load other times just now.</div></div>
  if (options == null) return <div className="changebox"><div className="tsloading">Finding other departures…</div></div>
  if (options.length === 0) return <div className="changebox"><div className="empty">No other buses on this trip.</div></div>

  const currentKey = rideKey(journey.departure)

  return (
    <div className="changebox">
      <div className="changehead">
        Pick a different departure. It keeps its place in your plan.
      </div>
      {options.map((o, oi) => (
        <div key={oi} className="changeopt">
          <div className="changeoptlbl">
            Bus to <b>{terminusOf(o.route_label)}</b>
            <span className="daypill">{DAY_LABEL[o.day_type] ?? o.day_type}</span>
          </div>
          <div className="depsgrid">
            {o.departures.map((d, di) => {
              const key = rideKey({
                scheduleId: d.schedule_id, tripIndex: d.trip_index,
                fromSeq: d.from_seq, toSeq: d.to_seq,
              })
              const isCurrent = key === currentKey
              return (
                <button
                  key={di}
                  className={`dep ${isCurrent ? 'current' : ''}`}
                  disabled={isCurrent}
                  onClick={() => onPick(buildJourney(
                    toEndpoint(journey.from), toEndpoint(journey.to), o, d,
                  ))}
                >
                  <span className="bt">{d.board_raw}</span>
                  <span className="da">to</span>
                  <span className="at">{d.arrive_raw}</span>
                  {isCurrent && <span className="curtag">now</span>}
                </button>
              )
            })}
          </div>
        </div>
      ))}
    </div>
  )
}
