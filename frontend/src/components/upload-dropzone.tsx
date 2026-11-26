import { useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, Copy, FileUp, Loader2, Upload, XCircle } from "lucide-react";
import { type DragEvent, useRef, useState } from "react";
import { analysisKeys } from "@/api/analysis";
import { useHealth } from "@/api/health";
import { ACCEPTED_EXTENSIONS, type DocumentDetail, documentKeys, uploadDocument } from "@/api/documents";
import { Button } from "@/components/ui/button";
import { ApiError } from "@/lib/api";
import { cn, formatBytes } from "@/lib/utils";

type Phase = "uploading" | "processing" | "processed" | "failed" | "rejected" | "duplicate";

interface QueueItem {
  key: number;
  name: string;
  size: number;
  phase: Phase;
  progress: number;
  document?: DocumentDetail;
  code?: string;
  message?: string;
  existingId?: string;
}

function hasAcceptedExtension(name: string) {
  const lower = name.toLowerCase();
  return ACCEPTED_EXTENSIONS.some((ext) => lower.endsWith(ext));
}

/**
 * Drag-and-drop or picker upload. Files go to the backend one at a time; each shows its own
 * progress and final outcome. The backend is the authority on every rule; the extension and size
 * pre-checks only save a pointless upload (the size limit comes from the backend's /health).
 */
export function UploadDropzone({ patientId, onUploaded }: { patientId: string; onUploaded?: (doc: DocumentDetail) => void }) {
  const qc = useQueryClient();
  const input = useRef<HTMLInputElement>(null);
  const nextKey = useRef(1);
  const running = useRef(Promise.resolve());
  const [items, setItems] = useState<QueueItem[]>([]);
  const [dragging, setDragging] = useState(false);
  const maxBytes = useHealth().data?.max_upload_bytes;

  const update = (key: number, patch: Partial<QueueItem>) =>
    setItems((list) => list.map((it) => (it.key === key ? { ...it, ...patch } : it)));

  async function send(file: File, key: number) {
    try {
      const doc = await uploadDocument(patientId, file, (f) => update(key, { progress: f, phase: f >= 1 ? "processing" : "uploading" }));
      update(key, {
        phase: doc.status === "processed" ? "processed" : "failed",
        progress: 1,
        document: doc,
        code: doc.error_code ?? undefined,
        message: doc.error_message ?? undefined,
      });
      onUploaded?.(doc);
    } catch (err) {
      const api = err instanceof ApiError ? err : null;
      const existing = (api?.details as { document_id?: string } | null)?.document_id;
      update(key, {
        phase: api?.status === 409 ? "duplicate" : "rejected",
        code: api?.code ?? "error",
        message: api?.message ?? String(err),
        existingId: existing,
      });
    } finally {
      await Promise.all([qc.invalidateQueries({ queryKey: documentKeys.list(patientId) }), qc.invalidateQueries({ queryKey: analysisKeys.all })]);
    }
  }

  function enqueue(files: FileList | File[]) {
    for (const file of Array.from(files)) {
      const key = nextKey.current++;
      if (!hasAcceptedExtension(file.name)) {
        setItems((l) => [...l, { key, name: file.name, size: file.size, phase: "rejected", progress: 0, code: "unsupported_type",
          message: "Only .pdf and .txt files are accepted. Nothing was uploaded." }]);
        continue;
      }
      if (maxBytes !== undefined && file.size > maxBytes) {
        setItems((l) => [...l, { key, name: file.name, size: file.size, phase: "rejected", progress: 0, code: "payload_too_large",
          message: `The file is ${formatBytes(file.size)}; the limit is ${maxBytes.toLocaleString("en-US")} bytes. Nothing was uploaded.` }]);
        continue;
      }
      setItems((l) => [...l, { key, name: file.name, size: file.size, phase: "uploading", progress: 0 }]);
      running.current = running.current.then(() => send(file, key)); // one at a time, in order
    }
  }

  function onDrop(e: DragEvent) {
    e.preventDefault();
    setDragging(false);
    if (e.dataTransfer.files.length) enqueue(e.dataTransfer.files);
  }

  const finished = items.filter((i) => i.phase !== "uploading" && i.phase !== "processing");

  return (
    <div className="space-y-3">
      <div
        onDragOver={(e) => { e.preventDefault(); setDragging(true); }}
        onDragLeave={() => setDragging(false)}
        onDrop={onDrop}
        data-testid="dropzone"
        className={cn(
          "flex flex-col items-center justify-center gap-2 rounded-lg border border-dashed px-6 py-7 text-center transition-colors",
          dragging ? "border-brand bg-brand-soft" : "border-line-strong bg-surface",
        )}
      >
        <FileUp className="size-6 text-ink-faint" aria-hidden />
        <p className="text-[13px] font-medium text-ink">Drop synthetic .pdf or .txt documents here</p>
        <p className="text-[12px] text-ink-muted">
          Each file is validated, stored, and its text and header metadata are extracted. Do not upload real patient data.
        </p>
        <Button variant="secondary" size="sm" onClick={() => input.current?.click()} className="mt-1">
          <Upload />
          Choose files
        </Button>
        <input
          ref={input}
          type="file"
          multiple
          accept={ACCEPTED_EXTENSIONS.join(",")}
          className="sr-only"
          aria-label="Choose documents to upload"
          onChange={(e) => { if (e.target.files?.length) enqueue(e.target.files); e.target.value = ""; }}
        />
      </div>

      {items.length > 0 && (
        <div className="rounded-lg border border-line bg-surface">
          <div className="flex items-center justify-between border-b border-line px-4 py-2">
            <span className="text-[12px] font-medium uppercase tracking-[0.06em] text-ink-muted">Uploads</span>
            {finished.length > 0 && (
              <button type="button" className="text-[12px] text-ink-muted hover:text-ink" onClick={() => setItems((l) => l.filter((i) => i.phase === "uploading" || i.phase === "processing"))}>
                Clear finished
              </button>
            )}
          </div>
          <ul className="divide-y divide-line" aria-label="Upload results">
            {items.map((it) => <UploadRow key={it.key} item={it} />)}
          </ul>
        </div>
      )}
    </div>
  );
}

