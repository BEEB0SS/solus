import { useState, useEffect, useRef } from 'react'
import { useProjectStore } from '../../stores/projectStore'

export interface SignalState {
  current: number
  min: number
  max: number
  unit: string
  history: number[]
}

export type ConnStatus = 'disconnected' | 'connecting' | 'connected'

export interface TelemetrySocket {
  status: ConnStatus
  connectionMode: 'simulated' | 'serial' | null
  signals: Record<string, SignalState>
  anomalies: any[]
  discoveryBanner: string
  flashBanner: boolean
  showErrorBanner: boolean
  errorBannerSent: boolean
  errorSummary: string
  connect: () => Promise<void>
  disconnect: () => void
  sendCommand: (cmd: string) => void
  sendLogsToAgent: () => Promise<void>
  dismissErrorBanner: () => void
}

// Owns the WebSocket lifecycle, telemetry buffers, and anomaly banner state.
// `connect` is deliberately a plain per-render function: its ws callbacks read
// `connectionMode`/`showErrorBanner`/`status` from the closure captured at
// connect() time, which is the established behavior of this tab.
export function useTelemetrySocket(opts: {
  pid: string
  mode: string
  port: string
  baud: string
}): TelemetrySocket {
  const { pid, mode, port, baud } = opts
  const store = useProjectStore()

  const [status, setStatus] = useState<ConnStatus>('disconnected')
  const [connectionMode, setConnectionMode] = useState<'simulated' | 'serial' | null>(null)
  const [signals, setSignals] = useState<Record<string, SignalState>>({})
  const [anomalies, setAnomalies] = useState<any[]>([])
  const [discoveryBanner, setDiscoveryBanner] = useState('')
  const [flashBanner, setFlashBanner] = useState(false)

  // Anomaly auto-detection
  const [showErrorBanner, setShowErrorBanner] = useState(false)
  const [errorBannerSent, setErrorBannerSent] = useState(false)
  const [errorSummary, setErrorSummary] = useState('')
  const anomalyCountRef = useRef(0)

  const wsRef = useRef<WebSocket | null>(null)
  const signalsRef = useRef<Record<string, SignalState>>({})

  // ── Poll telemetry when connected ──
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

  // ── Connect / disconnect ──
  const connect = async () => {
    const projectId = pid || 'demo'
    setStatus('connecting')
    setConnectionMode(mode as 'simulated' | 'serial')
    setAnomalies([])
    setSignals({})
    signalsRef.current = {}

    try {
      const startRes = await fetch(`/api/projects/${projectId}/live-bench/start`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ mode, port, baud: parseInt(baud) }),
      })
      console.log('[live-bench] start response:', startRes.status)
    } catch (e) { console.error('[live-bench] start failed:', e) }

    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
    const wsUrl = `${protocol}//${window.location.host}/ws/projects/${projectId}/live-bench`
    console.log('[live-bench] connecting WS:', wsUrl)
    const ws = new WebSocket(wsUrl)
    wsRef.current = ws

    ws.onopen = () => {
      console.log('[live-bench] WS connected')
      setStatus('connected')
      setTimeout(async () => {
        try {
          const disc = await store.discoverDevices(projectId)
          if (disc.discovered_peripherals?.length) {
            setDiscoveryBanner(`Discovered: ${disc.discovered_peripherals.join(', ')}`)
            setTimeout(() => setDiscoveryBanner(''), 10000)
          }
          store.fetchGraph(projectId)
        } catch { /* */ }
      }, 2000)
    }

    ws.onmessage = (evt) => {
      try {
        const data = JSON.parse(evt.data)
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
        if (data.anomalies?.length) {
          const newAnomalies = data.anomalies
          setAnomalies(prev => [...newAnomalies, ...prev].slice(0, 100))
          // Track pattern anomalies for auto-detection (serial mode only)
          if (connectionMode === 'serial') {
            const patternCount = newAnomalies.filter((a: any) => a.pattern_type).length
            if (patternCount >= 1) {
              anomalyCountRef.current += 1
            }
            if (anomalyCountRef.current >= 3 && !showErrorBanner) {
              const patternTypes = newAnomalies
                .filter((a: any) => a.pattern_type)
                .map((a: any) => (a.pattern_type as string).replace(/_/g, ' '))
              const uniqueTypes = [...new Set(patternTypes)] as string[]
              setErrorSummary(uniqueTypes.length > 0
                ? `Detected on robot: ${uniqueTypes.join(', ')}`
                : 'Multiple anomalies detected on the connected device')
              setShowErrorBanner(true)
              setErrorBannerSent(false)
            }
          }
        }
        if (data.event === 'disconnected') { setStatus('disconnected'); setConnectionMode(null); setSignals({}); signalsRef.current = {}; setAnomalies([]); setShowErrorBanner(false); anomalyCountRef.current = 0 }
        if (data.event === 'code_flashed') { setFlashBanner(true); setTimeout(() => setFlashBanner(false), 15000) }
      } catch { /* */ }
    }
    ws.onerror = (e) => { console.error('[live-bench] WS error:', e) }
    ws.onclose = (e) => { console.log('[live-bench] WS closed:', e.code, e.reason); if (status === 'connected') setStatus('disconnected') }
  }

  const disconnect = () => {
    if (wsRef.current) { wsRef.current.onmessage = null; wsRef.current.close(); wsRef.current = null }
    fetch(`/api/projects/${pid || 'demo'}/live-bench/stop`, { method: 'POST' }).catch(() => {})
    setStatus('disconnected')
    setConnectionMode(null)
    setSignals({})
    signalsRef.current = {}
    setAnomalies([])
    setDiscoveryBanner('')
    setFlashBanner(false)
    setShowErrorBanner(false)
    setErrorBannerSent(false)
    anomalyCountRef.current = 0
  }

  const sendCommand = (cmd: string) => {
    fetch(`/api/projects/${pid || 'demo'}/live-bench/command`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ command: cmd }),
    }).catch(() => {})
  }

  const sendLogsToAgent = async () => {
    try {
      const res = await fetch(`/api/projects/${pid || 'demo'}/live-bench/logs`)
      const data = await res.json()
      localStorage.setItem('solus_agent_context', JSON.stringify({
        source: 'live_bench', logs: data, timestamp: Date.now(),
        prompt: 'Robot anomalies detected. ' + (data.report || '') + '\nAnalyze the robot code, identify the bug, and generate corrected code.',
      }))
      setErrorBannerSent(true)
      setErrorSummary('Logs sent — switch to Intelligence tab to see the diagnosis')
    } catch { /* */ }
  }

  const dismissErrorBanner = () => setShowErrorBanner(false)

  return {
    status,
    connectionMode,
    signals,
    anomalies,
    discoveryBanner,
    flashBanner,
    showErrorBanner,
    errorBannerSent,
    errorSummary,
    connect,
    disconnect,
    sendCommand,
    sendLogsToAgent,
    dismissErrorBanner,
  }
}
