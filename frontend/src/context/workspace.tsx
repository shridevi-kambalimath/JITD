import { createContext, type ReactNode, useCallback, useContext, useMemo, useState } from "react";

/** The active patient record bundle. All workspace screens read from this patient. */
export const DEFAULT_PATIENT_ID = "SYN-0001";
export const PATIENT_ID_PATTERN = /^[A-Za-z0-9_-]{1,64}$/;
const STORAGE_KEY = "medusa-x.patient-id";

interface WorkspaceContextValue {
  patientId: string;
  setPatientId: (id: string) => void;
}

const WorkspaceContext = createContext<WorkspaceContextValue | null>(null);

function readStored(): string {
  try {
    const v = window.localStorage.getItem(STORAGE_KEY);
    return v && PATIENT_ID_PATTERN.test(v) ? v : DEFAULT_PATIENT_ID;
  } catch {
    return DEFAULT_PATIENT_ID; // storage can be unavailable (private mode, embedded views)
  }
}

export function WorkspaceProvider({ children, initialPatientId }: { children: ReactNode; initialPatientId?: string }) {
  const [patientId, setState] = useState<string>(() => initialPatientId ?? readStored());
  const setPatientId = useCallback((id: string) => {
    if (!PATIENT_ID_PATTERN.test(id)) return;
    setState(id);
    try {
      window.localStorage.setItem(STORAGE_KEY, id);
    } catch {
      /* remembering the choice is a convenience only */
    }
  }, []);
  const value = useMemo(() => ({ patientId, setPatientId }), [patientId, setPatientId]);
  return <WorkspaceContext.Provider value={value}>{children}</WorkspaceContext.Provider>;
}

export function useWorkspace(): WorkspaceContextValue {
  const ctx = useContext(WorkspaceContext);
  if (!ctx) throw new Error("useWorkspace must be used inside WorkspaceProvider");
  return ctx;
}
