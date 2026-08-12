import { useState, useEffect, useRef, useCallback } from 'react'
import { Play, Square, RotateCw, Activity, Download } from 'lucide-react'
import { useProjectStore } from '../../stores/projectStore'
import * as THREE from 'three'
import { createBodyMesh, createScene, applyMujocoTransform, DEFAULT_BODIES } from './simScene'
import type { BodyState } from './simScene'

interface CompareRow {
  signal: string
  simulated: number
  observed: number
  delta: number
  status: 'match' | 'deviation' | 'mismatch'
}

const SIM_PARAM_DEFS = [
  { key: 'wheel_radius', label: 'Wheel Radius', step: 0.001, unit: 'm' },
  { key: 'chassis_length', label: 'Chassis Length', step: 0.01, unit: 'm' },
  { key: 'chassis_width', label: 'Chassis Width', step: 0.01, unit: 'm' },
  { key: 'motor_torque', label: 'Motor Torque', step: 0.01, unit: 'Nm' },
] as const

interface SimulationPanelProps {
  pid: string
  serialConnected: boolean
  sendSerialCommand: (cmd: string) => void
  onMismatchAlert: (msg: string) => void
  onResyncMsg: (msg: string) => void
}

export default function SimulationPanel({ pid, serialConnected, sendSerialCommand, onMismatchAlert, onResyncMsg }: SimulationPanelProps) {
  const store = useProjectStore()

  // Sim state
  const [simParams, setSimParams] = useState({
    wheel_radius: 0.033, chassis_length: 0.20, chassis_width: 0.15,
    motor_torque: 0.5, kp: 2.0, kd: 0.5, target_distance: 0.25,
  })
  const [simSensors, setSimSensors] = useState<Record<string, number>>({})
  const [pidRunning, setPidRunning] = useState(false)
  const [simPanelFocused, setSimPanelFocused] = useState(false)

  // Comparison state
  const [comparison, setComparison] = useState<CompareRow[]>([])
  const [paramsSource, setParamsSource] = useState<'manual' | 'onshape'>('manual')
  const [resyncing, setResyncing] = useState(false)

  // Three.js refs
  const containerRef = useRef<HTMLDivElement>(null)
  const sceneRef = useRef<ReturnType<typeof createScene> | null>(null)
  const meshesRef = useRef<Record<string, THREE.Mesh>>({})
  const trailCountRef = useRef(0)
  const animIdRef = useRef(0)
  const pidIntervalRef = useRef<number>(0)

  const bothActive = pidRunning && serialConnected

  // ── Update Three.js scene from backend state ──
  const updateScene = useCallback((state: { bodies?: Record<string, BodyState>, sensors?: Record<string, number> }) => {
    const s = sceneRef.current
    if (!s || !state.bodies) return

    for (const [name, body] of Object.entries(state.bodies)) {
      let mesh = meshesRef.current[name]
      if (!mesh) {
        mesh = createBodyMesh(name, body)
        s.scene.add(mesh)
        meshesRef.current[name] = mesh
      }
      mesh.position.set(body.pos[0], body.pos[2], -body.pos[1])
      mesh.quaternion.set(body.quat[1], body.quat[3], -body.quat[2], body.quat[0])
    }

    // Follow the chassis: move the orbit target (and camera by the same
    // delta, preserving the user's angle/zoom) so the car never drives
    // out of view.
    if (state.bodies.chassis) {
      const cp = state.bodies.chassis.pos
      const target = new THREE.Vector3(cp[0], cp[2], -cp[1])
      const delta = target.clone().sub(s.controls.target)
      s.controls.target.copy(target)
      s.camera.position.add(delta)
    }

    // Update trail
    if (state.bodies.chassis) {
      const cp = state.bodies.chassis.pos
      const idx = trailCountRef.current
      if (idx < 600) {
        s.trailPositions[idx * 3] = cp[0]
        s.trailPositions[idx * 3 + 1] = cp[2]
        s.trailPositions[idx * 3 + 2] = -cp[1]
        trailCountRef.current = idx + 1
        s.trailGeo.attributes.position.needsUpdate = true
        s.trailGeo.setDrawRange(0, trailCountRef.current)
      }
    }

    // Update ultrasonic beam
    if (state.bodies.chassis && state.sensors) {
      const cp = state.bodies.chassis.pos
      const dist = (state.sensors.distance_cm || 0) / 100
      const q = state.bodies.chassis.quat
      // Compute forward direction from quaternion
      const fwd = new THREE.Vector3(1, 0, 0)
      const quat = new THREE.Quaternion(q[1], q[3], -q[2], q[0])
      fwd.applyQuaternion(quat)

      const start = new THREE.Vector3(cp[0], cp[2], -cp[1])
      const end = start.clone().add(fwd.multiplyScalar(Math.min(dist, 4)))

      const positions = s.beamGeo.attributes.position as THREE.BufferAttribute
      positions.setXYZ(0, start.x, start.y, start.z)
      positions.setXYZ(1, end.x, end.y, end.z)
      positions.needsUpdate = true
    }

    if (state.sensors) {
      setSimSensors(state.sensors)
    }
  }, [])

  // ── Three.js init — single effect creates scene, meshes, and fetches state ──
  useEffect(() => {
    if (!containerRef.current) return

    // Always start fresh
    meshesRef.current = {}
    trailCountRef.current = 0

    const s = createScene(containerRef.current)
    sceneRef.current = s

    // Create all meshes immediately with default positions — guarantees they exist
    for (const [name, body] of Object.entries(DEFAULT_BODIES)) {
      const mesh = createBodyMesh(name, body)
      applyMujocoTransform(mesh, body)
      s.scene.add(mesh)
      meshesRef.current[name] = mesh
    }

    // Animation loop
    const animate = () => {
      animIdRef.current = requestAnimationFrame(animate)
      s.controls.update()
      s.renderer.render(s.scene, s.camera)
    }
    animate()

    // Fetch real positions from backend and update
    let cancelled = false
    const projectId = pid || 'demo'
    fetch(`/api/projects/${projectId}/simulator/state`)
      .then(r => { if (!r.ok) throw new Error(r.statusText); return r.json() })
      .then(data => {
        if (cancelled) return  // StrictMode: don't update if this mount was cleaned up
        console.log('[sim] State loaded:', Object.keys(data.bodies || {}))
        if (data.bodies) updateScene(data)
        if (data.params) setSimParams(p => ({ ...p, ...data.params }))
      })
      .catch(e => { if (!cancelled) console.warn('[sim] Fetch failed, using defaults:', e) })

    const observer = new ResizeObserver(entries => {
      const { width, height } = entries[0].contentRect
      if (width === 0 || height === 0) return
      s.camera.aspect = width / height
      s.camera.updateProjectionMatrix()
      s.renderer.setSize(width, height)
    })
    observer.observe(containerRef.current)

    return () => {
      cancelAnimationFrame(animIdRef.current)
      observer.disconnect()
      s.renderer.dispose()
      if (containerRef.current && s.renderer.domElement.parentNode === containerRef.current) {
        containerRef.current.removeChild(s.renderer.domElement)
      }
      sceneRef.current = null
      meshesRef.current = {}
      cancelled = true
    }
  }, []) // eslint-disable-line react-hooks/exhaustive-deps

  // ── Check Onshape source ──
  useEffect(() => {
    setParamsSource(store.sources.some((s: any) => s.source_type === 'onshape') ? 'onshape' : 'manual')
  }, [store.sources])

  // ── Auto-compare sim vs real ──
  useEffect(() => {
    if (!bothActive) { setComparison([]); onMismatchAlert(''); return }
    const iv = setInterval(async () => {
      try {
        const res = await fetch(`/api/projects/${pid}/simulator/compare`, { method: 'POST' })
        const data = await res.json()
        const rows: CompareRow[] = data.comparisons || []
        setComparison(rows)
        const mismatched = rows.filter(r => r.status === 'mismatch')
        onMismatchAlert(mismatched.length > 0
          ? `Simulation mismatch detected — wheel_radius may be incorrect. Check Onshape model dimensions. Mismatched: ${mismatched.map(r => r.signal).join(', ')}`
          : '')
      } catch { /* */ }
    }, 2000)
    return () => clearInterval(iv)
  }, [bothActive, pid]) // eslint-disable-line react-hooks/exhaustive-deps

  // ── Sim controls ──
  const handleManualCommand = useCallback(async (command: string, nSteps?: number) => {
    const projectId = pid || 'demo'
    try {
      const res = await fetch(`/api/projects/${projectId}/simulator/manual`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(nSteps ? { command, n_steps: nSteps } : { command }),
      })
      if (!res.ok) { console.error('[sim] manual API error:', res.status); return }
      const state = await res.json()
      updateScene(state)
    } catch (e) { console.error('[sim] manual command failed:', e) }
  }, [pid, updateScene])

  const startPid = useCallback(async () => {
    const projectId = pid || 'demo'
    // Reset trail
    trailCountRef.current = 0

    await fetch(`/api/projects/${projectId}/simulator/reset`, { method: 'POST' })
    await fetch(`/api/projects/${projectId}/simulator/start-pid`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ kp: simParams.kp, kd: simParams.kd, target_distance: simParams.target_distance }),
    })
    setPidRunning(true)

    // Poll /step every 100ms
    const iv = window.setInterval(async () => {
      try {
        const res = await fetch(`/api/projects/${projectId}/simulator/step`, { method: 'POST' })
        const state = await res.json()
        updateScene(state)
      } catch { /* */ }
    }, 100)
    pidIntervalRef.current = iv
  }, [pid, simParams, updateScene])

  const stopPid = useCallback(async () => {
    if (pidIntervalRef.current) window.clearInterval(pidIntervalRef.current)
    pidIntervalRef.current = 0
    setPidRunning(false)
    await fetch(`/api/projects/${pid || 'demo'}/simulator/stop-pid`, { method: 'POST' }).catch(() => {})
    // Stop motors
    handleManualCommand('STOP')
  }, [pid, handleManualCommand])

  const resetSim = useCallback(async () => {
    if (pidIntervalRef.current) { window.clearInterval(pidIntervalRef.current); pidIntervalRef.current = 0 }
    setPidRunning(false)
    trailCountRef.current = 0
    try {
      const res = await fetch(`/api/projects/${pid || 'demo'}/simulator/reset`, { method: 'POST' })
      const state = await res.json()
      updateScene(state)
    } catch { /* */ }
  }, [pid, updateScene])

  const updateParams = useCallback(async () => {
    trailCountRef.current = 0
    // Remove old meshes so they get recreated with new dimensions
    const s = sceneRef.current
    if (s) {
      for (const [name, mesh] of Object.entries(meshesRef.current)) {
        s.scene.remove(mesh)
        mesh.geometry.dispose()
      }
      meshesRef.current = {}
    }
    try {
      const res = await fetch(`/api/projects/${pid || 'demo'}/simulator/run`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          wheel_radius: simParams.wheel_radius, chassis_length: simParams.chassis_length,
          chassis_width: simParams.chassis_width, motor_torque: simParams.motor_torque,
          kp: simParams.kp, target_dist: simParams.target_distance,
          n_steps: 200, dt: 0.002,
        }),
      })
      const data = await res.json()
      // Animate trajectory
      const traj = data.trajectory || []
      for (let i = 0; i < traj.length; i++) {
        setTimeout(() => updateScene(traj[i]), i * 20)
      }
    } catch { /* */ }
  }, [pid, simParams, updateScene])

  const resyncFromOnshape = useCallback(async () => {
    setResyncing(true)
    onResyncMsg('')
    try {
      const res = await fetch(`/api/projects/${pid || 'demo'}/simulator/update-from-onshape`, { method: 'POST' })
      const data = await res.json()
      if (data.params) {
        const changes: string[] = []
        for (const [k, v] of Object.entries(data.params) as [string, number][]) {
          if (k in simParams && simParams[k as keyof typeof simParams] !== v) {
            changes.push(`${k} changed from ${simParams[k as keyof typeof simParams]} to ${v}`)
          }
        }
        setSimParams(p => ({ ...p, ...data.params }))
        onResyncMsg(changes.length > 0 ? `Updated: ${changes.join(', ')}` : 'Parameters already up to date')
        if (changes.length > 0) setTimeout(updateParams, 500)
      }
      setTimeout(() => onResyncMsg(''), 8000)
    } catch { onResyncMsg('Failed to resync from Onshape'); setTimeout(() => onResyncMsg(''), 5000) }
    setResyncing(false)
  }, [pid, simParams, updateParams]) // eslint-disable-line react-hooks/exhaustive-deps

  // ── Keyboard controls (hold-to-drive) ──
  // Held commands live in refs so the 10Hz drive loop survives re-renders;
  // the last-pressed key wins when several are held.
  const heldCmdsRef = useRef<string[]>([])
  const driveIvRef = useRef(0)
  const manualBusyRef = useRef(false)
  const serialConnectedRef = useRef(serialConnected)
  serialConnectedRef.current = serialConnected
  const sendSerialRef = useRef(sendSerialCommand)
  sendSerialRef.current = sendSerialCommand

  const driveTick = useCallback(async () => {
    const cmd = heldCmdsRef.current[heldCmdsRef.current.length - 1]
    if (!cmd || manualBusyRef.current) return
    manualBusyRef.current = true
    try {
      // 50 steps at dt=0.002 per 100ms tick keeps the sim at real-time speed
      await handleManualCommand(cmd, 50)
    } finally {
      manualBusyRef.current = false
    }
  }, [handleManualCommand])

  const stopDriving = useCallback(() => {
    heldCmdsRef.current = []
    if (driveIvRef.current) { window.clearInterval(driveIvRef.current); driveIvRef.current = 0 }
    handleManualCommand('STOP')
    if (serialConnectedRef.current) sendSerialRef.current('STOP')
  }, [handleManualCommand])

  useEffect(() => {
    const cmdMap: Record<string, string> = {
      'w': 'FORWARD', 'arrowup': 'FORWARD', 's': 'REVERSE', 'arrowdown': 'REVERSE',
      'a': 'LEFT', 'arrowleft': 'LEFT', 'd': 'RIGHT', 'arrowright': 'RIGHT',
    }

    const onKeyDown = (e: KeyboardEvent) => {
      if (!simPanelFocused) return
      const key = e.key.toLowerCase()
      if (['w', 's', 'a', 'd', ' ', 'arrowup', 'arrowdown', 'arrowleft', 'arrowright'].includes(key)) {
        e.preventDefault()
      }
      if (key === ' ') { stopDriving(); return }
      const cmd = cmdMap[key]
      if (!cmd || e.repeat) return
      if (!heldCmdsRef.current.includes(cmd)) heldCmdsRef.current.push(cmd)
      if (serialConnectedRef.current) sendSerialRef.current(cmd)
      if (!driveIvRef.current) {
        driveTick()
        driveIvRef.current = window.setInterval(driveTick, 100)
      }
    }

    // Keyup is not gated on focus so releasing a key always stops the drive,
    // even if the panel blurred mid-hold.
    const onKeyUp = (e: KeyboardEvent) => {
      const cmd = cmdMap[e.key.toLowerCase()]
      if (!cmd || !heldCmdsRef.current.includes(cmd)) return
      heldCmdsRef.current = heldCmdsRef.current.filter(c => c !== cmd)
      const next = heldCmdsRef.current[heldCmdsRef.current.length - 1]
      if (next) {
        if (serialConnectedRef.current) sendSerialRef.current(next)
      } else {
        stopDriving()
      }
    }

    const onWindowBlur = () => { if (heldCmdsRef.current.length) stopDriving() }

    window.addEventListener('keydown', onKeyDown)
    window.addEventListener('keyup', onKeyUp)
    window.addEventListener('blur', onWindowBlur)
    return () => {
      window.removeEventListener('keydown', onKeyDown)
      window.removeEventListener('keyup', onKeyUp)
      window.removeEventListener('blur', onWindowBlur)
    }
  }, [simPanelFocused, driveTick, stopDriving])

  // Cleanup
  useEffect(() => {
    return () => {
      if (pidIntervalRef.current) window.clearInterval(pidIntervalRef.current)
      if (driveIvRef.current) window.clearInterval(driveIvRef.current)
    }
  }, [])

  return (
    <div
      className={`flex-1 border-r border-solus-border overflow-y-auto p-3 focus:outline-none ${simPanelFocused ? 'ring-1 ring-solus-accent/30' : ''}`}
      tabIndex={0}
      onFocus={() => setSimPanelFocused(true)}
      onBlur={() => setSimPanelFocused(false)}
    >
      <div className="flex items-center gap-2 mb-2">
        <Activity size={12} className="text-solus-accent-bright" />
        <span className="text-[10px] font-mono font-semibold uppercase tracking-widest text-solus-text-muted">Simulation (MuJoCo)</span>
        {simPanelFocused && <span className="text-[9px] font-mono text-solus-text-muted ml-auto">hold WASD to drive · space stops</span>}
      </div>

      {/* Three.js container */}
      <div ref={containerRef} className="w-full rounded border border-solus-border overflow-hidden" style={{ minHeight: 300, height: 'calc(100vh - 450px)', maxHeight: 600 }} />

      {/* Sensor readout */}
      <div className="mt-2 flex items-center gap-3 text-[10px] font-mono text-solus-text-muted bg-solus-bg border border-solus-border px-3 py-1.5">
        <span>dist: <span className="text-solus-text">{(simSensors.distance_cm ?? 0).toFixed(1)}cm</span></span>
        <span>left: <span className="text-solus-text">{(simSensors.left_motor ?? 0).toFixed(2)}</span></span>
        <span>right: <span className="text-solus-text">{(simSensors.right_motor ?? 0).toFixed(2)}</span></span>
        <span>pid: <span className="text-solus-text">{(simSensors.pid_error ?? 0).toFixed(2)}</span></span>
      </div>

      {/* Sim controls */}
      <div className="mt-2 flex items-center gap-2 flex-wrap">
        {!pidRunning ? (
          <button onClick={startPid} className="flex items-center gap-1 bg-solus-success/20 hover:bg-solus-success/30 text-solus-success text-[10px] font-mono px-3 py-1.5 rounded">
            <Play size={10} /> Run
          </button>
        ) : (
          <button onClick={stopPid} className="flex items-center gap-1 bg-solus-error/20 hover:bg-solus-error/30 text-solus-error text-[10px] font-mono px-3 py-1.5 rounded">
            <Square size={10} /> Stop
          </button>
        )}
        <button onClick={resetSim} className="flex items-center gap-1 bg-solus-text-muted/20 hover:bg-solus-text-muted/30 text-solus-text-muted text-[10px] font-mono px-3 py-1.5 rounded">
          <RotateCw size={10} /> Reset
        </button>
        <button onClick={resyncFromOnshape} disabled={resyncing}
          className="flex items-center gap-1 bg-solus-warning/20 hover:bg-solus-warning/30 text-solus-warning text-[10px] font-mono px-3 py-1.5 rounded disabled:opacity-40">
          <Download size={10} /> {resyncing ? 'Resyncing...' : 'Resync from Onshape'}
        </button>
      </div>

      {/* Sim Parameters */}
      <div className="mt-3">
        <div className="flex items-center gap-2 mb-2">
          <span className="text-[10px] font-mono font-semibold uppercase tracking-widest text-solus-text-muted">Sim Parameters</span>
          <span className={`text-[9px] font-mono px-1.5 py-0.5 rounded ${
            paramsSource === 'onshape' ? 'bg-solus-accent/15 text-solus-accent-bright' : 'bg-solus-text-muted/15 text-solus-text-muted'
          }`}>{paramsSource === 'onshape' ? 'From Onshape' : 'Manual'}</span>
        </div>
        <div className="grid grid-cols-2 gap-2">
          {SIM_PARAM_DEFS.map(({ key, label, step, unit }) => (
            <div key={key} className="flex items-center gap-1.5">
              <label className="text-[9px] font-mono text-solus-text-muted w-24 shrink-0">{label}</label>
              <input type="number" step={step} value={simParams[key as keyof typeof simParams]}
                onChange={e => setSimParams(p => ({ ...p, [key]: parseFloat(e.target.value) || 0 }))}
                className="bg-solus-bg border border-solus-border rounded px-1.5 py-0.5 text-[10px] font-mono text-solus-text w-20" />
              <span className="text-[9px] font-mono text-solus-text-muted">{unit}</span>
            </div>
          ))}
          <div className="flex items-center gap-1.5">
            <label className="text-[9px] font-mono text-solus-text-muted w-24 shrink-0">Kp</label>
            <input type="number" step="0.1" value={simParams.kp}
              onChange={e => setSimParams(p => ({ ...p, kp: parseFloat(e.target.value) || 0 }))}
              className="bg-solus-bg border border-solus-border rounded px-1.5 py-0.5 text-[10px] font-mono text-solus-text w-20" />
          </div>
          <div className="flex items-center gap-1.5">
            <label className="text-[9px] font-mono text-solus-text-muted w-24 shrink-0">Target Dist</label>
            <input type="number" step="0.01" value={simParams.target_distance}
              onChange={e => setSimParams(p => ({ ...p, target_distance: parseFloat(e.target.value) || 0 }))}
              className="bg-solus-bg border border-solus-border rounded px-1.5 py-0.5 text-[10px] font-mono text-solus-text w-20" />
            <span className="text-[9px] font-mono text-solus-text-muted">m</span>
          </div>
        </div>
        <button onClick={updateParams}
          className="mt-2 bg-solus-accent/20 hover:bg-solus-accent/30 text-solus-accent-bright text-[10px] font-mono px-3 py-1.5 rounded">
          Update Params
        </button>
      </div>

      {/* SIM vs REAL comparison */}
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
              {comparison.map(d => (
                <tr key={d.signal} className="border-b border-solus-border/30">
                  <td className="py-1 pr-2 text-solus-text">{d.signal}</td>
                  <td className="py-1 pr-2 text-right text-solus-text-muted">{d.simulated?.toFixed(4)}</td>
                  <td className="py-1 pr-2 text-right text-solus-text-muted">{d.observed?.toFixed(4)}</td>
                  <td className="py-1 pr-2 text-right text-solus-text-muted">{d.delta?.toFixed(4)}</td>
                  <td className="py-1">
                    <span className={`px-1.5 py-0.5 rounded text-[9px] font-bold ${
                      d.status === 'match' ? 'bg-green-500/20 text-green-400' :
                      d.status === 'deviation' ? 'bg-yellow-500/20 text-yellow-400' :
                      'bg-red-500/20 text-red-400'
                    }`}>
                      {d.status === 'match' ? '✓ MATCH' : d.status === 'deviation' ? '⚠ DEVIATION' : '⚠ MISMATCH'}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
