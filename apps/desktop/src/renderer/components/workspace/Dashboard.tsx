import { useEffect, useState } from 'react'
import { useProjectStore } from '../../stores/projectStore'
import {
  FolderGit2, Cpu, Box, RefreshCw, Plus, Users, Clock, GitCommit,
  Target, Pencil,
} from 'lucide-react'
import { ROLES } from './CreationFlow'

const SOURCE_ICONS: Record<string, typeof FolderGit2> = {
  github: FolderGit2,
  kicad: Cpu,
  onshape: Box,
}

export default function Dashboard() {
  const store = useProjectStore()
  const pid = store.currentProjectId
  const project = store.currentProject

  const [editingName, setEditingName] = useState(false)
  const [editingGoal, setEditingGoal] = useState(false)
  const [nameVal, setNameVal] = useState('')
  const [goalVal, setGoalVal] = useState('')

  const [showAddSource, setShowAddSource] = useState(false)
  const [expandedSrc, setExpandedSrc] = useState<string | null>(null)
  const [srcInput, setSrcInput] = useState('')
  const [addingSrc, setAddingSrc] = useState(false)

  const [showAddMember, setShowAddMember] = useState(false)
  const [memberName, setMemberName] = useState('')
  const [memberRole, setMemberRole] = useState(ROLES[0])

  const [syncResult, setSyncResult] = useState<Record<string, string>>({})
  const [syncing, setSyncing] = useState<Record<string, boolean>>({})

  useEffect(() => {
    store.fetchSources(pid)
    store.fetchTeam(pid)
    store.fetchChanges(pid)
    store.fetchActivity(pid)
  }, [pid])

  const saveName = async () => {
    if (nameVal.trim() && nameVal.trim() !== project?.name) {
      await store.updateProject(pid, { name: nameVal.trim() })
    }
    setEditingName(false)
  }

  const saveGoal = async () => {
    if (goalVal.trim() !== project?.description) {
      await store.updateProject(pid, { description: goalVal.trim() })
    }
    setEditingGoal(false)
  }

  const handleSync = async (sid: string) => {
    setSyncing(p => ({ ...p, [sid]: true }))
    try {
      const res = await store.syncSource(pid, sid)
      const ents = res.entities_created ?? res.entities?.length ?? 0
      const rels = res.relations_created ?? res.relations?.length ?? 0
      setSyncResult(p => ({ ...p, [sid]: `${ents} entities, ${rels} relations linked` }))
      store.fetchSources(pid)
      store.fetchActivity(pid)
      store.fetchChanges(pid)
    } catch {
      setSyncResult(p => ({ ...p, [sid]: 'Sync failed' }))
    }
    setSyncing(p => ({ ...p, [sid]: false }))
  }

  const handleAddSource = async (sourceType: string) => {
    if (!srcInput.trim()) return
    setAddingSrc(true)
    try {
      let config: Record<string, any> = {}
      let name = ''
      if (sourceType === 'github') {
        config = { path: srcInput.trim() }
        name = srcInput.trim().split('/').pop() || 'github-repo'
      } else if (sourceType === 'kicad') {
        config = { path: srcInput.trim() }
        name = srcInput.trim().split('/').pop() || 'kicad-project'
      } else if (sourceType === 'onshape') {
        config = { url: srcInput.trim() }
        name = 'onshape-model'
      }
      const source = await store.addSource(pid, sourceType, name, config)
      if (source?.id) {
        store.syncSource(pid, source.id).catch(() => {})
      }
      await store.fetchSources(pid)
      setSrcInput('')
      setExpandedSrc(null)
      setShowAddSource(false)
    } finally {
      setAddingSrc(false)
    }
  }

  const handleAddMember = async () => {
    if (!memberName.trim()) return
    await store.addTeamMember(pid, memberName.trim(), memberRole, '')
    await store.fetchTeam(pid)
    setMemberName('')
    setMemberRole(ROLES[0])
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
        {/* Project Header */}
        <section className="bg-solus-elevated border border-solus-border rounded-lg px-4 py-3">
          <div className="flex items-center gap-2 mb-1 group">
            <Target size={14} className="text-solus-accent-bright shrink-0" />
            {editingName ? (
              <input
                value={nameVal}
                onChange={e => setNameVal(e.target.value)}
                onBlur={saveName}
                onKeyDown={e => { if (e.key === 'Enter') saveName(); if (e.key === 'Escape') setEditingName(false) }}
                className="bg-solus-bg border border-solus-border rounded px-2 py-0.5 text-sm font-mono font-semibold text-solus-text flex-1"
                autoFocus
              />
            ) : (
              <h2
                className="text-sm font-mono font-semibold text-solus-text cursor-pointer flex items-center gap-1.5"
                onClick={() => { setNameVal(project?.name || ''); setEditingName(true) }}
              >
                {project?.name}
                <Pencil size={10} className="text-solus-text-muted opacity-0 group-hover:opacity-100 transition-opacity" />
              </h2>
            )}
          </div>
          <div className="ml-[22px] group">
            {editingGoal ? (
              <input
                value={goalVal}
                onChange={e => setGoalVal(e.target.value)}
                onBlur={saveGoal}
                onKeyDown={e => { if (e.key === 'Enter') saveGoal(); if (e.key === 'Escape') setEditingGoal(false) }}
                className="w-full bg-solus-bg border border-solus-border rounded px-2 py-0.5 text-xs font-mono text-solus-text-muted"
                autoFocus
              />
            ) : (
              <p
                className="text-xs font-mono text-solus-text-muted cursor-pointer flex items-center gap-1.5"
                onClick={() => { setGoalVal(project?.description || ''); setEditingGoal(true) }}
              >
                {project?.description || 'Click to add a project goal'}
                <Pencil size={9} className="text-solus-text-muted opacity-0 group-hover:opacity-100 transition-opacity" />
              </p>
            )}
          </div>
        </section>

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
              {([
                { type: 'github', Icon: FolderGit2, title: 'Code Repository', placeholder: 'Repository URL or local path' },
                { type: 'kicad', Icon: Cpu, title: 'PCB Schematic', placeholder: 'Project folder path' },
                { type: 'onshape', Icon: Box, title: 'CAD Model', placeholder: 'Onshape document URL' },
              ] as const).map(({ type, Icon, title, placeholder }) => (
                <div key={type} className="bg-solus-bg border border-solus-border rounded-lg overflow-hidden">
                  <button
                    onClick={() => { setExpandedSrc(expandedSrc === type ? null : type); setSrcInput('') }}
                    className="w-full flex items-center gap-3 px-3 py-2 text-left hover:bg-solus-surface/50 transition-colors"
                  >
                    <Icon size={14} className="text-solus-text-muted" />
                    <span className="text-xs font-mono font-medium text-solus-text">{title}</span>
                  </button>
                  {expandedSrc === type && (
                    <div className="px-3 pb-2 flex gap-2">
                      <input
                        value={srcInput}
                        onChange={e => setSrcInput(e.target.value)}
                        placeholder={placeholder}
                        className="flex-1 bg-solus-elevated border border-solus-border rounded px-2 py-1 text-xs font-mono text-solus-text placeholder:text-solus-text-muted"
                        onKeyDown={e => { if (e.key === 'Enter') handleAddSource(type) }}
                        autoFocus
                      />
                      <button
                        onClick={() => handleAddSource(type)}
                        disabled={!srcInput.trim() || addingSrc}
                        className="bg-solus-accent hover:bg-solus-accent-bright text-white text-xs font-mono px-3 py-1 rounded transition-colors disabled:opacity-50"
                      >
                        {addingSrc ? '...' : 'Add'}
                      </button>
                    </div>
                  )}
                </div>
              ))}
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
                <select value={memberRole} onChange={e => setMemberRole(e.target.value)}
                  className="bg-solus-bg border border-solus-border rounded px-2 py-1 text-xs font-mono text-solus-text">
                  {ROLES.map(r => <option key={r} value={r}>{r}</option>)}
                </select>
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
