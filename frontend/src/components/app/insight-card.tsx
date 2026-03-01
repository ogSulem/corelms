"use client";

import { useEffect, useState } from "react";
import { Quote } from "lucide-react";

const QUOTES = [
  {
    text: "Качество — это делать что-то правильно, даже когда никто не смотрит.",
    author: "Генри Форд",
  },
  {
    text: "Единственный способ делать великие дела — любить то, что вы делаете.",
    author: "Стив Джобс",
  },
  {
    text: "Ваше время ограничено, поэтому не тратьте его на жизнь чужой жизнью.",
    author: "Стив Джобс",
  },
  {
    text: "Самолет взлетает против ветра, а не по ветру.",
    author: "Генри Форд",
  },
];

export function InsightCard({ nonce }: { nonce: number }) {
  const [quote, setQuote] = useState(QUOTES[0]);

  useEffect(() => {
    const idx = Math.floor(Math.random() * QUOTES.length);
    setQuote(QUOTES[idx]);
  }, [nonce]);

  return (
    <div className="relative overflow-hidden p-8 h-full min-h-[140px] flex flex-col justify-center">
      <div className="absolute top-4 right-6 text-[#fe9900]/10">
        <Quote size={80} strokeWidth={3} />
      </div>
      
      <div className="relative z-10">
        <p className="text-xl font-black text-zinc-950 leading-tight uppercase tracking-tighter mb-4 italic">
          "{quote.text}"
        </p>
        <div className="flex items-center gap-3">
          <div className="h-px w-8 bg-[#fe9900]/60" />
          <span className="text-[10px] font-black text-[#284e13] uppercase tracking-[0.3em]">
            {quote.author}
          </span>
        </div>
      </div>
      
      <div className="absolute bottom-0 left-0 w-full h-[2px] bg-gradient-to-r from-transparent via-[#fe9900]/25 to-transparent" />
    </div>
  );
}
