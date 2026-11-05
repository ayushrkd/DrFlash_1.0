import { useState, useEffect, useCallback } from 'react'
import { api, type TaskResponse, type TaskEvent, type HealthResponse } from '../api'

export function useHealth() {
  const [health, setHealth] = useState<HealthResponse | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    api.health().then(setHealth).catch(e => setError(e.message))
    const interval = setInterval(() => {
      api.health().then(setHealth).catch(e => setError(e.message))
    }, 10000)
    return () => clearInterval(interval)
  }, [])

  return { health, error }
}

export function useTasks() {
  const [tasks, setTasks] = useState<TaskResponse[]>([])
  const [loading, setLoading] = useState(false)

  const refresh = useCallback(async () => {
    setLoading(true)
    try {
      const data = await api.listTasks()
      setTasks(data)
    } catch {
      // Silently handle — UI shows empty state
    }
    setLoading(false)
  }, [])

  useEffect(() => { refresh() }, [refresh])

  const create = useCallback(async (input: string) => {
    const task = await api.createTask(input)
    await refresh()
    return task
  }, [refresh])

  const run = useCallback(async (id: string) => {
    const result = await api.runTask(id)
    await refresh()
    return result
  }, [refresh])

  const cancel = useCallback(async (id: string) => {
    const result = await api.cancelTask(id)
    await refresh()
    return result
  }, [refresh])

  return { tasks, loading, refresh, create, run, cancel }
}

export function useTaskEvents(taskId: string | null) {
  const [events, setEvents] = useState<TaskEvent[]>([])

  useEffect(() => {
    if (!taskId) { setEvents([]); return }
    api.getEvents(taskId).then(setEvents).catch(() => setEvents([]))
  }, [taskId])

  return events
}
