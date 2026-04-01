import { useState, useRef, useCallback, useEffect } from 'react'
import { Send, Zap, Loader2 } from 'lucide-react'
import { useProjectStore } from '../../stores/projectStore'

interface Message {
  id: string
  role: 'user' | 'assistant' | 'system'
  content: string
  timestamp: number
  variant?: 'logs' | 'success' | 'error'
}

function detectQueryType(query: string): string {
  const q = query.toLowerCase()
  if (/bug|error|oscillat|diagnos|fix|fail|crash|wrong|broken/.test(q)) return 'debug'
  if (/what part|recommend|component|suggest.*part|find.*part/.test(q)) return 'search_parts'
  return 'general'
}

export default function IntelligenceTab() {
  const store = useProjectStore()
  const pid = store.currentProjectId

  const messages = store.agentMessages as Message[]
  const [input, setInput] = useState('')
  const [loading, setLoading] = useState(false)
  const [flashStates, setFlashStates] = useState<Record<string, string>>({})
  const scrollRef = useRef<HTMLDivElement>(null)

  const scrollToBottom = () => {
    setTimeout(() => scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: 'smooth' }), 50)
  }

  const addMessage = useCallback((msg: Omit<Message, 'id' | 'timestamp'>) => {
    const m = store.addAgentMessage(msg)
    scrollToBottom()
    return m as Message
  }, [store])

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
    sendQuery(q, detectQueryType(q))
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
      if (data.success) {
        setFlashStates(p => ({ ...p, [blockId]: 'success' }))
        addMessage({ role: 'system', content: 'Code flashed successfully! Switch to Live Bench and reconnect.', variant: 'success' })
      } else {
        setFlashStates(p => ({ ...p, [blockId]: 'error' }))
        addMessage({ role: 'system', content: `Flash failed at ${data.stage}: ${data.errors || 'Unknown error'}`, variant: 'error' })
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
          <div key={i} className="my-3">
            {lang && (
              <div className="text-[9px] font-mono uppercase tracking-widest text-solus-text-muted px-4 pt-2 pb-1 bg-solus-bg border border-b-0 border-solus-border">
                {lang}
              </div>
            )}
            <pre className={`bg-solus-bg p-4 border border-solus-border ${lang ? '' : ''} font-mono text-xs overflow-x-auto text-solus-text`}>
              {codeLines.map((cl, li) => (
                <div key={li} className="flex">
                  <span className="select-none text-solus-text-muted w-8 shrink-0 text-right pr-3">{li + 1}</span>
                  <span className="whitespace-pre-wrap">{cl}</span>
                </div>
              ))}
            </pre>
            {isArduino && (
              <button
                onClick={() => handleFlash(code, blockId)}
                disabled={flashState === 'compiling' || flashState === 'success'}
                className={`w-full py-2.5 font-mono font-semibold text-sm transition-colors ${
                  flashState === 'compiling' ? 'bg-amber-600 text-white' :
                  flashState === 'success' ? 'bg-green-600 text-white' :
                  flashState === 'error' ? 'bg-red-600 text-white hover:bg-red-500' :
                  'bg-solus-accent hover:bg-solus-accent-bright text-white'
                }`}
              >
                {flashState === 'compiling' ? 'COMPILING...' :
                 flashState === 'success' ? 'FLASHED' :
                 flashState === 'error' ? 'FLASH FAILED — RETRY' :
                 '\u26A1 FLASH FIX TO ROBOT'}
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
          <div key={i} className="bg-solus-accent/10 px-3 py-1 mt-3 mb-1">
            <span className="text-xs font-mono font-semibold uppercase tracking-widest text-solus-accent-bright">{headerMatch[1]}</span>
            {headerMatch[2]?.trim() && <span className="text-xs font-mono text-solus-text ml-2">{headerMatch[2].trim()}</span>}
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
            return <code key={si} className="bg-solus-bg border border-solus-border px-1 py-0.5 font-mono text-xs">{seg.slice(1, -1)}</code>
          }
          return <span key={si}>{seg}</span>
        })
        parts.push(<p key={i} className="text-sm font-mono leading-relaxed text-solus-text">{rendered}</p>)
      } else if (line.trim()) {
        parts.push(<p key={i} className="text-sm font-mono leading-relaxed text-solus-text">{line}</p>)
      } else {
        parts.push(<div key={i} className="h-2" />)
      }
      i++
      lineIdx++
    }

    return parts
  }

  return (
    <div className="flex h-full flex-col overflow-hidden">
      {/* Header */}
      <div className="bg-solus-surface border-b border-solus-border px-4 py-2.5 flex items-center gap-2">
        <Zap size={14} className="text-solus-accent-bright" />
        <span className="text-xs font-mono font-semibold uppercase tracking-widest text-solus-text-muted">System Intelligence</span>
      </div>

      {/* Messages */}
      <div ref={scrollRef} className="flex-1 overflow-y-auto p-4 space-y-2">
        {messages.map(msg => {
          if (msg.role === 'user') {
            return (
              <div key={msg.id} className="py-1">
                <span className="text-xs font-mono text-solus-text-muted">Q:</span>
                <span className="text-xs font-mono text-solus-text ml-2">{msg.content}</span>
              </div>
            )
          }

          if (msg.role === 'system') {
            const bg = msg.variant === 'error' ? 'bg-solus-error/10 border-solus-error/20 text-solus-error'
              : msg.variant === 'success' ? 'bg-solus-success/10 border-solus-success/20 text-solus-success'
              : 'bg-solus-warning/10 border-solus-warning/20 text-solus-warning'
            return (
              <div key={msg.id} className={`w-full ${bg} border px-3 py-1.5`}>
                <span className="text-xs font-mono">{msg.content}</span>
              </div>
            )
          }

          // Assistant
          return (
            <div key={msg.id} className="w-full bg-solus-elevated border border-solus-border px-4 py-3">
              {renderContent(msg.content, msg.id)}
            </div>
          )
        })}
        {loading && (
          <div className="flex items-center gap-2 text-solus-text-muted py-2">
            <Loader2 size={14} className="animate-spin" />
            <span className="text-xs font-mono uppercase tracking-widest">Analyzing...</span>
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
        <input
          value={input}
          onChange={e => setInput(e.target.value)}
          onKeyDown={e => { if (e.key === 'Enter') handleSubmit() }}
          placeholder="Ask about your system..."
          className="flex-1 bg-solus-bg border border-solus-border px-3 py-1.5 font-mono text-sm text-solus-text placeholder:text-solus-text-muted"
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
            className="bg-solus-accent hover:bg-solus-accent-bright text-white p-2 transition-colors">
            <Send size={14} />
          </button>
        )}
      </div>
    </div>
  )
}
