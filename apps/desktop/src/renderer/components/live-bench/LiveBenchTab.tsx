import { useState, useEffect, useRef, useCallback } from 'react'
import { Play, Square, RotateCw, Send, RefreshCw, Clipboard } from 'lucide-react'
import { LineChart, Line, ResponsiveContainer } from 'recharts'
import { useProjectStore } from '../../stores/projectStore'

interface SignalState {
  current: number
  min: number
  max: number
  unit: string
  history: number[]
}

type ConnStatus = 'disconnected' | 'connecting' | 'connected'

export default function LiveBenchTab() {
  const store = useProjectStore()
  const pid = store.currentProjectId

  const [status, setStatus] = useState<ConnStatus>('disconnected')
  const [mode, setMode] = useState('simulated')
  const [port, setPort] = useState('')
  const [baud, setBaud] = useState('9600')
  const [ports, setPorts] = useState<any[]>([])
  const [signals, setSignals] = useState<Record<string, SignalState>>({})
  const [anomalies, setAnomalies] = useState<any[]>([])
  const [customCmd, setCustomCmd] = useState('')
  const [discoveryBanner, setDiscoveryBanner] = useState('')
  const [flashBanner, setFlashBanner] = useState(false)
  const wsRef = useRef<WebSocket | null>(null)
  const signalsRef = useRef<Record<string, SignalState>>({})

  // Fetch serial ports
  const fetchPorts = useCallback(async () => {
    try {
      const res = await fetch('/api/serial-ports')
      const data = await res.json()
      setPorts(data)
      const arduino = data.find((p: any) => p.is_arduino)
      if (arduino && !port) setPort(arduino.device)
    } catch { /* */ }
  }, [port])

  useEffect(() => { fetchPorts() }, [])

  // Poll state when connected
  useEffect(() => {
    if (status !== 'connected') return
    const iv = setInterval(async () => {
      try {
        const res = await fetch(`/api/projects/${pid}/live-bench/state`)
        const data = await res.json()
        if (data.signals && typeof data.signals === 'object') {
          setSignals(prev => {
            const next = { ...prev }
            for (const [name, info] of Object.entries(data.signals) as [string, any][]) {
              const existing = next[name]
              next[name] = {
                current: info.value ?? existing?.current ?? 0,
                min: info.min ?? existing?.min ?? 0,
                max: info.max ?? existing?.max ?? 0,
                unit: info.unit ?? existing?.unit ?? '',
                history: existing?.history ?? [],
              }
            }
            signalsRef.current = next
            return next
          })
        }
      } catch { /* */ }
    }, 3000)
    return () => clearInterval(iv)
  }, [status, pid])

  const connect = async () => {
    setStatus('connecting')
    setAnomalies([])
    setSignals({})
    signalsRef.current = {}

    try {
      await fetch(`/api/projects/${pid}/live-bench/start`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ mode, port, baud: parseInt(baud) }),
      })
    } catch { /* */ }

    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
    const ws = new WebSocket(`${protocol}//${window.location.host}/ws/projects/${pid}/live-bench`)
    wsRef.current = ws

    ws.onopen = () => {
      setStatus('connected')
      // Discover devices after 2s
      setTimeout(async () => {
        try {
          const disc = await store.discoverDevices(pid)
          if (disc.discovered_peripherals?.length) {
            setDiscoveryBanner(`Discovered: ${disc.discovered_peripherals.join(', ')}`)
            setTimeout(() => setDiscoveryBanner(''), 10000)
          }
          store.fetchGraph(pid)
        } catch { /* */ }
      }, 2000)
    }

    ws.onmessage = (evt) => {
      try {
        const data = JSON.parse(evt.data)

        // Handle signals array from packet
        if (data.packet?.signals && Array.isArray(data.packet.signals)) {
          setSignals(prev => {
            const next = { ...prev }
            for (const sig of data.packet.signals) {
              const existing = next[sig.name]
              const val = sig.value ?? 0
              const hist = [...(existing?.history ?? []), val].slice(-50)
              next[sig.name] = {
                current: val,
                min: existing ? Math.min(existing.min, val) : val,
                max: existing ? Math.max(existing.max, val) : val,
                unit: sig.unit ?? existing?.unit ?? '',
                history: hist,
              }
            }
            signalsRef.current = next
            return next
          })
        }

        // Anomalies
        if (data.anomalies?.length) {
          setAnomalies(prev => [...data.anomalies, ...prev].slice(0, 100))
        }

        // Events
        if (data.event === 'disconnected') {
          setStatus('disconnected')
          setSignals({})
          signalsRef.current = {}
          setAnomalies([])
        }
        if (data.event === 'code_flashed') {
          setFlashBanner(true)
          setTimeout(() => setFlashBanner(false), 15000)
        }
      } catch { /* */ }
    }

    ws.onclose = () => {
      if (status === 'connected') setStatus('disconnected')
    }
  }

  const disconnect = () => {
    if (wsRef.current) {
      wsRef.current.onmessage = null
      wsRef.current.close()
      wsRef.current = null
    }
    fetch(`/api/projects/${pid}/live-bench/stop`, { method: 'POST' }).catch(() => {})
    setStatus('disconnected')
    setSignals({})
    signalsRef.current = {}
    setAnomalies([])
    setDiscoveryBanner('')
    setFlashBanner(false)
  }

  const sendCommand = (cmd: string) => {
    fetch(`/api/projects/${pid}/live-bench/command`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ command: cmd }),
    }).catch(() => {})
  }

  const sendLogsToAgent = async () => {
    try {
      const res = await fetch(`/api/projects/${pid}/live-bench/logs`)
      const data = await res.json()
      localStorage.setItem('solus_agent_context', JSON.stringify({
        source: 'live_bench',
        logs: data,
        timestamp: Date.now(),
        prompt: 'Robot anomalies detected. ' + (data.report || '') + '\nAnalyze the robot code, identify the bug, and generate corrected code.',
      }))
      alert('Logs sent — switch to Intelligence tab')
    } catch { /* */ }
  }

  const signalColor = (name: string, value: number): string => {
    const n = name.toLowerCase()
    if (n === 'running') return value === 1 ? '#22c55e' : '#64748b'
    if (n === 'bug_active') return value === 1 ? '#ef4444' : '#22c55e'
    if (n === 'kp_value') return value > 10 ? '#ef4444' : '#22c55e'
    if (n === 'kd_value') return value === 0 ? '#ef4444' : '#22c55e'
    if (n === 'pid_error') {
      const abs = Math.abs(value)
      if (abs < 5) return '#22c55e'
      if (abs < 15) return '#f59e0b'
      return '#ef4444'
    }
    if (n.includes('motor')) return Math.abs(value) > 1.2 ? '#ef4444' : '#22c55e'
    return '#e2e8f0'
  }

  const signalDisplay = (name: string, value: number): string => {
    const n = name.toLowerCase()
    if (n === 'running') return value === 1 ? 'RUNNING' : 'STOPPED'
    if (n === 'bug_active') return value === 1 ? 'BUG ACTIVE' : 'CLEAN'
    return value.toFixed(3)
  }

  const signalCount = Object.keys(signals).length
  const anomalyCount = anomalies.length

  return (
    <div className="flex h-full flex-col overflow-hidden">
      {/* Flash banner */}
      {flashBanner && (
        <div className="bg-green-600/90 text-white text-xs font-mono px-4 py-2 flex items-center justify-between">
          <span>New code deployed! Reconnect to see the fix.</span>
          <button onClick={() => { disconnect(); setTimeout(connect, 500) }}
            className="bg-white/20 hover:bg-white/30 px-2 py-0.5 rounded text-[10px]">Reconnect</button>
        </div>
      )}

      {/* Discovery banner */}
      {discoveryBanner && (
        <div className="bg-solus-accent/20 text-solus-accent-bright text-xs font-mono px-4 py-1.5">
          {discoveryBanner}
        </div>
      )}

      {/* Connection bar */}
      <div className="bg-solus-surface border-b border-solus-border p-2 flex items-center gap-2 flex-wrap">
        <div className={`w-2.5 h-2.5 rounded-full shrink-0 ${
          status === 'connected' ? 'bg-solus-success animate-pulse' :
          status === 'connecting' ? 'bg-solus-warning' : 'bg-solus-text-muted'
        }`} />

        <select value={mode} onChange={e => setMode(e.target.value)}
          className="bg-solus-bg border border-solus-border rounded px-2 py-1 text-[10px] font-mono text-solus-text">
          <option value="simulated">Simulated</option>
          <option value="serial">Serial</option>
        </select>

        {mode === 'serial' && (
          <>
            <div className="flex items-center gap-1">
              <select value={port} onChange={e => setPort(e.target.value)}
                className="bg-solus-bg border border-solus-border rounded px-2 py-1 text-[10px] font-mono text-solus-text max-w-[180px]">
                {ports.map(p => (
                  <option key={p.device} value={p.device}>
                    {p.device.split('/').pop()} {p.is_arduino ? '\u2713' : ''}
                  </option>
                ))}
                {ports.length === 0 && <option value="">No ports</option>}
              </select>
              <button onClick={fetchPorts} className="text-solus-text-muted hover:text-solus-text">
                <RefreshCw size={11} />
              </button>
            </div>

            <select value={baud} onChange={e => setBaud(e.target.value)}
              className="bg-solus-bg border border-solus-border rounded px-2 py-1 text-[10px] font-mono text-solus-text">
              <option value="9600">9600</option>
              <option value="115200">115200</option>
            </select>
          </>
        )}

        {status === 'disconnected' ? (
          <button onClick={connect}
            className="bg-solus-accent hover:bg-solus-accent-bright text-white text-[10px] font-mono px-3 py-1 rounded transition-colors">
            Connect
          </button>
        ) : (
          <button onClick={disconnect}
            className="bg-solus-error/80 hover:bg-solus-error text-white text-[10px] font-mono px-3 py-1 rounded transition-colors">
            Disconnect
          </button>
        )}

        <div className="flex-1" />
        <span className="text-[10px] font-mono text-solus-text-muted">
          {signalCount} signals · {anomalyCount} anomalies
        </span>
      </div>

      {/* Robot controls (serial mode) */}
      {mode === 'serial' && status === 'connected' && (
        <div className="bg-solus-surface/50 border-b border-solus-border p-2 flex items-center gap-2">
          <button onClick={() => sendCommand('start')}
            className="flex items-center gap-1 bg-solus-success/20 hover:bg-solus-success/30 text-solus-success text-[10px] font-mono px-2.5 py-1 rounded transition-colors">
            <Play size={10} /> START
          </button>
          <button onClick={() => sendCommand('stop')}
            className="flex items-center gap-1 bg-solus-error/20 hover:bg-solus-error/30 text-solus-error text-[10px] font-mono px-2.5 py-1 rounded transition-colors">
            <Square size={10} /> STOP
          </button>
          <button onClick={() => sendCommand('sweep')}
            className="flex items-center gap-1 bg-solus-accent/20 hover:bg-solus-accent/30 text-solus-accent-bright text-[10px] font-mono px-2.5 py-1 rounded transition-colors">
            <RotateCw size={10} /> SWEEP
          </button>
          <div className="flex-1" />
          <input value={customCmd} onChange={e => setCustomCmd(e.target.value)}
            onKeyDown={e => { if (e.key === 'Enter' && customCmd) { sendCommand(customCmd); setCustomCmd('') } }}
            placeholder="Command..."
            className="bg-solus-bg border border-solus-border rounded px-2 py-1 text-[10px] font-mono text-solus-text w-36 placeholder:text-solus-text-muted" />
          <button onClick={() => { if (customCmd) { sendCommand(customCmd); setCustomCmd('') } }}
            className="text-solus-text-muted hover:text-solus-text">
            <Send size={11} />
          </button>
        </div>
      )}

      {/* Main area */}
      <div className="flex flex-1 overflow-hidden">
        {/* Signal grid */}
        <div className="flex-1 overflow-y-auto p-3">
          <div className="grid grid-cols-2 xl:grid-cols-3 gap-2">
            {Object.entries(signals).map(([name, sig]) => {
              const color = signalColor(name, sig.current)
              const chartData = sig.history.map((v, i) => ({ i, v }))
              return (
                <div key={name} className="bg-solus-elevated border border-solus-border rounded-lg p-3">
                  <div className="text-[10px] font-mono uppercase tracking-widest text-solus-text-muted mb-1">
                    {name.replace(/_/g, ' ')}
                  </div>
                  <div className="text-xl font-mono font-bold tabular-nums" style={{ color }}>
                    {signalDisplay(name, sig.current)}
                  </div>
                  {chartData.length > 1 && (
                    <div className="mt-1.5 h-9">
                      <ResponsiveContainer width="100%" height="100%">
                        <LineChart data={chartData}>
                          <Line type="monotone" dataKey="v" stroke={color} dot={false} strokeWidth={1.5} isAnimationActive={false} />
                        </LineChart>
                      </ResponsiveContainer>
                    </div>
                  )}
                  <div className="text-[10px] font-mono text-solus-text-muted mt-1">
                    min {sig.min.toFixed(2)} · max {sig.max.toFixed(2)}
                  </div>
                </div>
              )
            })}
            {signalCount === 0 && (
              <div className="col-span-full text-xs font-mono text-solus-text-muted py-12 text-center">
                {status === 'connected' ? 'Waiting for signals...' : 'Connect to start receiving telemetry'}
              </div>
            )}
          </div>
        </div>

        {/* Anomaly sidebar */}
        <div className="w-72 border-l border-solus-border bg-solus-surface flex flex-col">
          <div className="p-3 border-b border-solus-border flex items-center justify-between">
            <div className="flex items-center gap-2">
              <span className="text-[10px] font-mono font-semibold uppercase tracking-widest text-solus-text-muted">Anomalies</span>
              {anomalyCount > 0 && (
                <span className="bg-solus-error text-white rounded-full px-2 text-[10px] font-mono font-bold min-w-[20px] text-center">
                  {anomalyCount}
                </span>
              )}
            </div>
          </div>

          <button onClick={sendLogsToAgent}
            className="mx-3 mt-2 flex items-center justify-center gap-1.5 bg-solus-accent/15 hover:bg-solus-accent/25 text-solus-accent-bright text-[10px] font-mono py-2 rounded transition-colors">
            <Clipboard size={11} /> Send Logs to Agent
          </button>

          <div className="flex-1 overflow-y-auto p-3 space-y-2">
            {anomalies.map((a: any, i: number) => (
              <div key={a.id || i} className="bg-solus-elevated border border-solus-border rounded-lg p-2.5 space-y-1">
                <div className="flex items-center gap-1.5 flex-wrap">
                  <span className={`text-[9px] font-mono font-bold px-1.5 py-0.5 rounded ${
                    a.severity === 'error' ? 'bg-red-500/20 text-red-400' : 'bg-yellow-500/20 text-yellow-400'
                  }`}>
                    {(a.severity || 'warn').toUpperCase()}
                  </span>
                  {a.pattern_type && (
                    <span className="text-[9px] font-mono px-1.5 py-0.5 rounded bg-solus-accent/15 text-solus-accent-bright">
                      {a.pattern_type.toUpperCase().replace(/_/g, '-')}
                    </span>
                  )}
                </div>
                {a.signal_name && (
                  <div className="text-[10px] font-mono text-solus-text">{a.signal_name}</div>
                )}
                {a.description && (
                  <div className="text-[10px] text-solus-text-dim leading-snug">{a.description}</div>
                )}
                {a.evidence && (
                  <div className="text-[9px] font-mono text-solus-text-muted">evidence: {a.evidence}</div>
                )}
                {a.expected && (
                  <div className="text-[9px] font-mono text-solus-text-muted">expected: {a.expected}</div>
                )}
              </div>
            ))}
            {anomalyCount === 0 && (
              <div className="text-[10px] font-mono text-solus-text-muted py-6 text-center">No anomalies detected</div>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}
