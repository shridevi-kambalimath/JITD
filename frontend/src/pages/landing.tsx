import { ArrowRight, Database, FileSearch, GitCompareArrows, ListChecks, Quote, ShieldCheck, Waypoints } from "lucide-react";
import { Link, useNavigate } from "react-router";
import { useLoadDemo } from "@/api/documents";
import { BackendBanner } from "@/components/backend-banner";
import { Brand } from "@/components/brand";
import { ErrorState } from "@/components/error-state";
import { HealthIndicator } from "@/components/health-indicator";
import { Button, buttonVariants } from "@/components/ui/button";
import { DEFAULT_PATIENT_ID, useWorkspace } from "@/context/workspace";

const WORKFLOW = [
  { icon: <Database />, title: "Documents", text: "Admission notes, labs, progress notes, medication lists, discharge summaries." },
  { icon: <Quote />, title: "Structured claims", text: "Diagnoses, medications, results and events, each tied to an exact passage." },
  { icon: <FileSearch />, title: "Source traceability", text: "Every claim cites its document and character span." },
  { icon: <Waypoints />, title: "Timeline", text: "Event dates kept apart from document dates; uncertain dates stay uncertain." },
  { icon: <GitCompareArrows />, title: "Reconciliation", text: "Disagreements between records are preserved side by side, not resolved." },
  { icon: <ShieldCheck />, title: "Verification", text: "Rule-based checks decide what the evidence supports and when to stop." },
  { icon: <ListChecks />, title: "Human review", text: "Unresolved items go to a reviewer with the evidence attached." },
];

export function LandingPage() {
  const navigate = useNavigate();
  const { setPatientId } = useWorkspace();
  const demo = useLoadDemo();

  function openDemo() {
    demo.mutate(DEFAULT_PATIENT_ID, {
      onSuccess: () => {
        setPatientId(DEFAULT_PATIENT_ID);
        navigate("/workspace/overview");
      },
    });
  }

  return (
    <div className="min-h-screen bg-canvas">
      <header className="border-b border-line bg-surface">
        <div className="mx-auto flex h-14 max-w-6xl items-center justify-between px-6">
          <Brand />
          <HealthIndicator />
        </div>
      </header>
      <BackendBanner />

      <main className="mx-auto max-w-6xl px-6">
        <section className="grid gap-10 py-16 lg:grid-cols-[1.2fr_1fr] lg:py-20">
          <div>
            <p className="text-[12px] font-medium uppercase tracking-[0.08em] text-brand">
              Clinical documentation reconciliation · synthetic prototype
            </p>
            <h1 className="mt-3 text-[36px] font-semibold leading-[1.15] tracking-tight text-ink lg:text-[42px]">
              Reconstruct what the records actually say.
            </h1>
            <p className="mt-4 max-w-xl text-[15px] leading-relaxed text-ink-muted">
              MEDUSA-X turns fragmented clinical documents into traceable claims, a reconstructed timeline and a list
              of documentation discrepancies. It never fills gaps or picks a winner between conflicting records. It
              shows the evidence, and stops for human review where the evidence runs out.
            </p>
            <div className="mt-8 flex flex-wrap items-center gap-3">
              <Link to="/workspace/overview" className={buttonVariants({ size: "lg" })}>
                Enter workspace
                <ArrowRight />
              </Link>
              <Button variant="secondary" size="lg" onClick={openDemo} loading={demo.isPending}>
                Open synthetic demo workspace
              </Button>
            </div>
            <p className="mt-3 text-[12px] text-ink-faint">
              The demo loads fictional documents for patient {DEFAULT_PATIENT_ID} through the real ingestion pipeline.
            </p>
            {demo.isError && <ErrorState className="mt-4 max-w-xl" error={demo.error} onRetry={openDemo} />}
          </div>

          <aside className="self-start rounded-lg border border-line bg-surface p-5 shadow-panel">
            <h2 className="text-[13px] font-semibold uppercase tracking-[0.06em] text-ink-muted">What it is not</h2>
            <ul className="mt-3 space-y-2.5 text-[13px] text-ink">
              <li className="flex gap-2"><span className="text-review">✕</span>Not a diagnostic or treatment recommendation system.</li>
              <li className="flex gap-2"><span className="text-review">✕</span>Not a chatbot: no free-text answers without citations.</li>
              <li className="flex gap-2"><span className="text-review">✕</span>Never decides which conflicting record is clinically correct.</li>
              <li className="flex gap-2"><span className="text-supported">✓</span>Synthetic records only. Do not upload real patient data.</li>
            </ul>
          </aside>
        </section>

        <section className="border-t border-line py-12" aria-labelledby="workflow-heading">
          <h2 id="workflow-heading" className="text-[13px] font-semibold uppercase tracking-[0.06em] text-ink-muted">
            Evidence-driven workflow
          </h2>
          <ol className="mt-6 grid gap-px overflow-hidden rounded-lg border border-line bg-line sm:grid-cols-2 lg:grid-cols-7">
            {WORKFLOW.map((step, i) => (
              <li key={step.title} className="bg-surface p-4">
                <div className="flex items-center gap-2 text-brand [&_svg]:size-4">
                  {step.icon}
                  <span className="font-mono text-[11px] text-ink-faint">{String(i + 1).padStart(2, "0")}</span>
                </div>
                <p className="mt-2 text-[13px] font-semibold text-ink">{step.title}</p>
                <p className="mt-1 text-[12px] leading-snug text-ink-muted">{step.text}</p>
              </li>
            ))}
          </ol>
        </section>
      </main>

      <footer className="border-t border-line">
        <p className="mx-auto max-w-6xl px-6 py-5 text-[12px] text-ink-faint">
          Hackathon prototype. Outputs are not clinically validated and require review by a qualified clinician.
        </p>
      </footer>
    </div>
  );
}
