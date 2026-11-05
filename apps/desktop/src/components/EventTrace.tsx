import type { TaskEvent } from '../api'

interface Props {
  events: TaskEvent[]
  taskId: string | null
}

const TYPE_COLORS: Record<string, string> = {
  'task.created': '#3b82f6',
  'task.transition.understanding': '#8b5cf6',
  'task.transition.planned': '#6366f1',
  'task.transition.policy_check': '#f59e0b',
  'task.transition.running': '#3b82f6',
  'task.transition.verifying': '#06b6d4',
  'task.transition.completed': '#22c55e',
  'task.transition.failed': '#ef4444',
  'task.transition.cancelled': '#666',
  'task.plan.updated': '#6366f1',
  'broker.policy_checked': '#f59e0b',
  'broker.executed': '#3b82f6',
  'broker.verified': '#22c55e',
  'broker.execution_error': '#ef4444',
  'broker.approval_required': '#ef4444',
}

export function EventTrace({ events, taskId }: Props) {
  if (!taskId) {
    return (
      <div style={styles.empty}>
        <div style={styles.emptyIcon}>◇</div>
        <div style={styles.emptyText}>Select a task to view its execution trace</div>
      </div>
    )
  }

  return (
    <div style={styles.container}>
      <h3 style={styles.heading}>Execution Trace</h3>
      <div style={styles.taskIdLabel}>Task: {taskId}</div>
      {events.length === 0 && (
        <div style={styles.noEvents}>No events recorded yet.</div>
      )}
      <div style={styles.timeline}>
        {events.map(event => (
          <div key={event.event_id} style={styles.event}>
            <div style={styles.eventDot}>
              <span style={{
                ...styles.dot,
                background: TYPE_COLORS[event.event_type] ?? '#555',
              }} />
              <span style={styles.eventLine} />
            </div>
            <div style={styles.eventContent}>
              <div style={styles.eventHeader}>
                <span style={{
                  ...styles.eventType,
                  color: TYPE_COLORS[event.event_type] ?? '#888',
                }}>
                  {event.event_type}
                </span>
                <span style={styles.eventTime}>
                  {new Date(event.timestamp).toLocaleTimeString()}
                </span>
              </div>
              {Object.keys(event.data).length > 0 && (
                <pre style={styles.eventData}>
                  {JSON.stringify(event.data, null, 2)}
                </pre>
              )}
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}

const styles: Record<string, React.CSSProperties> = {
  container: {
    padding: '20px',
  },
  heading: {
    fontSize: '13px',
    color: '#888',
    textTransform: 'uppercase',
    letterSpacing: '1px',
    marginBottom: '6px',
  },
  taskIdLabel: {
    fontSize: '11px',
    color: '#444',
    fontFamily: 'monospace',
    marginBottom: '16px',
  },
  empty: {
    display: 'flex',
    flexDirection: 'column',
    alignItems: 'center',
    justifyContent: 'center',
    height: '100%',
    gap: '12px',
  },
  emptyIcon: {
    fontSize: '48px',
    color: '#222',
  },
  emptyText: {
    color: '#444',
    fontSize: '14px',
  },
  noEvents: {
    color: '#555',
    fontSize: '13px',
    padding: '20px 0',
  },
  timeline: {
    display: 'flex',
    flexDirection: 'column',
    gap: '4px',
  },
  event: {
    display: 'flex',
    gap: '12px',
  },
  eventDot: {
    display: 'flex',
    flexDirection: 'column',
    alignItems: 'center',
    width: '16px',
    paddingTop: '6px',
  },
  dot: {
    width: '8px',
    height: '8px',
    borderRadius: '50%',
    flexShrink: 0,
  },
  eventLine: {
    flex: 1,
    width: '1px',
    background: '#1a1f2e',
    minHeight: '20px',
  },
  eventContent: {
    flex: 1,
    background: '#111318',
    borderRadius: '6px',
    padding: '10px 12px',
    border: '1px solid #1a1f2e',
    marginBottom: '4px',
  },
  eventHeader: {
    display: 'flex',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: '4px',
  },
  eventType: {
    fontSize: '12px',
    fontWeight: 600,
    fontFamily: 'monospace',
  },
  eventTime: {
    fontSize: '10px',
    color: '#555',
  },
  eventData: {
    fontSize: '11px',
    color: '#888',
    fontFamily: "'Cascadia Code', 'Fira Code', monospace",
    background: '#0a0a0f',
    borderRadius: '4px',
    padding: '8px',
    margin: '4px 0 0',
    overflow: 'auto',
    maxHeight: '200px',
    whiteSpace: 'pre-wrap',
    wordBreak: 'break-word',
  },
}
