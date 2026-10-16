// Response shapes of the v1 API (backend/app/platform/api). Keep in sync with the serializers there.

export interface Metric {
  value: number | null; unit: "count" | "paise"; basis: "measured" | "unavailable"; href: string | null; note: string | null;
  previous?: number; numerator?: number; denominator?: number;
}
export interface Summary {
  range: { start: string; end: string; label: string };
  comparisonAvailable: boolean;
  metrics: Record<string, Metric>;
  generatedAt: string;
}
export interface TrendPoint {
  date: string; ndrOpened: number; ndrResolved: number; recovered: number; recoveryRate: number | null;
  preDeliveryStarted: number; preDeliveryConfirmed: number; preDeliveryRate: number | null;
}
export interface Trends { series: TrendPoint[]; dayBasis: string; definitions: Record<string, string>; generatedAt: string }
export interface QueueItem { id: string; code: string; customerName: string | null; reason: string; carrier: string; slaDueAt: string | null; status: string; pendingAction: string | null }
export interface Queues { queues: Record<string, { total: number; items: QueueItem[] }>; generatedAt: string }

export interface NdrRow {
  id: string; code: string; orderRef: string | null; shipmentId: string; awb: string | null; merchant: string;
  customerName: string | null; phoneMasked: string | null; city: string | null; state: string | null; pincode: string | null;
  carrier: string; paymentMode: string | null; codAmountPaise: number | null; shipmentStatus: string | null; status: string;
  reason: string; carrierReason: string | null; attempts: number; languagePredicted: string | null; languageConfirmed: string | null;
  preferredDate: string | null; preferredWindow: string | null; whatsappStatus: string | null; callOutcome: string | null;
  lastContactAt: string | null; lastContactChannel: string | null; agentStatus: string | null; pendingAction: string | null;
  slaDueAt: string | null; priority: string; recoveryOutcome: string | null; resolution: string | null;
  contactability: string | null; hasOpenEscalation: boolean; openedAt: string; updatedAt: string;
}

export interface Decision {
  id: string; verdict: string; action: string | null; requestedDate: string | null; requestedWindow: string | null;
  reasons: string[]; rules: { id: string; text: string }[]; rulesVersion: string; approvalStatus: string | null; createdAt: string;
}
export interface CarrierActionT {
  id: string; action: string; status: string; carrier: string; requestedDate: string | null; requestedWindow: string | null;
  carrierReference: string | null; rejectionReason: string | null; attempts: number; lastError: string | null;
  requestedAt: string | null; respondedAt: string | null; verifiedAt: string | null; decisionId: string | null; idempotencyKey: string;
}
export interface EscalationBrief {
  id: string; code: string; reason: string; priority: string; status: string; assignedTo: string | null; summary: string;
  slaDueAt: string | null; pendingDecisionId: string | null; createdAt: string; resolution: string | null; resolutionReason: string | null;
}
export interface CaseDetail {
  case: NdrRow;
  shipment: { id: string; code: string; awb: string; carrier: string; status: string; attempts: number; createdAt: string; dispatchedAt: string | null; etaStart: string | null; etaEnd: string | null; deliveredAt: string | null; lastEventAt: string | null };
  order: { id: string; ref: string; merchantOrderId: string; paymentMode: string; codAmountPaise: number; orderValuePaise: number | null };
  customer: { id: string; name: string; phoneMasked: string; preferredLanguage: string | null; predictedLanguage: string | null; optedOut?: boolean; [k: string]: unknown } | null;
  address: { line1?: string; city?: string; state?: string; pincode?: string; [k: string]: unknown } | null;
  courierReported: { reason: string; carrierReason: string | null; attempt: number };
  customerSupplied: { preferredDate: string | null; preferredWindow: string | null; preferenceStatus: string | null; channel: string | null; confirmedAt: string | null; languageConfirmed: string | null };
  aiInferred: { intent: string | null; confidence: number | null; extractor: string | null; validation: string | null; languagePredicted: string | null; languagePredictionSource: string | null; languagePredictionConfidence: number | null };
  decision: Decision | null;
  carrierAction: CarrierActionT | null;
  agent: { taskId: string | null; taskType: string | null; status: string | null; waitingFor: string | null; nextRunAt: string | null; timers: Record<string, string>; policyVersionId: string | null };
  escalation: EscalationBrief | null;
  isDemo: boolean;
  nextStep: string;
}
export interface TimelineItem {
  id: string; at: string; category: "shipment" | "communication" | "ai" | "carrier" | "admin"; type: string; title: string;
  source: string; actor: string; result: string | null; refs: { entity: string; id: string }; detail: Record<string, unknown>; correlationId: string | null;
}

export interface Step {
  id: string; seq: number; kind: string; purpose: string | null; tool: string | null; toolVersion: string | null; provider: string | null;
  status: string; input: unknown; output: unknown; decisionId: string | null; extractionId: string | null; carrierActionId: string | null;
  messageId: string | null; callId: string | null; policyRule: string | null; languageBefore: string | null; languageAfter: string | null;
  confidence: number | null; retryCount: number; error: string | null; startedAt: string; finishedAt: string | null; durationMs: number | null;
}
export interface Run {
  id: string; agent: string; trigger: string; status: string; taskId: string | null; ndrCaseId: string | null; shipmentId: string | null;
  correlationId: string | null; stepCount: number; hasFailures: boolean; humanInvolved: boolean; nextAction: string | null;
  nextActionAt: string | null; error: string | null; startedAt: string; finishedAt: string | null; durationMs: number | null;
  steps?: Step[]; ndrCode?: string | null;
}

