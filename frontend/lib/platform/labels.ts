// One vocabulary for every screen: human labels and a restrained tone for each operational state.
// Tone is never the only signal — labels always accompany colour.
export type Tone = "neutral" | "ok" | "warn" | "danger" | "info" | "brand" | "muted";

type Entry = { label: string; tone: Tone; hint?: string };
const e = (label: string, tone: Tone, hint?: string): Entry => ({ label, tone, hint });

export const NDR_STATUS: Record<string, Entry> = {
  open: e("Open", "warn", "Failed attempt recorded; recovery not started yet"),
  contacting: e("Contacting", "info", "Agent is reaching the customer"),
  awaiting_customer: e("Awaiting customer", "info", "Message sent; waiting for a reply"),
  decided: e("Decided", "info"),
  action_requested: e("Carrier requested", "info", "A request was sent to the carrier; not yet confirmed"),
  reattempt_scheduled: e("Reattempt confirmed", "ok", "The carrier accepted a new delivery attempt"),
  escalated: e("Escalated", "danger", "Waiting for an operator"),
  rto: e("RTO in progress", "warn", "Return to origin initiated by the carrier"),
  resolved: e("Resolved", "muted"),
  closed_no_response: e("Closed – no response", "muted"),
};

export const NDR_REASON: Record<string, string> = {
  customer_unavailable: "Customer unavailable",
  customer_refused: "Customer refused",
  address_issue: "Address issue",
  phone_unreachable: "Phone unreachable",
  cod_not_ready: "COD not ready",
  other: "Other",
};

export const SHIPMENT_STATUS: Record<string, Entry> = {
  SHIPMENT_CREATED: e("Booked", "neutral"),
  PICKED_UP: e("Picked up", "neutral"),
  IN_TRANSIT: e("In transit", "neutral"),
  OUT_FOR_DELIVERY: e("Out for delivery", "info"),
  DELIVERY_FAILED: e("Delivery failed", "danger"),
  DELIVERED: e("Delivered", "ok"),
  RTO: e("RTO initiated", "warn"),
  RTO_DELIVERED: e("Returned to origin", "muted"),
  CARRIER_SELECTED: e("Carrier selected", "neutral"),
};

export const AGENT_STATUS: Record<string, Entry> = {
  not_started: e("Not started", "muted"),
  running: e("Working", "info"),
  awaiting_customer: e("Awaiting reply", "info"),
  awaiting_call: e("On a call", "info"),
  awaiting_carrier: e("Awaiting carrier", "info"),
  awaiting_delivery: e("Awaiting delivery", "ok"),
  escalated: e("With operator", "danger"),
  completed: e("Done", "muted"),
  cancelled: e("Stopped", "muted"),
  superseded: e("Superseded", "muted", "A newer delivery attempt started a new workflow"),
  failed: e("Failed", "danger"),
};

export const MESSAGE_STATUS: Record<string, Entry> = {
  queued: e("Queued", "muted", "Created; not yet handed to WhatsApp"),
  submitted: e("Submitted", "neutral", "WhatsApp accepted the request. Delivery is only confirmed by a callback"),
  sent: e("Sent", "neutral", "Provider callback: sent"),
  delivered: e("Delivered", "ok", "Provider callback: delivered to the phone"),
  read: e("Read", "ok", "Provider callback: read by the customer"),
  failed: e("Failed", "danger"),
  received: e("Received", "info"),
  blocked: e("Not sent", "warn", "Blocked by contact policy before sending"),
};

export const CALL_STATUS: Record<string, Entry> = {
  queued: e("Scheduled", "muted"),
  initiated: e("Dialling", "info"),
  ringing: e("Ringing", "info"),
  answered: e("In progress", "info"),
  completed: e("Answered", "ok"),
  no_answer: e("No answer", "warn"),
  busy: e("Busy", "warn"),
  failed: e("Failed", "danger"),
  cancelled: e("Cancelled", "muted"),
  unknown: e("Unconfirmed", "warn", "The provider has not confirmed this call"),
};

export const CALL_RESULT: Record<string, Entry> = {
  preference_captured: e("Preference captured", "ok"),
  available_confirmed: e("Availability confirmed", "ok"),
  refused: e("Refused", "warn"),
  callback_requested: e("Callback requested", "info"),
  review_needed: e("Needs review", "warn"),
  opted_out: e("Opted out", "warn"),
  no_response: e("Silent", "warn"),
  unsupported_language: e("Unsupported language", "danger"),
  unresolved: e("Not understood", "warn"),
  no_answer: e("No answer", "warn"),
  busy: e("Busy", "warn"),
  failed: e("Failed", "danger"),
};

