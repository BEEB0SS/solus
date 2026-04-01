import { useState, useEffect, useRef, useCallback } from 'react'
import { Send, Zap, Loader2 } from 'lucide-react'
import { useProjectStore } from '../../stores/projectStore'

interface Message {
  id: string
  role: 'user' | 'assistant' | 'system'
  content: string
  timestamp: number
  variant?: 'logs' | 'success' | 'error'
}

let msgCounter = 0
function uid() { return `msg-${++msgCounter}-${Date.now()}` }

export default function IntelligenceTab() {
  const store = useProjectStore()
  const pid = store.currentProjectId

  const [messages, setMessages] = useState<Message[]>([])
  const [input, setInput] = useState('')
  const [queryType, setQueryType] = useState('general')
  const [loading, setLoading] = useState(false)
  const [flashStates, setFlashStates] = useState<Record<string, string>>({})
  const scrollRef = useRef<HTMLDivElement>(null)
  const checkedRef = useRef(false)

  const scrollToBottom = () => {
    setTimeout(() => scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: 'smooth' }), 50)
  }

  const addMessage = useCallback((msg: Omit<Message, 'id' | 'timestamp'>) => {
    const m: Message = { ...msg, id: uid(), timestamp: Date.now() }
    setMessages(prev => [...prev, m])
    scrollToBottom()
    return m
  }, [])

  const sendQuery = useCallback(async (query: string, type: string) => {
    if (!query.trim()) return
    addMessage({ role: 'user', content: query })
    setLoading(true)
    try {
      const data = await store.queryAgent(pid, query, type)
      const text = data.response_text || data.response || JSON.stringify(data)
      addMessage({ role: 'assistant', content: text })
    } catch {
      addMessage({ role: 'system', content: 'Failed to get response from agent.', variant: 'error' })
    }
    setLoading(false)
  }, [pid, addMessage, store])

  // Auto-load from Live Bench
  useEffect(() => {
    const iv = setInterval(() => {
      const raw = localStorage.getItem('solus_agent_context')
      if (!raw) return
      try {
        const item = JSON.parse(raw)
        if (Date.now() - item.timestamp > 60000) return
        localStorage.removeItem('solus_agent_context')
        addMessage({ role: 'system', content: 'Live Bench telemetry logs received', variant: 'logs' })
        const report = typeof item.logs === 'object' ? (item.logs.report || JSON.stringify(item.logs).slice(0, 500)) : String(item.logs).slice(0, 500)
        if (report) addMessage({ role: 'system', content: report, variant: 'logs' })
        if (item.prompt) {
          setTimeout(() => sendQuery(item.prompt, 'debug'), 300)
        }
      } catch { /* */ }
    }, 1000)
    return () => clearInterval(iv)
  }, [addMessage, sendQuery])

  const handleSubmit = () => {
    if (!input.trim() || loading) return
    const q = input
    setInput('')
    sendQuery(q, queryType)
  }

  const handleFlash = async (code: string, blockId: string) => {
    setFlashStates(p => ({ ...p, [blockId]: 'compiling' }))
    try {
      const res = await fetch('/api/arduino/flash', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name: 'agent_fix', code, port: '' }),
      })
      const data = await res.json()
      if (data.success || res.ok) {
        setFlashStates(p => ({ ...p, [blockId]: 'success' }))
        addMessage({ role: 'system', content: 'Code flashed successfully! Switch to Live Bench and reconnect.', variant: 'success' })
      } else {
        setFlashStates(p => ({ ...p, [blockId]: 'error' }))
        addMessage({ role: 'system', content: `Flash failed: ${data.error || 'Unknown error'}`, variant: 'error' })
      }
    } catch {
      setFlashStates(p => ({ ...p, [blockId]: 'error' }))
      addMessage({ role: 'system', content: 'Flash request failed.', variant: 'error' })
    }
  }

  const renderContent = (content: string, msgId: string) => {
    const parts: JSX.Element[] = []
    let i = 0
    const lines = content.split('\n')
    let lineIdx = 0

    while (lineIdx < lines.length) {
      const line = lines[lineIdx]

      // Code block
      if (line.startsWith('```')) {
        const lang = line.slice(3).trim()
        const codeLines: string[] = []
        lineIdx++
        while (lineIdx < lines.length && !lines[lineIdx].startsWith('```')) {
          codeLines.push(lines[lineIdx])
          lineIdx++
        }
        lineIdx++ // skip closing ```
        const code = codeLines.join('\n')
        const blockId = `${msgId}-code-${i}`
        const isArduino = code.includes('void setup()') || code.includes('void loop()')
        const flashState = flashStates[blockId]

        parts.push(
          <div key={i} className="my-2">
            {lang && <div className="text-[9px] font-mono text-solus-text-muted px-3 pt-1.5 bg-solus-bg rounded-t">{lang}</div>}
            <pre className={`bg-solus-bg p-3 ${lang ? 'rounded-b' : 'rounded'} font-mono text-xs overflow-x-auto text-solus-text whitespace-pre-wrap`}>{code}</pre>
            {isArduino && (
              <button
                onClick={() => handleFlash(code, blockId)}
                disabled={flashState === 'compiling' || flashState === 'success'}
                className={`w-full mt-1 py-2 font-semibold text-sm rounded transition-colors ${
                  flashState === 'compiling' ? 'bg-amber-600 text-white' :
                  flashState === 'success' ? 'bg-green-600 text-white' :
                  flashState === 'error' ? 'bg-red-600 text-white hover:bg-red-500' :
                  'bg-solus-accent hover:bg-solus-accent-bright text-white'
                }`}
              >
                {flashState === 'compiling' ? 'Compiling...' :
                 flashState === 'success' ? 'Flashed!' :
                 flashState === 'error' ? 'Flash Failed — Retry' :
                 '\u26A1 Flash Fix to Robot'}
              </button>
            )}
          </div>
        )
        i++
        continue
      }

      // Section headers
      const headerMatch = line.match(/^(LIKELY CAUSE|ROOT CAUSE|SUGGESTED FIX|CORRECTED CODE):(.*)$/i)
      if (headerMatch) {
        parts.push(
          <div key={i} className="mt-3 mb-1">
            <span className="text-sm font-bold uppercase tracking-wide text-solus-accent-bright">{headerMatch[1]}:</span>
            {headerMatch[2] && <span className="text-sm text-solus-text ml-1">{headerMatch[2]}</span>}
          </div>
        )
        i++
        lineIdx++
        continue
      }

      // Inline code
      if (line.includes('`')) {
        const rendered = line.split(/(`[^`]+`)/).map((seg, si) => {
          if (seg.startsWith('`') && seg.endsWith('`')) {
            return <code key={si} className="bg-solus-bg px-1 rounded font-mono text-xs">{seg.slice(1, -1)}</code>
          }
          return <span key={si}>{seg}</span>
        })
        parts.push(<p key={i} className="text-sm leading-relaxed">{rendered}</p>)
      } else if (line.trim()) {
        parts.push(<p key={i} className="text-sm leading-relaxed">{line}</p>)
      } else {
        parts.push(<div key={i} className="h-2" />)
      }
      i++
      lineIdx++
    }

    return parts
  }

  const msgBg = (msg: Message) => {
    if (msg.role === 'user') return 'bg-solus-accent/20'
    if (msg.role === 'system') {
      if (msg.variant === 'error') return 'bg-solus-error/10'
      if (msg.variant === 'success') return 'bg-solus-success/10'
      return 'bg-solus-warning/10'
    }
    return 'bg-solus-elevated'
  }

  return (
    <div className="flex h-full flex-col overflow-hidden">
      {/* Header */}
      <div className="bg-solus-surface border-b border-solus-border px-4 py-2.5 flex items-center gap-2">
        <Zap size={14} className="text-solus-accent-bright" />
        <span className="text-xs font-mono font-semibold uppercase tracking-widest text-solus-text-muted">System Intelligence</span>
      </div>

      {/* Messages */}
      <div ref={scrollRef} className="flex-1 overflow-y-auto p-4 space-y-3">
        {messages.map(msg => (
          <div key={msg.id} className={`${msg.role === 'user' ? 'flex justify-end' : ''}`}>
            <div className={`${msgBg(msg)} rounded-lg px-4 py-3 ${
              msg.role === 'user' ? 'max-w-[70%]' : 'w-full'
            }`}>
              {msg.role === 'user' ? (
                <p className="text-sm font-mono">{msg.content}</p>
              ) : (
                <div>{renderContent(msg.content, msg.id)}</div>
              )}
            </div>
          </div>
        ))}
        {loading && (
          <div className="flex items-center gap-2 text-solus-text-muted">
            <Loader2 size={14} className="animate-spin" />
            <span className="text-xs font-mono">Analyzing...</span>
          </div>
        )}
        {messages.length === 0 && !loading && (
          <div className="flex flex-col items-center justify-center h-full text-solus-text-muted space-y-2">
            <Zap size={28} className="text-solus-accent/40" />
            <span className="text-xs font-mono">Ask about your robot system, debug issues, or analyze impact</span>
          </div>
        )}
      </div>

      {/* Input */}
      <div className="border-t border-solus-border bg-solus-surface p-3 flex items-center gap-2">
        <select value={queryType} onChange={e => setQueryType(e.target.value)}
          className="bg-solus-bg border border-solus-border rounded px-2 py-1.5 text-[10px] font-mono text-solus-text">
          <option value="general">general</option>
          <option value="debug">debug</option>
          <option value="search_parts">search_parts</option>
          <option value="extract_values">extract_values</option>
          <option value="impact_analysis">impact_analysis</option>
          <option value="plan">plan</option>
        </select>
        <input
          value={input}
          onChange={e => setInput(e.target.value)}
          onKeyDown={e => { if (e.key === 'Enter') handleSubmit() }}
          placeholder="Ask about your system..."
          className="flex-1 bg-solus-bg border border-solus-border rounded px-3 py-1.5 font-mono text-sm text-solus-text placeholder:text-solus-text-muted"
        />
        {loading ? (
          <div className="w-9 h-9 flex items-center justify-center">
            <div className="flex gap-0.5">
              <div className="w-1.5 h-1.5 bg-solus-accent rounded-full animate-bounce" style={{ animationDelay: '0ms' }} />
              <div className="w-1.5 h-1.5 bg-solus-accent rounded-full animate-bounce" style={{ animationDelay: '150ms' }} />
              <div className="w-1.5 h-1.5 bg-solus-accent rounded-full animate-bounce" style={{ animationDelay: '300ms' }} />
            </div>
          </div>
        ) : (
          <button onClick={handleSubmit}
            className="bg-solus-accent hover:bg-solus-accent-bright text-white p-2 rounded transition-colors">
            <Send size={14} />
          </button>
        )}
      </div>
    </div>
  )
}
