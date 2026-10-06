import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { api } from '@/lib/api'
import { Badge, Empty, ErrorBanner, JsonDetails, Spinner, Table, Td, Th } from '@/components/ui'
import { dt, pretty } from '@/lib/format'

const tone = (a: string) => ({ AGENT: 'brand', BUYER: 'violet', CARRIER: 'info', SELLER: 'warn', OPS: 'warn', SYSTEM: 'neutral' }[a] ?? 'neutral') as 'brand' | 'violet' | 'info' | 'warn' | 'neutral'

export default function AuditTable({ caseId, orderId, showFilter }: { caseId?: string; orderId?: string; showFilter?: boolean }) {
  const [actorType, setActorType] = useState('')
  const q = useQuery({ queryKey: ['audit', caseId, orderId, actorType], queryFn: () => api.audit({ caseId, orderId, actorType, limit: 300 }), refetchInterval: 5000 })
  if (q.isLoading) return <Spinner />
  const logs = q.data?.logs ?? []
  return (
    <div>
      <ErrorBanner error={q.error} />
      {showFilter && (
        <div className="mb-3 flex items-center gap-2 text-sm">
          <label htmlFor="actor-type" className="text-ink2">Actor type</label>
          <select id="actor-type" className="h-8 rounded-lg border border-line bg-surface px-2" value={actorType} onChange={e => setActorType(e.target.value)}>
            <option value="">All</option>{['AGENT', 'SELLER', 'OPS', 'CARRIER', 'SYSTEM', 'BUYER'].map(t => <option key={t}>{t}</option>)}
          </select>
        </div>
      )}
      {logs.length === 0 ? <Empty title="No audit entries" /> : (
        <Table>
          <thead><tr><Th>Time</Th><Th>Actor</Th><Th>Action</Th><Th>Case</Th><Th>State change</Th><Th>Payloads</Th></tr></thead>
          <tbody>
            {logs.map(l => (
              <tr key={l.id}>
                <Td className="whitespace-nowrap">{dt(l.createdAt)}</Td>
                <Td><Badge tone={tone(l.actorType)}>{l.actorType.toLowerCase()}</Badge><div className="text-xs text-muted">{l.actor}</div></Td>
                <Td><span className="font-medium">{pretty(l.action)}</span>{l.requestId && <div className="font-mono text-[11px] text-muted">req {l.requestId.slice(0, 8)}</div>}</Td>
                <Td>{l.caseNumber || '—'}</Td>
                <Td className="text-xs text-ink2">{l.previousState || l.newState ? `${l.previousState || '—'} → ${l.newState || '—'}` : '—'}</Td>
                <Td><JsonDetails label="Evidence" data={l.evidence} /><JsonDetails label="Request" data={l.requestPayload} /><JsonDetails label="Response" data={l.responsePayload} /></Td>
              </tr>
            ))}
          </tbody>
        </Table>
      )}
    </div>
  )
}
