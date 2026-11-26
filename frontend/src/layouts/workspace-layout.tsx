import { Outlet } from "react-router";
import { BackendBanner } from "@/components/backend-banner";
import { Brand } from "@/components/brand";
import { HealthIndicator } from "@/components/health-indicator";
import { PatientSwitcher } from "@/components/patient-switcher";
import { Sidebar, SidebarNav } from "@/components/sidebar";
import { Badge } from "@/components/ui/badge";

export function WorkspaceLayout() {
  return (
    <div className="flex min-h-screen">
      <Sidebar />
      <div className="flex min-w-0 flex-1 flex-col">
        <header className="sticky top-0 z-10 border-b border-line bg-surface/95 backdrop-blur">
          <div className="flex h-14 items-center gap-4 px-5 lg:px-8">
            <div className="lg:hidden">
              <Brand subtitle={false} />
            </div>
            <div className="hidden text-[13px] text-ink-muted lg:block">Workspace</div>
            <div className="ml-auto flex items-center gap-4">
              <Badge tone="neutral" className="hidden sm:inline-flex">Synthetic demonstration data</Badge>
              <HealthIndicator />
            </div>
          </div>
          {/* below the lg breakpoint the sidebar collapses into this bar */}
          <div className="space-y-3 border-t border-line px-5 py-2 lg:hidden">
            <PatientSwitcher />
            <SidebarNav orientation="horizontal" />
          </div>
        </header>
        <BackendBanner />
        <main className="flex-1 px-5 py-6 lg:px-8 lg:py-8">
          <div className="mx-auto max-w-6xl">
            <Outlet />
          </div>
        </main>
      </div>
    </div>
  );
}
