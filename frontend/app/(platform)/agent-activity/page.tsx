import type { Metadata } from "next";
import { Suspense } from "react";

import { AgentActivityView } from "./view";

export const metadata: Metadata = { title: "Agent activity" };

export default function Page() {
  return <Suspense><AgentActivityView /></Suspense>;
}
