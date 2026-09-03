import { useEffect } from 'react'
import { LngLatBounds } from 'maplibre-gl'
import {
  Map, MapControls, MapMarker, MapRoute, MarkerContent, MarkerTooltip, useMap,
} from '@/components/ui/map'
import { PinIcon } from './icons'

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

export default function PlanMap({
  from, to, segment, roadPath, reachable, onMapClick, armLabel,
}: {
  from?: Pt | null
  to?: Pt | null
  segment?: Pt[]
  roadPath?: [number, number][]
  reachable?: Pt[]
  onMapClick?: (lat: number, lon: number) => void
  armLabel?: string | null
}) {
  const seg = (segment ?? []).filter((p) => p.lat != null && p.lon != null)
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
      <Map
        className="map"
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

        {seg.map((s, i) =>
          i > 0 && i < seg.length - 1 ? (
            <MapMarker key={`s${i}`} longitude={segPts[i][0]} latitude={segPts[i][1]}>
              <Dot size={9} fill="#c9ced4" stroke="#a8afb7" label={s.name} />
              <MarkerTooltip>{s.name}</MarkerTooltip>
            </MapMarker>
          ) : null,
        )}

        {reach.map((s, i) => (
          <MapMarker key={`r${i}`} longitude={s.lon as number} latitude={s.lat as number}>
            <Dot size={9} fill="#c9ced4" stroke="#a8afb7" label={s.name} />
            <MarkerTooltip>{s.name}</MarkerTooltip>
          </MapMarker>
        ))}

        {/* Start of the journey, the brand's black */}
        {from && from.lat != null && (
          <MapMarker longitude={from.lon as number} latitude={from.lat}>
            <Dot size={17} fill="#111111" stroke="#000000" label={from.name} />
            <MarkerTooltip>{`From: ${from.name ?? 'pin'}`}</MarkerTooltip>
          </MapMarker>
        )}

        {/* Destination: the orange dot the whole brand is built around */}
        {to && to.lat != null && (
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
