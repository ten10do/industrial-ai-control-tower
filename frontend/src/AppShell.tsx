import { useQuery } from '@tanstack/react-query'
import { NavLink, Outlet } from 'react-router-dom'
import { api, ApiError } from './api'
import { useAuth } from './auth'
import { StatusBadge } from './components'

const navigation = [
  ['Overview', '/'],
  ['Devices', '/devices'],
  ['Incidents', '/incidents'],
  ['Approvals', '/approvals'],
  ['Work Orders', '/work-orders'],
  ['Agent Observability', '/observability'],
  ['Connectivity', '/connectivity'],
  ['Assets & Config', '/assets-config'],
] as const

export function AppShell() {
  const { identity, logout } = useAuth()
  const ready = useQuery({ queryKey: ['ready'], queryFn: api.ready, refetchInterval: 15_000 })
  const dependencies = ready.data?.dependencies ?? (ready.error instanceof ApiError ? ready.error.details?.dependencies : undefined)
  const overall = ready.isPending ? 'CHECKING' : ready.data?.status === 'ready' ? 'HEALTHY' : 'DEGRADED'
  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand"><span className="brand-mark">IA</span><div><strong>Industrial AI Control Tower</strong><small>Industrial AI Operations</small></div></div>
        <nav aria-label="Primary navigation">
          {navigation.map(([label, path]) => <NavLink key={path} to={path} end={path === '/'}>{label}</NavLink>)}
        </nav>
        <div className="sidebar-foot">
          <small>{identity ? `Signed in as ${identity.username}` : 'No active session'}</small>
          <span>{identity?.roles.join(' · ') || 'NO ROLE'}</span>
          <button type="button" onClick={logout}>Sign out</button>
          <span>READ-ONLY DEVICE CONTROL</span>
        </div>
      </aside>
      <div className="workspace">
        <header className="topbar">
          <div><p className="eyebrow">Operational status</p><StatusBadge value={overall} /></div>
          <div className="dependency-strip" aria-label="System dependencies">
            {['postgres', 'redis', 'mqtt', 'diagnosis', 'knowledge', 'workflow', 'connectivity', 'configuration'].map((name) => <span key={name}><b>{name === 'workflow' ? 'Agent Runtime' : name === 'configuration' ? 'Config Mgmt' : name}</b><StatusBadge value={dependencies?.[name] || (ready.isPending ? 'CHECKING' : 'UNAVAILABLE')} /></span>)}
            <span><b>Backend</b><StatusBadge value={ready.data ? 'HEALTHY' : ready.isPending ? 'CHECKING' : 'UNAVAILABLE'} /></span>
          </div>
        </header>
        <main className="main-content"><Outlet /></main>
      </div>
    </div>
  )
}
