"use client";

import { PolicyEditor } from "@/components/platform/policy-editor";

const META = {
  quiet_start: { label: "Quiet hours start", help: "No messages or calls from this time, except replies to a customer who wrote within the last 24 hours." },
  quiet_end: { label: "Quiet hours end" },
  voice_window_start: { label: "Calls allowed from", help: "Voice calls are only placed inside this window." },
  voice_window_end: { label: "Calls allowed until" },
  max_contacts_per_customer_per_day: { label: "Contacts per customer per day", help: "Counts proactive messages and calls. Replies and confirmations are not counted.", unit: "contacts" },
  max_voice_calls_per_customer_per_day: { label: "Calls per customer per day", unit: "calls" },
  max_calls_per_merchant_per_day: { label: "Calls per day, whole workspace", unit: "calls" },
  max_concurrent_calls: { label: "Simultaneous calls", unit: "calls" },
  daily_voice_budget_paise: { label: "Daily voice budget", help: "Calls stop for the day once reported spend reaches this amount." },
  require_whatsapp_consent: { label: "Require WhatsApp consent", help: "Only message customers with recorded opt-in evidence." },
  require_voice_consent: { label: "Require voice consent" },
  whatsapp_fallback_to_voice: { label: "Fall back to voice when WhatsApp fails" },
  honour_opt_out_across_channels: { label: "An opt-out on one channel stops all channels" },
  ops_failure_notifications: { label: "Notify operations about provider failures" },
};

const SECTIONS = [
  { title: "When customers can be contacted", description: "Times are in the workspace timezone set under Settings", fields: ["quiet_start", "quiet_end", "voice_window_start", "voice_window_end"] },
  { title: "Limits", fields: ["max_contacts_per_customer_per_day", "max_voice_calls_per_customer_per_day", "max_calls_per_merchant_per_day", "max_concurrent_calls", "daily_voice_budget_paise"] },
  { title: "Consent & opt-out", fields: ["require_whatsapp_consent", "require_voice_consent", "honour_opt_out_across_channels", "whatsapp_fallback_to_voice", "ops_failure_notifications"] },
];

export function PoliciesView() {
  return <PolicyEditor path="/merchant/contact-policies" kind="contact_policy" pageTitle="Contact policy" readPerm="policies.read" writePerm="policies.write"
    description="The contact guard checks every message and call against these rules before it is sent, including retries and operator-triggered contact."
    meta={META} sections={SECTIONS} />;
}
