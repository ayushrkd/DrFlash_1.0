import type { TaskResponse } from '../api'

const STATUS_COLORS: Record<string, string> = {
  CREATED: '#f59e0b',
  UNDERSTANDING: '#8b5cf6',
  PLANNED: '#6366f1',
  POLICY_CHECK: '#f59e0b',
  AWAITING_APPROVAL: '#ef4444',
  RUNNING: '#3b82f6',
  VERIFYING: '#06b6d4',
  COMPLETED: '#22c55e',
  FAILED: '#ef4444',
  CANCELLED: '#666',
  RETRYING: '#f59e0b',
  REPLANNING: '#8b5cf6',
}

interface Props {
  tasks: TaskResponse[]
  loading: boolean
  selectedId: string | null
  onSelect: (id: string) => void
  onCancel: (id: string) => void
  onRefresh: () => void
}

export function TaskList({ tasks, loading, selectedId, onSelect, onCancel, onRefresh }: Props) {
  return (
    <div style={styles.container}>
      <div style={styles.header}>
        <h3 style={styles.heading}>Tasks</h3>
        <button style={styles.refreshBtn} onClick={onRefresh} title="Refresh">
          ↻
        </button>
      </div>
      {tasks.length === 0 && !loading && (
        <div style={styles.empty}>No tasks yet. Submit a request above.</div>
      )}
      {tasks.map(task => (
        <div
          key={task.task_id}
          style={{
            ...styles.task,
            borderColor: task.task_id === selectedId ? '#3b82f6' : '#1a1f2e',
            background: task.task_id === selectedId ? 'rgba(59,130,246,0.05)' : 'transparent',
          }}
          onClick={() => onSelect(task.task_id)}
        >
          <div style={styles.taskHeader}>
            <span style={{
              ...styles.statusBadge,
              color: STATUS_COLORS[task.status] ?? '#888',
              borderColor: STATUS_COLORS[task.status] ?? '#888',
            }}>
              {task.status}
            </span>
            <span style={styles.time}>
              {new Date(task.created_at).toLocaleTimeString()}
            </span>
          </div>
          <div style={styles.taskInput}>{task.input_text}</div>
          {task.error && <div style={styles.error}>{task.error}</div>}
          <div style={styles.taskFooter}>
            <span style={styles.taskId}>{task.task_id.slice(0, 12)}…</span>
            {!['COMPLETED', 'FAILED', 'CANCELLED'].includes(task.status) && (
              <button
                style={styles.cancelBtn}
                onClick={e => { e.stopPropagation(); onCancel(task.task_id) }}
              >
                Cancel
              </button>
            )}
          </div>
        </div>
      ))}
    </div>
  )
}

const styles: Record<string, React.CSSProperties> = {
  container: {
    flex: 1,
    overflow: 'auto',
    padding: '12px 20px',
  },
  header: {
    display: 'flex',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: '12px',
  },
  heading: {
    fontSize: '13px',
    color: '#888',
    textTransform: 'uppercase',
    letterSpacing: '1px',
  },
  refreshBtn: {
    background: 'none',
    border: '1px solid #333',
    color: '#888',
    borderRadius: '4px',
    padding: '2px 8px',
    cursor: 'pointer',
    fontSize: '14px',
  },
  empty: {
    color: '#555',
    fontSize: '13px',
    textAlign: 'center',
    padding: '40px 0',
  },
  task: {
    padding: '12px',
    borderRadius: '8px',
    border: '1px solid #1a1f2e',
    marginBottom: '8px',
    cursor: 'pointer',
    transition: 'border-color 0.2s',
  },
  taskHeader: {
    display: 'flex',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: '6px',
  },
  statusBadge: {
    fontSize: '10px',
    fontWeight: 700,
    padding: '2px 8px',
    borderRadius: '4px',
    border: '1px solid',
    letterSpacing: '0.5px',
  },
  time: {
    fontSize: '11px',
    color: '#555',
  },
  taskInput: {
    fontSize: '13px',
    color: '#ccc',
    lineHeight: 1.4,
    marginBottom: '6px',
  },
  error: {
    fontSize: '12px',
    color: '#ef4444',
    marginBottom: '4px',
  },
  taskFooter: {
    display: 'flex',
    justifyContent: 'space-between',
    alignItems: 'center',
  },
  taskId: {
    fontSize: '10px',
    color: '#444',
    fontFamily: 'monospace',
  },
  cancelBtn: {
    background: 'none',
    border: '1px solid #ef4444',
    color: '#ef4444',
    borderRadius: '4px',
    padding: '2px 10px',
    fontSize: '11px',
    cursor: 'pointer',
  },
}
