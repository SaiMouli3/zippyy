export class ApiError extends Error {
  status: number
  body: any
  constructor(message: string, status: number, body: any) {
    super(message)
    this.status = status
    this.body = body
  }
}

export async function api<T = any>(path: string, method = 'GET', body?: unknown): Promise<T> {
  const res = await fetch(path, {
    method,
    headers: body ? { 'Content-Type': 'application/json' } : undefined,
    body: body ? JSON.stringify(body) : undefined,
  })
  const data = await res.json().catch(() => null)
  if (!res.ok) {
    const msg = data?.error ?? (Array.isArray(data?.detail) ? data.detail.map((d: any) => `${d.loc?.slice(-1)}: ${d.msg}`).join('; ') : res.statusText)
    throw new ApiError(msg, res.status, data)
  }
  return data as T
}

export interface Rate {
  carrier: string; carrierName: string; service: string; serviceName: string
  price: number; etaMinDays: number; etaMaxDays: number
}
export interface Message { id: number; sender: 'BUYER' | 'AGENT'; message: string; timestamp: string }
export interface NdrDetail {
  id: string; orderId: string; reason: string; attemptNumber: number; status: string
  customerName: string; phone: string; address: string; deliveryPincode: string
  paymentMode: string; codAmount: number
  carrier: string; service: string; trackingNumber: string; shipmentStatus: string
  lastIntent: null | { intent: string; date?: string; time?: string; timeWindow?: string; pincode?: string; confidence: number }
  lastDecision: null | { outcome: string; reasons: string[]; requestedDate?: string; requestedWindow?: string }
  messages: Message[]
  actions: { id: number; actionType: string; status: string; request: any; response: any; createdAt: string }[]
  audit: { event: string; details: any; createdAt: string }[]
}
