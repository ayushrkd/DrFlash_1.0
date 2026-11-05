import { useState, useRef } from 'react'

interface Props {
  onSubmit: (input: string) => Promise<void>
}

export function CommandInput({ onSubmit }: Props) {
  const [input, setInput] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const inputRef = useRef<HTMLInputElement>(null)

  const handleSubmit = async () => {
    if (!input.trim() || submitting) return
    setSubmitting(true)
    try {
      await onSubmit(input.trim())
      setInput('')
    } catch (err) {
      console.error('Task submission failed:', err)
    }
    setSubmitting(false)
    inputRef.current?.focus()
  }

  return (
    <div style={styles.container}>
      <div style={styles.inputRow}>
        <span style={styles.prompt}>❯</span>
        <input
          ref={inputRef}
          style={styles.input}
          placeholder="What would you like me to do?"
          value={input}
          onChange={e => setInput(e.target.value)}
          onKeyDown={e => { if (e.key === 'Enter') handleSubmit() }}
          disabled={submitting}
          autoFocus
        />
        <button
          style={{
            ...styles.button,
            opacity: submitting || !input.trim() ? 0.5 : 1,
          }}
          onClick={handleSubmit}
          disabled={submitting || !input.trim()}
        >
          {submitting ? '...' : 'Execute'}
        </button>
      </div>
    </div>
  )
}

const styles: Record<string, React.CSSProperties> = {
  container: {
    padding: '16px 20px',
    borderBottom: '1px solid #1a1f2e',
  },
  inputRow: {
    display: 'flex',
    alignItems: 'center',
    gap: '10px',
    background: '#111318',
    borderRadius: '8px',
    padding: '10px 14px',
    border: '1px solid #1e2433',
  },
  prompt: {
    color: '#3b82f6',
    fontSize: '16px',
    fontWeight: 700,
  },
  input: {
    flex: 1,
    background: 'transparent',
    border: 'none',
    outline: 'none',
    color: '#e0e0e0',
    fontSize: '14px',
    fontFamily: "'Segoe UI', system-ui, sans-serif",
  },
  button: {
    background: '#3b82f6',
    color: '#fff',
    border: 'none',
    borderRadius: '6px',
    padding: '6px 16px',
    fontSize: '13px',
    fontWeight: 600,
    cursor: 'pointer',
    transition: 'opacity 0.2s',
  },
}
