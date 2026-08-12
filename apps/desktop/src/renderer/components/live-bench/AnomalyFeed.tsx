import { Clipboard } from 'lucide-react'

interface AnomalyFeedProps {
  anomalies: any[]
  onSendLogs: () => void
}

export default function AnomalyFeed({ anomalies, onSendLogs }: AnomalyFeedProps) {
  const anomalyCount = anomalies.length

  return (
    <div className="w-72 border-l border-solus-border bg-solus-surface flex flex-col">
      <div className="p-3 border-b border-solus-border flex items-center justify-between">
        <div className="flex items-center gap-2">
          <span className="text-[10px] font-mono font-semibold uppercase tracking-widest text-solus-text-muted">Anomalies</span>
          {anomalyCount > 0 && (
            <span className="bg-solus-error text-white rounded-full px-2 text-[10px] font-mono font-bold min-w-[20px] text-center">{anomalyCount}</span>
          )}
        </div>
      </div>
      <button onClick={onSendLogs}
        className="mx-3 mt-2 flex items-center justify-center gap-1.5 bg-solus-accent/15 hover:bg-solus-accent/25 text-solus-accent-bright text-[10px] font-mono py-2 rounded">
        <Clipboard size={11} /> Send Logs to Agent
      </button>
      <div className="flex-1 overflow-y-auto p-3 space-y-2">
        {/* Pattern anomalies first, with red accent */}
        {anomalies.filter((a: any) => a.pattern_type).map((a: any, i: number) => (
          <div key={`p-${a.id || i}`} className="bg-solus-elevated border-l-2 border-l-solus-error border border-solus-border rounded-lg p-2.5 space-y-1">
            <div className="flex items-center gap-1.5 flex-wrap">
              <span className="text-[9px] font-mono font-bold px-1.5 py-0.5 rounded bg-red-500/20 text-red-400">PATTERN</span>
              <span className="text-[9px] font-mono px-1.5 py-0.5 rounded bg-solus-accent/15 text-solus-accent-bright">
                {a.pattern_type.toUpperCase().replace(/_/g, '-')}
              </span>
            </div>
            {a.signal_name && <div className="text-[10px] font-mono text-solus-text">{a.signal_name}</div>}
            {a.description && <div className="text-[10px] text-solus-text-dim leading-snug">{a.description}</div>}
            {a.evidence && <div className="text-[9px] font-mono text-solus-text-muted">evidence: {a.evidence}</div>}
            {a.expected && <div className="text-[9px] font-mono text-solus-text-muted">expected: {a.expected}</div>}
          </div>
        ))}
        {/* Threshold/other anomalies below, dimmer */}
        {anomalies.filter((a: any) => !a.pattern_type).map((a: any, i: number) => (
          <div key={`t-${a.id || i}`} className="bg-solus-elevated border border-solus-border rounded-lg p-2.5 space-y-1 opacity-70">
            <div className="flex items-center gap-1.5 flex-wrap">
              <span className={`text-[9px] font-mono font-bold px-1.5 py-0.5 rounded ${
                a.severity === 'error' ? 'bg-red-500/20 text-red-400' : 'bg-yellow-500/20 text-yellow-400'
              }`}>{(a.severity || 'warn').toUpperCase()}</span>
            </div>
            {a.signal_name && <div className="text-[10px] font-mono text-solus-text">{a.signal_name}</div>}
            {a.description && <div className="text-[10px] text-solus-text-dim leading-snug">{a.description}</div>}
          </div>
        ))}
        {anomalyCount === 0 && <div className="text-[10px] font-mono text-solus-text-muted py-6 text-center">No anomalies detected</div>}
      </div>
    </div>
  )
}
