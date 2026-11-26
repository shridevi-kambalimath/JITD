import { cva, type VariantProps } from "class-variance-authority";
import type { HTMLAttributes } from "react";
import { cn } from "@/lib/utils";

export const badgeVariants = cva(
  "inline-flex items-center gap-1.5 whitespace-nowrap rounded-sm border px-1.5 py-0.5 text-[12px] font-medium leading-4 [&_svg]:size-3.5",
  {
    variants: {
      tone: {
        neutral: "border-line bg-subtle text-ink-muted",
        brand: "border-brand-line bg-brand-soft text-brand",
        supported: "border-supported-line bg-supported-soft text-supported",
        conflicting: "border-conflicting-line bg-conflicting-soft text-conflicting",
        insufficient: "border-insufficient-line bg-insufficient-soft text-insufficient",
        review: "border-review-line bg-review-soft text-review",
        pending: "border-pending-line bg-pending-soft text-pending",
      },
    },
    defaultVariants: { tone: "neutral" },
  },
);

export type BadgeTone = NonNullable<VariantProps<typeof badgeVariants>["tone"]>;

export interface BadgeProps extends HTMLAttributes<HTMLSpanElement>, VariantProps<typeof badgeVariants> {}

export function Badge({ className, tone, ...props }: BadgeProps) {
  return <span className={cn(badgeVariants({ tone }), className)} {...props} />;
}
