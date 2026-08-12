import { useEffect, useState } from 'react'
import { useProjectStore } from '../../stores/projectStore'
import CreationFlow from './CreationFlow'
import Dashboard from './Dashboard'

export default function WorkspaceTab() {
  const store = useProjectStore()
  const [loaded, setLoaded] = useState(false)

  useEffect(() => {
    store.fetchProjects().then(() => setLoaded(true))
  }, [])

  // Once projects load, auto-select the first one and fetch its details
  useEffect(() => {
    if (!loaded) return
    if (store.projects.length > 0 && !store.currentProject) {
      const first = store.projects[0]
      store.setCurrentProject(first.id)
      store.fetchCurrentProject(first.id)
    }
  }, [loaded, store.projects.length])

  if (!loaded) {
    return (
      <div className="flex items-center justify-center h-full">
        <span className="text-xs font-mono text-solus-text-muted">Loading...</span>
      </div>
    )
  }

  if (store.projects.length === 0 || !store.currentProject) {
    return <CreationFlow />
  }

  return <Dashboard />
}
