import type { Metadata } from "next";

import { CaseView } from "./view";

export const metadata: Metadata = { title: "NDR case" };

export default function Page() {
  return <CaseView />;
}
