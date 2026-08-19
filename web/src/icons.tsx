// Brand map pin: black teardrop with the orange destination dot at its centre.
export function PinIcon({ size = 14 }: { size?: number }) {
  return (
    <svg viewBox="0 0 24 24" width={size} height={size} aria-hidden="true" style={{ verticalAlign: '-2px' }}>
      <path
        d="M12 2c-3.87 0-7 3.13-7 7 0 5.25 7 13 7 13s7-7.75 7-13c0-3.87-3.13-7-7-7z"
        fill="#000000"
      />
      <circle cx="12" cy="9" r="2.6" fill="#ff4500" />
    </svg>
  )
}
