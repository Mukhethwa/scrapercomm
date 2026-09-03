import { Suspense, lazy, useEffect } from 'react'
import { LngLatBounds } from 'maplibre-gl'
import {
  Map, MapControls, MapMarker, MapRoute, MarkerContent, MarkerTooltip, useMap,
} from '@/components/ui/map'
import { PinIcon } from './icons'
import MapThemeToggle from './MapThemeToggle'
import { useMapTheme } from './mapTheme'
import { supportsWebGL2 } from './webgl'
import MapBoundary from './MapBoundary'

/**
 * Loaded only where MapLibre cannot run. Dynamic so a device that can run it never
 * downloads Leaflet at all - the fallback costs the common case nothing.
 */
const LeafletPlanMap = lazy(() => import('./LeafletPlanMap'))

/**
 * MapLibre, via mapcn, takes [longitude, latitude] where Leaflet took [latitude,
 * longitude]. Everything this app holds - stops, road geometry, the API - is lat/lon, so
 * the flip happens here and nowhere else. Getting it wrong does not throw; it silently
 * puts Cape Town in the Indian Ocean.
 */
const lngLat = (lat: number, lon: number): [number, number] => [lon, lat]

const CAPE_TOWN: [number, number] = lngLat(-33.925, 18.424)

export interface Pt {
  name?: string
  lat: number | null
  lon: number | null
  stop_sequence?: number
}

/** Frame whatever is being shown, the way fitBounds did before. */
function Fit({ pts }: { pts: [number, number][] }) {
  const { map, isLoaded } = useMap()
  const key = JSON.stringify(pts)
  useEffect(() => {
    if (!map || !isLoaded || pts.length === 0) return
    if (pts.length === 1) {
      map.easeTo({ center: pts[0], zoom: 14 })
      return
    }
    const bounds = pts.reduce((b, p) => b.extend(p), new LngLatBounds(pts[0], pts[0]))
    map.fitBounds(bounds, { padding: 40, duration: 400 })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key, map, isLoaded])
  return null
}

/**
 * MapLibre measures its container once and caches it, so a map created while its panel
 * is hidden - which this one is, because PlanView stays mounted and is hidden with CSS
 * when another tab is showing - comes back with a zero-sized drawing buffer and paints
 * nothing at all. Leaflet had the same flaw and the same fix; this is that fix again.
 */
function KeepSized() {
  const { map } = useMap()
  useEffect(() => {
    if (!map) return
    const ro = new ResizeObserver(() => map.resize())
    ro.observe(map.getContainer())
    map.resize()
    return () => ro.disconnect()
  }, [map])
  return null
}

/** Dropping a pin: the whole map is the target, so the click lives on the map itself. */
function Clicker({ onClick }: { onClick?: (lat: number, lon: number) => void }) {
  const { map } = useMap()
  useEffect(() => {
    if (!map || !onClick) return
    const handler = (e: { lngLat: { lat: number; lng: number } }) =>
      onClick(e.lngLat.lat, e.lngLat.lng)
    map.on('click', handler)
    return () => { map.off('click', handler) }
  }, [map, onClick])
  return null
}

/** A plain dot, so the map keeps the brand rather than MapLibre's default pin. */
function Dot({ size, fill, stroke, label }:
  { size: number; fill: string; stroke: string; label?: string }) {
  return (
    <MarkerContent>
      <span
        style={{
          display: 'block', width: size, height: size, borderRadius: '50%',
          background: fill, border: `2px solid ${stroke}`, boxSizing: 'border-box',
        }}
        aria-label={label}
      />
    </MarkerContent>
  )
}

/**
 * A stop on the ride, carrying its position in the journey.
 *
 * The order is the whole point: a route drawn as identical dots says where the bus goes
 * but not which way round, and a rider reading a map wants to know which stop is first.
 * First and last take the brand's black and orange, the same two colours the trip
 * breakdown uses for getting on and off, so the map and the list agree.
 */
function NumberedStop({ n, first, last, name }:
  { n: number; first: boolean; last: boolean; name?: string }) {
  const size = first || last ? 24 : 20
  const fill = first ? '#111111' : last ? '#ff4500' : '#ffffff'
  const stroke = first ? '#000000' : last ? '#cc3700' : '#a8afb7'
  const text = first || last ? '#ffffff' : '#111111'
  return (
    <MarkerContent>
      <span
        style={{
          display: 'flex', alignItems: 'center', justifyContent: 'center',
          width: size, height: size, borderRadius: '50%',
          background: fill, border: `2px solid ${stroke}`, color: text,
          fontSize: first || last ? 11 : 10, fontWeight: 700, lineHeight: 1,
          fontVariantNumeric: 'tabular-nums', boxSizing: 'border-box',
          boxShadow: '0 1px 3px rgba(0,0,0,.35)',
        }}
        aria-label={name ? `Stop ${n}: ${name}` : `Stop ${n}`}
      >
        {n}
      </span>
    </MarkerContent>
  )
}

