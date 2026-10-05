import { useState } from 'react'
import { useForm, type FieldErrors, type UseFormRegister } from 'react-hook-form'
import { zodResolver } from '@hookform/resolvers/zod'
import { z } from 'zod'
import { Link, useNavigate } from 'react-router-dom'
import { useMutation } from '@tanstack/react-query'
import { CheckCircle2, Wand2 } from 'lucide-react'
import { api, ApiError } from '@/lib/api'
import { Banner, Button, Card, ErrorBanner, Field, inputCls, PageHeader } from '@/components/ui'

const phone = z.string().regex(/^[6-9]\d{9}$/, 'Enter a valid 10-digit Indian mobile number')
const pincode = z.string().regex(/^[1-9]\d{5}$/, 'Enter a valid 6-digit pincode')
const num = (label: string) => z.coerce.number({ message: `${label} is required` }).positive(`${label} must be greater than zero`)
const address = z.object({
  addressLine1: z.string().trim().min(1, 'Address is required'), addressLine2: z.string().optional(),
  city: z.string().trim().min(1, 'City is required'), state: z.string().trim().min(1, 'State is required'), pincode,
})

// Mirrors the backend validation so users get instant feedback; the API remains the source of truth.
export const orderSchema = z.object({
  merchantId: z.string().trim().min(1, 'Merchant is required'),
  merchantOrderId: z.string().trim().min(1, 'Merchant order id is required'),
  customer: z.object({ name: z.string().trim().min(1, 'Name is required'), phone, email: z.string().email('Invalid email').or(z.literal('')).optional() }),
  pickupAddress: address,
  deliveryAddress: address,
  package: z.object({ weightGrams: num('Weight'), lengthCm: num('Length'), widthCm: num('Width'), heightCm: num('Height') }),
  paymentType: z.enum(['COD', 'PREPAID']),
  codAmount: z.coerce.number({ message: 'Enter an amount' }).min(0),
  language: z.string().optional(),
}).superRefine((v, ctx) => {
  if (v.paymentType === 'COD' && !(v.codAmount > 0)) ctx.addIssue({ code: 'custom', path: ['codAmount'], message: 'COD amount must be greater than zero' })
})
type Form = z.input<typeof orderSchema>

const demo = (): Form => ({
  merchantId: 'MRC-100', merchantOrderId: 'MERCHANT-10001',
  customer: { name: 'Rahul Sharma', phone: '9876543210', email: 'rahul@example.com' },
  pickupAddress: { addressLine1: '15 MG Road', addressLine2: '', city: 'Bengaluru', state: 'Karnataka', pincode: '560001' },
  deliveryAddress: { addressLine1: '22 Connaught Place', addressLine2: '', city: 'New Delhi', state: 'Delhi', pincode: '110001' },
  package: { weightGrams: 1500, lengthCm: 20, widthCm: 15, heightCm: 10 }, paymentType: 'COD', codAmount: 2500, language: '',
})

function AddressFields({ prefix, register, errors }: { prefix: 'pickupAddress' | 'deliveryAddress'; register: UseFormRegister<Form>; errors: FieldErrors<Form> }) {
  const e = errors[prefix]
  return (
    <div className="grid gap-3 sm:grid-cols-6">
      <Field className="sm:col-span-4" label="Address line 1" error={e?.addressLine1?.message}><input className={inputCls} {...register(`${prefix}.addressLine1`)} /></Field>
      <Field className="sm:col-span-2" label="Pincode" error={e?.pincode?.message}><input className={inputCls} inputMode="numeric" maxLength={6} {...register(`${prefix}.pincode`)} /></Field>
      <Field className="sm:col-span-2" label="City" error={e?.city?.message}><input className={inputCls} {...register(`${prefix}.city`)} /></Field>
      <Field className="sm:col-span-2" label="State" error={e?.state?.message}><input className={inputCls} {...register(`${prefix}.state`)} /></Field>
      <Field className="sm:col-span-2" label="Line 2 / landmark (optional)"><input className={inputCls} {...register(`${prefix}.addressLine2`)} /></Field>
    </div>
  )
}

