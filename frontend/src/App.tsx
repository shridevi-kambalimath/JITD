import { Navigate, type RouteObject } from "react-router";
import { WorkspaceLayout } from "@/layouts/workspace-layout";
import { DocumentsPage } from "@/pages/documents";
import { EvidencePage } from "@/pages/evidence";
import { LandingPage } from "@/pages/landing";
import { NotFoundPage } from "@/pages/not-found";
import { OverviewPage } from "@/pages/overview";
import { ReconciliationPage } from "@/pages/reconciliation";
import { ReviewPage } from "@/pages/review";
import { SearchPage } from "@/pages/search";
import { SummaryPage } from "@/pages/summary";
import { TimelinePage } from "@/pages/timeline";

/** Route table, shared by the browser router (main.tsx) and memory routers in tests. */
export const routes: RouteObject[] = [
  { path: "/", element: <LandingPage /> },
  {
    path: "/workspace",
    element: <WorkspaceLayout />,
    children: [
      { index: true, element: <Navigate to="overview" replace /> },
      { path: "overview", element: <OverviewPage /> },
      { path: "documents", element: <DocumentsPage /> },
      { path: "timeline", element: <TimelinePage /> },
      { path: "reconciliation", element: <ReconciliationPage /> },
      { path: "evidence/:claimId", element: <EvidencePage /> },
      { path: "search", element: <SearchPage /> },
      { path: "review", element: <ReviewPage /> },
      { path: "summary", element: <SummaryPage /> },
      { path: "*", element: <NotFoundPage /> },
    ],
  },
  { path: "*", element: <div className="p-8"><NotFoundPage /></div> },
];
