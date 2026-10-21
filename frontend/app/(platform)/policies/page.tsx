import type { Metadata } from "next";

import { PoliciesView } from "./view";

export const metadata: Metadata = { title: "Contact policy" };

export default function Page() {
  return <PoliciesView />;
}
