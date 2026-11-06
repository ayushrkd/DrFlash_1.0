const API = '/api/v1'

// ─── Types ─────────────────────────────────────────────────

export interface TaskResponse {
  task_id: string; status: string; input_text: string
  created_at: string; updated_at: string; error: string | null
}

export interface TaskEvent {
  event_id: string; task_id: string; event_type: string
  data: Record<string, unknown>; timestamp: string
}

export interface SystemStatus {
  system: { status: string; version: string; uptime_seconds: number; uptime_display: string }
  models: { providers: Record<string, { status: string; models?: string[] }>; total_cost_usd: number; total_requests: number }
  tasks: Record<string, number>
  tools: Array<{ tool_id: string; capabilities: number }>
  conversations: { active: number; total_messages: number }
  privacy: Record<string, string>
  metrics: Record<string, unknown>
}

export interface ConversationInfo {
  conversation_id: string; message_count: number
  last_message: string; updated_at: string
}

export interface ConversationFull {
  conversation_id: string
  messages: Array<{ role: string; content: string; timestamp: string; metadata: Record<string, unknown> }>
  created_at: string; updated_at: string; message_count: number
}

// ─── Fetch helper ──────────────────────────────────────────

async function f<T>(path: string, init?: RequestInit): Promise<T> {
  const resp = await fetch(path.startsWith('/') ? path : `${API}${path}`, {
    headers: { 'Content-Type': 'application/json' },
    ...init,
  })
  if (!resp.ok) {
    const err = await resp.json().catch(() => ({ detail: resp.statusText }))
    throw new Error(err.detail || `HTTP ${resp.status}`)
  }
  return resp.json()
}

// ─── API ───────────────────────────────────────────────────

export const api = {
  // System
  health: () => f<{ status: string; version: string; uptime_seconds: number }>('/health'),
  systemStatus: () => f<SystemStatus>(`${API}/system/status`),
  activity: (limit = 50) => f<TaskEvent[]>(`${API}/system/activity?limit=${limit}`),
  privacy: () => f<Record<string, string>>(`${API}/privacy/status`),

  // Tasks
  createTask: (text: string) => f<TaskResponse>(`${API}/tasks`, { method: 'POST', body: JSON.stringify({ input_text: text }) }),
  listTasks: (limit = 50) => f<TaskResponse[]>(`${API}/tasks?limit=${limit}`),
  getTask: (id: string) => f<TaskResponse>(`${API}/tasks/${id}`),
  runTask: (id: string) => f<TaskResponse>(`${API}/tasks/${id}/run`, { method: 'POST' }),
  cancelTask: (id: string) => f<TaskResponse>(`${API}/tasks/${id}/cancel`, { method: 'POST' }),
  taskEvents: (id: string) => f<TaskEvent[]>(`${API}/tasks/${id}/events`),

  // Chat
  chat: (message: string, conversationId = 'default') =>
    f<{ conversation_id: string; message: string; metadata: Record<string, unknown> }>(
      `${API}/chat`, { method: 'POST', body: JSON.stringify({ message, conversation_id: conversationId }) }
    ),

  streamChat: async function* (message: string, conversationId = 'default'): AsyncGenerator<string> {
    const resp = await fetch(`${API}/chat/stream`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ message, conversation_id: conversationId }),
    })
    if (!resp.ok) throw new Error(`Stream failed: ${resp.status}`)
    const reader = resp.body?.getReader()
    if (!reader) return
    const decoder = new TextDecoder()
    while (true) {
      const { done, value } = await reader.read()
      if (done) break
      const text = decoder.decode(value, { stream: true })
      for (const line of text.split('\n')) {
        if (line.startsWith('data: ')) {
          const data = line.slice(6)
          if (data === '[DONE]') return
          yield data
        }
      }
    }
  },

  conversations: () => f<ConversationInfo[]>(`${API}/conversations`),
  conversation: (id: string) => f<ConversationFull>(`${API}/conversations/${id}`),
  deleteConversation: (id: string) => f<{ deleted: boolean }>(`${API}/conversations/${id}`, { method: 'DELETE' }),

  // Models/Tools
  models: () => f<Record<string, unknown>>(`${API}/models`),
  tools: () => f<Array<{ tool_id: string; version: string; description: string; capabilities: unknown[] }>>(`${API}/tools`),
}
