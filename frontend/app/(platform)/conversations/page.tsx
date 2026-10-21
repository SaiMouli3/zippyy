import type { Metadata } from "next";
import { Suspense } from "react";

import { ConversationsView } from "./view";

export const metadata: Metadata = { title: "Conversations" };

export default function Page() {
  return <Suspense><ConversationsView /></Suspense>;
}
