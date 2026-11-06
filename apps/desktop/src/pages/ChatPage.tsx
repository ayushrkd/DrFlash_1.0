import { useState, useRef, useEffect, useCallback } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { api } from '../api'
import {
  ArrowLeft, ArrowUp, Bot, Loader2, Mic, MicOff,
  Plus, Settings, Sparkles, Square, User, Volume2,
  Trash2, MessageSquare
} from 'lucide-react'

interface ChatMessage {
  role: 'user' | 'assistant'
  content: string
  timestamp: string
  metadata?: Record<string, unknown>
  streaming?: boolean
}

export function ChatPage() {
  const navigate = useNavigate()
  const { conversationId: paramConvId } = useParams()
  const [conversationId, setConversationId] = useState(paramConvId || `conv_${Date.now()}`)
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [input, setInput] = useState('')
  const [streaming, setStreaming] = useState(false)
  const [convList, setConvList] = useState<Array<{ conversation_id: string; message_count: number; last_message: string }>>([])
  const [showSidebar, setShowSidebar] = useState(false)
  const bottomRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLTextAreaElement>(null)

  // Load conversation history
  useEffect(() => {
    if (paramConvId) {
      api.conversation(paramConvId).then(conv => {
        setMessages(conv.messages.map(m => ({
          role: m.role as 'user' | 'assistant',
          content: m.content,
          timestamp: m.timestamp,
          metadata: m.metadata,
        })))
      }).catch(() => {})
    }
  }, [paramConvId])

  // Load conversation list
  useEffect(() => {
    api.conversations().then(setConvList).catch(() => {})
  }, [messages.length])

  // Auto scroll
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  const sendMessage = useCallback(async () => {
    if (!input.trim() || streaming) return
    const userMsg = input.trim()
    setInput('')
    setStreaming(true)

    // Add user message
    setMessages(prev => [...prev, {
      role: 'user', content: userMsg,
      timestamp: new Date().toISOString(),
    }])

    // Add empty assistant message for streaming
    setMessages(prev => [...prev, {
      role: 'assistant', content: '', streaming: true,
      timestamp: new Date().toISOString(),
    }])

    try {
      let accumulated = ''
      for await (const token of api.streamChat(userMsg, conversationId)) {
        accumulated += token
        setMessages(prev => {
          const updated = [...prev]
          const last = updated[updated.length - 1]
          if (last.role === 'assistant') {
            updated[updated.length - 1] = { ...last, content: accumulated }
          }
          return updated
        })
      }
      // Mark streaming done
      setMessages(prev => {
        const updated = [...prev]
        const last = updated[updated.length - 1]
        if (last.role === 'assistant') {
          updated[updated.length - 1] = { ...last, streaming: false }
        }
        return updated
      })
    } catch (err: any) {
      setMessages(prev => {
        const updated = [...prev]
        const last = updated[updated.length - 1]
        if (last.role === 'assistant') {
          updated[updated.length - 1] = {
            ...last,
            content: `Connection error: ${err.message}. Is the server running?`,
            streaming: false,
          }
        }
        return updated
      })
    }

    setStreaming(false)
    inputRef.current?.focus()
  }, [input, streaming, conversationId])

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      sendMessage()
    }
  }

  const newConversation = () => {
    const newId = `conv_${Date.now()}`
    setConversationId(newId)
    setMessages([])
    navigate(`/chat/${newId}`)
  }

  return (
    <div style={S.root}>
      {/* Sidebar */}
      {showSidebar && (
        <div style={S.sidebar}>
          <div style={S.sidebarHeader}>
            <span style={S.sidebarTitle}>Conversations</span>
            <button style={S.iconBtn} onClick={newConversation} title="New chat">
              <Plus size={16} />
            </button>
          </div>
          <div style={S.convList}>
            {convList.map(c => (
              <button
                key={c.conversation_id}
                style={{
                  ...S.convItem,
                  background: c.conversation_id === conversationId ? 'var(--bg-elevated)' : 'transparent',
                }}
                onClick={() => {
                  setConversationId(c.conversation_id)
                  navigate(`/chat/${c.conversation_id}`)
                }}
              >
                <MessageSquare size={14} color="var(--text-dim)" />
                <div style={S.convItemText}>
                  <div style={S.convItemTitle}>{c.last_message || 'New conversation'}</div>
                  <div style={S.convItemMeta}>{c.message_count} messages</div>
                </div>
              </button>
            ))}
          </div>
        </div>
      )}

      {/* Main Chat */}
      <div style={S.main}>
        {/* Top bar */}
        <div style={S.topBar}>
          <div style={S.topBarLeft}>
            <button style={S.iconBtn} onClick={() => navigate('/')} title="Dashboard">
              <ArrowLeft size={18} />
            </button>
            <button style={S.iconBtn} onClick={() => setShowSidebar(!showSidebar)} title="Conversations">
              <MessageSquare size={16} />
            </button>
          </div>
          <div style={S.topBarCenter}>
            <Sparkles size={14} color="var(--accent)" />
            <span style={{ fontSize: 14, fontWeight: 600 }}>JARVIS</span>
          </div>
          <div style={S.topBarRight}>
            <button style={S.iconBtn} onClick={newConversation} title="New chat">
              <Plus size={16} />
            </button>
          </div>
        </div>

        {/* Messages */}
        <div style={S.messages}>
          {messages.length === 0 && (
            <div style={S.welcome}>
              <div style={S.welcomeIcon}>
                <Sparkles size={40} color="var(--accent)" />
              </div>
              <h2 style={S.welcomeTitle}>Hello, I'm JARVIS</h2>
              <p style={S.welcomeText}>
                Your personal AI operating system. Ask me anything — I can help with research,
                file analysis, task planning, and much more.
              </p>
              <div style={S.welcomeHints}>
                {['Summarize the documents in my sandbox', 'What can you help me with?', 'List all available tools'].map(hint => (
                  <button key={hint} style={S.hintBtn} onClick={() => { setInput(hint) }}>
                    {hint}
                  </button>
                ))}
              </div>
            </div>
          )}

          {messages.map((msg, i) => (
            <div key={i} style={{ ...S.msgRow, justifyContent: msg.role === 'user' ? 'flex-end' : 'flex-start' }}>
              {msg.role === 'assistant' && (
                <div style={S.avatar}>
                  <Bot size={16} color="var(--accent)" />
                </div>
              )}
              <div style={msg.role === 'user' ? S.userBubble : S.assistantBubble}>
                <div style={S.msgContent}>
                  {msg.content || (msg.streaming ? <span className="animate-pulse" style={{ color: 'var(--text-dim)' }}>Thinking...</span> : '')}
                  {msg.streaming && msg.content && (
                    <span style={S.cursor}>▊</span>
                  )}
                </div>
                {msg.metadata && Object.keys(msg.metadata).length > 0 && !msg.streaming && (
                  <div style={S.msgMeta}>
                    {msg.metadata.model && <span>{String(msg.metadata.model)}</span>}
                    {msg.metadata.latency_ms && <span>{String(msg.metadata.latency_ms)}ms</span>}
                  </div>
                )}
              </div>
              {msg.role === 'user' && (
                <div style={S.userAvatar}>
                  <User size={14} />
                </div>
              )}
            </div>
          ))}
          <div ref={bottomRef} />
        </div>

        {/* Input area */}
        <div style={S.inputArea}>
          <div style={S.inputContainer}>
            <textarea
              ref={inputRef}
              style={S.textInput}
              value={input}
              onChange={e => setInput(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder="Message JARVIS..."
              rows={1}
              disabled={streaming}
              autoFocus
            />
            <button
              style={{
                ...S.sendBtn,
                opacity: (!input.trim() || streaming) ? 0.3 : 1,
                background: streaming ? 'var(--error)' : 'var(--accent)',
              }}
              onClick={streaming ? undefined : sendMessage}
              disabled={!input.trim() || streaming}
            >
              {streaming ? <Square size={16} /> : <ArrowUp size={16} />}
            </button>
          </div>
          <div style={S.inputFooter}>
            <span style={{ fontSize: 11, color: 'var(--text-dim)' }}>
              JARVIS v0.2 • Local LLM via Ollama • No data leaves your machine
            </span>
          </div>
        </div>
      </div>
    </div>
  )
}


// ─── Styles ──────────────────────────────────────────────────

const S: Record<string, React.CSSProperties> = {
  root: { height: '100vh', display: 'flex', background: 'var(--bg-primary)' },

  // Sidebar
  sidebar: { width: 280, borderRight: '1px solid var(--border)', background: 'var(--bg-secondary)', display: 'flex', flexDirection: 'column', flexShrink: 0 },
  sidebarHeader: { display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '14px 16px', borderBottom: '1px solid var(--border)' },
  sidebarTitle: { fontSize: 13, fontWeight: 600, color: 'var(--text-secondary)' },
  convList: { flex: 1, overflow: 'auto', padding: 8 },
  convItem: { width: '100%', display: 'flex', alignItems: 'center', gap: 10, padding: '10px 12px', borderRadius: 'var(--radius)', border: 'none', cursor: 'pointer', textAlign: 'left' as const, color: 'var(--text-secondary)', fontSize: 13 },
  convItemText: { flex: 1, minWidth: 0 },
  convItemTitle: { fontSize: 12, whiteSpace: 'nowrap' as const, overflow: 'hidden', textOverflow: 'ellipsis', color: 'var(--text-secondary)' },
  convItemMeta: { fontSize: 10, color: 'var(--text-dim)' },

  // Main
  main: { flex: 1, display: 'flex', flexDirection: 'column', minWidth: 0 },

  // Top bar
  topBar: { display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '10px 16px', borderBottom: '1px solid var(--border)', flexShrink: 0 },
  topBarLeft: { display: 'flex', gap: 4 },
  topBarCenter: { display: 'flex', alignItems: 'center', gap: 6 },
  topBarRight: { display: 'flex', gap: 4 },
  iconBtn: { display: 'grid', placeItems: 'center', width: 32, height: 32, borderRadius: 'var(--radius)', border: '1px solid var(--border)', background: 'transparent', color: 'var(--text-secondary)', cursor: 'pointer' },

  // Messages
  messages: { flex: 1, overflow: 'auto', padding: '20px 0' },

  // Welcome
  welcome: { display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', height: '100%', padding: '0 20px', textAlign: 'center' as const },
  welcomeIcon: { width: 72, height: 72, borderRadius: 20, background: 'var(--accent-glow)', display: 'grid', placeItems: 'center', marginBottom: 20, border: '1px solid rgba(59,130,246,0.2)' },
  welcomeTitle: { fontSize: 24, fontWeight: 700, marginBottom: 8 },
  welcomeText: { fontSize: 14, color: 'var(--text-muted)', maxWidth: 460, lineHeight: 1.6, marginBottom: 28 },
  welcomeHints: { display: 'flex', flexWrap: 'wrap' as const, gap: 8, justifyContent: 'center', maxWidth: 520 },
  hintBtn: { padding: '8px 16px', borderRadius: 20, border: '1px solid var(--border)', background: 'var(--bg-card)', color: 'var(--text-secondary)', fontSize: 13, cursor: 'pointer', transition: 'border-color 0.2s, background 0.2s' },

  // Message rows
  msgRow: { display: 'flex', gap: 10, padding: '4px 20px', maxWidth: 860, margin: '0 auto', width: '100%', alignItems: 'flex-start' },
  avatar: { width: 32, height: 32, borderRadius: 10, background: 'var(--accent-glow)', display: 'grid', placeItems: 'center', flexShrink: 0, marginTop: 2, border: '1px solid rgba(59,130,246,0.2)' },
  userAvatar: { width: 28, height: 28, borderRadius: 8, background: 'var(--bg-elevated)', display: 'grid', placeItems: 'center', flexShrink: 0, color: 'var(--text-muted)', marginTop: 2 },

  userBubble: { maxWidth: '75%', padding: '10px 16px', borderRadius: '18px 18px 4px 18px', background: 'var(--accent)', color: '#fff' },
  assistantBubble: { maxWidth: '80%', padding: '10px 16px', borderRadius: '4px 18px 18px 18px', background: 'var(--bg-card)', border: '1px solid var(--border)' },
  msgContent: { fontSize: 14, lineHeight: 1.6, whiteSpace: 'pre-wrap' as const, wordBreak: 'break-word' as const },
  msgMeta: { display: 'flex', gap: 8, marginTop: 6, fontSize: 10, color: 'var(--text-dim)', fontFamily: 'var(--font-mono)' },
  cursor: { color: 'var(--accent)', animation: 'pulse 1s infinite' },

  // Input
  inputArea: { padding: '12px 20px 16px', borderTop: '1px solid var(--border)', flexShrink: 0 },
  inputContainer: { display: 'flex', alignItems: 'flex-end', gap: 8, maxWidth: 820, margin: '0 auto', background: 'var(--bg-card)', borderRadius: 'var(--radius-xl)', border: '1px solid var(--border)', padding: '8px 8px 8px 16px' },
  textInput: { flex: 1, background: 'transparent', border: 'none', outline: 'none', color: 'var(--text-primary)', fontSize: 14, lineHeight: 1.5, resize: 'none' as const, maxHeight: 120, fontFamily: 'var(--font-sans)' },
  sendBtn: { width: 36, height: 36, borderRadius: 10, border: 'none', color: '#fff', display: 'grid', placeItems: 'center', cursor: 'pointer', flexShrink: 0, transition: 'opacity 0.2s, background 0.2s' },
  inputFooter: { textAlign: 'center' as const, padding: '8px 0 0' },
}
