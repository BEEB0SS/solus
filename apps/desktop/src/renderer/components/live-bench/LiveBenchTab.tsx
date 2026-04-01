import { useState, useEffect, useRef, useCallback } from 'react'
import { Play, Square, RotateCw, Send, RefreshCw, Clipboard, Activity, AlertTriangle, Download } from 'lucide-react'
import { LineChart, Line, ResponsiveContainer } from 'recharts'
import { useProjectStore } from '../../stores/projectStore'
import * as THREE from 'three'
import { OrbitControls } from 'three/addons/controls/OrbitControls.js'

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

interface BodyState {
  pos: number[]
  quat: number[]
  size?: number[]
  type?: string
}

type ConnStatus = 'disconnected' | 'connecting' | 'connected'

const SIM_PARAM_DEFS = [
  { key: 'wheel_radius', label: 'Wheel Radius', step: 0.001, unit: 'm' },
  { key: 'chassis_length', label: 'Chassis Length', step: 0.01, unit: 'm' },
  { key: 'chassis_width', label: 'Chassis Width', step: 0.01, unit: 'm' },
  { key: 'motor_torque', label: 'Motor Torque', step: 0.01, unit: 'Nm' },
] as const

// ── Three.js scene management ────────────────────────────────────────

function createBodyMesh(name: string, body: BodyState): THREE.Mesh {
  const sz = body.size || []
  let geo: THREE.BufferGeometry
  let mat: THREE.MeshStandardMaterial
  if (name === 'chassis') {
    geo = new THREE.BoxGeometry((sz[0] || 0.1) * 2, (sz[2] || 0.015) * 2, (sz[1] || 0.075) * 2)
    mat = new THREE.MeshStandardMaterial({ color: 0x3344aa })
  } else if (name.startsWith('wheel_')) {
    geo = new THREE.CylinderGeometry(sz[0] || 0.033, sz[0] || 0.033, (sz[1] || 0.013) * 2, 16)
    geo.rotateX(Math.PI / 2)
    mat = new THREE.MeshStandardMaterial({ color: 0x333333 })
  } else {
    geo = new THREE.BoxGeometry((sz[0] || 0.1) * 2, (sz[2] || 0.05) * 2, (sz[1] || 0.1) * 2)
    mat = new THREE.MeshStandardMaterial({ color: 0xcc3333, transparent: true, opacity: 0.8 })
  }
  return new THREE.Mesh(geo, mat)
}

function createScene(container: HTMLDivElement) {
  const width = container.clientWidth
  const height = container.clientHeight || 400

  const scene = new THREE.Scene()
  scene.background = new THREE.Color(0x0a0a0f)

  const camera = new THREE.PerspectiveCamera(50, width / height, 0.01, 50)
  camera.position.set(0.3, 0.8, 0.8)
  camera.lookAt(0, 0, 0)

  const renderer = new THREE.WebGLRenderer({ antialias: true })
  renderer.setSize(width, height)
  renderer.setPixelRatio(window.devicePixelRatio)
  container.appendChild(renderer.domElement)

  const controls = new OrbitControls(camera, renderer.domElement)
  controls.target.set(0, 0, 0)
  controls.enableDamping = true
  controls.dampingFactor = 0.1

  // Lights
  const dirLight = new THREE.DirectionalLight(0xffffff, 1.5)
  dirLight.position.set(2, 5, 3)
  scene.add(dirLight)
  scene.add(new THREE.AmbientLight(0x666680, 1.0))

  // Ground plane with grid
  const groundGeo = new THREE.PlaneGeometry(4, 4)
  const groundMat = new THREE.MeshStandardMaterial({ color: 0x1a1a24, roughness: 0.9 })
  const ground = new THREE.Mesh(groundGeo, groundMat)
  ground.rotation.x = -Math.PI / 2
  ground.position.y = -0.001
  scene.add(ground)

  const grid = new THREE.GridHelper(4, 40, 0x2a2a3e, 0x222235)
  scene.add(grid)

  // Trail line
  const trailMat = new THREE.LineBasicMaterial({ color: 0x3b82f6, transparent: true, opacity: 0.6 })
  const trailGeo = new THREE.BufferGeometry()
  const trailPositions = new Float32Array(600 * 3) // max 600 points
  trailGeo.setAttribute('position', new THREE.BufferAttribute(trailPositions, 3))
  trailGeo.setDrawRange(0, 0)
  const trailLine = new THREE.Line(trailGeo, trailMat)
  scene.add(trailLine)

  // Ultrasonic beam
  const beamMat = new THREE.LineBasicMaterial({ color: 0x06b6d4, transparent: true, opacity: 0.5 })
  const beamGeo = new THREE.BufferGeometry()
  beamGeo.setAttribute('position', new THREE.BufferAttribute(new Float32Array(6), 3))
  const beamLine = new THREE.Line(beamGeo, beamMat)
  scene.add(beamLine)

  return { scene, camera, renderer, controls, trailLine, trailGeo, trailPositions, beamLine, beamGeo }
}

