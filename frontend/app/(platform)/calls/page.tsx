import type { Metadata } from "next";
import { Suspense } from "react";

import { CallsView } from "./view";

export const metadata: Metadata = { title: "Voice calls" };

export default function Page() {
  return <Suspense><CallsView /></Suspense>;
}
