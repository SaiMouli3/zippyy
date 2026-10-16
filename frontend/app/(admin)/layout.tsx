import type { Metadata } from "next";
import { Shell } from "@/components/ui";

export const metadata: Metadata = { title: "Zippy Admin" };

export default function AdminLayout({ children }: { children: React.ReactNode }) {
  return <Shell>{children}</Shell>;
}