function applyMujocoTransform(mesh: THREE.Object3D, body: BodyState) {
  // MuJoCo: pos=[x,y,z] → Three.js: x=mj.x, y=mj.z, z=-mj.y (swap Y↔Z, negate)
  mesh.position.set(body.pos[0], body.pos[2], -body.pos[1])
  // MuJoCo quat: [w,x,y,z] → Three.js Quaternion(x,y,z,w) with axis swap
  mesh.quaternion.set(body.quat[1], body.quat[3], -body.quat[2], body.quat[0])
}

// ── Main component ───────────────────────────────────────────────────

export default function LiveBenchTab() {
  const store = useProjectStore()
  const pid = store.currentProjectId

  // Connection state
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
  const [mismatchAlert, setMismatchAlert] = useState('')
  const [paramsSource, setParamsSource] = useState<'manual' | 'onshape'>('manual')
  const [resyncMsg, setResyncMsg] = useState('')
  const [resyncing, setResyncing] = useState(false)

  // Three.js refs
  const containerRef = useRef<HTMLDivElement>(null)
  const sceneRef = useRef<ReturnType<typeof createScene> | null>(null)
  const meshesRef = useRef<Record<string, THREE.Mesh>>({})
  const trailCountRef = useRef(0)
  const animIdRef = useRef(0)
  const wsRef = useRef<WebSocket | null>(null)
  const signalsRef = useRef<Record<string, SignalState>>({})
  const pidIntervalRef = useRef<number>(0)

  const serialConnected = mode === 'serial' && status === 'connected'
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
    const defaultBodies: Record<string, BodyState> = {
      chassis: { pos: [0, 0, 0.049], quat: [1, 0, 0, 0], size: [0.1, 0.075, 0.015], type: 'box' },
      wheel_fl: { pos: [0.05, 0.08, 0.034], quat: [1, 0, 0, 0], size: [0.033, 0.013], type: 'cylinder' },
      wheel_fr: { pos: [0.05, -0.08, 0.034], quat: [1, 0, 0, 0], size: [0.033, 0.013], type: 'cylinder' },
      wheel_rl: { pos: [-0.05, 0.08, 0.034], quat: [1, 0, 0, 0], size: [0.033, 0.013], type: 'cylinder' },
      wheel_rr: { pos: [-0.05, -0.08, 0.034], quat: [1, 0, 0, 0], size: [0.033, 0.013], type: 'cylinder' },
      obstacle_1: { pos: [0.5, 0, 0.05], quat: [1, 0, 0, 0], size: [0.1, 0.15, 0.05], type: 'box' },
      obstacle_2: { pos: [-0.3, 0.4, 0.05], quat: [1, 0, 0, 0], size: [0.075, 0.075, 0.05], type: 'box' },
      obstacle_3: { pos: [0.1, -0.5, 0.03], quat: [1, 0, 0, 0], size: [0.15, 0.05, 0.03], type: 'box' },
      obstacle_4: { pos: [-0.5, -0.3, 0.05], quat: [1, 0, 0, 0], size: [0.05, 0.2, 0.05], type: 'box' },
    }
    for (const [name, body] of Object.entries(defaultBodies)) {
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

  // ── Auto-compare sim vs real ──
  useEffect(() => {
    if (!bothActive) { setComparison([]); setMismatchAlert(''); return }
    const iv = setInterval(async () => {
      try {
        const res = await fetch(`/api/projects/${pid}/simulator/compare`, { method: 'POST' })
        const data = await res.json()
        const rows: CompareRow[] = data.comparisons || []
        setComparison(rows)
        const mismatched = rows.filter(r => r.status === 'mismatch')
        setMismatchAlert(mismatched.length > 0
          ? `Simulation mismatch detected \u2014 wheel_radius may be incorrect. Check Onshape model dimensions. Mismatched: ${mismatched.map(r => r.signal).join(', ')}`
          : '')
      } catch { /* */ }
    }, 2000)
    return () => clearInterval(iv)
  }, [bothActive, pid])

  // ── Connect / disconnect ──
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
        if (data.anomalies?.length) setAnomalies(prev => [...data.anomalies, ...prev].slice(0, 100))
        if (data.event === 'disconnected') { setStatus('disconnected'); setSignals({}); signalsRef.current = {}; setAnomalies([]) }
        if (data.event === 'code_flashed') { setFlashBanner(true); setTimeout(() => setFlashBanner(false), 15000) }
      } catch { /* */ }
    }
    ws.onclose = () => { if (status === 'connected') setStatus('disconnected') }
  }

  const disconnect = () => {
    if (wsRef.current) { wsRef.current.onmessage = null; wsRef.current.close(); wsRef.current = null }
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
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ command: cmd }),
    }).catch(() => {})
  }

  const sendLogsToAgent = async () => {
    try {
      const res = await fetch(`/api/projects/${pid}/live-bench/logs`)
      const data = await res.json()
      localStorage.setItem('solus_agent_context', JSON.stringify({
        source: 'live_bench', logs: data, timestamp: Date.now(),
        prompt: 'Robot anomalies detected. ' + (data.report || '') + '\nAnalyze the robot code, identify the bug, and generate corrected code.',
      }))
      alert('Logs sent \u2014 switch to Intelligence tab')
    } catch { /* */ }
  }

  // ── Sim controls ──
  const handleManualCommand = useCallback(async (command: string) => {
    const projectId = pid || 'demo'
    try {
      const res = await fetch(`/api/projects/${projectId}/simulator/manual`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ command }),
      })
      if (!res.ok) { console.error('[sim] manual API error:', res.status); return }
      const state = await res.json()
      console.log('[sim] WASD response:', command, 'chassis:', state?.bodies?.chassis?.pos, 'scene:', !!sceneRef.current, 'meshes:', Object.keys(meshesRef.current).length)
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
    setResyncMsg('')
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
        setResyncMsg(changes.length > 0 ? `Updated: ${changes.join(', ')}` : 'Parameters already up to date')
        if (changes.length > 0) setTimeout(updateParams, 500)
      }
      setTimeout(() => setResyncMsg(''), 8000)
    } catch { setResyncMsg('Failed to resync from Onshape'); setTimeout(() => setResyncMsg(''), 5000) }
    setResyncing(false)
  }, [pid, simParams, updateParams])

  // ── Keyboard controls ──
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (!simPanelFocused) return
      const key = e.key.toLowerCase()
      if (['w', 's', 'a', 'd', ' ', 'arrowup', 'arrowdown', 'arrowleft', 'arrowright'].includes(key)) {
        e.preventDefault()
      }
      const cmdMap: Record<string, string> = {
        'w': 'FORWARD', 'arrowup': 'FORWARD', 's': 'REVERSE', 'arrowdown': 'REVERSE',
        'a': 'LEFT', 'arrowleft': 'LEFT', 'd': 'RIGHT', 'arrowright': 'RIGHT', ' ': 'STOP',
      }
      const cmd = cmdMap[key]
      if (cmd) {
        handleManualCommand(cmd)
        if (serialConnected) sendCommand(cmd)
      }
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [simPanelFocused, serialConnected, handleManualCommand, sendCommand])

  // Cleanup
  useEffect(() => {
    return () => { if (pidIntervalRef.current) window.clearInterval(pidIntervalRef.current) }
  }, [])

  const signalColor = (name: string, value: number): string => {
    const n = name.toLowerCase()
    if (n === 'running') return value === 1 ? '#22c55e' : '#64748b'
    if (n === 'bug_active') return value === 1 ? '#ef4444' : '#22c55e'
    if (n === 'kp_value') return value > 10 ? '#ef4444' : '#22c55e'
    if (n === 'kd_value') return value === 0 ? '#ef4444' : '#22c55e'
    if (n === 'pid_error') { const a = Math.abs(value); return a < 5 ? '#22c55e' : a < 15 ? '#f59e0b' : '#ef4444' }
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
      {/* Banners */}
      {flashBanner && (
        <div className="bg-green-600/90 text-white text-xs font-mono px-4 py-2 flex items-center justify-between">
          <span>New code deployed! Reconnect to see the fix.</span>
          <button onClick={() => { disconnect(); setTimeout(connect, 500) }}
            className="bg-white/20 hover:bg-white/30 px-2 py-0.5 rounded text-[10px]">Reconnect</button>
        </div>
      )}
      {mismatchAlert && (
        <div className="bg-red-600/20 border-b border-red-500/30 text-red-400 text-xs font-mono px-4 py-2 flex items-center gap-2">
          <AlertTriangle size={14} className="shrink-0" />
          <span>{mismatchAlert}</span>
        </div>
      )}
      {resyncMsg && (
        <div className="bg-solus-accent/20 text-solus-accent-bright text-xs font-mono px-4 py-1.5">{resyncMsg}</div>
      )}
      {discoveryBanner && (
        <div className="bg-solus-accent/20 text-solus-accent-bright text-xs font-mono px-4 py-1.5">{discoveryBanner}</div>
      )}

      {/* Connection bar */}
      <div className="bg-solus-surface border-b border-solus-border p-2 flex items-center gap-2 flex-wrap">
        <div className={`w-2.5 h-2.5 rounded-full shrink-0 ${
          status === 'connected' ? 'bg-solus-success animate-pulse' : status === 'connecting' ? 'bg-solus-warning' : 'bg-solus-text-muted'
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
                {ports.map(p => <option key={p.device} value={p.device}>{p.device.split('/').pop()} {p.is_arduino ? '\u2713' : ''}</option>)}
                {ports.length === 0 && <option value="">No ports</option>}
              </select>
              <button onClick={fetchPorts} className="text-solus-text-muted hover:text-solus-text"><RefreshCw size={11} /></button>
            </div>
            <select value={baud} onChange={e => setBaud(e.target.value)}
              className="bg-solus-bg border border-solus-border rounded px-2 py-1 text-[10px] font-mono text-solus-text">
              <option value="9600">9600</option><option value="115200">115200</option>
            </select>
            <input value={cameraUrl} onChange={e => { setCameraUrl(e.target.value); setCameraConnected(true) }}
              placeholder="192.168.4.1"
              className="bg-solus-bg border border-solus-border rounded px-2 py-1 text-[10px] font-mono text-solus-text w-32 placeholder:text-solus-text-muted" />
          </>
        )}
        {status === 'disconnected' ? (
          <button onClick={connect} className="bg-solus-accent hover:bg-solus-accent-bright text-white text-[10px] font-mono px-3 py-1 rounded transition-colors">Connect</button>
        ) : (
          <button onClick={disconnect} className="bg-solus-error/80 hover:bg-solus-error text-white text-[10px] font-mono px-3 py-1 rounded transition-colors">Disconnect</button>
        )}
        <div className="flex-1" />
        <span className="text-[10px] font-mono text-solus-text-muted">{signalCount} signals · {anomalyCount} anomalies</span>
      </div>

      {/* Serial controls */}
      {mode === 'serial' && status === 'connected' && (
        <div className="bg-solus-surface/50 border-b border-solus-border p-2 flex items-center gap-2">
          <button onClick={() => sendCommand('start')} className="flex items-center gap-1 bg-solus-success/20 hover:bg-solus-success/30 text-solus-success text-[10px] font-mono px-2.5 py-1 rounded"><Play size={10} /> START</button>
          <button onClick={() => sendCommand('stop')} className="flex items-center gap-1 bg-solus-error/20 hover:bg-solus-error/30 text-solus-error text-[10px] font-mono px-2.5 py-1 rounded"><Square size={10} /> STOP</button>
          <button onClick={() => sendCommand('sweep')} className="flex items-center gap-1 bg-solus-accent/20 hover:bg-solus-accent/30 text-solus-accent-bright text-[10px] font-mono px-2.5 py-1 rounded"><RotateCw size={10} /> SWEEP</button>
          <div className="flex-1" />
          <input value={customCmd} onChange={e => setCustomCmd(e.target.value)}
            onKeyDown={e => { if (e.key === 'Enter' && customCmd) { sendCommand(customCmd); setCustomCmd('') } }}
            placeholder="Command..." className="bg-solus-bg border border-solus-border rounded px-2 py-1 text-[10px] font-mono text-solus-text w-36 placeholder:text-solus-text-muted" />
          <button onClick={() => { if (customCmd) { sendCommand(customCmd); setCustomCmd('') } }} className="text-solus-text-muted hover:text-solus-text"><Send size={11} /></button>
        </div>
      )}

      {/* Camera feed */}
      {mode === 'serial' && status === 'connected' && cameraUrl && (
        <div className="relative bg-black border-b border-solus-border">
          {cameraConnected ? (
            <>
              <img src={`http://${cameraUrl}:81/stream`} alt="Camera feed" className="w-full max-h-48 object-contain bg-black" onError={() => setCameraConnected(false)} />
              <span className="absolute top-2 right-2 bg-red-500 text-white text-[10px] font-mono font-bold px-1 rounded">LIVE</span>
            </>
          ) : (
            <div className="w-full h-20 flex items-center justify-center text-xs font-mono text-solus-text-muted">Camera unavailable</div>
          )}
        </div>
      )}

      {/* Main panels */}
      <div className="flex flex-1 overflow-hidden">
        {/* LEFT: SIMULATION (3D) — hidden when serial is connected */}
        <div
          className={`flex-1 border-r border-solus-border overflow-y-auto p-3 focus:outline-none ${simPanelFocused ? 'ring-1 ring-solus-accent/30' : ''}`}
          tabIndex={0}
          onFocus={() => setSimPanelFocused(true)}
          onBlur={() => setSimPanelFocused(false)}
        >
          <div className="flex items-center gap-2 mb-2">
            <Activity size={12} className="text-solus-accent-bright" />
            <span className="text-[10px] font-mono font-semibold uppercase tracking-widest text-solus-text-muted">Simulation (MuJoCo)</span>
            {simPanelFocused && <span className="text-[9px] font-mono text-solus-text-muted ml-auto">WASD to drive</span>}
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
                <Play size={10} /> Start PID
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
                          {d.status === 'match' ? '\u2713 MATCH' : d.status === 'deviation' ? '\u26A0 DEVIATION' : '\u26A0 MISMATCH'}
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
                    <div className="text-[10px] font-mono uppercase tracking-widest text-solus-text-muted mb-1">{name.replace(/_/g, ' ')}</div>
                    <div className="text-xl font-mono font-bold tabular-nums" style={{ color }}>{signalDisplay(name, sig.current)}</div>
                    {chartData.length > 1 && (
                      <div className="mt-1.5 h-9">
                        <ResponsiveContainer width="100%" height="100%">
                          <LineChart data={chartData}>
                            <Line type="monotone" dataKey="v" stroke={color} dot={false} strokeWidth={1.5} isAnimationActive={false} />
                          </LineChart>
                        </ResponsiveContainer>
                      </div>
                    )}
                    <div className="text-[10px] font-mono text-solus-text-muted mt-1">min {sig.min.toFixed(2)} · max {sig.max.toFixed(2)}</div>
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
                  <span className="bg-solus-error text-white rounded-full px-2 text-[10px] font-mono font-bold min-w-[20px] text-center">{anomalyCount}</span>
                )}
              </div>
            </div>
            <button onClick={sendLogsToAgent}
              className="mx-3 mt-2 flex items-center justify-center gap-1.5 bg-solus-accent/15 hover:bg-solus-accent/25 text-solus-accent-bright text-[10px] font-mono py-2 rounded">
              <Clipboard size={11} /> Send Logs to Agent
            </button>
            <div className="flex-1 overflow-y-auto p-3 space-y-2">
              {anomalies.map((a: any, i: number) => (
                <div key={a.id || i} className="bg-solus-elevated border border-solus-border rounded-lg p-2.5 space-y-1">
                  <div className="flex items-center gap-1.5 flex-wrap">
                    <span className={`text-[9px] font-mono font-bold px-1.5 py-0.5 rounded ${
                      a.severity === 'error' ? 'bg-red-500/20 text-red-400' : 'bg-yellow-500/20 text-yellow-400'
                    }`}>{(a.severity || 'warn').toUpperCase()}</span>
                    {a.pattern_type && (
                      <span className="text-[9px] font-mono px-1.5 py-0.5 rounded bg-solus-accent/15 text-solus-accent-bright">
                        {a.pattern_type.toUpperCase().replace(/_/g, '-')}
                      </span>
                    )}
                  </div>
                  {a.signal_name && <div className="text-[10px] font-mono text-solus-text">{a.signal_name}</div>}
                  {a.description && <div className="text-[10px] text-solus-text-dim leading-snug">{a.description}</div>}
                  {a.evidence && <div className="text-[9px] font-mono text-solus-text-muted">evidence: {a.evidence}</div>}
                  {a.expected && <div className="text-[9px] font-mono text-solus-text-muted">expected: {a.expected}</div>}
                </div>
              ))}
              {anomalyCount === 0 && <div className="text-[10px] font-mono text-solus-text-muted py-6 text-center">No anomalies detected</div>}
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
