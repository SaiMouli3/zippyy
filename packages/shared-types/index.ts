// API contract types shared by the web app. They mirror the Go domain/JSON shapes in apps/api (docs/openapi.yaml).

export type Role = 'SELLER' | 'OPS' | ''

export type ShipmentStatus =
  | 'SHIPMENT_CREATED' | 'PICKED_UP' | 'IN_TRANSIT' | 'OUT_FOR_DELIVERY' | 'DELIVERED' | 'DELIVERY_FAILED' | 'RTO'

export type OrderStatus = 'ORDER_CREATED' | 'RATES_FETCHED' | 'CARRIER_SELECTED' | ShipmentStatus

export type CarrierCode = 'FASTSHIP' | 'QUICKEXPRESS' | 'RELIABLE'

export interface Address { addressLine1: string; addressLine2?: string; city: string; state: string; pincode: string }

export interface Order {
  id: string
  orderId: string
  merchantId: string
  merchantOrderId: string
  customer: { name: string; phone: string; email?: string }
  pickupAddress: Address
  deliveryAddress: Address
  package: { weightGrams: number; lengthCm: number; widthCm: number; heightCm: number }
  paymentType: 'COD' | 'PREPAID'
  codAmount: number
  language?: string
  status: OrderStatus
  selectedCarrierCode?: CarrierCode
  selectedServiceCode?: string
  quotedAmount?: number
  selectedAt?: string
  ratesFetchedAt?: string
  createdAt: string
  updatedAt: string
}

export interface CreateOrderRequest {
  merchantOrderId: string
  merchantId: string
  customer: { name: string; phone: string; email?: string }
  pickupAddress: Address
  deliveryAddress: Address
  package: { weightGrams: number; lengthCm: number; widthCm: number; heightCm: number }
  paymentType: 'COD' | 'PREPAID'
  codAmount: number
  language?: string
}

export interface CreateOrderResponse { id: string; orderId: string; merchantOrderId: string; status: string; createdAt: string }

export interface Quote {
  carrierCode: CarrierCode
  carrierName: string
  serviceCode: string
  serviceName: string
  baseCharge: number
  codCharge: number
  additionalCharges: number
  tax: number
  totalCharge: number
  estimatedMinDays: number
  estimatedMaxDays: number
  quoteReference: string | null
}

export interface FailedCarrier { carrierCode: string; reason: 'TIMEOUT' | 'HTTP_ERROR' | 'MALFORMED_RESPONSE' | 'UNAVAILABLE'; message: string }

export interface RatesResponse {
  orderId: string
  complete: boolean
  shippingOptions: Quote[]
  failedCarriers: FailedCarrier[]
  cached: boolean
  fetchedAt?: string
  expiresAt?: string
  expired: boolean
}

export interface Shipment {
  id: string
  orderId: string
  zippyOrderId: string
  carrierCode: CarrierCode
  carrierShipmentId: string
  trackingNumber: string
  serviceCode: string
  quotedAmount: number
  currentStatus: ShipmentStatus
  labelUrl?: string
  createdAt: string
  updatedAt: string
}

export interface ShipmentEvent {
  id: string
  carrierCode: string
  carrierStatus: string
  status: ShipmentStatus
  description: string
  location: string
  eventTime: string
  receivedAt: string
  ndrReasonCode?: string
  ndrRemark?: string
}

export interface TimelineEntry { status: string; label: string; at: string; description?: string; location?: string; source: string }

export interface Tracking {
  order: Order
  shipment: Shipment | null
  carrier?: { code: string; name: string; service: string }
  trackingNumber?: string
  currentStatus: string
  history: ShipmentEvent[]
  timeline: TimelineEntry[]
  ndrCases: NdrCase[]
}

export type NdrReason =
  | 'CUST_UNAVAILABLE' | 'CUST_REFUSED' | 'ADDRESS_ISSUE' | 'PHONE_UNREACHABLE' | 'COD_NOT_READY'
  | 'FUTURE_DELIVERY' | 'ACCESS_RESTRICTED' | 'OUT_OF_AREA' | 'SUSPECT_FALSE_ATTEMPT'

export type CaseState =
  | 'OPENED' | 'BUYER_CONTACT_PENDING' | 'BUYER_RESPONDED' | 'INTENT_EXTRACTED' | 'AWAITING_APPROVAL' | 'ACTION_PENDING'
  | 'ACTION_SUBMITTED' | 'CARRIER_ACCEPTED' | 'REATTEMPT_SCHEDULED' | 'RESOLVED' | 'ESCALATED' | 'RTO_INITIATED' | 'CLOSED'

export interface ExtractedIntent {
  intent: string
  preferredDate: string | null
  preferredTimeStart: string | null
  preferredTimeEnd: string | null
  landmark: string | null
  specialInstruction: string | null
  newPincode?: string | null
  newCity?: string | null
  newPhone?: string | null
  confidence: number
  detectedLanguage: string
  languageConfidence: number
  internalSummary: string
}

