import { LineChart, Line, ResponsiveContainer } from 'recharts'
import type { SignalState, ConnStatus } from './useTelemetrySocket'

function signalColor(name: string, value: number): string {
  const n = name.toLowerCase()
  if (n === 'running') return value === 1 ? '#22c55e' : '#64748b'
  if (n === 'bug_active') return value === 1 ? '#ef4444' : '#22c55e'
  if (n === 'kp_value') return value > 10 ? '#ef4444' : '#22c55e'
  if (n === 'kd_value') return value === 0 ? '#ef4444' : '#22c55e'
  if (n === 'pid_error') { const a = Math.abs(value); return a < 5 ? '#22c55e' : a < 15 ? '#f59e0b' : '#ef4444' }
  if (n.includes('motor')) return Math.abs(value) > 1.2 ? '#ef4444' : '#22c55e'
  return '#e2e8f0'
}

function signalDisplay(name: string, value: number): string {
  const n = name.toLowerCase()
  if (n === 'running') return value === 1 ? 'RUNNING' : 'STOPPED'
  if (n === 'bug_active') return value === 1 ? 'BUG ACTIVE' : 'CLEAN'
  return value.toFixed(3)
}

interface TelemetryGridProps {
  signals: Record<string, SignalState>
  status: ConnStatus
}

export default function TelemetryGrid({ signals, status }: TelemetryGridProps) {
  const signalCount = Object.keys(signals).length

  return (
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
  )
}
