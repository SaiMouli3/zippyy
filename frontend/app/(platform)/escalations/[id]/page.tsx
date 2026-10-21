import type { Metadata } from "next";

import { EscalationView } from "./view";

export const metadata: Metadata = { title: "Escalation" };

export default function Page() {
  return <EscalationView />;
}
