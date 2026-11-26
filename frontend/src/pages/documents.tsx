import { FileText, RotateCcw } from "lucide-react";
import { useState } from "react";
import { useSearchParams } from "react-router";
import { useClaims } from "@/api/analysis";
import { type DocumentSummary, useDocuments, useLoadDemo, useResetDemo } from "@/api/documents";
import { ConfirmAction } from "@/components/confirm-action";
import { DocumentViewer } from "@/components/document-viewer";
import { EmptyState } from "@/components/empty-state";
import { ErrorState } from "@/components/error-state";
import { PageHeader } from "@/components/page-header";
import { DocumentStatusBadge } from "@/components/status-badge";
import { UploadDropzone } from "@/components/upload-dropzone";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { useWorkspace } from "@/context/workspace";
import { cn, formatBytes } from "@/lib/utils";

type Filter = "all" | "processed" | "failed";

export function DocumentsPage() {
  const { patientId } = useWorkspace();
  const [params, setParams] = useSearchParams();
  const selected = params.get("doc");
  const claimParam = params.get("claim");
  const [filter, setFilter] = useState<Filter>("all");
  const [notice, setNotice] = useState<string | null>(null);
  const docs = useDocuments(patientId);
  const demo = useLoadDemo();
  const reset = useResetDemo();
  const claims = useClaims(patientId);
  const claimCounts = new Map<string, number>();
  for (const c of claims.data ?? []) claimCounts.set(c.source.document_id, (claimCounts.get(c.source.document_id) ?? 0) + 1);
  const analysed = (claims.data?.length ?? 0) > 0;

  const select = (id: string | null) => setParams(id ? { doc: id } : {}, { replace: true });
  const list = docs.data ?? [];
  const counts = { all: list.length, processed: list.filter((d) => d.status === "processed").length, failed: list.filter((d) => d.status === "failed").length };
  const shown = filter === "all" ? list : list.filter((d) => d.status === filter);
  const selectedExists = selected !== null && list.some((d) => d.document_id === selected);

  function runReset() {
    setNotice(null);
    reset.mutate(patientId, {
      onSuccess: (r) => {
        select(null);
        setNotice(`Demo reset: removed ${r.removed} document${r.removed === 1 ? "" : "s"}, loaded ${r.loaded.length} through the ingestion pipeline.`);
      },
    });
  }

  return (
    <div className="space-y-6">
      <PageHeader
        title="Documents"
        description={<>Synthetic source records for patient <span className="font-mono text-ink">{patientId}</span>. Every later claim cites a passage in one of these documents.</>}
        actions={
          <ConfirmAction
            label="Reset demo data"
            icon={<RotateCcw />}
            variant="secondary"
            confirmLabel="Reset"
            description={<>Remove all {list.length} document{list.length === 1 ? "" : "s"} for {patientId} and reload the synthetic demo bundle?</>}
            pending={reset.isPending}
            onConfirm={runReset}
          />
        }
      />
      {reset.isError && <ErrorState error={reset.error} />}
      {notice && <p aria-live="polite" className="rounded-md border border-supported-line bg-supported-soft px-4 py-2 text-[13px] text-supported">{notice}</p>}

      <UploadDropzone patientId={patientId} onUploaded={(d) => select(d.document_id)} />

      {docs.isError ? (
        <ErrorState error={docs.error} onRetry={() => docs.refetch()} />
      ) : (
        <div className="grid grid-cols-[minmax(0,1fr)] gap-6 xl:grid-cols-[minmax(0,5fr)_minmax(0,7fr)]">
          <Card className="self-start">
            <div className="flex items-center gap-1 border-b border-line px-3 py-2" role="tablist" aria-label="Filter documents by status">
              {(["all", "processed", "failed"] as const).map((f) => (
                <button
                  key={f}
                  role="tab"
                  aria-selected={filter === f}
                  onClick={() => setFilter(f)}
                  className={cn("rounded-md px-2.5 py-1 text-[12px] font-medium capitalize", filter === f ? "bg-brand-soft text-brand" : "text-ink-muted hover:bg-subtle")}
                >
                  {f} <span className="tabular-nums text-ink-faint">{counts[f]}</span>
                </button>
              ))}
            </div>
            {docs.isPending ? (
              <div className="space-y-2 p-4" aria-busy="true">{Array.from({ length: 5 }, (_, i) => <Skeleton key={i} className="h-10" />)}</div>
            ) : list.length === 0 ? (
              <EmptyState
                icon={<FileText />}
                title="No documents yet"
                description="Upload synthetic .pdf or .txt files above, or load the synthetic demo bundle."
                action={
                  <div className="space-y-3">
                    <Button onClick={() => demo.mutate(patientId)} loading={demo.isPending}>Load synthetic demo bundle</Button>
                    {demo.isError && <ErrorState error={demo.error} />}
                  </div>
                }
              />
            ) : shown.length === 0 ? (
              <p className="px-4 py-8 text-center text-[13px] text-ink-muted">No {filter} documents.</p>
            ) : (
              <ul aria-label="Documents" className="divide-y divide-line">
                {shown.map((d) => (
                  <DocumentRow key={d.document_id} doc={d} active={d.document_id === selected} onSelect={() => select(d.document_id)}
                    claimCount={analysed && d.status === "processed" ? claimCounts.get(d.document_id) ?? 0 : null} />
                ))}
              </ul>
            )}
          </Card>

          <div>
            {selectedExists ? (
              <DocumentViewer key={selected} documentId={selected!} patientId={patientId} initialClaimId={claimParam} onDeleted={() => select(null)} />
            ) : (
              list.length > 0 && (
                <Card>
                  <EmptyState icon={<FileText />} title="Select a document" description="See its extracted claims with the exact source words, its metadata, any processing problem, the full extracted text and its status history." />
                </Card>
              )
            )}
          </div>
        </div>
      )}
    </div>
  );
}

function DocumentRow({ doc, active, onSelect, claimCount }: { doc: DocumentSummary; active: boolean; onSelect: () => void; claimCount: number | null }) {
  return (
    <li>
      <button
        type="button"
        onClick={onSelect}
        aria-current={active || undefined}
        className={cn("flex w-full items-start gap-3 px-4 py-3 text-left hover:bg-canvas", active && "bg-brand-soft hover:bg-brand-soft")}
      >
        <div className="min-w-0 flex-1">
          <div className="truncate text-[13px] font-medium text-ink">{doc.document_type ?? <span className="text-ink-muted">Type not established</span>}</div>
          <div className="truncate text-[12px] text-ink-muted">{doc.filename}</div>
          <div className="mt-0.5 flex flex-wrap gap-x-3 text-[11px] text-ink-faint">
            <span className="tabular-nums">{doc.document_date ?? "no document date"}</span>
            <span>{doc.file_format.toUpperCase()} · {formatBytes(doc.size_bytes)}</span>
            {claimCount !== null && <span className="text-brand" data-testid="claim-count">{claimCount} claim{claimCount === 1 ? "" : "s"}</span>}
            {doc.warnings.length > 0 && <span className="text-conflicting">{doc.warnings.length} warning{doc.warnings.length === 1 ? "" : "s"}</span>}
          </div>
        </div>
        <div className="flex shrink-0 flex-col items-end gap-1">
          <DocumentStatusBadge status={doc.status} />
          {doc.error_code && <span className="font-mono text-[11px] text-review">{doc.error_code}</span>}
        </div>
      </button>
    </li>
  );
}
