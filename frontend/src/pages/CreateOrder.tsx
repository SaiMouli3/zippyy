import { useState, type FormEvent } from 'react'
import { useNavigate } from 'react-router-dom'
import { api } from '../api'
import { Btn, Card, ErrorBox, PageTitle } from '../ui'

const field = 'mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm focus:border-indigo-500 focus:outline-none'

export default function CreateOrder() {
  const nav = useNavigate()
  const [f, setF] = useState({ customerName: 'Rahul Sharma', phone: '9876543210', address: '12 MG Road, Connaught Place, New Delhi',
    pickupPincode: '560001', deliveryPincode: '110001', weightKg: '1.5', paymentMode: 'COD', codAmount: '2500' })
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const set = (k: string) => (e: any) => setF({ ...f, [k]: e.target.value })

  async function submit(e: FormEvent) {
    e.preventDefault(); setBusy(true); setError(null)
    try {
      const o = await api('/api/orders', 'POST', { ...f, weightKg: Number(f.weightKg), codAmount: f.paymentMode === 'COD' ? Number(f.codAmount) : 0 })
      nav(`/orders/${o.id}/rates`)
    } catch (e: any) { setError(e.message) } finally { setBusy(false) }
  }
  const L = ({ label, children }: any) => <label className="block text-sm font-medium text-slate-700">{label}{children}</label>
  return (
    <>
      <PageTitle title="Create Order" sub="Prefilled with the demo order" />
      <Card className="max-w-2xl">
        <ErrorBox error={error} />
        <form onSubmit={submit} className="grid grid-cols-2 gap-4">
          <L label="Customer name"><input className={field} value={f.customerName} onChange={set('customerName')} required /></L>
          <L label="Phone"><input className={field} value={f.phone} onChange={set('phone')} /></L>
          <div className="col-span-2"><L label="Delivery address"><input className={field} value={f.address} onChange={set('address')} /></L></div>
          <L label="Pickup pincode"><input className={field} value={f.pickupPincode} onChange={set('pickupPincode')} /></L>
          <L label="Delivery pincode"><input className={field} value={f.deliveryPincode} onChange={set('deliveryPincode')} /></L>
          <L label="Weight (kg)"><input className={field} type="number" step="0.1" value={f.weightKg} onChange={set('weightKg')} /></L>
          <L label="Payment"><select className={field} value={f.paymentMode} onChange={set('paymentMode')}><option>COD</option><option>PREPAID</option></select></L>
          {f.paymentMode === 'COD' && <L label="COD amount (₹)"><input className={field} type="number" value={f.codAmount} onChange={set('codAmount')} /></L>}
          <div className="col-span-2"><Btn type="submit" disabled={busy}>{busy ? 'Creating…' : 'Create order & get rates'}</Btn></div>
        </form>
      </Card>
    </>
  )
}
