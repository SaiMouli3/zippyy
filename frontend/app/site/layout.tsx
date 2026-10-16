import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Zippy – AI shipping for every carrier",
  description: "Compare carriers, book and track shipments from one place, or just ask the Zippy agent on WhatsApp.",
};

export default function SiteLayout({ children }: { children: React.ReactNode }) {
  return (
    <>
      {/* eslint-disable-next-line @next/next/no-page-custom-font */}
      <link
        rel="stylesheet"
        href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600&family=Lato:wght@400;500;600;700&family=Manrope:wght@400;600&display=swap"
      />
      <div className="font-body text-zy-ink-3 antialiased">{children}</div>
    </>
  );
}
