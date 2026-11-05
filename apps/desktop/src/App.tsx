import { useState } from 'react'
import { useHealth, useTasks, useTaskEvents } from './hooks/useJarvis'
import { StatusBar } from './components/StatusBar'
import { CommandInput } from './components/CommandInput'
import { TaskList } from './components/TaskList'
import { EventTrace } from './components/EventTrace'

export function App() {
  const { health, error: healthError } = useHealth()
  const { tasks, loading, create, run, cancel, refresh } = useTasks()
  const [selectedTaskId, setSelectedTaskId] = useState<string | null>(null)
  const events = useTaskEvents(selectedTaskId)

  const handleSubmit = async (input: string) => {
    const task = await create(input)
    const result = await run(task.task_id)
    setSelectedTaskId(result.task_id)
    refresh()
  }

  return (
    <div style={styles.container}>
      <header style={styles.header}>
        <div style={styles.logo}>
          <span style={styles.logoIcon}>◆</span>
          <h1 style={styles.title}>JARVIS</h1>
          <span style={styles.subtitle}>Personal AI Operating System</span>
        </div>
        <StatusBar health={health} error={healthError} />
      </header>

      <main style={styles.main}>
        <div style={styles.leftPanel}>
          <CommandInput onSubmit={handleSubmit} />
          <TaskList
            tasks={tasks}
            loading={loading}
            selectedId={selectedTaskId}
            onSelect={setSelectedTaskId}
            onCancel={cancel}
            onRefresh={refresh}
          />
        </div>

        <div style={styles.rightPanel}>
          <EventTrace events={events} taskId={selectedTaskId} />
        </div>
      </main>
    </div>
  )
}

const styles: Record<string, React.CSSProperties> = {
  container: {
    minHeight: '100vh',
    display: 'flex',
    flexDirection: 'column',
    background: 'linear-gradient(180deg, #0a0a0f 0%, #0d1117 100%)',
  },
  header: {
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'space-between',
    padding: '12px 24px',
    borderBottom: '1px solid #1a1f2e',
    background: 'rgba(10, 10, 15, 0.95)',
  },
  logo: {
    display: 'flex',
    alignItems: 'center',
    gap: '10px',
  },
  logoIcon: {
    fontSize: '24px',
    color: '#3b82f6',
  },
  title: {
    fontSize: '20px',
    fontWeight: 700,
    color: '#e0e0e0',
    letterSpacing: '2px',
  },
  subtitle: {
    fontSize: '11px',
    color: '#666',
    marginLeft: '8px',
    textTransform: 'uppercase' as const,
    letterSpacing: '1px',
  },
  main: {
    display: 'flex',
    flex: 1,
    overflow: 'hidden',
  },
  leftPanel: {
    flex: 1,
    display: 'flex',
    flexDirection: 'column',
    borderRight: '1px solid #1a1f2e',
    minWidth: '400px',
  },
  rightPanel: {
    flex: 1,
    overflow: 'auto',
  },
}
