import { type ReactNode, useState } from "react";
import { Button, type ButtonProps } from "@/components/ui/button";

/**
 * A destructive action that asks first, inline, without a modal library.
 * The trigger turns into a short explanation with Cancel and a clearly labelled confirm button.
 */
export function ConfirmAction({ label, icon, confirmLabel, description, onConfirm, pending = false, variant = "danger", size = "sm" }: {
  label: string;
  icon?: ReactNode;
  confirmLabel: string;
  description: ReactNode;
  onConfirm: () => void;
  pending?: boolean;
  variant?: ButtonProps["variant"];
  size?: ButtonProps["size"];
}) {
  const [asking, setAsking] = useState(false);
  if (!asking) {
    return (
      <Button variant={variant} size={size} onClick={() => setAsking(true)}>
        {icon}
        {label}
      </Button>
    );
  }
  return (
    <div role="group" aria-label={`Confirm: ${label}`} className="flex flex-wrap items-center gap-2 rounded-md border border-review-line bg-review-soft px-3 py-2">
      <p className="text-[12px] text-ink">{description}</p>
      <div className="ml-auto flex gap-2">
        <Button variant="secondary" size="sm" onClick={() => setAsking(false)} disabled={pending}>Cancel</Button>
        <Button variant="danger" size="sm" loading={pending} onClick={onConfirm}>{confirmLabel}</Button>
      </div>
    </div>
  );
}
