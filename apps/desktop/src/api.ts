const API_BASE = '/api/v1'

export interface TaskResponse {
  task_id: string
  status: string
  input_text: string
  created_at: string
  updated_at: string
  error: string | null
}

export interface TaskEvent {
  event_id: string
  task_id: string
  event_type: string
  data: Record<string, unknown>
  timestamp: string
}

export interface ToolInfo {
  tool_id: string
  version: string
  description: string
  capabilities: Array<{
    action: string
    side_effect: string
    risk: string
    description: string
  }>
}

export interface HealthResponse {
  status: string
  version: string
  services: Record<string, unknown>
}

export interface PrivacyStatus {
  microphone: string
  screen_capture: string
  cloud_streaming: string
  local_wake_word: string
  data_transmission: string
}

async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const resp = await fetch(`${API_BASE}${path}`, {
    headers: { 'Content-Type': 'application/json' },
    ...init,
  })
  if (!resp.ok) {
    const err = await resp.json().catch(() => ({ detail: resp.statusText }))
    throw new Error(err.detail || `HTTP ${resp.status}`)
  }
  return resp.json()
}

export const api = {
  health: () => fetch('/health').then(r => r.json()) as Promise<HealthResponse>,
  privacy: () => apiFetch<PrivacyStatus>('/privacy/status'),
  tools: () => apiFetch<ToolInfo[]>('/tools'),
  metrics: () => apiFetch<Record<string, unknown>>('/metrics/summary'),

  createTask: (input_text: string) =>
    apiFetch<TaskResponse>('/tasks', {
      method: 'POST',
      body: JSON.stringify({ input_text }),
    }),

  getTask: (id: string) => apiFetch<TaskResponse>(`/tasks/${id}`),
  listTasks: () => apiFetch<TaskResponse[]>('/tasks'),

  runTask: (id: string) =>
    apiFetch<TaskResponse>(`/tasks/${id}/run`, { method: 'POST' }),

  cancelTask: (id: string) =>
    apiFetch<TaskResponse>(`/tasks/${id}/cancel`, { method: 'POST' }),

  getEvents: (id: string) => apiFetch<TaskEvent[]>(`/tasks/${id}/events`),
}
