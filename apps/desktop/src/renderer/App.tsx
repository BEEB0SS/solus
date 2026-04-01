import { useState } from 'react'
import { Boxes, Network, Search, Activity } from 'lucide-react'
import WorkspaceTab from './components/workspace/WorkspaceTab'
import ContextModelTab from './components/context-model/ContextModelTab'
import IntelligenceTab from './components/intelligence/IntelligenceTab'
import LiveBenchTab from './components/live-bench/LiveBenchTab'

const tabs = [
  { id: 'workspace', label: 'Workspace', icon: Boxes },
  { id: 'context', label: 'Context Model', icon: Network },
  { id: 'intelligence', label: 'Intelligence', icon: Search },
  { id: 'livebench', label: 'Live Bench', icon: Activity },
] as const

type TabId = (typeof tabs)[number]['id']

export default function App() {
  const [activeTab, setActiveTab] = useState<TabId>('workspace')

  return (
    <div className="flex h-screen w-screen overflow-hidden">
      <div className="flex w-14 flex-col items-center gap-1 bg-solus-surface py-2 border-r border-solus-border">
        <div className="h-8 flex items-center justify-center mb-2">
          <span className="text-[9px] font-mono font-bold tracking-widest text-solus-accent-bright">
            SOLUS
          </span>
        </div>
        {tabs.map((tab) => {
          const Icon = tab.icon
          const isActive = activeTab === tab.id
          return (
            <button
              key={tab.id}
              onClick={() => setActiveTab(tab.id)}
              className={`flex h-10 w-10 items-center justify-center rounded-md transition-colors ${
                isActive
                  ? 'bg-solus-accent/20 text-solus-accent-bright'
                  : 'text-solus-text-muted hover:text-solus-text-dim hover:bg-solus-elevated'
              }`}
              title={tab.label}
            >
              <Icon size={18} />
            </button>
          )
        })}
      </div>
      <div className="flex-1 overflow-hidden">
        {activeTab === 'workspace' && <WorkspaceTab />}
        {activeTab === 'context' && <ContextModelTab />}
        {activeTab === 'intelligence' && <IntelligenceTab />}
        {activeTab === 'livebench' && <LiveBenchTab />}
      </div>
    </div>
  )
}
