import { useEffect, useMemo, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ArrowDown, ArrowUp, Check, RefreshCw, Timer } from 'lucide-react'
import type { Quote, RatesResponse } from '@zippy/shared-types'
import { api } from '@/lib/api'
import { Badge, Banner, Button, Card, ErrorBanner, PageHeader, Spinner, Table, Td, Th } from '@/components/ui'
import { bestValue, carrierName, days, money } from '@/lib/format'

type SortKey = 'price' | 'eta' | 'carrier'

function useCountdown(expiresAt?: string) {
  const [now, setNow] = useState(Date.now())
  useEffect(() => { const t = setInterval(() => setNow(Date.now()), 1000); return () => clearInterval(t) }, [])
  if (!expiresAt) return null
  const ms = new Date(expiresAt).getTime() - now
  if (ms <= 0) return 'expired'
  const s = Math.floor(ms / 1000)
  return `${Math.floor(s / 60)}m ${String(s % 60).padStart(2, '0')}s`
}

export default function ShippingOptions() {
  const { orderId = '' } = useParams()
  const nav = useNavigate()
  const qc = useQueryClient()
  const [sort, setSort] = useState<{ key: SortKey; dir: 1 | -1 }>({ key: 'price', dir: 1 })
  const [selected, setSelected] = useState<string | null>(null)

  const order = useQuery({ queryKey: ['order', orderId], queryFn: () => api.order(orderId) })
  const rates = useQuery({ queryKey: ['rates', orderId], queryFn: () => api.fetchRates(orderId, false), staleTime: 60_000 })
  const refresh = useMutation({ mutationFn: () => api.fetchRates(orderId, true), onSuccess: r => { qc.setQueryData(['rates', orderId], r); setSelected(null) } })
  const select = useMutation({
    mutationFn: (q: Quote) => api.selectCarrier(orderId, { carrierCode: q.carrierCode, serviceCode: q.serviceCode, quotedAmount: q.totalCharge, quoteReference: q.quoteReference }),
    onSuccess: (_r, q) => { setSelected(q.carrierCode + ':' + q.serviceCode); qc.invalidateQueries({ queryKey: ['order', orderId] }) },
  })
  const ship = useMutation({ mutationFn: () => api.createShipment(orderId), onSuccess: () => nav(`/orders/${orderId}/tracking`) })
  const data: RatesResponse | undefined = rates.data
  const countdown = useCountdown(data?.expiresAt)
  const expired = countdown === 'expired'

  const rows = useMemo(() => {
    const list = [...(data?.shippingOptions ?? [])]
    const cmp: Record<SortKey, (a: Quote, b: Quote) => number> = {
      price: (a, b) => a.totalCharge - b.totalCharge,
      eta: (a, b) => a.estimatedMinDays - b.estimatedMinDays || a.estimatedMaxDays - b.estimatedMaxDays || a.totalCharge - b.totalCharge,
      carrier: (a, b) => a.carrierName.localeCompare(b.carrierName) || a.totalCharge - b.totalCharge,
    }
    return list.sort((a, b) => cmp[sort.key](a, b) * sort.dir)
  }, [data, sort])
  const cheapest = data ? [...data.shippingOptions].sort((a, b) => a.totalCharge - b.totalCharge)[0] : undefined
  const fastest = data ? [...data.shippingOptions].sort((a, b) => a.estimatedMinDays - b.estimatedMinDays || a.totalCharge - b.totalCharge)[0] : undefined
  const best = data ? bestValue(data.shippingOptions) : undefined
  const sameQ = (a?: Quote, b?: Quote) => !!a && !!b && a.carrierCode === b.carrierCode && a.serviceCode === b.serviceCode
  const alreadySelected = order.data?.selectedCarrierCode ? order.data.selectedCarrierCode + ':' + order.data.selectedServiceCode : selected

  const SortTh = ({ k, children, right }: { k: SortKey; children: string; right?: boolean }) => (
    <Th right={right}>
      <button className="inline-flex items-center gap-1 uppercase" onClick={() => setSort(s => ({ key: k, dir: s.key === k ? (s.dir === 1 ? -1 : 1) : 1 }))} aria-label={`Sort by ${children}`}>
        {children}{sort.key === k && (sort.dir === 1 ? <ArrowUp className="h-3 w-3" /> : <ArrowDown className="h-3 w-3" />)}
      </button>
    </Th>
  )

  return (
    <>
      <PageHeader title="Shipping options" crumbs={<Link to={`/orders/${orderId}`} className="text-brand">{orderId}</Link>}
        subtitle={order.data ? `${order.data.pickupAddress.pincode} → ${order.data.deliveryAddress.pincode} · ${order.data.package.weightGrams} g · ${order.data.paymentType}${order.data.paymentType === 'COD' ? ' ' + money(order.data.codAmount) : ''}` : undefined}
        actions={<Button onClick={() => refresh.mutate()} loading={refresh.isPending}><RefreshCw className="h-4 w-4" /> Refresh rates</Button>} />
      <div className="space-y-3">
        <ErrorBanner error={rates.error ?? refresh.error ?? select.error ?? ship.error} />
        {rates.isLoading && <Spinner label="Asking carriers for rates…" />}
        {data && data.failedCarriers.length > 0 && (
          <Banner tone="warn" title={`${data.failedCarriers.length} carrier${data.failedCarriers.length > 1 ? 's' : ''} did not return a quote`}>
            {data.failedCarriers.map(f => `${carrierName(f.carrierCode)}: ${f.reason.replace(/_/g, ' ').toLowerCase()}`).join(' · ')}. Available options are still shown — refresh to retry.
          </Banner>
        )}
        {data && (
          <div className="flex flex-wrap items-center gap-3 text-xs text-muted">
            <Badge tone={data.cached ? 'info' : 'neutral'}>{data.cached ? 'Served from cache' : 'Fresh from carriers'}</Badge>
            {!data.complete && <Badge tone="warn">Partial result (short cache)</Badge>}
            <span className="inline-flex items-center gap-1"><Timer className="h-3.5 w-3.5" /> Quotes valid for <b className={expired ? 'text-bad' : 'text-ink'}>{countdown}</b></span>
          </div>
        )}
        {expired && <Banner tone="bad" title="These quotes have expired">Refresh rates to get a valid quote set. The server rejects selection of expired quotes.</Banner>}

        {data && (
          <Card pad={false}>
            <Table>
              <thead><tr>
                <SortTh k="carrier">Carrier</SortTh><Th>Service</Th><Th right>Base</Th><Th right>COD</Th><Th right>Other</Th><Th right>Tax</Th>
                <SortTh k="price" right>Total</SortTh><SortTh k="eta">ETA</SortTh><Th className="text-right">Action</Th>
              </tr></thead>
              <tbody>
                {rows.map(q => {
                  const key = q.carrierCode + ':' + q.serviceCode
                  const isSel = alreadySelected === key
                  return (
                    <tr key={key} className={isSel ? 'bg-brandsoft' : 'hover:bg-surface2'}>
                      <Td><div className="font-medium">{carrierName(q.carrierCode)}</div></Td>
                      <Td>
                        <div>{q.serviceName}</div>
                        <div className="mt-1 flex flex-wrap gap-1">
                          {sameQ(q, cheapest) && <Badge tone="ok">Cheapest</Badge>}
                          {sameQ(q, fastest) && <Badge tone="info">Fastest</Badge>}
                          {sameQ(q, best) && <Badge tone="violet">Best value</Badge>}
                        </div>
                      </Td>
                      <Td right>{money(q.baseCharge)}</Td><Td right>{money(q.codCharge)}</Td><Td right>{money(q.additionalCharges)}</Td><Td right>{money(q.tax)}</Td>
                      <Td right className="font-semibold">{money(q.totalCharge)}</Td>
                      <Td>{days(q.estimatedMinDays, q.estimatedMaxDays)}</Td>
                      <Td right>
                        {isSel ? <Badge tone="brand"><Check className="h-3 w-3" /> Selected</Badge>
                          : <Button variant="primary" disabled={expired || select.isPending || !!order.data?.selectedCarrierCode && order.data.status !== 'CARRIER_SELECTED' && order.data.status !== 'RATES_FETCHED'}
                              loading={select.isPending && select.variables === q} onClick={() => select.mutate(q)}>Select</Button>}
                      </Td>
                    </tr>
                  )
                })}
              </tbody>
            </Table>
          </Card>
        )}

        {alreadySelected && (
          <Card>
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div>
                <div className="text-sm font-medium">Carrier selected: {carrierName(alreadySelected.split(':')[0])} · {alreadySelected.split(':')[1]}</div>
                <div className="text-sm text-ink2">The quoted amount {money(order.data?.quotedAmount)} is now locked to this order; the server never recalculates it.</div>
              </div>
              <Button variant="primary" loading={ship.isPending} onClick={() => ship.mutate()}>Create shipment</Button>
            </div>
          </Card>
        )}
        <p className="text-xs text-muted">Highlights (cheapest / fastest / best value) are advisory. Every selection is re-validated by the backend against the stored quote — price, quote reference and expiry.</p>
      </div>
    </>
  )
}
