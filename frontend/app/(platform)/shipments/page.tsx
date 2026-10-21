import type { Metadata } from "next";
import { Suspense } from "react";

import { ShipmentsView } from "./view";

export const metadata: Metadata = { title: "Shipments" };

export default function Page() {
  return <Suspense><ShipmentsView /></Suspense>;
}