export const ACTION_STATUS: Record<string, Entry> = {
  requested: e("Requested", "info", "Sent to the carrier; waiting for its answer"),
  accepted: e("Accepted", "ok", "The carrier confirmed it"),
  rejected: e("Rejected", "danger"),
  failed: e("Failed", "danger"),
  timed_out: e("Timed out", "danger"),
  retrying: e("Retrying", "warn"),
  completed: e("Completed", "ok", "The carrier actually made the new attempt"),
  cancelled: e("Cancelled", "muted"),
  unknown: e("Outcome unknown", "warn", "The carrier did not answer; reconciling before any retry"),
};

export const STEP_STATUS: Record<string, Entry> = {
  proposed: e("Proposed", "neutral"), validated: e("Validated", "ok"), requested: e("Requested", "info"),
  accepted: e("Accepted", "ok"), rejected: e("Rejected", "danger"), failed: e("Failed", "danger"),
  timed_out: e("Timed out", "danger"), retrying: e("Retrying", "warn"), completed: e("Completed", "ok"),
  cancelled: e("Cancelled", "muted"), skipped: e("Skipped", "muted"),
};

export const VERDICT: Record<string, Entry> = {
  ALLOWED: e("Allowed", "ok"), REQUIRES_APPROVAL: e("Needs approval", "warn"), DENIED: e("Denied", "danger"),
};

export const ESC_PRIORITY: Record<string, Entry> = {
  urgent: e("Urgent", "danger"), high: e("High", "warn"), medium: e("Medium", "info"), low: e("Low", "muted"),
};

export const ESC_REASON: Record<string, string> = {
  sla_breached: "SLA breached", no_response: "No response", rto_approval: "RTO needs approval",
  address_change: "Address change", phone_change: "Phone change", approval_required: "Approval required",
  carrier_rejected: "Carrier rejected", carrier_action_failed: "Carrier request failed",
  carrier_capability: "Carrier can't take preference", carrier_no_show: "Carrier didn't attempt",
  customer_opted_out: "Customer opted out", contact_restricted: "Contact restricted",
  suspicious_message: "Suspicious message", unsupported_language: "Unsupported language",
  low_confidence: "Unclear customer intent", policy_denied: "Policy denied", no_contact_channel: "No contact channel",
  contact_failed: "Contact failed", operator_bulk: "Operator escalation",
};

export const RECOVERY: Record<string, Entry> = {
  recovered_after_contact: e("Recovered by Zippyy", "ok", "Delivered after an NDR with evidence the customer was reached"),
  recovered_without_contact: e("Delivered (no contact)", "neutral", "Delivered, but not attributable to customer contact"),
  rto_after_contact: e("RTO after contact", "warn"),
  rto_without_contact: e("RTO", "warn"),
  first_attempt: e("First attempt", "neutral"),
  delivered: e("Delivered", "ok"), rto: e("RTO", "warn"), no_response: e("No response", "muted"),
};

export const CONTACTABILITY: Record<string, Entry> = {
  reachable: e("Reachable", "ok"), unreachable: e("Unreachable", "warn"), opted_out: e("Opted out", "danger"),
  unknown: e("Not yet", "muted"),
};

export const LANG: Record<string, string> = {
  en: "English", hi: "Hindi", te: "Telugu", ta: "Tamil", kn: "Kannada", ml: "Malayalam", mr: "Marathi",
  bn: "Bengali", gu: "Gujarati", pa: "Punjabi", or: "Odia",
};

export const CARRIERS: Record<string, string> = { FASTSHIP: "FastShip", QUICKEXPRESS: "QuickExpress", RELIABLE: "ReliableCourier" };

export function entry(map: Record<string, Entry>, key: string | null | undefined): Entry {
  if (!key) return e("—", "muted");
  return map[key] ?? e(key.replace(/_/g, " ").replace(/^\w/, (c) => c.toUpperCase()), "neutral");
}

export function title(s: string | null | undefined): string {
  if (!s) return "—";
  return s.replace(/_/g, " ").replace(/^\w/, (c) => c.toUpperCase());
}
