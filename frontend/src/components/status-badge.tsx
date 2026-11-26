import { AlertTriangle, CheckCircle2, CircleDashed, HelpCircle, Loader2, ShieldAlert, XCircle } from "lucide-react";
import type { ReactNode } from "react";
import type { DocumentStatus } from "@/api/documents";
import { Badge, type BadgeTone } from "@/components/ui/badge";

/** Evidence states as returned by the API. Labels are the wording shown to users. */
export type EvidenceState = "EVIDENCE_SUPPORTED" | "CONFLICTING_EVIDENCE" | "INSUFFICIENT_EVIDENCE" | "REVIEW_REQUIRED";

interface StatusStyle {
  label: string;
  tone: BadgeTone;
  icon: ReactNode;
}

export const EVIDENCE_STATES: Record<EvidenceState, StatusStyle> = {
  EVIDENCE_SUPPORTED: { label: "Evidence-supported", tone: "supported", icon: <CheckCircle2 /> },
  CONFLICTING_EVIDENCE: { label: "Conflicting evidence", tone: "conflicting", icon: <AlertTriangle /> },
  INSUFFICIENT_EVIDENCE: { label: "Insufficient evidence", tone: "insufficient", icon: <HelpCircle /> },
  REVIEW_REQUIRED: { label: "Review required", tone: "review", icon: <ShieldAlert /> },
};

export const DOCUMENT_STATUSES: Record<DocumentStatus, StatusStyle> = {
  uploaded: { label: "Uploaded", tone: "pending", icon: <CircleDashed /> },
  processing: { label: "Processing", tone: "pending", icon: <Loader2 className="animate-spin" /> },
  processed: { label: "Processed", tone: "supported", icon: <CheckCircle2 /> },
  failed: { label: "Failed", tone: "review", icon: <XCircle /> },
};

export function EvidenceStateBadge({ state }: { state: EvidenceState }) {
  const s = EVIDENCE_STATES[state];
  return (
    <Badge tone={s.tone}>
      {s.icon}
      {s.label}
    </Badge>
  );
}

export function DocumentStatusBadge({ status }: { status: DocumentStatus }) {
  const s = DOCUMENT_STATUSES[status];
  return (
    <Badge tone={s.tone}>
      {s.icon}
      {s.label}
    </Badge>
  );
}
