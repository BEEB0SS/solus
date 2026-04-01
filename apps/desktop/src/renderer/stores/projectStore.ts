import { create } from 'zustand'

const API = ''

interface ProjectStore {
  currentProjectId: string
  currentProject: { id: string; name: string; description: string } | null
  projects: any[]
  entities: any[]
  relations: any[]
  changes: any[]
  sources: any[]
  team: any[]
  activity: any[]
  impact: any | null
  agentMessages: Array<{ id: string; role: string; content: string; timestamp: number; variant?: string }>

  addAgentMessage: (msg: { role: string; content: string; variant?: string }) => { id: string; role: string; content: string; timestamp: number; variant?: string }
  clearAgentMessages: () => void
  fetchProjects: () => Promise<void>
  createProject: (name: string, description: string, id?: string) => Promise<any>
  setCurrentProject: (id: string) => void
  fetchCurrentProject: (pid: string) => Promise<void>
  updateProject: (pid: string, updates: { name?: string; description?: string }) => Promise<void>
  fetchGraph: (pid: string) => Promise<void>
  fetchChanges: (pid: string) => Promise<void>
  fetchSources: (pid: string) => Promise<void>
  addSource: (pid: string, sourceType: string, name: string, config: Record<string, any>) => Promise<any>
  syncSource: (pid: string, sid: string) => Promise<any>
  fetchTeam: (pid: string) => Promise<void>
  addTeamMember: (pid: string, name: string, role: string, email: string) => Promise<any>
  removeTeamMember: (pid: string, memberId: string) => Promise<void>
  fetchImpact: (pid: string, entityId: string) => Promise<void>
  queryAgent: (pid: string, query: string, queryType: string) => Promise<any>
  fetchActivity: (pid: string) => Promise<void>
  discoverDevices: (pid: string) => Promise<any>
}

export const useProjectStore = create<ProjectStore>((set, get) => ({
  currentProjectId: '',
  currentProject: null,
  projects: [],
  entities: [],
  relations: [],
  changes: [],
  sources: [],
  team: [],
  activity: [],
  impact: null,
  agentMessages: [],

  addAgentMessage: (msg) => {
    const m = { ...msg, id: `msg-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`, timestamp: Date.now() }
    set((s) => ({ agentMessages: [...s.agentMessages, m] }))
    return m
  },

  clearAgentMessages: () => set({ agentMessages: [] }),

  fetchProjects: async () => {
    const res = await fetch(`${API}/api/projects`)
    const data = await res.json()
    set({ projects: data })
  },

  createProject: async (name, description, id) => {
    const res = await fetch(`${API}/api/projects`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name, description, ...(id ? { id } : {}) }),
    })
    const proj = await res.json()
    set({ currentProjectId: proj.id, currentProject: proj })
    return proj
  },

  setCurrentProject: (id) => set({ currentProjectId: id }),

  fetchCurrentProject: async (pid) => {
    const res = await fetch(`${API}/api/projects/${pid}`)
    const data = await res.json()
    set({ currentProject: data, currentProjectId: pid })
  },

  updateProject: async (pid, updates) => {
    const res = await fetch(`${API}/api/projects/${pid}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(updates),
    })
    const data = await res.json()
    set({ currentProject: data })
  },

  fetchGraph: async (pid) => {
    const res = await fetch(`${API}/api/projects/${pid}/graph`)
    const data = await res.json()
    set({ entities: data.entities || [], relations: data.relations || [] })
  },

  fetchChanges: async (pid) => {
    const res = await fetch(`${API}/api/projects/${pid}/changes`)
    const data = await res.json()
    set({ changes: data })
  },

  fetchSources: async (pid) => {
    const res = await fetch(`${API}/api/projects/${pid}/sources`)
    const data = await res.json()
    set({ sources: data })
  },

  addSource: async (pid, sourceType, name, config) => {
    const res = await fetch(`${API}/api/projects/${pid}/sources`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ source_type: sourceType, name, config }),
    })
    return res.json()
  },

  syncSource: async (pid, sid) => {
    const res = await fetch(`${API}/api/projects/${pid}/sources/${sid}/sync`, {
      method: 'POST',
    })
    return res.json()
  },

  fetchTeam: async (pid) => {
    const res = await fetch(`${API}/api/projects/${pid}/team`)
    const data = await res.json()
    set({ team: data })
  },

  addTeamMember: async (pid, name, role, email) => {
    const res = await fetch(`${API}/api/projects/${pid}/team`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name, role, email }),
    })
    return res.json()
  },

  removeTeamMember: async (pid, memberId) => {
    await fetch(`${API}/api/projects/${pid}/team/${memberId}`, { method: 'DELETE' })
    const { team } = get()
    set({ team: team.filter((m: any) => m.id !== memberId) })
  },

  fetchImpact: async (pid, entityId) => {
    const res = await fetch(`${API}/api/projects/${pid}/impact/${entityId}`)
    const data = await res.json()
    set({ impact: data })
  },

  queryAgent: async (pid, query, queryType) => {
    const res = await fetch(`${API}/api/projects/${pid}/agent/query`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ query, query_type: queryType, context_entity_ids: [] }),
    })
    return res.json()
  },

  fetchActivity: async (pid) => {
    const res = await fetch(`${API}/api/projects/${pid}/activity`)
    const data = await res.json()
    set({ activity: data })
  },

  discoverDevices: async (pid) => {
    const res = await fetch(`${API}/api/projects/${pid}/live-bench/discover`, {
      method: 'POST',
    })
    return res.json()
  },
}))
