import { AlertTriangle, Trash2 } from "lucide-react";
import { type ReactNode, type RefObject, useEffect, useRef, useState } from "react";
import { useClaims } from "@/api/analysis";
import { type DocumentDetail, useDeleteDocument, useDocument } from "@/api/documents";
import { ClaimsList } from "@/components/claims-list";
import { ConfirmAction } from "@/components/confirm-action";
import { ErrorState } from "@/components/error-state";
import { DocumentStatusBadge } from "@/components/status-badge";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { cn, formatBytes, formatDateTime } from "@/lib/utils";

/** Full view of one stored document: metadata, problems, the canonical extracted text and its status history. */
export function DocumentViewer({ documentId, patientId, onDeleted, initialClaimId = null }: {
  documentId: string;
  patientId: string;
  onDeleted: () => void;
  /** Claim to highlight on open, e.g. when arriving from the timeline. */
  initialClaimId?: string | null;
}) {
  const query = useDocument(documentId);
  const del = useDeleteDocument(patientId);
  const [selectedId, setSelectedId] = useState<string | null>(initialClaimId);
  // a highlight belongs to one document
  useEffect(() => setSelectedId(initialClaimId), [documentId, initialClaimId]);
  const claims = useClaims(patientId, documentId, query.data?.status === "processed");
  const selected = claims.data?.find((c) => c.claim_id === selectedId) ?? null;

  if (query.isPending) {
    return (
      <Card aria-busy="true">
        <CardContent className="space-y-3">
          <Skeleton className="h-5 w-48" />
          <Skeleton className="h-24" />
          <Skeleton className="h-64" />
        </CardContent>
      </Card>
    );
  }
  if (query.isError) return <ErrorState error={query.error} onRetry={() => query.refetch()} />;
  const doc = query.data;

  return (
    <Card aria-label={`Document ${doc.document_id}`}>
      <CardHeader className="flex-wrap">
        <div className="min-w-0">
          <h2 className="truncate text-[15px] font-semibold text-ink">{doc.document_type ?? doc.filename}</h2>
          <p className="font-mono text-[11px] text-ink-faint">{doc.document_id}</p>
        </div>
        <div className="flex items-center gap-2">
          <DocumentStatusBadge status={doc.status} />
        </div>
      </CardHeader>

      {doc.status === "failed" && (
        <div role="alert" className="border-b border-review-line bg-review-soft px-5 py-3">
          <p className="text-[13px] font-medium text-review">
            Processing failed <span className="ml-1 font-mono text-[11px]">{doc.error_code}</span>
          </p>
          <p className="mt-0.5 text-[13px] text-ink">{doc.error_message}</p>
          <p className="mt-1 text-[12px] text-ink-muted">The original file is kept so you can inspect it. It is excluded from analysis.</p>
        </div>
      )}
      {doc.warnings.length > 0 && (
        <ul className="space-y-1 border-b border-conflicting-line bg-conflicting-soft px-5 py-3" aria-label="Warnings">
          {doc.warnings.map((w) => (
            <li key={w} className="flex gap-2 text-[12px] text-ink [&_svg]:mt-0.5 [&_svg]:size-3.5 [&_svg]:shrink-0 [&_svg]:text-conflicting">
              <AlertTriangle />
              {w}
            </li>
          ))}
        </ul>
      )}

      <CardContent className="space-y-5">
        <Metadata doc={doc} />
        {doc.status === "processed" && (
          <ClaimsList patientId={patientId} documentId={doc.document_id} selected={selectedId} onSelect={setSelectedId} />
        )}
        <ExtractedText doc={doc} highlight={selected ? [selected.source.entity_char_start, selected.source.entity_char_end] : null} />
        <History doc={doc} />
        <div className="border-t border-line pt-4">
          <ConfirmAction
            label="Delete document"
            icon={<Trash2 />}
            confirmLabel="Delete permanently"
            description={<>Delete <strong>{doc.filename}</strong>? The stored file, its status history and any evidence derived from it are removed.</>}
            pending={del.isPending}
            onConfirm={() => del.mutate(doc.document_id, { onSuccess: onDeleted })}
          />
          {del.isError && <ErrorState className="mt-3" error={del.error} />}
        </div>
      </CardContent>
    </Card>
  );
}

