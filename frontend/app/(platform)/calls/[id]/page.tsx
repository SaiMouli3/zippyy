import type { Metadata } from "next";

import { CallView } from "./view";

export const metadata: Metadata = { title: "Voice call" };

export default function Page() {
  return <CallView />;
}
