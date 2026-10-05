import { useEffect, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { api, type Rate } from '../api'
import { Btn, Card, ErrorBox, PageTitle, CARRIER_NAMES, inr, useFetch } from '../ui'

export default function Rates() {
  const { id } = useParams()
  const nav = useNavigate()
  const { data: order, reload } = useFetch<any>(`/api/orders/${id}`)
  const [res, setRes] = useState<{ rates: Rate[]; cached: boolean; errors: { carrier: string; error: string }[] } | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  async function fetchRates(refresh = false) {
    setBusy(true); setError(null)
    try { setRes(await api(`/api/orders/${id}/rates${refresh ? '?refresh=true' : ''}`, 'POST')) }
    catch (e: any) { setError(e.message) } finally { setBusy(false) }
  }
  useEffect(() => { fetchRates() }, [id]) // eslint-disable-line

  async function select(r: Rate) {
    setError(null)
    try { await api(`/api/orders/${id}/select-carrier`, 'POST', { carrier: r.carrier, service: r.service }); reload() }
    catch (e: any) { setError(e.message) }
  }
  async function ship() {
    setError(null)
    try { await api(`/api/orders/${id}/shipment`, 'POST'); nav(`/orders/${id}/tracking`) }
    catch (e: any) { setError(e.message) }
  }
  const eta = (r: Rate) => (r.etaMinDays === r.etaMaxDays ? `${r.etaMaxDays} days` : `${r.etaMinDays}–${r.etaMaxDays} days`)
  const cheapest = res ? Math.min(...res.rates.map((r) => r.price)) : 0

  return (
    <>
      <PageTitle title={`Shipping rates · ${id}`} sub={order && `${order.customerName} · ${order.pickupPincode} → ${order.deliveryPincode} · ${order.weightKg} kg · ${order.paymentMode}${order.paymentMode === 'COD' ? ` ₹${order.codAmount}` : ''}`} />
      <ErrorBox error={error} />
      {res?.errors.map((e) => (
        <div key={e.carrier} className="mb-3 rounded-lg border border-amber-200 bg-amber-50 px-4 py-2 text-sm text-amber-800">
          {CARRIER_NAMES[e.carrier]} is unavailable right now — showing the other carriers.
        </div>))}
      <div className="mb-4 flex items-center gap-3">
        <Btn kind="ghost" onClick={() => fetchRates(true)} disabled={busy}>{busy ? 'Fetching…' : 'Refresh rates'}</Btn>
        {res && <span className="text-xs text-slate-500">{res.cached ? 'Served from Redis cache (5 min TTL)' : 'Live from carriers'}</span>}
      </div>
      <div className="grid max-w-5xl gap-4 md:grid-cols-3">
        {res?.rates.map((r) => {
          const chosen = order?.selectedCarrier === r.carrier && order?.selectedService === r.service
          return (
            <Card key={r.carrier + r.service} className={chosen ? 'ring-2 ring-indigo-500' : ''}>
              <div className="text-lg font-semibold">{r.carrierName}</div>
              <div className="text-sm text-slate-500">{r.serviceName}</div>
              <div className="mt-4 text-3xl font-semibold">{inr(r.price)}</div>
              <div className="text-sm text-slate-500">{eta(r)}</div>
              {r.price === cheapest && <div className="mt-2 text-xs font-medium text-emerald-600">Cheapest</div>}
              <div className="mt-4"><Btn kind={chosen ? 'ghost' : 'primary'} onClick={() => select(r)} disabled={!!order?.shipment}>{chosen ? 'Selected ✓' : 'Select Carrier'}</Btn></div>
            </Card>)
        })}
      </div>
      <div className="mt-6">
        <Btn onClick={ship} disabled={!order?.selectedCarrier || !!order?.shipment}>
          {order?.shipment ? 'Shipment created' : 'Create Shipment'}
        </Btn>
        {order?.selectedCarrier && !order.shipment && <span className="ml-3 text-sm text-slate-500">Selected: {CARRIER_NAMES[order.selectedCarrier]} {inr(order.quotedPrice)}</span>}
      </div>
    </>
  )
}
