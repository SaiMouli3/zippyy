import type {
  Approval, AuditRecord, CarrierRules, CaseDetail, CreateOrderRequest, CreateOrderResponse, Dashboard, NdrCase, NdrEvent, Order,
  RatesResponse, Role, SellerRules, Shipment, Tracking, TriggerResponse, ExtractedIntent,
} from '@zippy/shared-types'

export class ApiError extends Error {
  status: number
  code: string
  details?: Record<string, unknown>
  requestId?: string
  constructor(status: number, code: string, message: string, details?: Record<string, unknown>, requestId?: string) {
    super(message)
    this.status = status
    this.code = code
    this.details = details
    this.requestId = requestId
  }
}

// The acting identity is a UI convenience (MVP has no login). The backend enforces what each role may do.
let session: { role: Role; actor: string } = { role: '', actor: '' }
export function setSession(s: { role: Role; actor: string }) { session = s }

export async function http<T>(method: string, path: string, body?: unknown, extra?: Record<string, string>): Promise<T> {
  const headers: Record<string, string> = { Accept: 'application/json', ...extra }
  if (body !== undefined) headers['Content-Type'] = 'application/json'
  if (session.role) { headers['X-Zippy-Role'] = session.role; headers['X-Zippy-Actor'] = session.actor || session.role.toLowerCase() + '-user' }
  const res = await fetch(path, { method, headers, body: body === undefined ? undefined : JSON.stringify(body) })
  const text = await res.text()
  let data: unknown = undefined
  try { data = text ? JSON.parse(text) : undefined } catch { /* non-JSON error page */ }
  if (!res.ok) {
    const e = (data as { error?: { code: string; message: string; details?: Record<string, unknown>; requestId?: string } } | undefined)?.error
    throw new ApiError(res.status, e?.code ?? 'HTTP_' + res.status, e?.message ?? (text.slice(0, 200) || res.statusText), e?.details, e?.requestId)
  }
  return data as T
}

const qs = (o: Record<string, string | boolean | undefined>) => {
  const p = new URLSearchParams()
  Object.entries(o).forEach(([k, v]) => { if (v !== undefined && v !== '' && v !== false) p.set(k, String(v)) })
  const s = p.toString()
  return s ? '?' + s : ''
}

export const api = {
  dashboard: () => http<Dashboard>('GET', '/api/dashboard'),
  orders: () => http<{ orders: Order[] }>('GET', '/api/orders'),
  order: (id: string) => http<Order>('GET', `/api/orders/${id}`),
  createOrder: (b: CreateOrderRequest) => http<CreateOrderResponse>('POST', '/api/orders', b),
  fetchRates: (id: string, refresh: boolean) => http<RatesResponse>('POST', `/api/orders/${id}/rates${qs({ refresh })}`),
  rates: (id: string) => http<RatesResponse>('GET', `/api/orders/${id}/rates`),
  selectCarrier: (id: string, b: { carrierCode: string; serviceCode: string; quotedAmount: number; quoteReference: string | null }) =>
    http<{ status: string; quotedAmount: number }>('POST', `/api/orders/${id}/select-carrier`, b),
  createShipment: (id: string) => http<Shipment>('POST', `/api/orders/${id}/shipment`),
  tracking: (id: string) => http<Tracking>('GET', `/api/orders/${id}/tracking`),
  shipments: () => http<{ shipments: Shipment[] }>('GET', '/api/shipments'),
  trigger: (carrier: string, shipmentId: string, b: { event: string; ndrReason?: string; remark?: string; duplicates?: number }) =>
    http<TriggerResponse>('POST', `/api/mock-carriers/${carrier}/shipments/${shipmentId}/trigger`, b),
  setFault: (carrier: string, b: { fault?: string; rejectActions?: boolean }) =>
    http<{ faults: Record<string, string>; rejectActions: boolean }>('POST', `/api/mock-carriers/${carrier}/faults`, b),
  mockStats: (carrier: string) => http<{ calls: Record<string, number>; faults: Record<string, string>; rejectActions: boolean }>('GET', `/api/mock-carriers/${carrier}/stats`),
  inbox: () => http<{ entries: Array<{ id: string; carrierCode: string; outcome: string; detail: string; receivedAt: string }> }>('GET', '/api/webhooks-inbox'),

  cases: (f: { state?: string; reason?: string; open?: boolean } = {}) => http<{ cases: NdrCase[] }>('GET', `/api/ndr/cases${qs(f)}`),
  caseDetail: (id: string) => http<CaseDetail>('GET', `/api/ndr/cases/${id}`),
  contact: (id: string, b: { simulateFailures?: string[] }) => http<{ delivered: boolean; deferred: boolean; exhausted: boolean; channel?: string }>('POST', `/api/ndr/cases/${id}/contact`, b),
  buyerReply: (id: string, b: { text: string; channel?: string }) =>
    http<{ intent: ExtractedIntent; decision?: { outcome: string; reason: string } }>('POST', `/api/ndr/cases/${id}/buyer-reply`, b),
  process: (id: string, trigger: string) => http<{ summary: string }>('POST', `/api/ndr/cases/${id}/process`, { trigger }),
  manualAction: (id: string, b: Record<string, unknown>) => http<unknown>('POST', `/api/ndr/cases/${id}/actions`, b),
  timeline: (id: string) => http<{ timeline: NdrEvent[] }>('GET', `/api/ndr/cases/${id}/timeline`),

  approvals: (status?: string) => http<{ approvals: Approval[] }>('GET', `/api/approvals${qs({ status })}`),
  decide: (id: string, approve: boolean, note?: string) => http<Approval>('POST', `/api/approvals/${id}/${approve ? 'approve' : 'reject'}`, { note }),

  sellerRules: () => http<{ rules: SellerRules[] }>('GET', '/api/rules/seller'),
  saveSellerRules: (r: SellerRules) => http<SellerRules>('PUT', `/api/rules/seller/${r.merchantId}`, r),
  carrierRules: () => http<{ rules: CarrierRules[] }>('GET', '/api/rules/carriers'),
  saveCarrierRules: (r: CarrierRules) => http<CarrierRules>('PUT', `/api/rules/carriers/${r.carrierCode}`, r),
  audit: (f: { actorType?: string; caseId?: string; orderId?: string; limit?: number } = {}) =>
    http<{ logs: AuditRecord[] }>('GET', `/api/audit-logs${qs({ ...f, limit: f.limit ? String(f.limit) : undefined })}`),
}
