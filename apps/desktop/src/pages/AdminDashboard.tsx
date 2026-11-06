import { useState, useEffect, useCallback } from 'react'
import { useNavigate } from 'react-router-dom'
import { api, type SystemStatus, type TaskResponse, type TaskEvent } from '../api'
import {
  Activity, Bot, Brain, ChevronRight, Clock, Cpu, Database,
  Eye, HardDrive, MessageSquare, Mic, MicOff, Monitor,
  Power, RefreshCw, Shield, ShieldCheck, Sparkles, Terminal,
  TrendingUp, Volume2, Wifi, WifiOff, Zap
} from 'lucide-react'

export function AdminDashboard() {
  const navigate = useNavigate()
  const [status, setStatus] = useState<SystemStatus | null>(null)
  const [tasks, setTasks] = useState<TaskResponse[]>([])
  const [activity, setActivity] = useState<TaskEvent[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const refresh = useCallback(async () => {
    try {
      const [s, t, a] = await Promise.all([
        api.systemStatus(),
        api.listTasks(20),
        api.activity(30),
      ])
      setStatus(s)
      setTasks(t)
      setActivity(a)
      setError(null)
    } catch (e: any) {
      setError(e.message)
    }
    setLoading(false)
  }, [])

  useEffect(() => {
    refresh()
    const interval = setInterval(refresh, 5000)
    return () => clearInterval(interval)
  }, [refresh])

  if (loading && !status) {
    return <div className="animate-pulse" style={{ height: '100vh', display: 'grid', placeItems: 'center', color: 'var(--text-muted)' }}>
      <div style={{ textAlign: 'center' }}>
        <Sparkles size={48} style={{ marginBottom: 16, color: 'var(--accent)' }} />
        <div style={{ fontSize: 18, fontWeight: 600 }}>Initializing JARVIS...</div>
      </div>
    </div>
  }

  const isOnline = status?.system.status === 'online'
  const providers = status?.models.providers || {}
  const ollamaOnline = (providers as any)?.ollama?.status === 'healthy'

  return (
    <div style={S.root}>
      {/* ─── Top Bar ─────────────────────────────── */}
      <header style={S.header}>
        <div style={S.headerLeft}>
          <div style={S.logoMark}>
            <Zap size={18} color="var(--accent)" />
          </div>
          <span style={S.logoText}>JARVIS</span>
          <span style={S.versionBadge}>v{status?.system.version}</span>
        </div>
        <div style={S.headerCenter}>
          <StatusPill
            icon={<Power size={11} />}
            label="System"
            value={isOnline ? 'Online' : 'Offline'}
            color={isOnline ? 'var(--success)' : 'var(--error)'}
          />
          <StatusPill
            icon={<Brain size={11} />}
            label="LLM"
            value={ollamaOnline ? 'Ollama' : 'Mock'}
            color={ollamaOnline ? 'var(--success)' : 'var(--warning)'}
          />
          <StatusPill
            icon={<MicOff size={11} />}
            label="Mic"
            value="Off"
            color="var(--text-dim)"
          />
          <StatusPill
            icon={<WifiOff size={11} />}
            label="Cloud"
            value="Off"
            color="var(--text-dim)"
          />
          <StatusPill
            icon={<Shield size={11} />}
            label="Policy"
            value="Active"
            color="var(--success)"
          />
        </div>
        <div style={S.headerRight}>
          <button style={S.headerBtn} onClick={() => navigate('/chat')}>
            <MessageSquare size={15} />
            Open Chat
          </button>
          <button style={S.headerBtnIcon} onClick={refresh} title="Refresh">
            <RefreshCw size={15} />
          </button>
        </div>
      </header>

      {/* ─── Content ─────────────────────────────── */}
      <div style={S.content}>
        {/* ─── Stat Cards Row ──────────────────── */}
        <div style={S.statRow}>
          <StatCard
            icon={<Clock size={18} />}
            label="Uptime"
            value={status?.system.uptime_display || '—'}
            color="var(--accent)"
          />
          <StatCard
            icon={<Activity size={18} />}
            label="Tasks"
            value={String(status?.tasks.total || 0)}
            sub={`${status?.tasks.COMPLETED || 0} completed`}
            color="var(--success)"
          />
          <StatCard
            icon={<MessageSquare size={18} />}
            label="Conversations"
            value={String(status?.conversations.active || 0)}
            sub={`${status?.conversations.total_messages || 0} messages`}
            color="var(--purple)"
          />
          <StatCard
            icon={<Brain size={18} />}
            label="Model Calls"
            value={String(status?.models.total_requests || 0)}
            sub={`$${(status?.models.total_cost_usd || 0).toFixed(4)} spent`}
            color="var(--info)"
          />
          <StatCard
            icon={<ShieldCheck size={18} />}
            label="Tools"
            value={String(status?.tools.length || 0)}
            sub="registered"
            color="var(--warning)"
          />
        </div>

        {/* ─── Main Grid ──────────────────────── */}
        <div style={S.grid}>
          {/* Activity Feed */}
          <div style={S.card}>
            <div style={S.cardHeader}>
              <div style={S.cardTitle}><Activity size={15} /> Live Activity</div>
              <span style={S.cardBadge}>{activity.length} events</span>
            </div>
            <div style={S.activityList}>
              {activity.length === 0 && (
                <div style={S.emptyState}>No activity yet</div>
              )}
              {activity.slice(0, 25).map((ev, i) => (
                <ActivityItem key={ev.event_id || i} event={ev} />
              ))}
            </div>
          </div>

          {/* Tasks Panel */}
          <div style={S.card}>
            <div style={S.cardHeader}>
              <div style={S.cardTitle}><Terminal size={15} /> Tasks</div>
              <span style={S.cardBadge}>{tasks.length}</span>
            </div>
            <div style={S.taskList}>
              {tasks.length === 0 && (
                <div style={S.emptyState}>No tasks yet. Use chat to create tasks.</div>
              )}
              {tasks.map(task => (
                <TaskItem key={task.task_id} task={task} />
              ))}
            </div>
          </div>

          {/* System Info Panel */}
          <div style={S.card}>
            <div style={S.cardHeader}>
              <div style={S.cardTitle}><Cpu size={15} /> System</div>
            </div>
            <div style={S.systemInfo}>
              <InfoRow label="Status" value={status?.system.status || '—'} color="var(--success)" />
              <InfoRow label="Version" value={status?.system.version || '—'} />
              <InfoRow label="Policy Engine" value="Deny-by-default" color="var(--success)" />
              <InfoRow label="Task Store" value="SQLite + WAL" />
              <InfoRow label="Mic" value="Off" color="var(--text-dim)" />
              <InfoRow label="Cloud Stream" value="Off" color="var(--text-dim)" />
              <InfoRow label="Wake Word" value="Off" color="var(--text-dim)" />

              <div style={S.sectionDivider} />
              <div style={{ ...S.cardTitle, fontSize: 11, marginBottom: 8 }}><Brain size={13} /> Models</div>
              {Object.entries(providers).map(([name, info]: [string, any]) => (
                <InfoRow
                  key={name}
                  label={name}
                  value={info.status}
                  color={info.status === 'healthy' ? 'var(--success)' : 'var(--error)'}
                  extra={info.models?.length ? `${info.models.length} models` : undefined}
                />
              ))}

              <div style={S.sectionDivider} />
              <div style={{ ...S.cardTitle, fontSize: 11, marginBottom: 8 }}><Shield size={13} /> Privacy</div>
              {status && Object.entries(status.privacy).map(([k, v]) => (
                <InfoRow key={k} label={k.replace(/_/g, ' ')} value={v} color={v === 'off' ? 'var(--text-dim)' : 'var(--warning)'} />
              ))}
            </div>
          </div>
        </div>
      </div>

      {error && (
        <div style={S.errorBar}>
          ⚠ Connection error: {error}
        </div>
      )}
    </div>
  )
}


// ─── Sub-components ──────────────────────────────────────────

function StatusPill({ icon, label, value, color }: { icon: React.ReactNode; label: string; value: string; color: string }) {
  return (
    <div style={S.pill}>
      <span style={{ color }}>{icon}</span>
      <span style={S.pillLabel}>{label}</span>
      <span style={{ ...S.pillValue, color }}>{value}</span>
    </div>
  )
}

function StatCard({ icon, label, value, sub, color }: {
  icon: React.ReactNode; label: string; value: string; sub?: string; color: string
}) {
  return (
    <div style={S.statCard}>
      <div style={{ ...S.statIcon, color, background: `${color}15` }}>{icon}</div>
      <div>
        <div style={S.statValue}>{value}</div>
        <div style={S.statLabel}>{label}</div>
        {sub && <div style={S.statSub}>{sub}</div>}
      </div>
    </div>
  )
}

const EVENT_COLORS: Record<string, string> = {
  'task.created': 'var(--accent)',
  'task.transition.completed': 'var(--success)',
  'task.transition.failed': 'var(--error)',
  'task.transition.cancelled': 'var(--text-dim)',
  'task.transition.running': 'var(--accent)',
  'task.transition.understanding': 'var(--purple)',
  'task.transition.planned': 'var(--info)',
  'broker.policy_checked': 'var(--warning)',
  'broker.executed': 'var(--accent)',
  'broker.verified': 'var(--success)',
  'broker.execution_error': 'var(--error)',
}

function ActivityItem({ event }: { event: TaskEvent }) {
  const color = EVENT_COLORS[event.type] || 'var(--text-muted)'
  const time = new Date(event.timestamp).toLocaleTimeString()
  return (
    <div style={S.activityItem}>
      <div style={{ ...S.activityDot, background: color }} />
      <div style={S.activityContent}>
        <span style={{ ...S.activityType, color }}>{event.type.replace('task.transition.', '').replace('broker.', '🔒 ')}</span>
        <span style={S.activityTime}>{time}</span>
      </div>
    </div>
  )
}

const STATUS_COLORS: Record<string, string> = {
  COMPLETED: 'var(--success)', FAILED: 'var(--error)', CANCELLED: 'var(--text-dim)',
  RUNNING: 'var(--accent)', CREATED: 'var(--text-muted)', VERIFYING: 'var(--info)',
  PLANNED: 'var(--purple)', UNDERSTANDING: 'var(--purple)', AWAITING_APPROVAL: 'var(--warning)',
}

function TaskItem({ task }: { task: TaskResponse }) {
  const color = STATUS_COLORS[task.status] || 'var(--text-muted)'
  return (
    <div style={S.taskItem}>
      <div style={{ ...S.taskStatus, color, borderColor: color }}>{task.status}</div>
      <div style={S.taskText}>{task.input_text}</div>
      {task.error && <div style={S.taskError}>{task.error}</div>}
      <div style={S.taskMeta}>{new Date(task.created_at).toLocaleString()}</div>
    </div>
  )
}

function InfoRow({ label, value, color, extra }: { label: string; value: string; color?: string; extra?: string }) {
  return (
    <div style={S.infoRow}>
      <span style={S.infoLabel}>{label}</span>
      <span style={{ ...S.infoValue, color: color || 'var(--text-secondary)' }}>{value}</span>
      {extra && <span style={S.infoExtra}>{extra}</span>}
    </div>
  )
}


// ─── Styles ──────────────────────────────────────────────────

const S: Record<string, React.CSSProperties> = {
  root: { height: '100vh', display: 'flex', flexDirection: 'column', background: 'var(--bg-primary)' },

  // Header
  header: { display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '10px 20px', borderBottom: '1px solid var(--border)', background: 'var(--bg-secondary)', flexShrink: 0, zIndex: 10 },
  headerLeft: { display: 'flex', alignItems: 'center', gap: 10 },
  logoMark: { width: 32, height: 32, borderRadius: 8, background: 'var(--accent-glow)', display: 'grid', placeItems: 'center', border: '1px solid rgba(59,130,246,0.3)' },
  logoText: { fontSize: 16, fontWeight: 800, letterSpacing: 2, color: 'var(--text-primary)' },
  versionBadge: { fontSize: 10, color: 'var(--text-dim)', background: 'var(--bg-elevated)', padding: '2px 6px', borderRadius: 4, fontFamily: 'var(--font-mono)' },
  headerCenter: { display: 'flex', gap: 6, alignItems: 'center' },
  headerRight: { display: 'flex', gap: 8, alignItems: 'center' },
  headerBtn: { display: 'flex', alignItems: 'center', gap: 6, background: 'var(--accent)', color: '#fff', border: 'none', borderRadius: 'var(--radius)', padding: '7px 14px', fontSize: 13, fontWeight: 600, cursor: 'pointer', transition: 'background 0.2s' },
  headerBtnIcon: { display: 'grid', placeItems: 'center', background: 'var(--bg-elevated)', color: 'var(--text-secondary)', border: '1px solid var(--border)', borderRadius: 'var(--radius)', width: 32, height: 32, cursor: 'pointer' },

  // Status pills
  pill: { display: 'flex', alignItems: 'center', gap: 4, padding: '4px 10px', borderRadius: 20, background: 'var(--bg-card)', border: '1px solid var(--border)', fontSize: 11 },
  pillLabel: { color: 'var(--text-muted)', fontWeight: 500 },
  pillValue: { fontWeight: 600 },

  // Content
  content: { flex: 1, overflow: 'auto', padding: 20, display: 'flex', flexDirection: 'column', gap: 20 },

  // Stat row
  statRow: { display: 'grid', gridTemplateColumns: 'repeat(5, 1fr)', gap: 12 },
  statCard: { display: 'flex', alignItems: 'center', gap: 14, padding: '16px 18px', background: 'var(--bg-card)', borderRadius: 'var(--radius-lg)', border: '1px solid var(--border)' },
  statIcon: { width: 40, height: 40, borderRadius: 10, display: 'grid', placeItems: 'center', flexShrink: 0 },
  statValue: { fontSize: 22, fontWeight: 700, lineHeight: 1.1 },
  statLabel: { fontSize: 12, color: 'var(--text-muted)', fontWeight: 500 },
  statSub: { fontSize: 10, color: 'var(--text-dim)', marginTop: 1 },

  // Grid
  grid: { display: 'grid', gridTemplateColumns: '1fr 1fr 340px', gap: 16, flex: 1, minHeight: 0 },
  card: { background: 'var(--bg-card)', borderRadius: 'var(--radius-lg)', border: '1px solid var(--border)', display: 'flex', flexDirection: 'column', overflow: 'hidden' },
  cardHeader: { display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '14px 18px', borderBottom: '1px solid var(--border)' },
  cardTitle: { display: 'flex', alignItems: 'center', gap: 8, fontSize: 13, fontWeight: 600, color: 'var(--text-secondary)', textTransform: 'uppercase' as const, letterSpacing: '0.5px' },
  cardBadge: { fontSize: 11, color: 'var(--text-dim)', fontFamily: 'var(--font-mono)' },

  // Activity
  activityList: { flex: 1, overflow: 'auto', padding: '8px 0' },
  activityItem: { display: 'flex', alignItems: 'center', gap: 10, padding: '6px 18px' },
  activityDot: { width: 6, height: 6, borderRadius: 3, flexShrink: 0 },
  activityContent: { display: 'flex', justifyContent: 'space-between', alignItems: 'center', flex: 1, minWidth: 0 },
  activityType: { fontSize: 12, fontWeight: 500, fontFamily: 'var(--font-mono)', whiteSpace: 'nowrap' as const, overflow: 'hidden', textOverflow: 'ellipsis' },
  activityTime: { fontSize: 10, color: 'var(--text-dim)', flexShrink: 0, marginLeft: 8 },

  // Tasks
  taskList: { flex: 1, overflow: 'auto', padding: 8 },
  taskItem: { padding: '10px 12px', borderRadius: 'var(--radius)', border: '1px solid var(--border)', marginBottom: 6, transition: 'border-color 0.2s' },
  taskStatus: { display: 'inline-block', fontSize: 9, fontWeight: 700, padding: '2px 8px', borderRadius: 4, border: '1px solid', letterSpacing: '0.5px', marginBottom: 4, textTransform: 'uppercase' as const },
  taskText: { fontSize: 13, color: 'var(--text-secondary)', lineHeight: 1.4 },
  taskError: { fontSize: 11, color: 'var(--error)', marginTop: 4 },
  taskMeta: { fontSize: 10, color: 'var(--text-dim)', marginTop: 4, fontFamily: 'var(--font-mono)' },

  // System info
  systemInfo: { flex: 1, overflow: 'auto', padding: '12px 18px' },
  infoRow: { display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '5px 0', borderBottom: '1px solid rgba(30,36,51,0.5)' },
  infoLabel: { fontSize: 12, color: 'var(--text-muted)', textTransform: 'capitalize' as const },
  infoValue: { fontSize: 12, fontWeight: 600 },
  infoExtra: { fontSize: 10, color: 'var(--text-dim)', marginLeft: 8 },
  sectionDivider: { height: 1, background: 'var(--border)', margin: '12px 0' },

  // States
  emptyState: { padding: 32, textAlign: 'center' as const, color: 'var(--text-dim)', fontSize: 13 },
  errorBar: { position: 'fixed' as const, bottom: 0, left: 0, right: 0, padding: '8px 20px', background: 'rgba(239,68,68,0.1)', borderTop: '1px solid var(--error)', color: 'var(--error)', fontSize: 12, textAlign: 'center' as const },
}
