import "./globals.css";
import type { Metadata } from "next";
import { Shell } from "@/components/ui";

export const metadata: Metadata = { title: "Zippy Admin" };

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body><Shell>{children}</Shell></body>
    </html>
  );
}
