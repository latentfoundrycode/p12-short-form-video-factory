import { useState } from "react";
import type { Workflow } from "../types";
import { RunLaunchForm } from "./RunLaunchForm";

function EmptyThumb() {
  return (
    <div className="thumb thumb-empty">
      <span className="ico">
        <svg
          width="18"
          height="18"
          viewBox="0 0 16 16"
          fill="none"
          stroke="currentColor"
          strokeWidth="1.3"
        >
          <rect x="1.8" y="3.4" width="12.4" height="10.8" rx="1" />
          <path d="M1.8 6.6h12.4M6.2 9.6h3.6" />
        </svg>
      </span>
    </div>
  );
}

function Thumb({ url }: { url: string | null }) {
  const [failed, setFailed] = useState(false);
  if (!url || failed) {
    return <EmptyThumb />;
  }
  return (
    <div className="thumb">
      <img
        src={url}
        alt=""
        onError={() => {
          setFailed(true);
        }}
      />
    </div>
  );
}

type WorkflowCardProps = {
  workflow: Workflow;
  onStarted: (runId: string) => void;
};

export function WorkflowCard({ workflow, onStarted }: WorkflowCardProps) {
  const [launching, setLaunching] = useState(false);
  const title = workflow.name ?? workflow.id;
  const broken = !workflow.valid;
  const warnings = workflow.problems.filter((problem) => problem.severity === "warning");
  const errors = workflow.problems.filter((problem) => problem.severity === "error");

  if (launching) {
    return (
      <RunLaunchForm
        workflowId={workflow.id}
        workflowName={title}
        onCancel={() => {
          setLaunching(false);
        }}
        onStarted={(runId) => {
          setLaunching(false);
          onStarted(runId);
        }}
      />
    );
  }

  return (
    <article className={broken ? "card s-fail" : "card"}>
      <Thumb url={workflow.thumbnail_url} />
      <div className="card-body">
        <div className="card-top">
          <div>
            <div className="card-title">{title}</div>
            {workflow.description ? <div className="card-desc">{workflow.description}</div> : null}
          </div>
          {broken ? <span className="pill fail">Broken</span> : <span className="pill">Idle</span>}
        </div>
        {broken ? (
          <div className="card-state fail">
            {errors.map((problem, index) => (
              <span key={`${problem.code}-${index}`}>{problem.message}</span>
            ))}
          </div>
        ) : null}
        {!broken && warnings.length > 0 ? (
          <div className="card-state warn">
            <span className="pill warn">Warning</span>
            {warnings.map((problem, index) => (
              <span key={`${problem.code}-${index}`}>{problem.message}</span>
            ))}
          </div>
        ) : null}
        {!broken ? (
          <div className="card-foot">
            <button
              type="button"
              className="btn btn-primary btn-sm"
              onClick={() => {
                setLaunching(true);
              }}
            >
              Run workflow
            </button>
          </div>
        ) : null}
      </div>
    </article>
  );
}
