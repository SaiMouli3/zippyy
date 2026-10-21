import type { Metadata } from "next";

import { AgentConfigView } from "./view";

export const metadata: Metadata = { title: "Agent config" };

export default function Page() {
  return <AgentConfigView />;
}
