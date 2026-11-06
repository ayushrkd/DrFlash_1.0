import { useState, useRef, useEffect, useCallback } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { api } from '../api'
import {
  ArrowLeft, ArrowUp, Bot, Mic, MicOff,
  Plus, Sparkles, Square, User, Volume2, VolumeX,
  MessageSquare, Radio, Settings2
} from 'lucide-react'

interface ChatMessage {
  role: 'user' | 'assistant'
  content: string
  timestamp: string
  metadata?: Record<string, unknown>
  streaming?: boolean
  fromVoice?: boolean
}

type VoiceStatus = 'OFF' | 'IDLE' | 'LISTENING' | 'PROCESSING' | 'SPEAKING' | 'ERROR'

export function ChatPage() {
  const navigate = useNavigate()
  const { conversationId: paramConvId } = useParams()
  const [conversationId, setConversationId] = useState(paramConvId || `conv_${Date.now()}`)
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [input, setInput] = useState('')
  const [streaming, setStreaming] = useState(false)
  const [showSidebar, setShowSidebar] = useState(false)
  const [convList, setConvList] = useState<Array<{ conversation_id: string; message_count: number; last_message: string }>>([])

  // Voice state
  const [voiceMode, setVoiceMode] = useState(false)
  const [voiceStatus, setVoiceStatus] = useState<VoiceStatus>('OFF')
  const [isListening, setIsListening] = useState(false)
  const [interimTranscript, setInterimTranscript] = useState('')
  const [voiceEnabled, setVoiceEnabled] = useState(false)

  const bottomRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLTextAreaElement>(null)
  const wsRef = useRef<WebSocket | null>(null)
  const recognitionRef = useRef<any>(null)
  const audioContextRef = useRef<AudioContext | null>(null)
  const audioQueueRef = useRef<Uint8Array[]>([])
  const isPlayingRef = useRef(false)

  // Load conversation list
  useEffect(() => {
    api.conversations().then(setConvList).catch(() => {})
  }, [messages.length])

  // Auto scroll
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, interimTranscript])

  // ─── WebSocket for voice ────────────────────────────────

  const connectVoiceWS = useCallback(() => {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
    const ws = new WebSocket(`${protocol}//localhost:8000/api/v1/voice/ws`)
    wsRef.current = ws

    ws.onopen = () => {
      setVoiceEnabled(true)
      setVoiceStatus('IDLE')
    }

    ws.onmessage = async (event) => {
      if (event.data instanceof Blob) {
        // Audio chunk — queue for playback
        const arrayBuf = await event.data.arrayBuffer()
        audioQueueRef.current.push(new Uint8Array(arrayBuf))
        if (!isPlayingRef.current) playAudioQueue()
        return
      }

      const msg = JSON.parse(event.data)
      if (msg.type === 'state') {
        setVoiceStatus(msg.state)
        if (msg.state === 'IDLE' && voiceMode) {
          // Auto-listen after speaking
          setTimeout(() => startListening(), 500)
        }
      } else if (msg.type === 'response') {
        // Add both user and assistant messages from voice
        setMessages(prev => [
          ...prev,
          { role: 'user', content: msg.user_text, timestamp: new Date().toISOString(), fromVoice: true },
          { role: 'assistant', content: msg.text, timestamp: new Date().toISOString(), fromVoice: true },
        ])
      } else if (msg.type === 'audio_start') {
        audioQueueRef.current = []
        isPlayingRef.current = false
      } else if (msg.type === 'audio_end') {
        // Final chunk marker
      } else if (msg.type === 'speak_browser') {
        // Browser TTS fallback when edge-tts fails
        const utterance = new SpeechSynthesisUtterance(msg.text)
        utterance.rate = 1.05
        utterance.pitch = 1.0
        utterance.onend = () => {
          setVoiceStatus('IDLE')
          if (voiceMode) setTimeout(() => startListening(), 500)
        }
        window.speechSynthesis.speak(utterance)
      }
    }

    ws.onclose = () => {
      setVoiceEnabled(false)
      setVoiceStatus('OFF')
    }

    ws.onerror = () => {
      setVoiceStatus('ERROR')
    }

    return ws
  }, [voiceMode])

  // ─── Audio playback ─────────────────────────────────────

  const playAudioQueue = async () => {
    if (isPlayingRef.current) return
    isPlayingRef.current = true

    try {
      // Collect all chunks into one blob
      await new Promise(resolve => setTimeout(resolve, 300)) // small buffer
      const allChunks = audioQueueRef.current.splice(0)
      if (allChunks.length === 0) { isPlayingRef.current = false; return }

      const blob = new Blob(allChunks, { type: 'audio/mpeg' })
      const url = URL.createObjectURL(blob)
      const audio = new Audio(url)
      audio.onended = () => {
        URL.revokeObjectURL(url)
        isPlayingRef.current = false
        if (audioQueueRef.current.length > 0) playAudioQueue()
      }
      audio.onerror = () => {
        isPlayingRef.current = false
      }
      await audio.play()
    } catch {
      isPlayingRef.current = false
    }
  }

  // ─── Speech Recognition (Web Speech API) ────────────────

  const startListening = useCallback(() => {
    const SpeechRecognition = (window as any).SpeechRecognition || (window as any).webkitSpeechRecognition
    if (!SpeechRecognition) return

    const recognition = new SpeechRecognition()
    recognition.continuous = false
    recognition.interimResults = true
    recognition.lang = 'en-US'
    recognition.maxAlternatives = 1

    recognition.onstart = () => {
      setIsListening(true)
      setVoiceStatus('LISTENING')
      wsRef.current?.send(JSON.stringify({ type: 'control', action: 'start' }))
    }

    recognition.onresult = (event: any) => {
      let interim = ''
      let final = ''
      for (let i = event.resultIndex; i < event.results.length; i++) {
        const transcript = event.results[i][0].transcript
        if (event.results[i].isFinal) {
          final += transcript
        } else {
          interim += transcript
        }
      }
      setInterimTranscript(interim)
      if (final) {
        setInterimTranscript('')
        // Send final transcript to voice WebSocket
        wsRef.current?.send(JSON.stringify({
          type: 'transcript', text: final, final: true,
        }))
      }
    }

    recognition.onend = () => {
      setIsListening(false)
      setInterimTranscript('')
    }

    recognition.onerror = (event: any) => {
      setIsListening(false)
      setInterimTranscript('')
      if (event.error !== 'no-speech' && event.error !== 'aborted') {
        setVoiceStatus('ERROR')
      }
    }

    recognitionRef.current = recognition
    recognition.start()
  }, [])

  const stopListening = useCallback(() => {
    recognitionRef.current?.stop()
    setIsListening(false)
    setInterimTranscript('')
  }, [])

  // ─── Toggle voice mode ──────────────────────────────────

  const toggleVoiceMode = useCallback(() => {
    if (voiceMode) {
      // Turning off
      stopListening()
      wsRef.current?.close()
      wsRef.current = null
      setVoiceMode(false)
      setVoiceStatus('OFF')
      setVoiceEnabled(false)
    } else {
      // Turning on
      setVoiceMode(true)
      connectVoiceWS()
      setTimeout(() => startListening(), 500)
    }
  }, [voiceMode, connectVoiceWS, startListening, stopListening])

  // ─── Text chat ──────────────────────────────────────────

  const sendMessage = useCallback(async () => {
    if (!input.trim() || streaming) return
    const userMsg = input.trim()
    setInput('')
    setStreaming(true)

    setMessages(prev => [...prev, {
      role: 'user', content: userMsg, timestamp: new Date().toISOString(),
    }])

    setMessages(prev => [...prev, {
      role: 'assistant', content: '', streaming: true, timestamp: new Date().toISOString(),
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
          updated[updated.length - 1] = { ...last, content: `Error: ${err.message}`, streaming: false }
        }
        return updated
      })
    }

    setStreaming(false)
    inputRef.current?.focus()
  }, [input, streaming, conversationId])

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendMessage() }
  }

  const newConversation = () => {
    const id = `conv_${Date.now()}`
    setConversationId(id)
    setMessages([])
    navigate(`/chat/${id}`)
  }

  // ─── Voice status color/label ───────────────────────────

  const voiceColor = {
    OFF: 'var(--text-dim)', IDLE: 'var(--success)', LISTENING: 'var(--accent)',
    PROCESSING: 'var(--warning)', SPEAKING: 'var(--purple)', ERROR: 'var(--error)',
  }[voiceStatus] || 'var(--text-dim)'

  return (
    <div style={S.root}>
      {/* Sidebar */}
      {showSidebar && (
        <div style={S.sidebar}>
          <div style={S.sidebarHeader}>
            <span style={S.sidebarTitle}>Conversations</span>
            <button style={S.iconBtn} onClick={newConversation}><Plus size={16} /></button>
          </div>
          <div style={S.convList}>
            {convList.map(c => (
              <button key={c.conversation_id} style={{
                ...S.convItem,
                background: c.conversation_id === conversationId ? 'var(--bg-elevated)' : 'transparent',
              }} onClick={() => { setConversationId(c.conversation_id); navigate(`/chat/${c.conversation_id}`) }}>
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

      <div style={S.main}>
        {/* Top bar */}
        <div style={S.topBar}>
          <div style={S.topBarLeft}>
            <button style={S.iconBtn} onClick={() => navigate('/')} title="Dashboard"><ArrowLeft size={18} /></button>
            <button style={S.iconBtn} onClick={() => setShowSidebar(!showSidebar)} title="Conversations"><MessageSquare size={16} /></button>
          </div>
          <div style={S.topBarCenter}>
            <Sparkles size={14} color="var(--accent)" />
            <span style={{ fontSize: 14, fontWeight: 600 }}>JARVIS</span>
            {voiceMode && (
              <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginLeft: 8 }}>
                <div style={{ width: 6, height: 6, borderRadius: 3, background: voiceColor, boxShadow: `0 0 8px ${voiceColor}` }} />
                <span style={{ fontSize: 11, color: voiceColor, fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.5px' }}>
                  {voiceStatus}
                </span>
              </div>
            )}
          </div>
          <div style={S.topBarRight}>
            <button
              style={{ ...S.voiceToggle, background: voiceMode ? 'var(--accent)' : 'transparent', color: voiceMode ? '#fff' : 'var(--text-secondary)', borderColor: voiceMode ? 'var(--accent)' : 'var(--border)' }}
              onClick={toggleVoiceMode}
              title={voiceMode ? 'Disable voice' : 'Enable voice'}
            >
              {voiceMode ? <Volume2 size={15} /> : <VolumeX size={15} />}
              <span style={{ fontSize: 12, fontWeight: 600 }}>{voiceMode ? 'Voice ON' : 'Voice'}</span>
            </button>
            <button style={S.iconBtn} onClick={newConversation} title="New chat"><Plus size={16} /></button>
          </div>
        </div>

        {/* ─── Voice Mode Overlay ─────────────────── */}
        {voiceMode && messages.length === 0 && voiceStatus !== 'SPEAKING' && voiceStatus !== 'PROCESSING' && (
          <div style={S.voiceOverlay}>
            <div style={{
              ...S.voiceOrb,
              boxShadow: isListening
                ? `0 0 60px 20px ${voiceColor}, 0 0 120px 40px rgba(59,130,246,0.1)`
                : `0 0 30px 10px rgba(59,130,246,0.1)`,
              transform: isListening ? 'scale(1.1)' : 'scale(1)',
            }}>
              {isListening ? <Mic size={48} color="#fff" /> : <Radio size={48} color="var(--accent)" />}
            </div>
            <div style={S.voiceLabel}>
              {isListening ? (interimTranscript || 'Listening...') : voiceStatus === 'IDLE' ? 'Say something...' : voiceStatus}
            </div>
            {interimTranscript && (
              <div style={S.interimText}>"{interimTranscript}"</div>
            )}
            <button style={S.voiceActionBtn} onClick={isListening ? stopListening : startListening}>
              {isListening ? 'Stop' : 'Start Listening'}
            </button>
          </div>
        )}

        {/* Messages */}
        <div style={S.messages}>
          {!voiceMode && messages.length === 0 && (
            <div style={S.welcome}>
              <div style={S.welcomeIcon}><Sparkles size={40} color="var(--accent)" /></div>
              <h2 style={S.welcomeTitle}>Hello, I'm JARVIS</h2>
              <p style={S.welcomeText}>
                Your personal AI operating system. Ask me anything — I can help with research,
                file analysis, task planning, and much more.
              </p>
              <div style={S.welcomeHints}>
                {['Summarize the documents in my sandbox', 'What can you help me with?', 'List all available tools'].map(hint => (
                  <button key={hint} style={S.hintBtn} onClick={() => setInput(hint)}>{hint}</button>
                ))}
              </div>
            </div>
          )}

          {messages.map((msg, i) => (
            <div key={i} style={{ ...S.msgRow, justifyContent: msg.role === 'user' ? 'flex-end' : 'flex-start', animation: 'fadeIn 0.3s ease-out' }}>
              {msg.role === 'assistant' && <div style={S.avatar}><Bot size={16} color="var(--accent)" /></div>}
              <div style={msg.role === 'user' ? S.userBubble : S.assistantBubble}>
                <div style={S.msgContent}>
                  {msg.content || (msg.streaming ? <span className="animate-pulse" style={{ color: 'var(--text-dim)' }}>Thinking...</span> : '')}
                  {msg.streaming && msg.content && <span style={S.cursor}>▊</span>}
                </div>
                {msg.fromVoice && <div style={{ fontSize: 10, color: 'var(--text-dim)', marginTop: 4 }}>🎤 via voice</div>}
                {msg.metadata && !msg.streaming && Object.keys(msg.metadata).length > 0 && (
                  <div style={S.msgMeta}>
                    {msg.metadata.model && <span>{String(msg.metadata.model)}</span>}
                    {msg.metadata.latency_ms && <span>{String(msg.metadata.latency_ms)}ms</span>}
                  </div>
                )}
              </div>
              {msg.role === 'user' && <div style={S.userAvatar}>{msg.fromVoice ? <Mic size={12} /> : <User size={14} />}</div>}
            </div>
          ))}
          <div ref={bottomRef} />
        </div>

        {/* Input area */}
        <div style={S.inputArea}>
          <div style={S.inputContainer}>
            {/* Mic button */}
            <button
              style={{
                ...S.micBtn,
                background: isListening ? 'var(--accent)' : 'transparent',
                color: isListening ? '#fff' : 'var(--text-muted)',
                borderColor: isListening ? 'var(--accent)' : 'var(--border)',
                boxShadow: isListening ? `0 0 12px var(--accent)` : 'none',
              }}
              onClick={() => {
                if (!voiceMode) {
                  setVoiceMode(true)
                  connectVoiceWS()
                }
                isListening ? stopListening() : startListening()
              }}
              title={isListening ? 'Stop listening' : 'Voice input'}
            >
              {isListening ? <Mic size={18} /> : <MicOff size={16} />}
            </button>
            <textarea
              ref={inputRef}
              style={S.textInput}
              value={input}
              onChange={e => setInput(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder={isListening ? 'Listening...' : 'Message JARVIS...'}
              rows={1}
              disabled={streaming || isListening}
              autoFocus={!voiceMode}
            />
            <button
              style={{ ...S.sendBtn, opacity: (!input.trim() || streaming) ? 0.3 : 1, background: streaming ? 'var(--error)' : 'var(--accent)' }}
              onClick={streaming ? undefined : sendMessage}
              disabled={!input.trim() || streaming}
            >
              {streaming ? <Square size={16} /> : <ArrowUp size={16} />}
            </button>
          </div>
          <div style={S.inputFooter}>
            JARVIS v0.2 · {voiceMode ? `Voice ${voiceStatus}` : 'Local LLM via Ollama'} · No data leaves your machine
          </div>
        </div>
      </div>
    </div>
  )
}


// ─── Styles ──────────────────────────────────────────────────

const S: Record<string, React.CSSProperties> = {
  root: { height: '100vh', display: 'flex', background: 'var(--bg-primary)' },

  sidebar: { width: 280, borderRight: '1px solid var(--border)', background: 'var(--bg-secondary)', display: 'flex', flexDirection: 'column', flexShrink: 0 },
  sidebarHeader: { display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '14px 16px', borderBottom: '1px solid var(--border)' },
  sidebarTitle: { fontSize: 13, fontWeight: 600, color: 'var(--text-secondary)' },
  convList: { flex: 1, overflow: 'auto', padding: 8 },
  convItem: { width: '100%', display: 'flex', alignItems: 'center', gap: 10, padding: '10px 12px', borderRadius: 'var(--radius)', border: 'none', cursor: 'pointer', textAlign: 'left' as const, color: 'var(--text-secondary)', fontSize: 13 },
  convItemText: { flex: 1, minWidth: 0 },
  convItemTitle: { fontSize: 12, whiteSpace: 'nowrap' as const, overflow: 'hidden', textOverflow: 'ellipsis', color: 'var(--text-secondary)' },
  convItemMeta: { fontSize: 10, color: 'var(--text-dim)' },

  main: { flex: 1, display: 'flex', flexDirection: 'column', minWidth: 0 },

  topBar: { display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '10px 16px', borderBottom: '1px solid var(--border)', flexShrink: 0 },
  topBarLeft: { display: 'flex', gap: 4 },
  topBarCenter: { display: 'flex', alignItems: 'center', gap: 6 },
  topBarRight: { display: 'flex', gap: 8, alignItems: 'center' },
  iconBtn: { display: 'grid', placeItems: 'center', width: 32, height: 32, borderRadius: 'var(--radius)', border: '1px solid var(--border)', background: 'transparent', color: 'var(--text-secondary)', cursor: 'pointer' },
  voiceToggle: { display: 'flex', alignItems: 'center', gap: 6, padding: '6px 12px', borderRadius: 20, border: '1px solid', fontSize: 12, fontWeight: 600, cursor: 'pointer', transition: 'all 0.2s' },

  // Voice overlay
  voiceOverlay: { flex: 1, display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', gap: 24, padding: 40 },
  voiceOrb: { width: 140, height: 140, borderRadius: '50%', background: 'linear-gradient(135deg, rgba(59,130,246,0.2), rgba(139,92,246,0.2))', display: 'grid', placeItems: 'center', transition: 'all 0.3s ease', border: '2px solid rgba(59,130,246,0.3)' },
  voiceLabel: { fontSize: 18, fontWeight: 500, color: 'var(--text-secondary)', textAlign: 'center' as const },
  interimText: { fontSize: 16, color: 'var(--accent)', fontStyle: 'italic', textAlign: 'center' as const, maxWidth: 500 },
  voiceActionBtn: { padding: '10px 24px', borderRadius: 20, border: '1px solid var(--border)', background: 'var(--bg-card)', color: 'var(--text-secondary)', fontSize: 14, fontWeight: 600, cursor: 'pointer' },

  // Messages
  messages: { flex: 1, overflow: 'auto', padding: '20px 0' },

  welcome: { display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', height: '100%', padding: '0 20px', textAlign: 'center' as const },
  welcomeIcon: { width: 72, height: 72, borderRadius: 20, background: 'var(--accent-glow)', display: 'grid', placeItems: 'center', marginBottom: 20, border: '1px solid rgba(59,130,246,0.2)' },
  welcomeTitle: { fontSize: 24, fontWeight: 700, marginBottom: 8 },
  welcomeText: { fontSize: 14, color: 'var(--text-muted)', maxWidth: 460, lineHeight: 1.6, marginBottom: 28 },
  welcomeHints: { display: 'flex', flexWrap: 'wrap' as const, gap: 8, justifyContent: 'center', maxWidth: 520 },
  hintBtn: { padding: '8px 16px', borderRadius: 20, border: '1px solid var(--border)', background: 'var(--bg-card)', color: 'var(--text-secondary)', fontSize: 13, cursor: 'pointer' },

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
  inputContainer: { display: 'flex', alignItems: 'flex-end', gap: 8, maxWidth: 820, margin: '0 auto', background: 'var(--bg-card)', borderRadius: 'var(--radius-xl)', border: '1px solid var(--border)', padding: '6px 8px 6px 6px' },
  micBtn: { width: 38, height: 38, borderRadius: 10, border: '1px solid', display: 'grid', placeItems: 'center', cursor: 'pointer', flexShrink: 0, transition: 'all 0.2s' },
  textInput: { flex: 1, background: 'transparent', border: 'none', outline: 'none', color: 'var(--text-primary)', fontSize: 14, lineHeight: 1.5, resize: 'none' as const, maxHeight: 120, fontFamily: 'var(--font-sans)', padding: '8px 4px' },
  sendBtn: { width: 36, height: 36, borderRadius: 10, border: 'none', color: '#fff', display: 'grid', placeItems: 'center', cursor: 'pointer', flexShrink: 0, transition: 'opacity 0.2s, background 0.2s' },
  inputFooter: { textAlign: 'center' as const, padding: '8px 0 0', fontSize: 11, color: 'var(--text-dim)' },
}
