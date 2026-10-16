import type { Metadata } from "next";
import { Suspense } from "react";

import { SkeletonRows } from "@/components/platform/ui";

import { NdrView } from "./view";

export const metadata: Metadata = { title: "NDR cases" };

export default function Page() {
  return <Suspense fallback={<SkeletonRows rows={12} />}><NdrView /></Suspense>;
}