function Metadata({ doc }: { doc: DocumentDetail }) {
  const rows: [string, string][] = [
    ["Document date", doc.document_date ?? "not established"],
    ["Source file", doc.filename],
    ["Format", `${doc.file_format.toUpperCase()} · ${formatBytes(doc.size_bytes)}${doc.page_count ? ` · ${doc.page_count} page${doc.page_count === 1 ? "" : "s"}` : ""}`],
    ["Extraction", doc.extraction_method === "pdf_text_layer" ? "PDF text layer" : doc.extraction_method === "utf8_text" ? "UTF-8 text" : "none"],
    ["Characters", doc.char_count != null ? doc.char_count.toLocaleString() : "0"],
    ["Uploaded", formatDateTime(doc.uploaded_at)],
  ];
  const header = Object.entries(doc.metadata);
  return (
    <div className="grid gap-5 md:grid-cols-2">
      <section>
        <h3 className="mb-2 text-[11px] font-semibold uppercase tracking-[0.06em] text-ink-faint">File</h3>
        <dl className="space-y-1.5 text-[13px]">
          {rows.map(([k, v]) => (
            <div key={k} className="flex justify-between gap-3">
              <dt className="text-ink-muted">{k}</dt>
              <dd className="text-right text-ink">{v}</dd>
            </div>
          ))}
        </dl>
      </section>
      <section>
        <h3 className="mb-2 text-[11px] font-semibold uppercase tracking-[0.06em] text-ink-faint">Header metadata</h3>
        {header.length === 0 ? (
          <p className="text-[13px] text-ink-muted">None: processing stopped before a valid header was read.</p>
        ) : (
          <dl className="space-y-1.5 text-[13px]">
            {header.map(([k, v]) => (
              <div key={k} className="flex justify-between gap-3">
                <dt className="text-ink-muted">{k.toLowerCase().replace(/^\w/, (c) => c.toUpperCase())}</dt>
                <dd className="text-right font-mono text-[12px] text-ink">{v}</dd>
              </div>
            ))}
          </dl>
        )}
      </section>
    </div>
  );
}

function ExtractedText({ doc, highlight }: { doc: DocumentDetail; highlight: [number, number] | null }) {
  const text = doc.extracted_text;
  const markRef = useRef<HTMLElement>(null);
  const [hlStart, hlEnd] = highlight ?? [null, null];
  // scroll only when the highlighted span changes, not on every re-render
  useEffect(() => {
    if (hlStart !== null) markRef.current?.scrollIntoView?.({ block: "center", behavior: "smooth" });
  }, [hlStart, hlEnd]);
  const pages = doc.page_count && doc.page_count > 1 && text ? doc.page_spans.map(([a, b], i) => ({ n: i + 1, start: a, text: text.slice(a, b) })) : null;
  return (
    <section>
      <div className="mb-2 flex items-baseline justify-between gap-3">
        <h3 className="text-[11px] font-semibold uppercase tracking-[0.06em] text-ink-faint">Extracted text</h3>
        <span className="text-[11px] text-ink-faint">canonical text; evidence offsets point into it</span>
      </div>
      {!text ? (
        <p className="rounded-md border border-line bg-canvas px-4 py-6 text-center text-[13px] text-ink-muted">No text was extracted from this document.</p>
      ) : (
        <div className="max-h-[420px] overflow-auto rounded-md border border-line bg-canvas" data-testid="extracted-text">
          {pages ? (
            pages.map((p) => (
              <div key={p.n} className="border-b border-line last:border-b-0">
                <div className="sticky top-0 border-b border-line bg-subtle px-4 py-1 text-[11px] font-medium text-ink-muted">Page {p.n}</div>
                {p.text ? <pre className={preClass}>{withMark(p.text, p.start, highlight, markRef)}</pre> : <p className="px-4 py-3 text-[12px] italic text-ink-faint">No extractable text on this page.</p>}
              </div>
            ))
          ) : (
            <pre className={preClass}>{withMark(text, 0, highlight, markRef)}</pre>
          )}
        </div>
      )}
    </section>
  );
}

/** Render text (which starts at absolute offset `base`) with the highlighted absolute span wrapped in <mark>. */
function withMark(text: string, base: number, hl: [number, number] | null, ref: RefObject<HTMLElement | null>): ReactNode {
  if (!hl) return text;
  const a = Math.max(hl[0] - base, 0);
  const b = Math.min(hl[1] - base, text.length);
  if (a >= b) return text;
  return (
    <>
      {text.slice(0, a)}
      <mark ref={ref} className="rounded-sm bg-brand-soft px-0.5 text-ink ring-1 ring-brand-line" data-testid="source-highlight">
        {text.slice(a, b)}
      </mark>
      {text.slice(b)}
    </>
  );
}

const preClass = "whitespace-pre-wrap break-words px-4 py-3 font-mono text-[12px] leading-relaxed text-ink";

function History({ doc }: { doc: DocumentDetail }) {
  return (
    <section>
      <h3 className="mb-2 text-[11px] font-semibold uppercase tracking-[0.06em] text-ink-faint">Status history</h3>
      <ol className="space-y-2" aria-label="Status history">
        {doc.events.map((e, i) => (
          <li key={i} className="flex gap-3 text-[12px]">
            <span className={cn("mt-1.5 size-1.5 shrink-0 rounded-full", e.status === "failed" ? "bg-review" : e.status === "processed" ? "bg-supported" : "bg-ink-faint")} aria-hidden />
            <div className="min-w-0">
              <span className="font-medium text-ink">{e.status}</span>
              <span className="ml-2 text-ink-faint">{formatDateTime(e.at)}</span>
              {e.detail && <p className="text-ink-muted">{e.detail}</p>}
            </div>
          </li>
        ))}
      </ol>
    </section>
  );
}
