import { useState, useEffect, useRef, useCallback } from 'react'
import { Play, Square, RotateCw, Send, RefreshCw, Clipboard, Activity, AlertTriangle, Download } from 'lucide-react'
import { LineChart, Line, ResponsiveContainer } from 'recharts'
import { useProjectStore } from '../../stores/projectStore'

interface SignalState {
  current: number
  min: number
  max: number
  unit: string
  history: number[]
}

interface CompareRow {
  signal: string
  simulated: number
  observed: number
  delta: number
  status: 'match' | 'deviation' | 'mismatch'
}

type ConnStatus = 'disconnected' | 'connecting' | 'connected'

const SIM_PARAM_DEFS = [
  { key: 'wheel_radius', label: 'Wheel Radius', step: 0.001, unit: 'm' },
  { key: 'chassis_length', label: 'Chassis Length', step: 0.01, unit: 'm' },
  { key: 'chassis_width', label: 'Chassis Width', step: 0.01, unit: 'm' },
  { key: 'motor_torque', label: 'Motor Torque', step: 0.01, unit: 'Nm' },
] as const

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
  const [cameraConnected, setCameraConnected] = useState(true)
  const [cameraUrl, setCameraUrl] = useState('')

  // Simulation state
  const [simParams, setSimParams] = useState({
    wheel_radius: 0.033, chassis_length: 0.16, chassis_width: 0.14,
    motor_torque: 0.5, kp: 2.0, target_distance: 0.25,
  })
  const [simTrajectory, setSimTrajectory] = useState<any[]>([])
  const [simRunning, setSimRunning] = useState(false)
  const [simPanelFocused, setSimPanelFocused] = useState(false)
  const [robotPos, setRobotPos] = useState({ x: 200, y: 150 })
  const [robotAngle, setRobotAngle] = useState(-Math.PI / 2)
  const [robotTrail, setRobotTrail] = useState<{ x: number; y: number }[]>([])
  const [obstacles] = useState([
    { x: 300, y: 80, w: 30, h: 20 },
    { x: 120, y: 220, w: 25, h: 25 },
    { x: 320, y: 200, w: 20, h: 30 },
  ])

  // Sim vs Real comparison state
  const [comparison, setComparison] = useState<CompareRow[]>([])
  const [mismatchAlert, setMismatchAlert] = useState('')
  const [paramsSource, setParamsSource] = useState<'manual' | 'onshape'>('manual')
  const [resyncMsg, setResyncMsg] = useState('')
  const [resyncing, setResyncing] = useState(false)

  const wsRef = useRef<WebSocket | null>(null)
  const signalsRef = useRef<Record<string, SignalState>>({})
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const simPanelRef = useRef<HTMLDivElement>(null)
  const animFrameRef = useRef<number>(0)

  const serialConnected = mode === 'serial' && status === 'connected'
  const bothActive = simRunning && serialConnected

  // Check if Onshape source is connected
  useEffect(() => {
    const hasOnshape = store.sources.some((s: any) => s.source_type === 'onshape')
    setParamsSource(hasOnshape ? 'onshape' : 'manual')
  }, [store.sources])

  // ── Fetch serial ports ──
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

  // ── Poll state when connected ──
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

  // ── Auto-compare sim vs real when both active ──
  useEffect(() => {
    if (!bothActive) {
      setComparison([])
      setMismatchAlert('')
      return
    }
    const iv = setInterval(async () => {
      try {
        const res = await fetch(`/api/projects/${pid}/simulator/compare`, { method: 'POST' })
        const data = await res.json()
        const rows: CompareRow[] = data.comparisons || []
        setComparison(rows)

        // Check for mismatches to show alert
        const mismatched = rows.filter(r => r.status === 'mismatch')
        if (mismatched.length > 0) {
          const sigNames = mismatched.map(r => r.signal).join(', ')
          setMismatchAlert(
            `Simulation mismatch detected \u2014 wheel_radius may be incorrect. Check Onshape model dimensions. Mismatched signals: ${sigNames}`
          )
        } else {
          setMismatchAlert('')
        }
      } catch { /* */ }
    }, 2000)
    return () => clearInterval(iv)
  }, [bothActive, pid])

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
          setAnomalies(prev => [...data.anomalies, ...prev].slice(0, 100))
        }

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
      alert('Logs sent \u2014 switch to Intelligence tab')
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

  // ── Canvas drawing ──
  const drawCanvas = useCallback(() => {
    const canvas = canvasRef.current
    if (!canvas) return
    const ctx = canvas.getContext('2d')
    if (!ctx) return
    const W = canvas.width
    const H = canvas.height

    ctx.fillStyle = '#0a0a0f'
    ctx.fillRect(0, 0, W, H)

    ctx.strokeStyle = '#1a1a2e'
    ctx.lineWidth = 0.5
    for (let gx = 0; gx < W; gx += 20) { ctx.beginPath(); ctx.moveTo(gx, 0); ctx.lineTo(gx, H); ctx.stroke() }
    for (let gy = 0; gy < H; gy += 20) { ctx.beginPath(); ctx.moveTo(0, gy); ctx.lineTo(W, gy); ctx.stroke() }

    ctx.fillStyle = '#ef4444'
    for (const o of obstacles) {
      ctx.fillRect(o.x, o.y, o.w, o.h)
    }

    if (robotTrail.length > 1) {
      ctx.beginPath()
      ctx.strokeStyle = '#3b82f680'
      ctx.lineWidth = 1.5
      ctx.moveTo(robotTrail[0].x, robotTrail[0].y)
      for (let i = 1; i < robotTrail.length; i++) ctx.lineTo(robotTrail[i].x, robotTrail[i].y)
      ctx.stroke()
    }

    if (simTrajectory.length > 1) {
      ctx.beginPath()
      ctx.strokeStyle = '#22c55e40'
      ctx.lineWidth = 1
      ctx.setLineDash([4, 4])
      const startX = 200, startY = 150
      ctx.moveTo(startX, startY)
      for (let i = 0; i < simTrajectory.length; i++) {
        const pt = simTrajectory[i]
        const px = startX + (pt.left_vel + pt.right_vel) * 50 * pt.t
        const py = startY + (pt.left_vel - pt.right_vel) * 20 * pt.t
        ctx.lineTo(px, py)
      }
      ctx.stroke()
      ctx.setLineDash([])
    }

    ctx.save()
    ctx.translate(robotPos.x, robotPos.y)
    ctx.rotate(robotAngle)

    const rw = 20, rh = 15
    const statusColor = status === 'connected' ? '#3b82f6' : '#64748b'
    ctx.fillStyle = statusColor
    ctx.fillRect(-rw / 2, -rh / 2, rw, rh)
    ctx.strokeStyle = '#e2e8f0'
    ctx.lineWidth = 1
    ctx.strokeRect(-rw / 2, -rh / 2, rw, rh)

    ctx.fillStyle = '#1e293b'
    const wheelW = 4, wheelH = 3
    ctx.fillRect(-rw / 2 - 1, -rh / 2 - 1, wheelW, wheelH)
    ctx.fillRect(rw / 2 - wheelW + 1, -rh / 2 - 1, wheelW, wheelH)
    ctx.fillRect(-rw / 2 - 1, rh / 2 - wheelH + 1, wheelW, wheelH)
    ctx.fillRect(rw / 2 - wheelW + 1, rh / 2 - wheelH + 1, wheelW, wheelH)

    ctx.beginPath()
    ctx.strokeStyle = '#06b6d4'
    ctx.lineWidth = 1.5
    ctx.moveTo(rw / 2, 0)
    ctx.lineTo(rw / 2 + 25, 0)
    ctx.stroke()
    ctx.beginPath()
    ctx.moveTo(rw / 2 + 20, -5)
    ctx.lineTo(rw / 2 + 25, 0)
    ctx.lineTo(rw / 2 + 20, 5)
    ctx.strokeStyle = '#06b6d480'
    ctx.stroke()

    ctx.restore()
  }, [robotPos, robotAngle, robotTrail, obstacles, simTrajectory, status])

  useEffect(() => {
    drawCanvas()
  }, [drawCanvas])

  // ── Keyboard controls ──
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (!simPanelFocused) return
      const key = e.key.toLowerCase()
      const step = 5
      const turnStep = 0.15

      if (['w', 's', 'a', 'd', ' ', 'arrowup', 'arrowdown', 'arrowleft', 'arrowright'].includes(key)) {
        e.preventDefault()
      }

      if (mode === 'serial' && status === 'connected') {
        const cmdMap: Record<string, string> = {
          'w': 'FORWARD', 'arrowup': 'FORWARD',
          's': 'REVERSE', 'arrowdown': 'REVERSE',
          'a': 'LEFT', 'arrowleft': 'LEFT',
          'd': 'RIGHT', 'arrowright': 'RIGHT',
          ' ': 'STOP',
        }
        const cmd = cmdMap[key]
        if (cmd) sendCommand(cmd)
      }

      setRobotPos(prev => {
        let nx = prev.x, ny = prev.y
        if (key === 'w' || key === 'arrowup') {
          nx += Math.cos(robotAngle) * step
          ny += Math.sin(robotAngle) * step
        } else if (key === 's' || key === 'arrowdown') {
          nx -= Math.cos(robotAngle) * step
          ny -= Math.sin(robotAngle) * step
        }
        nx = Math.max(10, Math.min(390, nx))
        ny = Math.max(10, Math.min(290, ny))
        if (nx !== prev.x || ny !== prev.y) {
          setRobotTrail(t => [...t.slice(-200), { x: nx, y: ny }])
        }
        return { x: nx, y: ny }
      })
      if (key === 'a' || key === 'arrowleft') {
        setRobotAngle(a => a - turnStep)
      } else if (key === 'd' || key === 'arrowright') {
        setRobotAngle(a => a + turnStep)
      }
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [simPanelFocused, status, mode, robotAngle, sendCommand])

  // ── Simulation handlers ──
  const runSimulation = useCallback(async () => {
    setSimRunning(true)
    setComparison([])
    setMismatchAlert('')
    try {
      const res = await fetch(`/api/projects/${pid}/simulator/run`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          wheel_radius: simParams.wheel_radius,
          chassis_length: simParams.chassis_length,
          chassis_width: simParams.chassis_width,
          motor_torque: simParams.motor_torque,
          kp: simParams.kp,
          target_dist: simParams.target_distance,
          n_steps: 500,
          dt: 0.002,
        }),
      })
      const data = await res.json()
      const traj: any[] = data.trajectory || []
      setSimTrajectory(traj)

      if (traj.length > 0) {
        let i = 0
        const startX = 200, startY = 150
        const animate = () => {
          if (i >= traj.length) { return }
          const pt = traj[i]
          const px = startX + (pt.left_vel + pt.right_vel) * 50 * pt.t
          const py = startY + (pt.left_vel - pt.right_vel) * 20 * pt.t
          setRobotPos({ x: Math.max(10, Math.min(390, px)), y: Math.max(10, Math.min(290, py)) })
          setRobotTrail(t => [...t.slice(-200), { x: px, y: py }])
          i += 5
          animFrameRef.current = requestAnimationFrame(animate)
        }
        animate()
      }
    } catch {
      setSimRunning(false)
    }
  }, [pid, simParams])

  const handleParamChange = (key: string, value: number) => {
    setSimParams(p => ({ ...p, [key]: value }))
  }

  const resyncFromOnshape = useCallback(async () => {
    setResyncing(true)
    setResyncMsg('')
    try {
      const res = await fetch(`/api/projects/${pid}/simulator/update-from-onshape`, { method: 'POST' })
      const data = await res.json()
      if (data.params) {
        const changes: string[] = []
        for (const [k, v] of Object.entries(data.params) as [string, number][]) {
          if (k in simParams && simParams[k as keyof typeof simParams] !== v) {
            changes.push(`${k} changed from ${simParams[k as keyof typeof simParams]} to ${v}`)
          }
        }
        setSimParams(p => ({ ...p, ...data.params }))
        setResyncMsg(changes.length > 0 ? `Updated: ${changes.join(', ')}` : 'Parameters already up to date')
        if (changes.length > 0) {
          // Re-run sim with new params after short delay
          setTimeout(() => runSimulation(), 500)
        }
      } else {
        setResyncMsg('No parameters returned from Onshape')
      }
      setTimeout(() => setResyncMsg(''), 8000)
    } catch {
      setResyncMsg('Failed to resync from Onshape')
      setTimeout(() => setResyncMsg(''), 5000)
    }
    setResyncing(false)
  }, [pid, simParams, runSimulation])

  useEffect(() => {
    return () => { if (animFrameRef.current) cancelAnimationFrame(animFrameRef.current) }
  }, [])

  const signalCount = Object.keys(signals).length
  const anomalyCount = anomalies.length

  const compareStatusColor = (s: string) =>
    s === 'match' ? 'bg-green-500/20 text-green-400' :
    s === 'deviation' ? 'bg-yellow-500/20 text-yellow-400' :
    'bg-red-500/20 text-red-400'

  const compareStatusIcon = (s: string) =>
    s === 'match' ? '\u2713 MATCH' :
    s === 'deviation' ? '\u26A0 DEVIATION' :
    '\u26A0 MISMATCH'

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

      {/* Mismatch alert banner */}
      {mismatchAlert && (
        <div className="bg-red-600/20 border-b border-red-500/30 text-red-400 text-xs font-mono px-4 py-2 flex items-center gap-2">
          <AlertTriangle size={14} className="shrink-0" />
          <span>{mismatchAlert}</span>
        </div>
      )}

      {/* Resync result banner */}
      {resyncMsg && (
        <div className="bg-solus-accent/20 text-solus-accent-bright text-xs font-mono px-4 py-1.5">
          {resyncMsg}
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

            <input
              value={cameraUrl}
              onChange={e => { setCameraUrl(e.target.value); setCameraConnected(true) }}
              placeholder="192.168.4.1"
              className="bg-solus-bg border border-solus-border rounded px-2 py-1 text-[10px] font-mono text-solus-text w-32 placeholder:text-solus-text-muted"
            />
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

      {/* Camera feed */}
      {mode === 'serial' && status === 'connected' && cameraUrl && (
        <div className="relative bg-black border-b border-solus-border">
          {cameraConnected ? (
            <>
              <img
                src={`http://${cameraUrl}:81/stream`}
                alt="Camera feed"
                className="w-full max-h-48 object-contain bg-black rounded border border-solus-border"
                onError={() => setCameraConnected(false)}
              />
              <span className="absolute top-2 right-2 bg-red-500 text-white text-[10px] font-mono font-bold px-1 rounded">
                LIVE
              </span>
            </>
          ) : (
            <div className="w-full h-20 flex items-center justify-center text-xs font-mono text-solus-text-muted">
              Camera unavailable
            </div>
          )}
        </div>
      )}

      {/* Main area — two panels */}
      <div className="flex flex-1 overflow-hidden">

        {/* LEFT: SIMULATION */}
        <div
          ref={simPanelRef}
          className={`flex-1 border-r border-solus-border overflow-y-auto p-3 focus:outline-none ${simPanelFocused ? 'ring-1 ring-solus-accent/30' : ''}`}
          tabIndex={0}
          onFocus={() => setSimPanelFocused(true)}
          onBlur={() => setSimPanelFocused(false)}
        >
          <div className="flex items-center gap-2 mb-2">
            <Activity size={12} className="text-solus-accent-bright" />
            <span className="text-[10px] font-mono font-semibold uppercase tracking-widest text-solus-text-muted">Simulation</span>
            {simPanelFocused && (
              <span className="text-[9px] font-mono text-solus-text-muted ml-auto">WASD to drive</span>
            )}
          </div>

          {/* Canvas */}
          <canvas
            ref={canvasRef}
            width={400}
            height={300}
            className="w-full max-w-[400px] bg-solus-bg border border-solus-border rounded"
          />

          {/* Sim Parameters */}
          <div className="mt-3">
            <div className="flex items-center gap-2 mb-2">
              <span className="text-[10px] font-mono font-semibold uppercase tracking-widest text-solus-text-muted">Sim Parameters</span>
              <span className={`text-[9px] font-mono px-1.5 py-0.5 rounded ${
                paramsSource === 'onshape' ? 'bg-solus-accent/15 text-solus-accent-bright' : 'bg-solus-text-muted/15 text-solus-text-muted'
              }`}>
                {paramsSource === 'onshape' ? 'From Onshape' : 'Manual'}
              </span>
            </div>
            <div className="grid grid-cols-2 gap-2">
              {SIM_PARAM_DEFS.map(({ key, label, step, unit }) => (
                <div key={key} className="flex items-center gap-1.5">
                  <label className="text-[9px] font-mono text-solus-text-muted w-24 shrink-0">{label}</label>
                  <input
                    type="number"
                    step={step}
                    value={simParams[key as keyof typeof simParams]}
                    onChange={e => handleParamChange(key, parseFloat(e.target.value) || 0)}
                    className="bg-solus-bg border border-solus-border rounded px-1.5 py-0.5 text-[10px] font-mono text-solus-text w-20"
                  />
                  <span className="text-[9px] font-mono text-solus-text-muted">{unit}</span>
                </div>
              ))}
              {/* kp and target_distance */}
              <div className="flex items-center gap-1.5">
                <label className="text-[9px] font-mono text-solus-text-muted w-24 shrink-0">Kp</label>
                <input
                  type="number" step="0.1"
                  value={simParams.kp}
                  onChange={e => handleParamChange('kp', parseFloat(e.target.value) || 0)}
                  className="bg-solus-bg border border-solus-border rounded px-1.5 py-0.5 text-[10px] font-mono text-solus-text w-20"
                />
              </div>
              <div className="flex items-center gap-1.5">
                <label className="text-[9px] font-mono text-solus-text-muted w-24 shrink-0">Target Dist</label>
                <input
                  type="number" step="0.01"
                  value={simParams.target_distance}
                  onChange={e => handleParamChange('target_distance', parseFloat(e.target.value) || 0)}
                  className="bg-solus-bg border border-solus-border rounded px-1.5 py-0.5 text-[10px] font-mono text-solus-text w-20"
                />
                <span className="text-[9px] font-mono text-solus-text-muted">m</span>
              </div>
            </div>
          </div>

          {/* Sim buttons */}
          <div className="mt-3 flex items-center gap-2 flex-wrap">
            <button
              onClick={runSimulation}
              disabled={simRunning}
              className="flex items-center gap-1 bg-solus-accent/20 hover:bg-solus-accent/30 text-solus-accent-bright text-[10px] font-mono px-3 py-1.5 rounded transition-colors disabled:opacity-40"
            >
              <Play size={10} /> {simRunning ? 'Running...' : 'Run Simulation'}
            </button>
            <button
              onClick={resyncFromOnshape}
              disabled={resyncing}
              className="flex items-center gap-1 bg-solus-warning/20 hover:bg-solus-warning/30 text-solus-warning text-[10px] font-mono px-3 py-1.5 rounded transition-colors disabled:opacity-40"
            >
              <Download size={10} /> {resyncing ? 'Resyncing...' : 'Resync from Onshape'}
            </button>
          </div>

          {/* SIM vs REAL comparison table */}
          {comparison.length > 0 && (
            <div className="mt-3">
              <span className="text-[10px] font-mono font-semibold uppercase tracking-widest text-solus-text-muted">SIM vs REAL</span>
              <table className="w-full mt-1 text-[10px] font-mono">
                <thead>
                  <tr className="text-solus-text-muted border-b border-solus-border">
                    <th className="text-left py-1 pr-2">Signal</th>
                    <th className="text-right py-1 pr-2">Simulated</th>
                    <th className="text-right py-1 pr-2">Real</th>
                    <th className="text-right py-1 pr-2">Delta</th>
                    <th className="text-left py-1">Status</th>
                  </tr>
                </thead>
                <tbody>
                  {comparison.map((d) => (
                    <tr key={d.signal} className="border-b border-solus-border/30">
                      <td className="py-1 pr-2 text-solus-text">{d.signal}</td>
                      <td className="py-1 pr-2 text-right text-solus-text-muted">{d.simulated?.toFixed(4)}</td>
                      <td className="py-1 pr-2 text-right text-solus-text-muted">{d.observed?.toFixed(4)}</td>
                      <td className="py-1 pr-2 text-right text-solus-text-muted">{d.delta?.toFixed(4)}</td>
                      <td className="py-1">
                        <span className={`px-1.5 py-0.5 rounded text-[9px] font-bold ${compareStatusColor(d.status)}`}>
                          {compareStatusIcon(d.status)}
                        </span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>

        {/* RIGHT: TELEMETRY */}
        <div className="flex-1 flex overflow-hidden">
          {/* Signal grid */}
          <div className="flex-1 overflow-y-auto p-3">
            <div className="flex items-center gap-2 mb-2">
              <span className="text-[10px] font-mono font-semibold uppercase tracking-widest text-solus-text-muted">Telemetry</span>
            </div>
            <div className="grid grid-cols-2 gap-2">
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
    </div>
  )
}
