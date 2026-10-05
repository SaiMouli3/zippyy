import { useState, type FormEvent } from 'react'
import { useNavigate, Link } from 'react-router-dom'
import { api } from '../api'
import { Btn, Card, ErrorBox, PageTitle } from '../ui'

const field = 'mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm focus:border-indigo-500 focus:outline-none'
const L = ({ label, children, span = '' }: { label: string; children: React.ReactNode; span?: string }) => (
  <label className={`block text-sm font-medium text-slate-700 ${span}`}>{label}{children}</label>
)
const newRef = () => `SHOP-${Math.floor(1000 + Math.random() * 9000)}`

export default function CreateOrder() {
  const nav = useNavigate()
  const [f, setF] = useState({ merchantId: 'MRC-100', merchantOrderId: newRef(), customerName: 'Rahul Sharma', phone: '9876543210',
    address: '12 MG Road, Connaught Place, New Delhi', pickupPincode: '560001', deliveryPincode: '110001',
    weightGrams: '1500', lengthCm: '20', widthCm: '15', heightCm: '10', paymentMode: 'COD', codAmount: '2500' })
  const [error, setError] = useState<string | null>(null)
  const [dup, setDup] = useState<any>(null)
  const [busy, setBusy] = useState(false)
  const set = (k: string) => (e: any) => setF({ ...f, [k]: e.target.value })

  async function submit(e: FormEvent) {
    e.preventDefault(); setBusy(true); setError(null); setDup(null)
    try {
      const o = await api('/api/orders', 'POST', {
        ...f, weightGrams: Number(f.weightGrams), lengthCm: Number(f.lengthCm), widthCm: Number(f.widthCm),
        heightCm: Number(f.heightCm), codAmount: f.paymentMode === 'COD' ? Number(f.codAmount) : 0 })
      if (o.duplicate) setDup(o); else nav(`/orders/${o.id}/rates`)
    } catch (e: any) { setError(e.message) } finally { setBusy(false) }
  }
  return (
    <>
      <PageTitle title="Create Order" sub="Prefilled with the demo order. Submitting the same Merchant order ID again returns the existing order." />
      <Card className="max-w-3xl">
        <ErrorBox error={error} />
        {dup && (
          <div data-testid="duplicate-notice" className="mb-4 rounded-lg border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800">
            Duplicate protection: order <b>{dup.id}</b> already exists for merchant order ID <b>{dup.merchantOrderId}</b> — no new order was created.{' '}
            <Link className="font-medium underline" to={`/orders/${dup.id}/rates`}>Continue with {dup.id}</Link>
          </div>)}
        <form onSubmit={submit} className="grid grid-cols-2 gap-4 md:grid-cols-4">
          <L label="Merchant ID" span="md:col-span-2"><input className={field} value={f.merchantId} onChange={set('merchantId')} required /></L>
          <L label="Merchant order ID" span="md:col-span-2"><input className={field} value={f.merchantOrderId} onChange={set('merchantOrderId')} /></L>
          <L label="Customer name" span="md:col-span-2"><input className={field} value={f.customerName} onChange={set('customerName')} required /></L>
          <L label="Phone" span="md:col-span-2"><input className={field} value={f.phone} onChange={set('phone')} /></L>
          <L label="Delivery address" span="col-span-2 md:col-span-4"><input className={field} value={f.address} onChange={set('address')} /></L>
          <L label="Pickup pincode" span="md:col-span-2"><input className={field} value={f.pickupPincode} onChange={set('pickupPincode')} /></L>
          <L label="Delivery pincode" span="md:col-span-2"><input className={field} value={f.deliveryPincode} onChange={set('deliveryPincode')} /></L>
          <L label="Weight (g)"><input className={field} type="number" value={f.weightGrams} onChange={set('weightGrams')} /></L>
          <L label="Length (cm)"><input className={field} type="number" value={f.lengthCm} onChange={set('lengthCm')} /></L>
          <L label="Width (cm)"><input className={field} type="number" value={f.widthCm} onChange={set('widthCm')} /></L>
          <L label="Height (cm)"><input className={field} type="number" value={f.heightCm} onChange={set('heightCm')} /></L>
          <L label="Payment" span="md:col-span-2"><select className={field} value={f.paymentMode} onChange={set('paymentMode')}><option>COD</option><option>PREPAID</option></select></L>
          {f.paymentMode === 'COD' && <L label="COD amount (₹)" span="md:col-span-2"><input className={field} type="number" value={f.codAmount} onChange={set('codAmount')} /></L>}
          <div className="col-span-2 md:col-span-4"><Btn type="submit" disabled={busy}>{busy ? 'Creating…' : 'Create order & get rates'}</Btn></div>
        </form>
      </Card>
    </>
  )
}
