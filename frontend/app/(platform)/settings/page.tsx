import type { Metadata } from "next";
import { Suspense } from "react";

import { SettingsView } from "./view";

export const metadata: Metadata = { title: "Settings" };

export default function Page() {
  return <Suspense><SettingsView /></Suspense>;
}
