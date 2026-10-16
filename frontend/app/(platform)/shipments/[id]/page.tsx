import type { Metadata } from "next";

import { ShipmentView } from "./view";

export const metadata: Metadata = { title: "Shipment" };

export default function Page() {
  return <ShipmentView />;
}
