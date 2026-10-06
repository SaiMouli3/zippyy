import { useEffect, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import type { SellerRules } from '@zippy/shared-types'
import { api } from '@/lib/api'
import { useSession } from '@/lib/session'
import { Banner, Button, Card, ErrorBanner, Field, inputCls, PageHeader, Spinner } from '@/components/ui'
import { pretty } from '@/lib/format'

const ACTIONS = ['REQUEST_REATTEMPT', 'RESCHEDULE', 'UPDATE_PHONE', 'UPDATE_ADDRESS', 'CONVERT_TO_PREPAID', 'INITIATE_RTO']
const CHANNELS = ['WHATSAPP', 'IVR', 'SMS']

function toggle(list: string[], v: string, on: boolean) { return on ? [...new Set([...list, v])] : list.filter(x => x !== v) }

export default function SellerRulesPage() {
  const qc = useQueryClient()
  const { role } = useSession()
  const q = useQuery({ queryKey: ['sellerRules'], queryFn: api.sellerRules })
  const [r, setR] = useState<SellerRules | null>(null)
  useEffect(() => { if (q.data?.rules[0] && !r) setR(q.data.rules[0]) }, [q.data, r])
  const save = useMutation({ mutationFn: (v: SellerRules) => api.saveSellerRules(v), onSuccess: v => { setR(v); qc.invalidateQueries({ queryKey: ['sellerRules'] }) } })
  if (q.isLoading || !r) return <Spinner />
  const set = <K extends keyof SellerRules>(k: K, v: SellerRules[K]) => setR({ ...r, [k]: v })
  const num = (k: keyof SellerRules) => (e: React.ChangeEvent<HTMLInputElement>) => set(k, Number(e.target.value) as never)
  const canEdit = role === 'SELLER'
  return (
    <>
      <PageHeader title="Seller rules" subtitle={`Deterministic policy for merchant ${r.merchantId}. The rules engine reads these live on every decision.`}
        actions={<Button variant="primary" disabled={!canEdit} loading={save.isPending} onClick={() => save.mutate(r)}>Save rules</Button>} />
      {!canEdit && <div className="mb-4"><Banner tone="info" title="Read-only">Switch “Acting as” to Seller to edit. Changes are audited.</Banner></div>}
      <ErrorBanner error={save.error} />
      {save.isSuccess && <div className="mb-4"><Banner tone="ok" title="Saved">New rules apply to the next decision.</Banner></div>}
      <fieldset disabled={!canEdit} className="grid gap-4 lg:grid-cols-2">
        <Card title="Attempts & risk">
          <div className="grid gap-3 sm:grid-cols-2">
            <Field label="Maximum delivery attempts" hint="Beyond this, an extra attempt needs seller approval"><input className={inputCls} type="number" min={1} max={10} value={r.maxAttempts} onChange={num('maxAttempts')} /></Field>
            <Field label="Auto-RTO at attempt" hint="Final attempt: unresponsive buyer → RTO decision"><input className={inputCls} type="number" min={0} max={10} value={r.autoRtoAttempt} onChange={num('autoRtoAttempt')} /></Field>
            <Field label="COD limit for repeat attempts (₹)" hint="Above this, attempt 2+ needs seller approval"><input className={inputCls} type="number" value={r.codLimit} onChange={num('codLimit')} /></Field>
            <Field label="Early RTO policy" hint="When a buyer cancels"><select className={inputCls} value={r.earlyRtoPolicy} onChange={e => set('earlyRtoPolicy', e.target.value as SellerRules['earlyRtoPolicy'])}><option value="AUTO">Agent may initiate</option><option value="APPROVAL">Seller approval</option><option value="DISALLOWED">Not allowed</option></select></Field>
            <Field label="If seller stays silent (final attempt)"><select className={inputCls} value={r.defaultOnSilence} onChange={e => set('defaultOnSilence', e.target.value as SellerRules['defaultOnSilence'])}><option value="RTO">Initiate RTO</option><option value="ESCALATE">Escalate to ops</option></select></Field>
          </div>
        </Card>
        <Card title="Buyer communication">
          <div className="mb-3 flex flex-wrap gap-4 text-sm">{CHANNELS.map(ch => <label key={ch} className="flex items-center gap-2"><input type="checkbox" checked={r.allowedChannels.includes(ch)} onChange={e => set('allowedChannels', toggle(r.allowedChannels, ch, e.target.checked))} />{ch}</label>)}</div>
          <p className="mb-3 text-xs text-muted">Priority is always WhatsApp → IVR → SMS, filtered by this list.</p>
          <div className="grid gap-3 sm:grid-cols-3">
            <Field label="Hours from"><input className={inputCls} value={r.commHoursStart} onChange={e => set('commHoursStart', e.target.value)} /></Field>
            <Field label="Hours to"><input className={inputCls} value={r.commHoursEnd} onChange={e => set('commHoursEnd', e.target.value)} /></Field>
            <label className="flex items-end gap-2 pb-2 text-sm"><input type="checkbox" checked={r.enforceCommHours} onChange={e => set('enforceCommHours', e.target.checked)} />Enforce (IST)</label>
            <Field label="Buyer response timeout (min)"><input className={inputCls} type="number" value={r.buyerResponseTimeoutMinutes} onChange={num('buyerResponseTimeoutMinutes')} /></Field>
            <Field label="Seller response timeout (min)"><input className={inputCls} type="number" value={r.sellerResponseTimeoutMinutes} onChange={num('sellerResponseTimeoutMinutes')} /></Field>
          </div>
        </Card>
        <Card title="Permissions">
          <div className="space-y-2 text-sm">
            <label className="flex items-center gap-2"><input type="checkbox" checked={r.prepaidConversionAllowed} onChange={e => set('prepaidConversionAllowed', e.target.checked)} />Allow COD → prepaid conversion</label>
            <label className="flex items-center gap-2"><input type="checkbox" checked={r.allowAddressChanges} onChange={e => set('allowAddressChanges', e.target.checked)} />Allow address changes (same pincode auto, new pincode/city need approval)</label>
          </div>
        </Card>
        <Card title="Actions the agent may take without approval">
          <div className="grid gap-2 sm:grid-cols-2 text-sm">{ACTIONS.map(a => <label key={a} className="flex items-center gap-2"><input type="checkbox" checked={r.allowedActions.includes(a)} onChange={e => set('allowedActions', toggle(r.allowedActions, a, e.target.checked))} />{pretty(a)}</label>)}</div>
        </Card>
      </fieldset>
    </>
  )
}
