import { useState } from 'react'
import { useProjectStore } from '../../stores/projectStore'
import { sourceInputToConfig } from './sourceConfig'
import {
  FolderGit2, Cpu, Box, Users, Target, ArrowRight, X, Check,
} from 'lucide-react'

export const ROLES = ['Software', 'Hardware', 'Electronics', 'Mechanical', 'Design', 'PM']

export default function CreationFlow() {
  const store = useProjectStore()
  const [step, setStep] = useState(1)
  const [projName, setProjName] = useState('')
  const [projGoal, setProjGoal] = useState('')
  const [creating, setCreating] = useState(false)

  // Step 2 state
  const [memberName, setMemberName] = useState('')
  const [memberRole, setMemberRole] = useState(ROLES[0])

  // Step 3 state
  const [expanded, setExpanded] = useState<string | null>(null)
  const [srcInput, setSrcInput] = useState('')
  const [addingSrc, setAddingSrc] = useState(false)
  const [connectedSources, setConnectedSources] = useState<Record<string, boolean>>({})

  const pid = store.currentProjectId

  const handleCreateProject = async () => {
    if (!projName.trim()) return
    setCreating(true)
    try {
      await store.createProject(projName.trim(), projGoal.trim())
      setStep(2)
    } finally {
      setCreating(false)
    }
  }

  const handleAddMember = async () => {
    if (!memberName.trim()) return
    await store.addTeamMember(pid, memberName.trim(), memberRole, '')
    await store.fetchTeam(pid)
    setMemberName('')
    setMemberRole(ROLES[0])
  }

  const handleRemoveMember = async (id: string) => {
    await store.removeTeamMember(pid, id)
  }

  const handleAddSource = async (sourceType: string) => {
    if (!srcInput.trim()) return
    setAddingSrc(true)
    try {
      const { config, name } = sourceInputToConfig(sourceType, srcInput)
      const source = await store.addSource(pid, sourceType, name, config)
      if (source?.id) {
        store.syncSource(pid, source.id).catch(() => {})
      }
      await store.fetchSources(pid)
      setConnectedSources(p => ({ ...p, [sourceType]: true }))
      setSrcInput('')
      setExpanded(null)
    } finally {
      setAddingSrc(false)
    }
  }

  const handleFinish = async () => {
    await store.fetchProjects()
    await store.fetchCurrentProject(pid)
  }

  return (
    <div className="flex items-start justify-center h-full overflow-y-auto py-20 px-4">
      <div className="w-full max-w-lg">
        {/* Step 1: Create Project */}
        {step === 1 && (
          <div className="bg-solus-elevated border border-solus-border rounded-xl p-6 space-y-4">
            <div className="flex items-center gap-2 mb-2">
              <Target size={18} className="text-solus-accent-bright" />
              <h1 className="text-base font-mono font-semibold text-solus-text">Create Your Project</h1>
            </div>
            <div className="space-y-3">
              <div>
                <label className="text-[10px] font-mono uppercase tracking-widest text-solus-text-muted mb-1 block">Project Name</label>
                <input
                  value={projName}
                  onChange={e => setProjName(e.target.value)}
                  placeholder="My Robot Project"
                  className="w-full bg-solus-bg border border-solus-border rounded-lg px-3 py-2 text-sm font-mono text-solus-text placeholder:text-solus-text-muted"
                  onKeyDown={e => { if (e.key === 'Enter') handleCreateProject() }}
                  autoFocus
                />
              </div>
              <div>
                <label className="text-[10px] font-mono uppercase tracking-widest text-solus-text-muted mb-1 block">What are you building?</label>
                <textarea
                  value={projGoal}
                  onChange={e => setProjGoal(e.target.value)}
                  placeholder="Build an obstacle avoidance robot using an Elegoo V4 with ultrasonic sensors"
                  rows={3}
                  className="w-full bg-solus-bg border border-solus-border rounded-lg px-3 py-2 text-sm font-mono text-solus-text placeholder:text-solus-text-muted resize-none"
                />
              </div>
            </div>
            <button
              onClick={handleCreateProject}
              disabled={!projName.trim() || creating}
              className="flex items-center gap-2 bg-solus-accent hover:bg-solus-accent-bright text-white text-sm font-mono px-4 py-2 rounded-lg transition-colors disabled:opacity-50 ml-auto"
            >
              {creating ? 'Creating...' : 'Create Project'} <ArrowRight size={14} />
            </button>
          </div>
        )}

        {/* Step 2: Add Team */}
        {step === 2 && (
          <div className="bg-solus-elevated border border-solus-border rounded-xl p-6 space-y-4">
            <div>
              <p className="text-[10px] font-mono uppercase tracking-widest text-solus-accent-bright mb-1">
                Project: {store.currentProject?.name}
              </p>
              <div className="flex items-center gap-2 mb-1">
                <Users size={18} className="text-solus-accent-bright" />
                <h1 className="text-base font-mono font-semibold text-solus-text">Add Your Team</h1>
              </div>
              <p className="text-xs font-mono text-solus-text-muted">Who's working on this?</p>
            </div>

            <div className="flex gap-2">
              <input
                value={memberName}
                onChange={e => setMemberName(e.target.value)}
                placeholder="Name"
                className="flex-1 bg-solus-bg border border-solus-border rounded-lg px-3 py-2 text-sm font-mono text-solus-text placeholder:text-solus-text-muted"
                onKeyDown={e => { if (e.key === 'Enter') handleAddMember() }}
              />
              <select
                value={memberRole}
                onChange={e => setMemberRole(e.target.value)}
                className="bg-solus-bg border border-solus-border rounded-lg px-2 py-2 text-sm font-mono text-solus-text"
              >
                {ROLES.map(r => <option key={r} value={r}>{r}</option>)}
              </select>
              <button
                onClick={handleAddMember}
                disabled={!memberName.trim()}
                className="bg-solus-accent hover:bg-solus-accent-bright text-white text-sm font-mono px-3 py-2 rounded-lg transition-colors disabled:opacity-50"
              >
                Add
              </button>
            </div>

            {store.team.length > 0 && (
              <div className="space-y-1.5">
                {store.team.map((m: any) => (
                  <div key={m.id} className="flex items-center gap-2 bg-solus-bg rounded-lg px-3 py-2">
                    <Users size={12} className="text-solus-text-muted" />
                    <span className="text-sm font-mono text-solus-text flex-1">{m.name}</span>
                    <span className="text-[10px] font-mono px-1.5 py-0.5 rounded bg-solus-accent/15 text-solus-accent-bright">{m.role}</span>
                    <button onClick={() => handleRemoveMember(m.id)} className="text-solus-text-muted hover:text-solus-error transition-colors">
                      <X size={12} />
                    </button>
                  </div>
                ))}
              </div>
            )}

            <div className="flex justify-end gap-2 pt-2">
              <button
                onClick={() => setStep(3)}
                className="text-xs font-mono text-solus-text-muted hover:text-solus-text transition-colors px-3 py-2"
              >
                Skip
              </button>
              <button
                onClick={() => setStep(3)}
                className="flex items-center gap-2 bg-solus-accent hover:bg-solus-accent-bright text-white text-sm font-mono px-4 py-2 rounded-lg transition-colors"
              >
                Continue <ArrowRight size={14} />
              </button>
            </div>
          </div>
        )}

        {/* Step 3: Connect Sources */}
        {step === 3 && (
          <div className="bg-solus-elevated border border-solus-border rounded-xl p-6 space-y-4">
            <div>
              <p className="text-[10px] font-mono uppercase tracking-widest text-solus-accent-bright mb-1">
                Project: {store.currentProject?.name}
              </p>
              <div className="flex items-center gap-2 mb-1">
                <FolderGit2 size={18} className="text-solus-accent-bright" />
                <h1 className="text-base font-mono font-semibold text-solus-text">Connect Your Sources</h1>
              </div>
              <p className="text-xs font-mono text-solus-text-muted">Where's your project data?</p>
            </div>

            <div className="space-y-2">
              {([
                { type: 'github', Icon: FolderGit2, title: 'Code Repository', desc: 'Connect your Arduino/ROS code', placeholder: 'Repository URL or local path' },
                { type: 'kicad', Icon: Cpu, title: 'PCB Schematic', desc: 'Connect your circuit design', placeholder: 'Project folder path' },
                { type: 'onshape', Icon: Box, title: 'CAD Model', desc: 'Connect your 3D design', placeholder: 'Onshape document URL' },
              ] as const).map(({ type, Icon, title, desc, placeholder }) => (
                <div key={type} className="bg-solus-bg border border-solus-border rounded-lg overflow-hidden">
                  <button
                    onClick={() => { setExpanded(expanded === type ? null : type); setSrcInput('') }}
                    className="w-full flex items-center gap-3 px-4 py-3 text-left hover:bg-solus-surface/50 transition-colors"
                  >
                    <Icon size={16} className={connectedSources[type] ? 'text-solus-success' : 'text-solus-text-muted'} />
                    <div className="flex-1">
                      <div className="text-sm font-mono font-medium text-solus-text flex items-center gap-2">
                        {title}
                        {connectedSources[type] && <Check size={12} className="text-solus-success" />}
                      </div>
                      <div className="text-[10px] font-mono text-solus-text-muted">{desc}</div>
                    </div>
                  </button>
                  {expanded === type && !connectedSources[type] && (
                    <div className="px-4 pb-3 flex gap-2">
                      <input
                        value={srcInput}
                        onChange={e => setSrcInput(e.target.value)}
                        placeholder={placeholder}
                        className="flex-1 bg-solus-elevated border border-solus-border rounded px-3 py-1.5 text-xs font-mono text-solus-text placeholder:text-solus-text-muted"
                        onKeyDown={e => { if (e.key === 'Enter') handleAddSource(type) }}
                        autoFocus
                      />
                      <button
                        onClick={() => handleAddSource(type)}
                        disabled={!srcInput.trim() || addingSrc}
                        className="bg-solus-accent hover:bg-solus-accent-bright text-white text-xs font-mono px-3 py-1.5 rounded transition-colors disabled:opacity-50"
                      >
                        {addingSrc ? '...' : 'Add Source'}
                      </button>
                    </div>
                  )}
                </div>
              ))}
            </div>

            <div className="flex justify-end pt-2">
              <button
                onClick={handleFinish}
                className="flex items-center gap-2 bg-solus-accent hover:bg-solus-accent-bright text-white text-sm font-mono px-4 py-2 rounded-lg transition-colors"
              >
                Finish Setup <ArrowRight size={14} />
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
