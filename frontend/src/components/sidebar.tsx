import { Activity, FileText, GitCompareArrows, LayoutDashboard, ListChecks, ScrollText, Search } from "lucide-react";
import type { ReactNode } from "react";
import { NavLink } from "react-router";
import { APP_VERSION } from "@/api/backend-status";
import { useHealth } from "@/api/health";
import { Brand } from "@/components/brand";
import { PatientSwitcher } from "@/components/patient-switcher";
import { cn } from "@/lib/utils";

export interface NavItem {
  label: string;
  to: string;
  icon: ReactNode;
}

/** Every workspace screen. All are built; there are no placeholder pages. */
export const NAV_ITEMS: NavItem[] = [
  { label: "Overview", to: "/workspace/overview", icon: <LayoutDashboard /> },
  { label: "Documents", to: "/workspace/documents", icon: <FileText /> },
  { label: "Clinical Timeline", to: "/workspace/timeline", icon: <Activity /> },
  { label: "Reconciliation", to: "/workspace/reconciliation", icon: <GitCompareArrows /> },
  { label: "Evidence Search", to: "/workspace/search", icon: <Search /> },
  { label: "Review Queue", to: "/workspace/review", icon: <ListChecks /> },
  { label: "Summary", to: "/workspace/summary", icon: <ScrollText /> },
];

const itemBase = "group flex h-9 items-center gap-2.5 rounded-md px-2.5 text-[13px] font-medium [&_svg]:size-4 [&_svg]:shrink-0";

export function SidebarNav({ orientation = "vertical" }: { orientation?: "vertical" | "horizontal" }) {
  return (
    <nav aria-label="Workspace">
      <ul className={cn(orientation === "vertical" ? "space-y-0.5" : "flex gap-1 overflow-x-auto")}>
        {NAV_ITEMS.map((item) => (
          <li key={item.to} className="shrink-0">
            <NavLink
              to={item.to}
              className={({ isActive }) =>
                cn(itemBase, isActive ? "bg-brand-soft text-brand" : "text-ink-muted hover:bg-subtle hover:text-ink")
              }
            >
              {item.icon}
              {item.label}
            </NavLink>
          </li>
        ))}
      </ul>
    </nav>
  );
}

export function Sidebar() {
  return (
    <aside className="hidden w-60 shrink-0 flex-col border-r border-line bg-surface lg:flex">
      <div className="flex h-14 items-center border-b border-line px-4">
        <Brand />
      </div>
      <div className="border-b border-line px-4 py-3">
        <PatientSwitcher />
      </div>
      <div className="flex-1 overflow-y-auto px-2.5 py-3">
        <SidebarNav />
      </div>
      <div className="border-t border-line px-4 py-3 text-[11px] leading-snug text-ink-faint">
        <p>Synthetic records only. Documentation review prototype; not a diagnostic or treatment tool.</p>
        <BuildVersions />
      </div>
    </aside>
  );
}

/** Shows which build of each half is running, so a stale server is visible at a glance. */
function BuildVersions() {
  const health = useHealth();
  return (
    <p className="mt-2 font-mono text-[10px]" data-testid="build-versions">
      UI v{APP_VERSION} · API {health.data ? `v${health.data.version}` : "unknown"}
    </p>
  );
}
