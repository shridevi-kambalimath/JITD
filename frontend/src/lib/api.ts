/**
 * The single HTTP client. Components never call fetch directly; they use the typed functions in src/api/*.
 *
 * All paths are relative to /api. In development Vite proxies /api to the FastAPI backend; in the
 * single-process demo build the backend serves this app on the same origin.
 */

export const API_BASE = "/api";

export interface ErrorEnvelope {
  error: { code: string; message: string; details: unknown; request_id: string };
}

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly details: unknown;
  readonly requestId: string | null;

  constructor(status: number, code: string, message: string, details: unknown = null, requestId: string | null = null) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    this.details = details;
    this.requestId = requestId;
  }

  /** True when the backend could not be reached at all (server down, proxy error, offline). */
  get isNetworkError(): boolean {
    return this.status === 0;
  }
}

function isEnvelope(body: unknown): body is ErrorEnvelope {
  return typeof body === "object" && body !== null && "error" in body && typeof (body as ErrorEnvelope).error?.code === "string";
}

export interface RequestOptions extends Omit<RequestInit, "body"> {
  body?: BodyInit | object | null;
  /** HTTP statuses that carry a meaningful body and must not throw (e.g. 503 from readiness). */
  allowStatus?: number[];
}

export async function apiRequest<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const { body, allowStatus = [], headers, ...init } = options;
  const isJsonBody = body !== undefined && body !== null && !(body instanceof FormData) && typeof body === "object";

  let response: Response;
  try {
    response = await fetch(`${API_BASE}${path}`, {
      ...init,
      headers: { Accept: "application/json", ...(isJsonBody ? { "Content-Type": "application/json" } : {}), ...headers },
      body: isJsonBody ? JSON.stringify(body) : (body as BodyInit | null | undefined),
    });
  } catch (cause) {
    throw networkError(cause);
  }

  if (response.status === 204) return undefined as T;
  return interpretResponse<T>(response.status, await response.text(), response.headers.get("X-Request-ID"), allowStatus);
}

const NETWORK_MESSAGE = "The MEDUSA-X backend could not be reached. Check that it is running.";

export function networkError(cause?: unknown): ApiError {
  return new ApiError(0, "network_error", NETWORK_MESSAGE, cause === undefined ? null : { cause: String(cause) });
}

/**
 * Turns a raw HTTP response into data or an ApiError. Shared by fetch (apiRequest) and XMLHttpRequest
 * (uploads, which need progress events), so both report errors identically.
 */
export function interpretResponse<T>(status: number, text: string, requestId: string | null, allowStatus: number[] = []): T {
  if (status === 204) return undefined as T;
  let parsed: unknown = null;
  if (text) {
    try {
      parsed = JSON.parse(text);
    } catch {
      parsed = null;
    }
  }
  const ok = status >= 200 && status < 300;
  if (ok || allowStatus.includes(status)) {
    if (parsed === null && text) {
      throw new ApiError(status, "invalid_response", "The backend returned a response that is not JSON.", null, requestId);
    }
    return parsed as T;
  }
  if (isEnvelope(parsed)) {
    const e = parsed.error;
    throw new ApiError(status, e.code, e.message, e.details, e.request_id ?? requestId);
  }
  // Vite's dev proxy answers 502/504 with plain text when the backend is down.
  if (status === 502 || status === 504 || status === 0) throw networkError();
  throw new ApiError(status, "http_error", `Request failed with status ${status}.`, null, requestId);
}