function UploadRow({ item }: { item: QueueItem }) {
  const busy = item.phase === "uploading" || item.phase === "processing";
  const icon = busy ? <Loader2 className="animate-spin text-ink-faint" />
    : item.phase === "processed" ? <CheckCircle2 className="text-supported" />
    : item.phase === "duplicate" ? <Copy className="text-conflicting" />
    : <XCircle className="text-review" />;
  const label: Record<Phase, string> = {
    uploading: `Uploading ${Math.round(item.progress * 100)}%`,
    processing: "Extracting text and metadata",
    processed: `Processed${item.document?.document_type ? ` as ${item.document.document_type}` : ""}`,
    failed: "Stored, but processing failed",
    rejected: "Rejected, not stored",
    duplicate: "Already uploaded",
  };
  return (
    <li className="px-4 py-2.5" data-phase={item.phase}>
      <div className="flex items-center gap-3 [&_svg]:size-4 [&_svg]:shrink-0">
        {icon}
        <div className="min-w-0 flex-1">
          <div className="flex items-baseline justify-between gap-3">
            <span className="truncate text-[13px] font-medium text-ink">{item.name}</span>
            <span className="shrink-0 text-[11px] text-ink-faint">{formatBytes(item.size)}</span>
          </div>
          <p className="text-[12px] text-ink-muted">
            {label[item.phase]}
            {item.code && <span className="ml-1.5 font-mono text-[11px] text-review">{item.code}</span>}
          </p>
          {item.message && !busy && <p className="mt-0.5 text-[12px] text-ink">{item.message}</p>}
          {item.existingId && <p className="mt-0.5 font-mono text-[11px] text-ink-muted">existing: {item.existingId}</p>}
        </div>
      </div>
      {busy && (
        <div className="mt-2 h-1 overflow-hidden rounded-full bg-subtle" role="progressbar" aria-label={`Upload progress for ${item.name}`}
          aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round(item.progress * 100)}>
          <div className={cn("h-full bg-brand transition-[width]", item.phase === "processing" && "animate-pulse")} style={{ width: `${Math.max(4, item.progress * 100)}%` }} />
        </div>
      )}
    </li>
  );
}
