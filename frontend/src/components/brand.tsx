import { cn } from "@/lib/utils";

export function BrandMark({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 32 32" className={cn("size-7", className)} aria-hidden>
      <rect width="32" height="32" rx="6" className="fill-brand" />
      <path d="M8 22V10l8 7 8-7v12" fill="none" stroke="#fff" strokeWidth="2.6" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

export function Brand({ subtitle = true }: { subtitle?: boolean }) {
  return (
    <div className="flex items-center gap-2.5">
      <BrandMark />
      <div className="leading-tight">
        <div className="whitespace-nowrap text-[15px] font-semibold tracking-tight text-ink">MEDUSA-X</div>
        {subtitle && <div className="text-[11px] text-ink-faint">Evidence reconstruction</div>}
      </div>
    </div>
  );
}
