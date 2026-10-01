import { useRef } from "react";
import { Link } from "react-router-dom";
import { PageHeader } from "@/components/ui/blocks";
import { usePageIntro } from "@/lib/motion";

export default function NotFound() {
  const ref = useRef<HTMLDivElement>(null);
  usePageIntro(ref);
  return (
    <div ref={ref} className="pt-2">
      <PageHeader eyebrow="Lost in space" title="404" subtitle="This page does not exist." />
      <Link to="/" className="btn btn-primary ml-5 mt-6">
        Back to the dashboard
      </Link>
    </div>
  );
}