export interface NdrCase {
  id: string
  caseNumber: string
  shipmentId: string
  orderUuid: string
  orderId: string
  merchantId: string
  trackingNumber: string
  attemptNumber: number
  carrierCode: CarrierCode
  carrierReasonCode: string
  carrierRemark: string
  normalizedReason: NdrReason
  reasonSource: string
  language: string
  languageSource: 'reply' | 'stored' | 'seller' | 'pincode'
  buyerIntent: ExtractedIntent | null
  recommendedAction: string
  actualAction: string
  state: CaseState
  outcome: string
  pending: { type: string } | null
  plan: unknown
  contactAttempts: number
  contactExhausted: boolean
  lastContactedAt: string | null
  openedAt: string
  updatedAt: string
  closedAt: string | null
  customerName: string
}

export interface Message {
  id: string
  direction: 'INBOUND' | 'OUTBOUND'
  senderType: string
  channel: string
  language: string
  originalText: string
  internalText?: string
  interpretation?: ExtractedIntent
  deliveryStatus: string
  createdAt: string
}

export interface NdrEvent { id: string; eventType: string; actor: string; actorType: string; description: string; data?: Record<string, unknown>; createdAt: string }
export interface CommAttempt { id: string; channel: string; status: string; error?: string; createdAt: string }

export interface CarrierAction {
  id: string
  carrierCode: string
  actionType: string
  status: 'PENDING' | 'ACCEPTED' | 'REJECTED' | 'FAILED'
  carrierReference?: string
  reason?: string
  payload: Record<string, unknown>
  createdAt: string
  respondedAt?: string
}

export interface Approval {
  id: string
  caseId: string
  caseNumber: string
  orderId: string
  trackingNumber: string
  carrierCode: string
  kind: string
  proposedAction: Array<Record<string, unknown>>
  buyerRequest: string
  reason: string
  evidence: Record<string, unknown>
  requiredRoles: string[]
  grantedRoles: string[]
  blocking: boolean
  status: 'PENDING' | 'APPROVED' | 'REJECTED' | 'EXPIRED'
  decidedBy?: string
  decisionNote?: string
  createdAt: string
  decidedAt?: string
}

export interface SellerRules {
  merchantId: string
  maxAttempts: number
  autoRtoAttempt: number
  codLimit: number
  allowedChannels: string[]
  commHoursStart: string
  commHoursEnd: string
  enforceCommHours: boolean
  prepaidConversionAllowed: boolean
  allowAddressChanges: boolean
  earlyRtoPolicy: 'AUTO' | 'APPROVAL' | 'DISALLOWED'
  allowedActions: string[]
  defaultOnSilence: 'RTO' | 'ESCALATE'
  buyerResponseTimeoutMinutes: number
  sellerResponseTimeoutMinutes: number
}

export interface CarrierRules {
  carrierCode: CarrierCode
  maxAttempts: number
  instructionCutoff: string
  holdWindowDays: number
  supportedActions: string[]
  supportsTimeSlot: boolean
  canChangePaymentMode: boolean
  canChangeAddress: boolean
  canChangePhone: boolean
}

export interface RuleCheck { rule: string; passed: boolean; detail: string }

export interface CaseDetail {
  case: NdrCase
  order: Order
  shipment: Shipment
  messages: Message[]
  events: NdrEvent[]
  communicationAttempts: CommAttempt[]
  carrierActions: CarrierAction[]
  approvals: Approval[]
  sellerRules: SellerRules
  carrierRules: CarrierRules
  nextSteps: string[]
}

export interface AuditRecord {
  id: number
  actor: string
  actorType: string
  action: string
  orderId?: string
  shipmentId?: string
  ndrCaseId?: string
  caseNumber?: string
  previousState?: string
  newState?: string
  evidence?: unknown
  requestPayload?: unknown
  responsePayload?: unknown
  requestId?: string
  createdAt: string
}

export interface Bucket { key: string; count: number }
export interface Dashboard {
  orders: number
  shipments: number
  delivered: number
  inTransit: number
  ndr: number
  rto: number
  openNdrCases: number
  openApprovals: number
  totalNdrCases: number
  recoveredCases: number
  recoveryRate: number
  ndrByReason: Bucket[]
  ndrByCarrier: Bucket[]
  ndrRecovery: Bucket[]
  rtoTrend: Array<{ day: string; rto: number; ndr: number }>
  languageResponse: Array<{ language: string; contacted: number; responded: number; rate: number }>
}

export interface ApiErrorBody { error: { code: string; message: string; requestId?: string; details?: Record<string, unknown> } }

export interface TriggerResponse {
  carrier: string
  trackingNumber: string
  event: string
  payload: Record<string, unknown>
  deliveries: Array<{ url: string; status: number; body?: unknown; error?: string }>
}
