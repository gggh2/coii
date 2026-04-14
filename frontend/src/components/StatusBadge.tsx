interface StatusBadgeProps {
  status: string
  showDot?: boolean
}

const STATUS_COLOR: Record<string, string> = {
  running: 'var(--green)',
  draft: 'var(--ink-3)',
  paused: 'var(--amber)',
  completed: 'var(--accent)',
}

const STATUS_BG: Record<string, string> = {
  running: 'var(--green-bg)',
  draft: 'var(--surface-3)',
  paused: 'var(--amber-bg)',
  completed: 'var(--accent-light)',
}

export function StatusBadge({ status, showDot = true }: StatusBadgeProps) {
  const color = STATUS_COLOR[status] || 'var(--ink-3)'
  const bg = STATUS_BG[status] || 'var(--surface-3)'
  return (
    <span
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        gap: 5,
        padding: '3px 8px',
        borderRadius: 99,
        fontSize: 11,
        fontWeight: 500,
        color,
        background: bg,
        letterSpacing: '0.01em',
        textTransform: 'capitalize',
      }}
    >
      {showDot && (
        <span
          style={{
            width: 5,
            height: 5,
            borderRadius: '50%',
            background: color,
            display: 'inline-block',
            animation: status === 'running' ? 'pulse 2s infinite' : undefined,
          }}
        />
      )}
      {status}
    </span>
  )
}
