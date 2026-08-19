import { useEffect } from 'react'
import {
  MapContainer,
  TileLayer,
  CircleMarker,
  Polyline,
  Tooltip,
  useMap,
} from 'react-leaflet'
import type { LatLngExpression } from 'leaflet'
import type { Stop } from './api'

const CAPE_TOWN: LatLngExpression = [-33.925, 18.424]

function FitBounds({ pts }: { pts: [number, number][] }) {
  const map = useMap()
  useEffect(() => {
    if (pts.length === 1) {
      map.setView(pts[0], 14)
    } else if (pts.length > 1) {
      map.fitBounds(pts, { padding: [30, 30] })
    }
  }, [JSON.stringify(pts), map])
  return null
}

export default function MapView({ stops }: { stops: Stop[] }) {
  const geo = stops.filter((s) => s.lat != null && s.lon != null)
  const pts: [number, number][] = geo.map((s) => [s.lat as number, s.lon as number])
  const missing = stops.length - geo.length

  return (
    <div className="map-wrap">
      <MapContainer center={pts[0] ?? CAPE_TOWN} zoom={12} scrollWheelZoom className="map">
        <TileLayer
          attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'
          url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
        />
        {pts.length > 1 && (
          <Polyline positions={pts} pathOptions={{ color: '#ff4500', weight: 3, opacity: 0.85 }} />
        )}
        {geo.map((s, i) => {
          const first = i === 0
          const last = i === geo.length - 1
          // Black start, orange destination, neutral stops in between.
          const style = first
            ? { color: '#000000', weight: 2, fillColor: '#111111', fillOpacity: 0.95 }
            : last
              ? { color: '#cc3700', weight: 2, fillColor: '#ff4500', fillOpacity: 0.95 }
              : { color: '#a8afb7', weight: 1, fillColor: '#c9ced4', fillOpacity: 0.9 }
          return (
            <CircleMarker
              key={`${s.stop_sequence}-${i}`}
              center={[s.lat as number, s.lon as number]}
              radius={first || last ? 7 : 5}
              pathOptions={style}
            >
              <Tooltip>{`${s.stop_sequence + 1}. ${s.name}`}</Tooltip>
            </CircleMarker>
          )
        })}
        <FitBounds pts={pts} />
      </MapContainer>
      {missing > 0 && (
        <p className="map-note">
          {missing} of {stops.length} stops could not be geocoded and are not shown on the map.
        </p>
      )}
      {geo.length === 0 && (
        <p className="map-note">No geocoded coordinates for this direction's stops yet.</p>
      )}
    </div>
  )
}
