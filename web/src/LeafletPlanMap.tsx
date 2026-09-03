import { useEffect } from 'react'
import {
  MapContainer, TileLayer, CircleMarker, Marker, Polyline, Tooltip, useMap, useMapEvents,
} from 'react-leaflet'
import { divIcon, type LatLngExpression } from 'leaflet'
import 'leaflet/dist/leaflet.css'
import { PinIcon } from './icons'
import type { Pt } from './PlanMap'

/**
 * The map for devices MapLibre cannot run on.
 *
 * Leaflet draws with DOM and raster tiles and needs no WebGL, so it works where mapcn
 * does not. Loaded only when that is the case - the import is dynamic, so a device that
 * can run MapLibre never downloads any of this.
 *
 * Kept deliberately close to the MapLibre map: the same numbered stops, the same brand
 * colours, the same click-to-drop-a-pin. A rider on a cheap phone should get the same
 * app, not a worse one.
 */

const CAPE_TOWN: LatLngExpression = [-33.925, 18.424]

/** Same tiles the app used before the MapLibre migration - raster, and keyless. */
const OSM_URL = 'https://tile.openstreetmap.org/{z}/{x}/{y}.png'
const OSM_ATTR =
  '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'

function Fit({ pts }: { pts: [number, number][] }) {
  const map = useMap()
  useEffect(() => {
    if (pts.length === 1) map.setView(pts[0], 14)
    else if (pts.length > 1) map.fitBounds(pts, { padding: [40, 40] })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [JSON.stringify(pts), map])
  return null
}

/** Leaflet caches its container size, so a map that was hidden comes back blank. */
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

/** The numbered circle, as markup, since Leaflet has no shape that carries a label. */
function stopIcon(n: number, first: boolean, last: boolean) {
  const size = first || last ? 24 : 20
  const fill = first ? '#111111' : last ? '#ff4500' : '#ffffff'
  const stroke = first ? '#000000' : last ? '#cc3700' : '#a8afb7'
  const text = first || last ? '#ffffff' : '#111111'
  return divIcon({
    className: '',
    iconSize: [size, size],
    iconAnchor: [size / 2, size / 2],
    html:
      `<span style="display:flex;align-items:center;justify-content:center;` +
      `width:${size}px;height:${size}px;border-radius:50%;background:${fill};` +
      `border:2px solid ${stroke};color:${text};font-size:${first || last ? 11 : 10}px;` +
      `font-weight:700;line-height:1;box-sizing:border-box;` +
      `box-shadow:0 1px 3px rgba(0,0,0,.35);font-family:inherit">${n}</span>`,
  })
}

export default function LeafletPlanMap({
  from, to, segment, roadPath, reachable, ride, onMapClick, armLabel,
}: {
  from?: Pt | null
  to?: Pt | null
  segment?: Pt[]
  roadPath?: [number, number][]
  reachable?: Pt[]
  ride?: { fromSeq: number; toSeq: number }
  onMapClick?: (lat: number, lon: number) => void
  armLabel?: string | null
}) {
  const seg = (segment ?? [])
    .filter((p) => p.lat != null && p.lon != null)
    .filter((p) => !ride || p.stop_sequence == null
      || (p.stop_sequence >= ride.fromSeq && p.stop_sequence <= ride.toSeq))
  const segPts: [number, number][] = seg.map((p) => [p.lat as number, p.lon as number])
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
    <div
      className="map-wrap"
      style={armLabel
        ? { outline: '3px solid #ff4500', outlineOffset: '-3px', cursor: 'crosshair' }
        : undefined}
    >
      <MapContainer center={fitPts[0] ?? CAPE_TOWN} zoom={12} scrollWheelZoom className="map">
        <TileLayer attribution={OSM_ATTR} url={OSM_URL} />
        <KeepSized />
        <Clicker onClick={onMapClick} />
        <Fit pts={fitPts} />

        {line.length > 1 && (
          <Polyline positions={line} pathOptions={{ color: '#ff4500', weight: 4, opacity: 0.9 }} />
        )}

        {seg.map((s, i) => (
          <Marker
            key={`s${i}`}
            position={segPts[i]}
            icon={stopIcon(i + 1, i === 0, i === seg.length - 1)}
          >
            <Tooltip>{`${i + 1}. ${s.name ?? 'stop'}`}</Tooltip>
          </Marker>
        ))}

        {reach.map((s, i) => (
          <CircleMarker
            key={`r${i}`}
            center={[s.lat as number, s.lon as number]}
            radius={4}
            pathOptions={{ color: '#a8afb7', weight: 1, fillColor: '#c9ced4', fillOpacity: 0.85 }}
          >
            <Tooltip>{s.name}</Tooltip>
          </CircleMarker>
        ))}
      </MapContainer>
      {armLabel && (
        <p className="map-note">
          <PinIcon /> Click anywhere on the map to set <b>{armLabel}</b>.
        </p>
      )}
    </div>
  )
}
