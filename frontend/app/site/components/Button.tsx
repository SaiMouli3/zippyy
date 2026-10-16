import Link from "next/link";
import { ReactNode } from "react";

const base = "inline-flex items-center justify-center gap-2.5 rounded-md px-[39px] py-[11px] font-body text-[15px] font-medium transition-all duration-500";
const variants = {
  filled: "bg-zy-brand text-white hover:bg-white hover:text-zy-brand",
  outline: "border border-white text-white hover:bg-white hover:text-zy-ink",
};

export function Button({ href, variant = "filled", children, className = "" }: {
  href: string; variant?: keyof typeof variants; children: ReactNode; className?: string;
}) {
  return <Link href={href} className={`${base} ${variants[variant]} ${className}`}>{children}</Link>;
}
