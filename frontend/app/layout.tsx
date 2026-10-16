import "./globals.css";
import type { Metadata, Viewport } from "next";
import { Inter, Lato } from "next/font/google";

// Lato for headings and Inter for UI text, exactly as zippyy.ai pairs them. Self-hosted at build time by next/font,
// so no runtime request leaves the origin.
const lato = Lato({ subsets: ["latin"], weight: ["400", "700", "900"], variable: "--font-lato", display: "swap" });
const inter = Inter({ subsets: ["latin"], variable: "--font-inter", display: "swap" });

export const metadata: Metadata = {
  title: { default: "Zippyy", template: "%s · Zippyy" },
  description: "Multilingual delivery and NDR autonomy for Indian commerce.",
  icons: { icon: "/brand/icon-32.jpg", apple: "/brand/icon-192.jpg" },
  robots: { index: false, follow: false },
};

export const viewport: Viewport = { themeColor: "#121212" };

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={`${lato.variable} ${inter.variable}`}>
      <body>{children}</body>
    </html>
  );
}