export interface Intent { id: string; intent: string; confidence: number; date: string | null; window: string | null; validation?: string }
export interface MessageItem {
  id: string; kind: "message"; channel: string; direction: "inbound" | "outbound"; at: string; sender: string; body: string;
  language: string | null; languageConfidence: number | null; templateCode: string | null; templateVersion: number | null; status: string;
  statusUpdatedAt: string | null; failureReason: string | null; provider: string; providerMessageId: string | null; sentAt: string | null;
  deliveredAt: string | null; readAt: string | null; shipmentId: string | null; ndrCaseId: string | null; agentRunId: string | null; intent: Intent | null;
}
export interface CallItem {
  id: string; kind: "call"; code: string; channel: "voice"; at: string; direction: string; purpose: string; provider: string;
  providerCallId: string | null; status: string; result: string | null; providerRawStatus: string | null; scheduledFor: string | null;
  startedAt: string | null; answeredAt: string | null; endedAt: string | null; durationSeconds: number | null; startLanguage: string | null;
  finalLanguage: string | null; languageSwitchCount: number; transcriptAvailable: boolean; recordingAvailable: boolean;
  preferenceCaptured: boolean; triggeredCarrierActionId: string | null; followupScheduled: boolean; attemptNo: number; costPaise: number | null;
  errorCode: string | null; errorMessage: string | null; shipmentId: string | null; ndrCaseId: string | null; intent: Intent | null;
  customerName?: string | null; phoneMasked?: string | null; ndrCode?: string | null;
  events?: { seq: number; kind: string; status: string | null; at: string; fromLanguage: string | null; toLanguage: string | null; confidence: number | null; codeMixed: boolean | null; data: unknown }[];
}
export interface Thread {
  items: (MessageItem | CallItem)[];
  customer: { name: string; phoneMasked: string; preferredLanguage: string | null; predictedLanguage: string | null; optedOut: boolean } | null;
  generatedAt: string;
}
export interface Turn {
  seq: number; kind: "turn" | "silence" | "language_switch"; speaker: string | null; text: string | null; textEn: string | null;
  language: string | null; confidence: number | null; codeMixed: boolean | null; fromLanguage: string | null; toLanguage: string | null;
  at: string; offsetSeconds: number | null;
}
export interface Transcript { available: boolean; reason?: string; callId?: string; startLanguage?: string; finalLanguage?: string; turns: Turn[] }

export interface EscalationRow extends EscalationBrief {
  assigneeName: string | null; supervisorRequested: boolean; resolvedAt: string | null; ndrCaseId: string; ndrCode: string | null;
  shipmentId: string | null; awb: string | null; carrier: string | null; ndrReason: string | null; customerName: string | null;
}
export interface EscalationDetail extends EscalationRow {
  notes: { kind: string; body: string; author: string; at: string }[];
  pendingDecision: Decision | null;
  excerpts: { direction: string; body: string; language: string | null; at: string; status: string }[];
  calls: { id: string; code: string; status: string; result: string | null; at: string; language: string | null }[];
  attempts: number; lastCarrierResponse: CarrierActionT | null; carrierActions: CarrierActionT[]; caseSlaDueAt: string | null;
}

export interface ShipmentRow {
  id: string; code: string; awb: string; carrier: string; status: string; attempts: number; orderRef: string; paymentMode: string;
  codAmountPaise: number; orderValuePaise: number | null; customerName: string | null; phoneMasked: string | null; city: string | null;
  state: string | null; pincode: string | null; createdAt: string; lastEventAt: string | null; deliveredAt: string | null; etaEnd: string | null;
  ndrCaseId: string | null; ndrCode: string | null; ndrStatus: string | null;
  preDelivery?: { status: string; outcome: string | null } | null;
  preference?: { date: string | null; window: string | null; status: string; channel: string | null } | null;
}

export interface PolicyDoc {
  kind: string; version: number; config: Record<string, unknown>; changeNote: string | null; createdAt: string; createdBy: string | null;
  rulesVersion: string; history: { version: number; createdAt: string; changeNote: string | null; createdBy: string | null; active: boolean }[];
  schema: JsonSchema;
}
export interface JsonSchema {
  type?: string; title?: string; description?: string; properties?: Record<string, JsonSchema>; items?: JsonSchema; enum?: unknown[];
  minimum?: number; maximum?: number; exclusiveMinimum?: number; minLength?: number; maxLength?: number; default?: unknown; $ref?: string;
  $defs?: Record<string, JsonSchema>; anyOf?: JsonSchema[]; allOf?: JsonSchema[]; additionalProperties?: boolean | JsonSchema; required?: string[];
  pattern?: string; minItems?: number; maxItems?: number;
}
export interface PublishResult { dryRun: boolean; changes: Record<string, { from: unknown; to: unknown }>; version: number; applied: boolean }
