import type { Metadata } from "next";
import { Suspense } from "react";

import { EscalationsView } from "./view";

export const metadata: Metadata = { title: "Escalations" };

export default function Page() {
  return <Suspense><EscalationsView /></Suspense>;
}
