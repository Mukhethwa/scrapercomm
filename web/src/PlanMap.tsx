import { useEffect } from 'react'
import {
  MapContainer, TileLayer, CircleMarker, Polyline, Tooltip, useMap, useMapEvents,
} from 'react-leaflet'
import type { LatLngExpression } from 'leaflet'
import { PinIcon } from './icons'

const CAPE_TOWN: LatLngExpression = [-33.925, 18.424]

export interface Pt {
  name?: string
  lat: number | null
  lon: number | null
}

function Fit({ pts }: { pts: [number, number][] }) {
  const map = useMap()
  useEffect(() => {
    if (pts.length === 1) map.setView(pts[0], 14)
    else if (pts.length > 1) map.fitBounds(pts, { padding: [40, 40] })
  }, [JSON.stringify(pts), map])
  return null
}

/**
 * Leaflet caches its container size, so a map that was hidden (display:none) comes back
 * blank or half-drawn. Watching the container and re-measuring covers both that and
 * ordinary window resizes.
 */
function KeepSized() {
  const map = useMap()
  useEffect(() => {
    const ro = new ResizeObserver(() => map.invalidateSize())
    ro.observe(map.getContainer())
    return () => ro.disconnect()
  }, [map])
  return null
}

function Clicker({ onClick }: { onClick?: (lat: number, lon: number) => void }) {
  useMapEvents({
    click(e) {
      onClick?.(e.latlng.lat, e.latlng.lng)
    },
  })
  return null
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
  const segPts: [number, number][] = seg.map((p) => [p.lat as number, p.lon as number])
  // Prefer the real road geometry for the drawn line; fall back to straight segments.
  const line: [number, number][] = roadPath && roadPath.length > 1 ? roadPath : segPts
  const reach = (reachable ?? []).filter((p) => p.lat != null && p.lon != null)

  const fitPts: [number, number][] = line.length
    ? line
    : [
        ...(from && from.lat != null ? [[from.lat, from.lon as number] as [number, number]] : []),
        ...(to && to.lat != null ? [[to.lat, to.lon as number] as [number, number]] : []),
        ...reach.map((p) => [p.lat as number, p.lon as number] as [number, number]),
      ]

  return (
    <div className="map-wrap" style={armLabel ? { outline: '3px solid #ff4500', outlineOffset: '-3px' } : undefined}>
      <MapContainer
        center={fitPts[0] ?? CAPE_TOWN}
        zoom={12}
        scrollWheelZoom
        className="map"
        style={armLabel ? { cursor: 'crosshair' } : undefined}
      >
        <TileLayer
          attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'
          url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
        />
        <KeepSized />
        <Clicker onClick={onMapClick} />
        {line.length > 1 && (
          <Polyline positions={line} pathOptions={{ color: '#ff4500', weight: 4, opacity: 0.9 }} />
        )}
        {seg.map((s, i) =>
          i > 0 && i < seg.length - 1 ? (
            <CircleMarker key={`s${i}`} center={segPts[i]} radius={4}
              pathOptions={{ color: '#a8afb7', weight: 1, fillColor: '#c9ced4', fillOpacity: 0.9 }}>
              <Tooltip>{s.name}</Tooltip>
            </CircleMarker>
          ) : null,
        )}
        {reach.map((s, i) => (
          <CircleMarker key={`r${i}`} center={[s.lat as number, s.lon as number]} radius={4}
            pathOptions={{ color: '#a8afb7', weight: 1, fillColor: '#c9ced4', fillOpacity: 0.85 }}>
            <Tooltip>{s.name}</Tooltip>
          </CircleMarker>
        ))}
        {/* Start of the journey, the brand's black */}
        {from && from.lat != null && (
          <CircleMarker center={[from.lat, from.lon as number]} radius={8}
            pathOptions={{ color: '#000000', weight: 2, fillColor: '#111111', fillOpacity: 0.95 }}>
            <Tooltip>{`From: ${from.name ?? 'pin'}`}</Tooltip>
          </CircleMarker>
        )}
        {/* Destination: the orange dot the whole brand is built around */}
        {to && to.lat != null && (
          <CircleMarker center={[to.lat, to.lon as number]} radius={8}
            pathOptions={{ color: '#cc3700', weight: 2, fillColor: '#ff4500', fillOpacity: 0.95 }}>
            <Tooltip>{`To: ${to.name ?? 'pin'}`}</Tooltip>
          </CircleMarker>
        )}
        <Fit pts={fitPts} />
      </MapContainer>
      {armLabel && <p className="map-note"><PinIcon /> Click anywhere on the map to set <b>{armLabel}</b>.</p>}
    </div>
  )
}
