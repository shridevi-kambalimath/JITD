import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { analysisKeys, replaceAnalysisResults } from "@/api/analysis";
import { API_BASE, apiRequest, interpretResponse, networkError } from "@/lib/api";

/** Mirrors backend/medusa/schemas/documents.py */
export type DocumentStatus = "uploaded" | "processing" | "processed" | "failed";

export interface DocumentSummary {
  document_id: string;
  patient_id: string;
  filename: string;
  file_format: "pdf" | "txt";
  size_bytes: number;
  sha256: string;
  status: DocumentStatus;
  document_type: string | null;
  document_date: string | null;
  source_document_id: string | null;
  extraction_method: "utf8_text" | "pdf_text_layer" | null;
  page_count: number | null;
  char_count: number | null;
  warnings: string[];
  error_code: string | null;
  error_message: string | null;
  uploaded_at: string;
  updated_at: string;
}

export interface DocumentEvent {
  status: DocumentStatus;
  detail: string | null;
  at: string;
}

export interface DocumentDetail extends DocumentSummary {
  metadata: Record<string, string>;
  extracted_text: string | null;
  page_spans: [number, number][];
  events: DocumentEvent[];
}

export interface DemoLoadResult {
  patient_id: string;
  loaded: DocumentSummary[];
  skipped_existing: string[];
  rejected: { filename: string; code: string; message: string }[];
  removed: number;
}

/** Same extension rule as backend/medusa/ingestion/validation.py; the backend still checks content and size. */
export const ACCEPTED_EXTENSIONS = [".pdf", ".txt"] as const;

const enc = encodeURIComponent;

export const listDocuments = (patientId: string) => apiRequest<DocumentSummary[]>(`/patients/${enc(patientId)}/documents`);
export const getDocument = (documentId: string) => apiRequest<DocumentDetail>(`/documents/${enc(documentId)}`);
export const deleteDocument = (documentId: string) => apiRequest<void>(`/documents/${enc(documentId)}`, { method: "DELETE" });
export const loadDemo = (patientId: string) =>
  apiRequest<DemoLoadResult>(`/patients/${enc(patientId)}/demo/load`, { method: "POST" });
export const resetDemo = (patientId: string) =>
  apiRequest<DemoLoadResult>(`/patients/${enc(patientId)}/demo/reset`, { method: "POST" });

/**
 * Upload one file. Uses XMLHttpRequest because fetch cannot report upload progress.
 * onProgress receives 0..1 for bytes sent; the response arrives after the backend has also processed the file.
 * Resolves with the document (status "processed" or "failed"); rejects with ApiError for 409/413/415/422 and network errors.
 */
export function uploadDocument(patientId: string, file: File, onProgress?: (fraction: number) => void): Promise<DocumentDetail> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", `${API_BASE}/patients/${enc(patientId)}/documents`);
    xhr.setRequestHeader("Accept", "application/json");
    xhr.upload.onprogress = (e) => {
      if (e.lengthComputable && e.total > 0) onProgress?.(e.loaded / e.total);
    };
    xhr.onload = () => {
      try {
        resolve(interpretResponse<DocumentDetail>(xhr.status, xhr.responseText, xhr.getResponseHeader("X-Request-ID")));
      } catch (err) {
        reject(err);
      }
    };
    xhr.onerror = () => reject(networkError("upload failed"));
    xhr.onabort = () => reject(networkError("upload aborted"));
    const form = new FormData();
    form.append("file", file, file.name);
    xhr.send(form);
  });
}

export const documentKeys = {
  all: ["documents"] as const,
  list: (patientId: string) => ["documents", "list", patientId] as const,
  detail: (documentId: string) => ["documents", "detail", documentId] as const,
};

export function useDocuments(patientId: string) {
  return useQuery({ queryKey: documentKeys.list(patientId), queryFn: () => listDocuments(patientId) });
}

export function useDocument(documentId: string | null) {
  return useQuery({
    queryKey: documentKeys.detail(documentId ?? ""),
    queryFn: () => getDocument(documentId!),
    enabled: documentId !== null,
  });
}

export function useLoadDemo() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: loadDemo,
    onSuccess: (_data, patientId) =>
      Promise.all([qc.invalidateQueries({ queryKey: documentKeys.list(patientId) }), qc.invalidateQueries({ queryKey: analysisKeys.all })]),
  });
}

export function useResetDemo() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: resetDemo,
    // stored claims are deleted with their documents, and results may now be stale
    onSuccess: () => Promise.all([qc.invalidateQueries({ queryKey: documentKeys.all }), replaceAnalysisResults(qc)]),
  });
}

export function useDeleteDocument(patientId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: deleteDocument,
    onSuccess: (_data, documentId) => {
      qc.removeQueries({ queryKey: documentKeys.detail(documentId) });
      return Promise.all([qc.invalidateQueries({ queryKey: documentKeys.list(patientId) }), qc.invalidateQueries({ queryKey: analysisKeys.all })]);
    },
  });
}
