import { useState, useEffect, useCallback } from 'react'
import { Play, Square, RotateCw, Send, RefreshCw, AlertTriangle } from 'lucide-react'
import { useProjectStore } from '../../stores/projectStore'
import { useTelemetrySocket } from './useTelemetrySocket'
import SimulationPanel from './SimulationPanel'
import TelemetryGrid from './TelemetryGrid'
import AnomalyFeed from './AnomalyFeed'

export default function LiveBenchTab() {
  const store = useProjectStore()
  const pid = store.currentProjectId

  // Connection settings
  const [mode, setMode] = useState('simulated')
  const [port, setPort] = useState('')
  const [baud, setBaud] = useState('9600')
  const [ports, setPorts] = useState<any[]>([])
  const [customCmd, setCustomCmd] = useState('')
  const [cameraConnected, setCameraConnected] = useState(true)
  const [cameraUrl, setCameraUrl] = useState('')

  // Banners fed by the simulation panel
  const [mismatchAlert, setMismatchAlert] = useState('')
  const [resyncMsg, setResyncMsg] = useState('')

  const {
    status, signals, anomalies, discoveryBanner, flashBanner,
    showErrorBanner, errorBannerSent, errorSummary,
    connect, disconnect, sendCommand, sendLogsToAgent, dismissErrorBanner,
  } = useTelemetrySocket({ pid, mode, port, baud })

  const serialConnected = mode === 'serial' && status === 'connected'

  // ── Fetch serial ports ──
  const fetchPorts = useCallback(async () => {
    try {
      const res = await fetch('/api/serial-ports')
      const data = await res.json()
      console.log('[live-bench] Ports fetched:', data.length, data.map((p: any) => p.device))
      setPorts(data)
      const arduino = data.find((p: any) => p.is_arduino)
      if (arduino && !port) setPort(arduino.device)
    } catch (e) { console.error('[live-bench] Port fetch failed:', e) }
  }, [port])

  useEffect(() => { fetchPorts() }, [mode, fetchPorts])

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
                {ports.map(p => <option key={p.device} value={p.device}>{p.device.split('/').pop()} {p.is_arduino ? '✓' : ''}</option>)}
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

      {/* Auto-detected anomaly banner (serial mode only) */}
      {showErrorBanner && (
        <div className={`${errorBannerSent ? 'bg-green-600/15 border-green-500/30' : 'bg-solus-error/15 border-solus-error/30'} border rounded-lg mx-3 mt-2 p-3 flex items-center justify-between`}>
          <div>
            <div className={`${errorBannerSent ? 'text-green-400' : 'text-solus-error'} font-semibold text-sm flex items-center gap-2`}>
              <AlertTriangle size={16} />
              {errorBannerSent ? 'Logs Sent to Intelligence' : 'Robot Anomaly Detected'}
            </div>
            <div className="text-solus-text-dim text-xs mt-1">
              {errorBannerSent ? 'Switch to the Intelligence tab to see the diagnosis' : errorSummary}
            </div>
          </div>
          {!errorBannerSent ? (
            <button onClick={sendLogsToAgent}
              className="bg-solus-accent text-white px-4 py-2 rounded text-sm font-medium hover:bg-solus-accent-bright shrink-0 ml-3">
              Send Logs to Agent →
            </button>
          ) : (
            <button onClick={dismissErrorBanner}
              className="text-solus-text-muted hover:text-solus-text text-xs font-mono px-2 py-1 shrink-0 ml-3">
              Dismiss
            </button>
          )}
        </div>
      )}

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
        {/* LEFT: SIMULATION (3D) */}
        <SimulationPanel
          pid={pid}
          serialConnected={serialConnected}
          sendSerialCommand={sendCommand}
          onMismatchAlert={setMismatchAlert}
          onResyncMsg={setResyncMsg}
        />

        {/* RIGHT: TELEMETRY */}
        <div className="flex-1 flex overflow-hidden">
          <TelemetryGrid signals={signals} status={status} />
          <AnomalyFeed anomalies={anomalies} onSendLogs={sendLogsToAgent} />
        </div>
      </div>
    </div>
  )
}