/** Two coordinates close enough to be the same stop, so it is not marked twice. */
const samePlace = (a: Pt, b: Pt) =>
  a.lat != null && b.lat != null
  && Math.abs((a.lat as number) - (b.lat as number)) < 1e-5
  && Math.abs((a.lon as number) - (b.lon as number)) < 1e-5

interface PlanMapProps {
  from?: Pt | null
  to?: Pt | null
  segment?: Pt[]
  roadPath?: [number, number][]
  reachable?: Pt[]
  /** The stop range actually ridden, so numbering stops where the rider gets off. */
  ride?: { fromSeq: number; toSeq: number }
  onMapClick?: (lat: number, lon: number) => void
  armLabel?: string | null
}

/**
 * MapLibre where the device can run it, Leaflet where it cannot, and the journey intact
 * either way. The map is the least important thing on this page and the most likely to
 * fail, so it is the one part wrapped in a boundary.
 */
export default function PlanMap(props: PlanMapProps) {
  if (!supportsWebGL2()) {
    return (
      <MapBoundary>
        <Suspense fallback={<div className="map-wrap"><p className="map-note">Loading the map…</p></div>}>
          <LeafletPlanMap {...props} />
        </Suspense>
      </MapBoundary>
    )
  }
  return (
    <MapBoundary>
      <GlPlanMap {...props} />
    </MapBoundary>
  )
}

function GlPlanMap({
  from, to, segment, roadPath, reachable, ride, onMapClick, armLabel,
}: PlanMapProps) {
  const { theme, toggle } = useMapTheme()

  const seg = (segment ?? [])
    .filter((p) => p.lat != null && p.lon != null)
    .filter((p) => !ride || p.stop_sequence == null
      || (p.stop_sequence >= ride.fromSeq && p.stop_sequence <= ride.toSeq))
  const segPts = seg.map((p) => lngLat(p.lat as number, p.lon as number))
  // Prefer the real road geometry for the drawn line; fall back to straight segments.
  const line = roadPath && roadPath.length > 1
    ? roadPath.map(([lat, lon]) => lngLat(lat, lon))
    : segPts
  const reach = (reachable ?? []).filter((p) => p.lat != null && p.lon != null)

  const fitPts: [number, number][] = line.length
    ? line
    : [
        ...(from && from.lat != null ? [lngLat(from.lat, from.lon as number)] : []),
        ...(to && to.lat != null ? [lngLat(to.lat, to.lon as number)] : []),
        ...reach.map((p) => lngLat(p.lat as number, p.lon as number)),
      ]

  return (
    <div
      className="map-wrap"
      style={armLabel
        // The crosshair belongs on the container: MapLibre owns the canvas cursor and
        // has no option for it.
        ? { outline: '3px solid #ff4500', outlineOffset: '-3px', cursor: 'crosshair' }
        : undefined}
    >
      <MapThemeToggle theme={theme} onToggle={toggle} />
      <Map
        className="map"
        theme={theme}
        center={fitPts[0] ?? CAPE_TOWN}
        zoom={12}
        attributionControl={{ compact: true }}
      >
        <MapControls position="top-left" />
        <KeepSized />
        <Clicker onClick={onMapClick} />
        <Fit pts={fitPts} />

        {line.length > 1 && (
          <MapRoute id="ride" coordinates={line} color="#ff4500" width={4} opacity={0.9} />
        )}

        {seg.map((s, i) => (
          <MapMarker key={`s${i}`} longitude={segPts[i][0]} latitude={segPts[i][1]}>
            <NumberedStop
              n={i + 1}
              first={i === 0}
              last={i === seg.length - 1}
              name={s.name}
            />
            <MarkerTooltip>{`${i + 1}. ${s.name ?? 'stop'}`}</MarkerTooltip>
          </MapMarker>
        ))}

        {reach.map((s, i) => (
          <MapMarker key={`r${i}`} longitude={s.lon as number} latitude={s.lat as number}>
            <Dot size={9} fill="#c9ced4" stroke="#a8afb7" label={s.name} />
            <MarkerTooltip>{s.name}</MarkerTooltip>
          </MapMarker>
        ))}

        {/* A dropped pin, or a search with no ride drawn yet. Where the endpoint IS a
            stop on the ride it is already numbered, and marking it twice stacks two
            markers on one point. */}
        {from && from.lat != null && !(seg.length && samePlace(from, seg[0])) && (
          <MapMarker longitude={from.lon as number} latitude={from.lat}>
            <Dot size={17} fill="#111111" stroke="#000000" label={from.name} />
            <MarkerTooltip>{`From: ${from.name ?? 'pin'}`}</MarkerTooltip>
          </MapMarker>
        )}

        {to && to.lat != null && !(seg.length && samePlace(to, seg[seg.length - 1])) && (
          <MapMarker longitude={to.lon as number} latitude={to.lat}>
            <Dot size={17} fill="#ff4500" stroke="#cc3700" label={to.name} />
            <MarkerTooltip>{`To: ${to.name ?? 'pin'}`}</MarkerTooltip>
          </MapMarker>
        )}
      </Map>
      {armLabel && (
        <p className="map-note">
          <PinIcon /> Click anywhere on the map to set <b>{armLabel}</b>.
        </p>
      )}
    </div>
  )
}
