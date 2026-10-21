import type { Metadata } from "next";
import { Suspense } from "react";

import { AuditView } from "./view";

export const metadata: Metadata = { title: "Audit log" };

export default function Page() {
  return <Suspense><AuditView /></Suspense>;
}
