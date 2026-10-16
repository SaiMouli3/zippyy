"use client";

import { PolicyEditor } from "@/components/platform/policy-editor";

const META = {
  agent_enabled: { label: "Agents enabled", help: "Master switch. When off, no workflow starts and nothing is sent; existing cases stay visible." },
  ndr_auto_contact: { label: "Contact customers after a failed delivery", help: "Start the NDR recovery workflow automatically when a carrier reports a failed attempt." },
  pre_delivery_enabled: { label: "Pre-delivery confirmation", help: "Ask customers whether they will be available before the delivery attempt." },
  pre_delivery_trigger: { label: "Start pre-delivery", help: "Which carrier event starts the confirmation." },
  pre_delivery_cod_only: { label: "Only for cash-on-delivery orders" },
  pre_delivery_min_order_value_paise: { label: "Minimum order value for pre-delivery" },
  channels: { label: "Contact channels", help: "WhatsApp is tried first; voice is used when WhatsApp gets no reply or cannot be delivered." },
  supported_languages: { label: "Languages for WhatsApp", help: "The agent writes only in these languages and escalates when the customer uses another." },
  voice_languages: { label: "Languages for voice", help: "Languages the voice agent may speak and switch into during a call." },
  whatsapp_reply_wait_minutes: { label: "Wait for a WhatsApp reply", unit: "minutes" },
  pre_delivery_reply_wait_minutes: { label: "Wait for a pre-delivery reply", unit: "minutes" },
  max_voice_attempts_per_case: { label: "Voice calls per case", unit: "calls" },
  voice_retry_minutes: { label: "Gaps between call attempts", help: "Comma-separated, one value per retry.", unit: "minutes" },
  max_clarifications: { label: "Clarifying questions before escalating", unit: "questions" },
  intent_confidence_threshold: { label: "Minimum confidence to act on a reply", help: "Below this, the agent asks a clarifying question instead of acting (0–1)." },
  language_switch_confidence: { label: "Confidence needed to switch language", help: "Hysteresis prevents flip-flopping on short or code-mixed turns (0–1)." },
  language_preference_save_confidence: { label: "Confidence needed to save a language preference", help: "Below this the language is used for the call but not stored as the customer's preference (0–1)." },
  max_auto_reschedule_days: { label: "Furthest automatic reschedule", unit: "days ahead" },
  max_attempts_before_rto: { label: "Delivery attempts before RTO is considered", unit: "attempts" },
  auto_actions: { label: "Actions the agent may request without approval", help: "The policy engine still checks carrier capability, dates and limits for each request." },
  approval_required_actions: { label: "Actions that always need an operator", help: "These go to the escalation inbox even when the customer asks clearly." },
  cod_high_value_approval_paise: { label: "COD value that needs approval", help: "Cash-on-delivery orders at or above this value need an operator for any carrier action." },
  sla_hours: { label: "Resolution SLA", unit: "hours from the failed attempt" },
  sla_warning_hours: { label: "Warn before the SLA", unit: "hours" },
  no_response_close_policy: { label: "When the customer never responds" },
  escalate_on_carrier_rejection: { label: "Escalate when a carrier rejects a request" },
};

const SECTIONS = [
  { title: "Automation", description: "What the agents are allowed to start on their own", fields: ["agent_enabled", "ndr_auto_contact", "pre_delivery_enabled", "pre_delivery_trigger", "pre_delivery_cod_only", "pre_delivery_min_order_value_paise"] },
  { title: "Channels & languages", fields: ["channels", "supported_languages", "voice_languages", "language_switch_confidence", "language_preference_save_confidence"] },
  { title: "Timing & retries", fields: ["whatsapp_reply_wait_minutes", "pre_delivery_reply_wait_minutes", "max_voice_attempts_per_case", "voice_retry_minutes", "max_clarifications", "sla_hours", "sla_warning_hours"] },
  { title: "Carrier actions & approvals", description: "Inputs to the deterministic policy engine. The language model never decides these.", fields: ["auto_actions", "approval_required_actions", "cod_high_value_approval_paise", "max_auto_reschedule_days", "max_attempts_before_rto", "intent_confidence_threshold", "escalate_on_carrier_rejection", "no_response_close_policy"] },
];

export function AgentConfigView() {
  return <PolicyEditor path="/merchant/agent-config" kind="agent_config" pageTitle="Agent configuration" readPerm="agent_config.read" writePerm="agent_config.write"
    description="How the delivery agents behave for this workspace. Every change is validated by the server, previewed as a diff, published as a new version and audited."
    meta={META} sections={SECTIONS} />;
}
