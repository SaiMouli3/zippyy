"use client";

import { useRef } from "react";

type Quote = { name: string; role: string; text: string };

export function Testimonials({ quotes }: { quotes: Quote[] }) {
  const track = useRef<HTMLDivElement>(null);
  // Scroll by one card (card width + 20px gap); scroll-snap keeps cards aligned.
  const move = (dir: number) => {
    const el = track.current;
    const card = el?.firstElementChild as HTMLElement | null;
    if (el && card) el.scrollBy({ left: dir * (card.offsetWidth + 20), behavior: "smooth" });
  };

  return (
    <section id="customers" className="bg-zy-paper px-5 pb-20 pt-10 lg:px-[60px]">
      <h2 className="text-center font-heading text-[26px] font-semibold text-black lg:text-5xl">What teams say after switching</h2>
      <div ref={track} className="mx-auto flex max-w-[1200px] snap-x snap-mandatory gap-5 overflow-x-auto px-1 py-10 [scrollbar-width:none]">
        {quotes.map((q) => (
          <article key={q.name} className="flex w-full shrink-0 snap-start flex-col rounded-[14px] bg-white p-[25px] shadow-zy-card min-[600px]:w-[calc(50%-10px)] min-[992px]:w-[calc(33.33%-13.33px)]">
            <div className="mb-4 flex items-center">
              <span className="mr-4 flex h-[55px] w-[55px] items-center justify-center rounded-full bg-zy-ink font-heading font-bold text-white">{q.name[0]}</span>
              <div>
                <div className="text-[17px] font-bold text-zy-ink">{q.name}</div>
                <div className="text-sm text-[#666]">{q.role}</div>
              </div>
            </div>
            <p className="mb-4 mt-2.5 text-sm leading-relaxed text-[#555]">{q.text}</p>
            <div className="mt-auto text-zy-star" aria-label="5 out of 5">★★★★★</div>
          </article>
        ))}
      </div>
      <div className="flex justify-center gap-5">
        <ArrowBtn label="Previous" onClick={() => move(-1)}>‹</ArrowBtn>
        <ArrowBtn label="Next" onClick={() => move(1)}>›</ArrowBtn>
      </div>
    </section>
  );
}

function ArrowBtn({ label, onClick, children }: { label: string; onClick: () => void; children: string }) {
  return (
    <button aria-label={label} onClick={onClick}
      className="flex h-[42px] w-[42px] items-center justify-center rounded-full border-2 border-zy-muted bg-white text-lg text-zy-muted transition hover:border-zy-ink-3 hover:text-black">
      {children}
    </button>
  );
}
