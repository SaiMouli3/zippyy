import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import type { CarrierRules } from '@zippy/shared-types'
import { api } from '@/lib/api'
import { useSession } from '@/lib/session'
import { Banner, Button, Card, ErrorBanner, Field, inputCls, PageHeader, Spinner } from '@/components/ui'
import { carrierName, pretty } from '@/lib/format'

const ACTIONS = ['REQUEST_REATTEMPT', 'RESCHEDULE', 'UPDATE_PHONE', 'UPDATE_ADDRESS', 'CONVERT_TO_PREPAID', 'INITIATE_RTO']

function Editor({ rules, canEdit }: { rules: CarrierRules; canEdit: boolean }) {
  const qc = useQueryClient()
  const [r, setR] = useState(rules)
  const save = useMutation({ mutationFn: () => api.saveCarrierRules(r), onSuccess: () => qc.invalidateQueries({ queryKey: ['carrierRules'] }) })
  const bool = (k: 'supportsTimeSlot' | 'canChangePaymentMode' | 'canChangeAddress' | 'canChangePhone', label: string) => (
    <label className="flex items-center gap-2 text-sm"><input type="checkbox" disabled={!canEdit} checked={r[k]} onChange={e => setR({ ...r, [k]: e.target.checked })} />{label}</label>
  )
  return (
    <Card title={carrierName(r.carrierCode)} actions={<Button variant="primary" disabled={!canEdit} loading={save.isPending} onClick={() => save.mutate()}>Save</Button>}>
      <ErrorBanner error={save.error} />
      <div className="grid gap-3 sm:grid-cols-3">
        <Field label="Max attempts"><input disabled={!canEdit} className={inputCls} type="number" min={1} value={r.maxAttempts} onChange={e => setR({ ...r, maxAttempts: Number(e.target.value) })} /></Field>
        <Field label="Instruction cutoff (IST, HH:MM)" hint="Later instructions miss next-day attempt"><input disabled={!canEdit} className={inputCls} value={r.instructionCutoff} onChange={e => setR({ ...r, instructionCutoff: e.target.value })} /></Field>
        <Field label="Hold window (days)"><input disabled={!canEdit} className={inputCls} type="number" min={1} value={r.holdWindowDays} onChange={e => setR({ ...r, holdWindowDays: Number(e.target.value) })} /></Field>
      </div>
      <div className="mt-4 grid gap-2 sm:grid-cols-2">{bool('supportsTimeSlot', 'Supports time-slot remarks')}{bool('canChangePaymentMode', 'Payment mode can change (COD → prepaid)')}{bool('canChangeAddress', 'Address can change')}{bool('canChangePhone', 'Phone can change')}</div>
      <div className="mt-4"><div className="mb-1 text-xs font-medium text-ink2">Supported actions (API)</div>
        <div className="grid gap-2 sm:grid-cols-3">{ACTIONS.map(a => <label key={a} className="flex items-center gap-2 text-sm"><input type="checkbox" disabled={!canEdit} checked={r.supportedActions.includes(a)} onChange={e => setR({ ...r, supportedActions: e.target.checked ? [...r.supportedActions, a] : r.supportedActions.filter(x => x !== a) })} />{pretty(a)}</label>)}</div></div>
    </Card>
  )
}

export default function CarrierRulesPage() {
  const { role } = useSession()
  const q = useQuery({ queryKey: ['carrierRules'], queryFn: api.carrierRules })
  return (
    <>
      <PageHeader title="Carrier rules" subtitle="What each carrier can and cannot do. The agent checks these before acting; they are never inferred by AI." />
      {role !== 'OPS' && <div className="mb-4"><Banner tone="info" title="Read-only">Switch “Acting as” to Ops to edit carrier constraints.</Banner></div>}
      {q.isLoading ? <Spinner /> : <div className="space-y-4">{q.data!.rules.map(r => <Editor key={r.carrierCode + r.maxAttempts + r.holdWindowDays + r.instructionCutoff} rules={r} canEdit={role === 'OPS'} />)}</div>}
    </>
  )
}