export default function CreateOrder() {
  const nav = useNavigate()
  const [created, setCreated] = useState<{ orderId: string; merchantOrderId: string } | null>(null)
  const { register, handleSubmit, watch, reset, formState: { errors } } = useForm<Form>({
    resolver: zodResolver(orderSchema),
    defaultValues: { merchantId: 'MRC-100', paymentType: 'COD', codAmount: 0, language: '', pickupAddress: { state: 'Karnataka', city: 'Bengaluru' } } as Form,
  })
  const payment = watch('paymentType')
  const m = useMutation({
    mutationFn: (v: z.output<typeof orderSchema>) => api.createOrder({
      ...v, language: v.language || undefined, customer: { ...v.customer, email: v.customer.email || undefined },
      codAmount: v.paymentType === 'PREPAID' ? 0 : v.codAmount,
    }),
    onSuccess: r => setCreated({ orderId: r.orderId, merchantOrderId: r.merchantOrderId }),
  })
  const dupe = m.error instanceof ApiError && m.error.code === 'DUPLICATE_ORDER' ? (m.error.details?.orderId as string) : undefined

  if (created) {
    return (
      <>
        <PageHeader title="Order created" />
        <Card>
          <div className="flex items-start gap-3">
            <CheckCircle2 className="mt-0.5 h-5 w-5 text-ok" aria-hidden />
            <div className="flex-1">
              <div className="font-medium">{created.orderId} <span className="text-muted">· {created.merchantOrderId}</span></div>
              <p className="mt-1 text-sm text-ink2">Status <b>ORDER_CREATED</b>. Next, ask the three carriers for rates and compare them.</p>
              <div className="mt-4 flex gap-2">
                <Button variant="primary" onClick={() => nav(`/orders/${created.orderId}/rates`)}>Get shipping rates</Button>
                <Link to={`/orders/${created.orderId}`}><Button>View order</Button></Link>
                <Button variant="ghost" onClick={() => { setCreated(null); m.reset() }}>Create another</Button>
              </div>
            </div>
          </div>
        </Card>
      </>
    )
  }

  return (
    <>
      <PageHeader title="Create order" subtitle="Capture the merchant order. Duplicate merchant order ids are rejected by the backend."
        actions={<Button onClick={() => reset(demo())} type="button"><Wand2 className="h-4 w-4" /> Fill demo data</Button>} />
      <form onSubmit={handleSubmit(v => m.mutate(v as z.output<typeof orderSchema>))} noValidate className="space-y-4">
        <ErrorBanner error={dupe ? undefined : m.error} />
        {dupe && <Banner tone="warn" title="This merchant order already exists">It was not created again. <Link className="text-brand underline" to={`/orders/${dupe}`}>Open {dupe}</Link> or change the merchant order id.</Banner>}
        <Card title="Merchant & customer">
          <div className="grid gap-3 sm:grid-cols-6">
            <Field className="sm:col-span-2" label="Merchant id" error={errors.merchantId?.message}><input className={inputCls} {...register('merchantId')} /></Field>
            <Field className="sm:col-span-2" label="Merchant order id" error={errors.merchantOrderId?.message}><input className={inputCls} {...register('merchantOrderId')} placeholder="MERCHANT-10001" /></Field>
            <Field className="sm:col-span-2" label="Order language (seller, optional)" hint="Used as the NDR conversation language unless the buyer has a stored preference">
              <select className={inputCls} {...register('language')}>
                <option value="">Not set (use pincode default)</option>
                <option value="en">English</option><option value="hi">Hindi</option><option value="te">Telugu</option><option value="ta">Tamil</option><option value="kn">Kannada</option>
              </select>
            </Field>
            <Field className="sm:col-span-2" label="Customer name" error={errors.customer?.name?.message}><input className={inputCls} {...register('customer.name')} /></Field>
            <Field className="sm:col-span-2" label="Mobile" error={errors.customer?.phone?.message}><input className={inputCls} inputMode="tel" maxLength={10} {...register('customer.phone')} /></Field>
            <Field className="sm:col-span-2" label="Email (optional)" error={errors.customer?.email?.message}><input className={inputCls} type="email" {...register('customer.email')} /></Field>
          </div>
        </Card>
        <Card title="Pickup address"><AddressFields prefix="pickupAddress" register={register} errors={errors} /></Card>
        <Card title="Delivery address"><AddressFields prefix="deliveryAddress" register={register} errors={errors} /></Card>
        <Card title="Package">
          <div className="grid gap-3 sm:grid-cols-4">
            <Field label="Weight (grams)" error={errors.package?.weightGrams?.message}><input className={inputCls} inputMode="numeric" {...register('package.weightGrams')} /></Field>
            <Field label="Length (cm)" error={errors.package?.lengthCm?.message}><input className={inputCls} inputMode="decimal" {...register('package.lengthCm')} /></Field>
            <Field label="Width (cm)" error={errors.package?.widthCm?.message}><input className={inputCls} inputMode="decimal" {...register('package.widthCm')} /></Field>
            <Field label="Height (cm)" error={errors.package?.heightCm?.message}><input className={inputCls} inputMode="decimal" {...register('package.heightCm')} /></Field>
          </div>
        </Card>
        <Card title="Payment">
          <div className="grid gap-3 sm:grid-cols-4">
            <Field label="Payment type"><select className={inputCls} {...register('paymentType')}><option value="COD">Cash on delivery</option><option value="PREPAID">Prepaid</option></select></Field>
            {payment === 'COD' && <Field label="COD amount (₹)" error={errors.codAmount?.message}><input className={inputCls} inputMode="decimal" {...register('codAmount')} /></Field>}
          </div>
        </Card>
        <div className="flex justify-end gap-2"><Button type="submit" variant="primary" loading={m.isPending}>Create order</Button></div>
      </form>
    </>
  )
}
