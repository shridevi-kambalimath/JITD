import type { Claim } from "@/api/analysis";

/** The source passage with the claim's exact words marked, so the evidence is readable in place. */
export function PassageWithMark({ claim: c }: { claim: Claim }) {
  const text = c.source.evidence_text;
  const a = c.source.entity_char_start - c.source.char_start;
  const b = c.source.entity_char_end - c.source.char_start;
  if (a < 0 || b > text.length || a >= b) return <q>{c.surface}</q>; // offsets outside the passage: show the quote alone
  return (
    <>
      {text.slice(0, a)}
      <mark className="rounded-sm bg-brand-soft px-0.5 font-semibold text-ink">{text.slice(a, b)}</mark>
      {text.slice(b)}
    </>
  );
}

