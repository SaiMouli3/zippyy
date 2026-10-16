import type { Metadata } from "next";
import { Suspense } from "react";

import { PreDeliveryView } from "./view";

export const metadata: Metadata = { title: "Pre-delivery" };

export default function Page() {
  return <Suspense><PreDeliveryView /></Suspense>;
}
