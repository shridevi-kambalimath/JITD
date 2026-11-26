import { Check, Pencil, X } from "lucide-react";
import { type FormEvent, useState } from "react";
import { Badge } from "@/components/ui/badge";
import { PATIENT_ID_PATTERN, useWorkspace } from "@/context/workspace";

export function PatientSwitcher() {
  const { patientId, setPatientId } = useWorkspace();
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(patientId);
  const valid = PATIENT_ID_PATTERN.test(draft);

  function submit(e: FormEvent) {
    e.preventDefault();
    if (!valid) return;
    setPatientId(draft);
    setEditing(false);
  }

  if (!editing) {
    return (
      <div>
        <div className="text-[11px] font-medium uppercase tracking-[0.06em] text-ink-faint">Patient record</div>
        <div className="mt-1 flex items-center gap-2">
          <span className="font-mono text-[13px] font-medium text-ink" data-testid="active-patient">{patientId}</span>
          <Badge tone="brand">Synthetic</Badge>
          <button
            type="button"
            onClick={() => { setDraft(patientId); setEditing(true); }}
            className="ml-auto rounded-sm p-1 text-ink-faint hover:bg-subtle hover:text-ink"
            aria-label="Change patient record"
          >
            <Pencil className="size-3.5" />
          </button>
        </div>
      </div>
    );
  }

  return (
    <form onSubmit={submit}>
      <label htmlFor="patient-id" className="text-[11px] font-medium uppercase tracking-[0.06em] text-ink-faint">
        Patient record
      </label>
      <div className="mt-1 flex items-center gap-1">
        <input
          id="patient-id"
          autoFocus
          value={draft}
          onChange={(e) => setDraft(e.target.value.trim())}
          aria-invalid={!valid}
          className="h-8 w-full min-w-0 rounded-md border border-line-strong bg-surface px-2 font-mono text-[13px] aria-[invalid=true]:border-review"
        />
        <button type="submit" disabled={!valid} className="rounded-sm p-1.5 text-brand hover:bg-brand-soft disabled:opacity-40" aria-label="Apply">
          <Check className="size-4" />
        </button>
        <button type="button" onClick={() => setEditing(false)} className="rounded-sm p-1.5 text-ink-faint hover:bg-subtle" aria-label="Cancel">
          <X className="size-4" />
        </button>
      </div>
      {!valid && <p className="mt-1 text-[11px] text-review">Letters, digits, - and _ only.</p>}
    </form>
  );
}
