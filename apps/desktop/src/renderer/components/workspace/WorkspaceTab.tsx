import { useEffect, useState } from 'react'
import { useProjectStore } from '../../stores/projectStore'
import { FolderGit2, Cpu, Box, RefreshCw, Plus, Users, Clock, GitCommit } from 'lucide-react'

const SOURCE_ICONS: Record<string, typeof FolderGit2> = {
  github: FolderGit2,
  kicad: Cpu,
  onshape: Box,
}

export default function WorkspaceTab() {
  const store = useProjectStore()
  const pid = store.currentProjectId

  const [showAddSource, setShowAddSource] = useState(false)
  const [srcType, setSrcType] = useState('github')
  const [srcName, setSrcName] = useState('')
  const [srcPath, setSrcPath] = useState('')
  const [srcDocId, setSrcDocId] = useState('')
  const [srcWsId, setSrcWsId] = useState('')
  const [syncResult, setSyncResult] = useState<Record<string, string>>({})
  const [syncing, setSyncing] = useState<Record<string, boolean>>({})

  const [showAddMember, setShowAddMember] = useState(false)
  const [memberName, setMemberName] = useState('')
  const [memberRole, setMemberRole] = useState('')

  useEffect(() => {
    store.fetchSources(pid)
    store.fetchTeam(pid)
    store.fetchChanges(pid)
    store.fetchActivity(pid)
  }, [pid])

  const handleAddSource = async () => {
    if (!srcName) return
    let config: Record<string, any> = {}
    if (srcType === 'github') config = { path: srcPath }
    else if (srcType === 'kicad') config = { path: srcPath }
    else if (srcType === 'onshape') config = { document_id: srcDocId, workspace_id: srcWsId }
    await store.addSource(pid, srcType, srcName, config)
    store.fetchSources(pid)
    setSrcName('')
    setSrcPath('')
    setSrcDocId('')
    setSrcWsId('')
    setShowAddSource(false)
  }

  const handleSync = async (sid: string) => {
    setSyncing(p => ({ ...p, [sid]: true }))
    try {
      const res = await store.syncSource(pid, sid)
      const ents = res.entities_created ?? res.entities?.length ?? 0
      const rels = res.relations_created ?? res.relations?.length ?? 0
      setSyncResult(p => ({ ...p, [sid]: `${ents} entities, ${rels} relations linked` }))
      store.fetchSources(pid)
    } catch {
      setSyncResult(p => ({ ...p, [sid]: 'Sync failed' }))
    }
    setSyncing(p => ({ ...p, [sid]: false }))
  }

  const handleAddMember = async () => {
    if (!memberName) return
    await store.addTeamMember(pid, memberName, memberRole, '')
    store.fetchTeam(pid)
    setMemberName('')
    setMemberRole('')
    setShowAddMember(false)
  }

  const relTime = (ts: string) => {
    if (!ts) return ''
    const d = Date.now() - new Date(ts).getTime()
    if (d < 60000) return 'just now'
    if (d < 3600000) return `${Math.floor(d / 60000)}m ago`
    if (d < 86400000) return `${Math.floor(d / 3600000)}h ago`
    return `${Math.floor(d / 86400000)}d ago`
  }

  const activityColor = (type: string) => {
    if (type === 'change' || type === 'modified') return 'bg-blue-500'
    if (type === 'issue' || type === 'error') return 'bg-red-500'
    if (type === 'fix' || type === 'resolved') return 'bg-green-500'
    return 'bg-solus-text-muted'
  }

  return (
    <div className="flex h-full overflow-hidden">
      {/* Left column */}
      <div className="flex-1 overflow-y-auto p-4 space-y-5">
        {/* Sources */}
        <section>
          <div className="flex items-center justify-between mb-3">
            <h2 className="text-xs font-mono font-semibold uppercase tracking-widest text-solus-text-muted">Sources</h2>
            <button onClick={() => setShowAddSource(!showAddSource)}
              className="flex items-center gap-1 text-[10px] font-mono text-solus-accent-bright hover:text-solus-accent transition-colors">
              <Plus size={12} /> Add Source
            </button>
          </div>

          {showAddSource && (
            <div className="bg-solus-elevated border border-solus-border rounded-lg p-3 mb-3 space-y-2">
              <div className="flex gap-2">
                <select value={srcType} onChange={e => setSrcType(e.target.value)}
                  className="bg-solus-bg border border-solus-border rounded px-2 py-1 text-xs font-mono text-solus-text">
                  <option value="github">GitHub</option>
                  <option value="kicad">KiCad</option>
                  <option value="onshape">Onshape</option>
                </select>
                <input value={srcName} onChange={e => setSrcName(e.target.value)}
                  placeholder="Source name" className="flex-1 bg-solus-bg border border-solus-border rounded px-2 py-1 text-xs font-mono text-solus-text placeholder:text-solus-text-muted" />
              </div>
              {(srcType === 'github' || srcType === 'kicad') && (
                <input value={srcPath} onChange={e => setSrcPath(e.target.value)}
                  placeholder={srcType === 'github' ? 'Repository URL or local path' : 'KiCad project folder'}
                  className="w-full bg-solus-bg border border-solus-border rounded px-2 py-1 text-xs font-mono text-solus-text placeholder:text-solus-text-muted" />
              )}
              {srcType === 'onshape' && (
                <div className="flex gap-2">
                  <input value={srcDocId} onChange={e => setSrcDocId(e.target.value)}
                    placeholder="Document ID" className="flex-1 bg-solus-bg border border-solus-border rounded px-2 py-1 text-xs font-mono text-solus-text placeholder:text-solus-text-muted" />
                  <input value={srcWsId} onChange={e => setSrcWsId(e.target.value)}
                    placeholder="Workspace ID" className="flex-1 bg-solus-bg border border-solus-border rounded px-2 py-1 text-xs font-mono text-solus-text placeholder:text-solus-text-muted" />
                </div>
              )}
              <button onClick={handleAddSource}
                className="bg-solus-accent hover:bg-solus-accent-bright text-white text-xs font-mono px-3 py-1.5 rounded transition-colors">
                Add Source
              </button>
            </div>
          )}

          <div className="space-y-1.5">
            {store.sources.map((s: any) => {
              const Icon = SOURCE_ICONS[s.source_type] || FolderGit2
              return (
                <div key={s.id} className="flex items-center gap-2 bg-solus-elevated border border-solus-border rounded-lg px-3 py-2">
                  <Icon size={14} className="text-solus-text-muted shrink-0" />
                  <div className="flex-1 min-w-0">
                    <div className="text-xs font-mono font-medium text-solus-text truncate">{s.name}</div>
                    <div className="text-[10px] font-mono text-solus-text-muted">
                      {s.source_type} · {s.last_synced_at ? relTime(s.last_synced_at) : 'never synced'}
                    </div>
                  </div>
                  {syncResult[s.id] && (
                    <span className="text-[10px] font-mono text-solus-success shrink-0">{syncResult[s.id]}</span>
                  )}
                  <button onClick={() => handleSync(s.id)} disabled={syncing[s.id]}
                    className="flex items-center gap-1 text-[10px] font-mono text-solus-accent-bright hover:text-solus-accent disabled:opacity-50 transition-colors shrink-0">
                    <RefreshCw size={11} className={syncing[s.id] ? 'animate-spin' : ''} /> Sync
                  </button>
                </div>
              )
            })}
            {store.sources.length === 0 && (
              <div className="text-xs font-mono text-solus-text-muted py-4 text-center">No sources connected</div>
            )}
          </div>
        </section>

        {/* Team */}
        <section>
          <div className="flex items-center justify-between mb-3">
            <h2 className="text-xs font-mono font-semibold uppercase tracking-widest text-solus-text-muted">Team</h2>
            <button onClick={() => setShowAddMember(!showAddMember)}
              className="flex items-center gap-1 text-[10px] font-mono text-solus-accent-bright hover:text-solus-accent transition-colors">
              <Plus size={12} /> Add Member
            </button>
          </div>

          {showAddMember && (
            <div className="bg-solus-elevated border border-solus-border rounded-lg p-3 mb-3 space-y-2">
              <div className="flex gap-2">
                <input value={memberName} onChange={e => setMemberName(e.target.value)}
                  placeholder="Name" className="flex-1 bg-solus-bg border border-solus-border rounded px-2 py-1 text-xs font-mono text-solus-text placeholder:text-solus-text-muted" />
                <input value={memberRole} onChange={e => setMemberRole(e.target.value)}
                  placeholder="Role" className="flex-1 bg-solus-bg border border-solus-border rounded px-2 py-1 text-xs font-mono text-solus-text placeholder:text-solus-text-muted" />
              </div>
              <button onClick={handleAddMember}
                className="bg-solus-accent hover:bg-solus-accent-bright text-white text-xs font-mono px-3 py-1.5 rounded transition-colors">
                Add
              </button>
            </div>
          )}

          <div className="space-y-1">
            {store.team.map((m: any) => (
              <div key={m.id} className="flex items-center gap-2 px-3 py-1.5">
                <Users size={12} className="text-solus-text-muted" />
                <span className="text-xs font-mono text-solus-text">{m.name}</span>
                {m.role && (
                  <span className="text-[10px] font-mono px-1.5 py-0.5 rounded bg-solus-accent/15 text-solus-accent-bright">{m.role}</span>
                )}
              </div>
            ))}
            {store.team.length === 0 && (
              <div className="text-xs font-mono text-solus-text-muted py-2 text-center">No team members</div>
            )}
          </div>
        </section>
      </div>

      {/* Right column */}
      <div className="w-80 border-l border-solus-border overflow-y-auto p-4 space-y-5">
        {/* Activity */}
        <section>
          <h2 className="text-xs font-mono font-semibold uppercase tracking-widest text-solus-text-muted mb-3 flex items-center gap-1.5">
            <Clock size={12} /> Activity
          </h2>
          <div className="space-y-2">
            {store.activity.map((a: any, i: number) => (
              <div key={a.id || i} className="flex items-start gap-2">
                <div className={`w-5 h-5 rounded-full ${activityColor(a.type || a.change_type)} flex items-center justify-center text-[9px] font-bold text-white mt-0.5 shrink-0`}>
                  {(a.attributed_to || a.user || '?')[0]?.toUpperCase()}
                </div>
                <div className="flex-1 min-w-0">
                  <div className="text-xs text-solus-text leading-tight">{a.description || a.entity_name || 'Activity'}</div>
                  <div className="text-[10px] font-mono text-solus-text-muted">{relTime(a.created_at || a.timestamp)}</div>
                </div>
              </div>
            ))}
            {store.activity.length === 0 && (
              <div className="text-xs font-mono text-solus-text-muted py-2 text-center">No activity yet</div>
            )}
          </div>
        </section>

        {/* Recent Changes */}
        <section>
          <h2 className="text-xs font-mono font-semibold uppercase tracking-widest text-solus-text-muted mb-3 flex items-center gap-1.5">
            <GitCommit size={12} /> Recent Changes
          </h2>
          <div className="space-y-1.5">
            {store.changes.map((c: any, i: number) => (
              <div key={c.id || i} className="bg-solus-elevated border border-solus-border rounded px-2.5 py-2">
                <div className="text-xs text-solus-text leading-tight">{c.description || c.entity_name}</div>
                <div className="text-[10px] font-mono text-solus-text-muted mt-0.5">
                  {c.attributed_to && <span className="text-solus-accent-bright">{c.attributed_to}</span>}
                  {c.attributed_to && ' · '}{relTime(c.created_at)}
                </div>
              </div>
            ))}
            {store.changes.length === 0 && (
              <div className="text-xs font-mono text-solus-text-muted py-2 text-center">No changes</div>
            )}
          </div>
        </section>
      </div>
    </div>
  )
}
