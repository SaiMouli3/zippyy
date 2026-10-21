import type { Metadata } from "next";

import { PlatformProviders } from "@/components/platform/providers";
import { AppShell } from "@/components/platform/shell";

export const metadata: Metadata = { title: { default: "Zippyy", template: "%s · Zippyy" } };

export default function PlatformLayout({ children }: { children: React.ReactNode }) {
  return (
    <PlatformProviders>
      <AppShell>{children}</AppShell>
    </PlatformProviders>
  );
}
