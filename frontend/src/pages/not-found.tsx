import { Link } from "react-router";
import { EmptyState } from "@/components/empty-state";
import { buttonVariants } from "@/components/ui/button";

export function NotFoundPage() {
  return (
    <EmptyState
      className="min-h-[50vh]"
      title="Page not found"
      description="This screen does not exist. Use the sidebar, or go back to the overview."
      action={<Link to="/workspace/overview" className={buttonVariants({ variant: "secondary" })}>Go to overview</Link>}
    />
  );
}
