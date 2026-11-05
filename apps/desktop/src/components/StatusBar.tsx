import type { HealthResponse } from '../api'

interface Props {
  health: HealthResponse | null
  error: string | null
}

export function StatusBar({ health, error }: Props) {
  const isHealthy = health?.status === 'healthy'

  return (
    <div style={styles.bar}>
      <div style={styles.indicator}>
        <span style={{
          ...styles.dot,
          background: error ? '#ef4444' : isHealthy ? '#22c55e' : '#f59e0b',
        }} />
        <span style={styles.text}>
          {error ? 'Disconnected' : isHealthy ? 'Connected' : 'Checking...'}
        </span>
      </div>
      <div style={styles.badges}>
        <Badge label="MIC" value="OFF" color="#666" />
        <Badge label="CLOUD" value="OFF" color="#666" />
        <Badge label="v" value={health?.version ?? '—'} color="#3b82f6" />
      </div>
    </div>
  )
}

function Badge({ label, value, color }: { label: string; value: string; color: string }) {
  return (
    <span style={{ ...styles.badge, borderColor: color }}>
      <span style={{ color: '#888', fontSize: '10px' }}>{label}</span>
      <span style={{ color, fontSize: '11px', fontWeight: 600 }}>{value}</span>
    </span>
  )
}

const styles: Record<string, React.CSSProperties> = {
  bar: {
    display: 'flex',
    alignItems: 'center',
    gap: '16px',
  },
  indicator: {
    display: 'flex',
    alignItems: 'center',
    gap: '6px',
  },
  dot: {
    width: '8px',
    height: '8px',
    borderRadius: '50%',
    display: 'inline-block',
  },
  text: {
    fontSize: '12px',
    color: '#888',
  },
  badges: {
    display: 'flex',
    gap: '8px',
  },
  badge: {
    display: 'flex',
    gap: '4px',
    alignItems: 'center',
    padding: '2px 8px',
    borderRadius: '4px',
    border: '1px solid',
    background: 'rgba(255,255,255,0.03)',
  },
}
