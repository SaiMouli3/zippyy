import { NavLink, Route, Routes } from 'react-router-dom'
import Dashboard from './pages/Dashboard'
import CreateOrder from './pages/CreateOrder'
import Rates from './pages/Rates'
import Tracking from './pages/Tracking'
import MockControl from './pages/MockControl'
import NdrList from './pages/NdrList'
import NdrDetail from './pages/NdrDetail'

const NAV = [
  ['/', 'Dashboard'], ['/orders/new', 'Create Order'], ['/tracking', 'Shipment Tracking'],
  ['/mock-control', 'Mock Carrier Control'], ['/ndr', 'NDR Cases'],
]

export default function App() {
  return (
    <div className="flex min-h-screen">
      <aside className="w-60 shrink-0 bg-slate-900 p-4 text-slate-300">
        <div className="mb-8 px-2 text-xl font-bold text-white">⚡ Zippy</div>
        <nav className="space-y-1">
          {NAV.map(([to, label]) => (
            <NavLink key={to} to={to} end={to === '/'}
              className={({ isActive }) => `block rounded-lg px-3 py-2 text-sm ${isActive ? 'bg-indigo-600 text-white' : 'hover:bg-slate-800'}`}>
              {label}
            </NavLink>
          ))}
        </nav>
        <p className="mt-8 px-2 text-xs text-slate-500">Demo merchant · MVP</p>
      </aside>
      <main className="min-w-0 flex-1 p-8">
        <Routes>
          <Route path="/" element={<Dashboard />} />
          <Route path="/orders/new" element={<CreateOrder />} />
          <Route path="/orders/:id/rates" element={<Rates />} />
          <Route path="/tracking" element={<Tracking />} />
          <Route path="/orders/:id/tracking" element={<Tracking />} />
          <Route path="/mock-control" element={<MockControl />} />
          <Route path="/ndr" element={<NdrList />} />
          <Route path="/ndr/:id" element={<NdrDetail />} />
        </Routes>
      </main>
    </div>
  )
}
