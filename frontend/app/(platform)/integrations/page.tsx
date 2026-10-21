import type { Metadata } from "next";

import { IntegrationsView } from "./view";

export const metadata: Metadata = { title: "Integrations" };

export default function Page() {
  return <IntegrationsView />;
}
