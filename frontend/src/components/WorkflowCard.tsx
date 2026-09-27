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

function formatAvgCost(amount: number): string {
  if (!Number.isFinite(amount)) {
    return "—";
  }
  if (Number.isInteger(amount)) {
    return String(amount);
  }
  return amount.toFixed(2);
}

function meterLabel(id: string): string {
  if (id.length === 0) {
    return id;
  }
  return id.charAt(0).toUpperCase() + id.slice(1);
}

type CardPresentation = {
  cardClass: string;
  pillClass: string;
  pillText: string;
  showValidationErrors: boolean;
  showAvgCost: boolean;
  hideRun: boolean;
  stateLines: string[];
};

function resolvePresentation(workflow: Workflow, seen: boolean): CardPresentation {
  if (workflow.archived) {
    return {
      cardClass: "card s-arch",
      pillClass: "pill",
      pillText: "Archived",
      showValidationErrors: false,
      showAvgCost: false,
      hideRun: true,
      stateLines: [],
    };
  }

  if (!workflow.valid) {
    return {
      cardClass: "card s-fail",
      pillClass: "pill fail",
      pillText: "Broken",
      showValidationErrors: true,
      showAvgCost: true,
      hideRun: true,
      stateLines: [],
    };
  }

  const status = workflow.last_run?.status;
  const stage = workflow.last_run?.stage;
  const progress = workflow.last_run?.progress;

  if (status === "running") {
    const stateLines: string[] = [];
    if (stage) {
      stateLines.push(`${stage.index} / ${stage.total} — ${stage.label}`);
    } else {
      stateLines.push("Running");
    }
    if (progress) {
      stateLines.push(`${progress.done} of ${progress.total}`);
    }
    return {
      cardClass: "card s-run",
      pillClass: "pill run",
      pillText: "Running",
      showValidationErrors: false,
      showAvgCost: true,
      hideRun: false,
      stateLines,
    };
  }

  if (status === "failed" || status === "stopped-budget") {
    return {
      cardClass: "card s-fail",
      pillClass: "pill fail",
      pillText: "Broken",
      showValidationErrors: false,
      showAvgCost: true,
      hideRun: true,
      stateLines: [],
    };
  }

  if ((status === "complete" || status === "partial") && !seen) {
    return {
      cardClass: "card s-done",
      pillClass: "pill done",
      pillText: "Finished",
      showValidationErrors: false,
      showAvgCost: true,
      hideRun: false,
      stateLines: [],
    };
  }

  return {
    cardClass: "card",
    pillClass: "pill idle",
    pillText: "Idle",
    showValidationErrors: false,
    showAvgCost: true,
    hideRun: false,
    stateLines: [],
  };
}

function AverageCostBlock({ workflow }: { workflow: Workflow }) {
  const entries = Object.entries(workflow.avg_cost_per_meter).filter(
    ([, amount]) => Number.isFinite(amount),
  );

  return (
    <div className="card-meters">
      <div className="avg-label">Average per video · last 10 runs</div>
      <div className="meters">
        {workflow.runs_counted === 0 ? (
          <div className="meter">
            <div className="meter-val none">No runs yet</div>
          </div>
        ) : (
          entries.map(([meterId, amount]) => (
            <div className="meter" key={meterId}>
              <div className="meter-name">{meterLabel(meterId)}</div>
              <div className="meter-val">{formatAvgCost(amount)}</div>
            </div>
          ))
        )}
      </div>
    </div>
  );
}

type WorkflowCardProps = {
  workflow: Workflow;
  seen: boolean;
  onStarted: (runId: string) => void;
  onViewRuns: (workflowId: string) => void;
};

export function WorkflowCard({ workflow, seen, onStarted, onViewRuns }: WorkflowCardProps) {
  const [launching, setLaunching] = useState(false);
  const title = workflow.name ?? workflow.id;
  const presentation = resolvePresentation(workflow, seen);
  const warnings = workflow.problems.filter((problem) => problem.severity === "warning");
  const errors = workflow.problems.filter((problem) => problem.severity === "error");

  if (launching) {
    return (
      <RunLaunchForm
        workflowId={workflow.id}
        workflowName={title}
        params={workflow.params}
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
    <article className={presentation.cardClass}>
      <Thumb url={workflow.thumbnail_url} />
      <div className="card-body">
        <div className="card-top">
          <div>
            <div className="card-title">{title}</div>
            {workflow.description ? <div className="card-desc">{workflow.description}</div> : null}
          </div>
          <span className={presentation.pillClass}>{presentation.pillText}</span>
        </div>
        {presentation.showValidationErrors ? (
          <div className="card-state fail">
            {errors.map((problem, index) => (
              <span key={`${problem.code}-${index}`}>{problem.message}</span>
            ))}
          </div>
        ) : null}
        {presentation.stateLines.length > 0 ? (
          <div className="card-state">
            {presentation.stateLines.map((line, index) => (
              <span key={index}>{line}</span>
            ))}
          </div>
        ) : null}
        {!presentation.showValidationErrors && warnings.length > 0 ? (
          <div className="card-state warn">
            <span className="pill warn">Warning</span>
            {warnings.map((problem, index) => (
              <span key={`${problem.code}-${index}`}>{problem.message}</span>
            ))}
          </div>
        ) : null}
        {presentation.showAvgCost ? <AverageCostBlock workflow={workflow} /> : null}
        <div className="card-foot">
          {!presentation.hideRun ? (
            <button
              type="button"
              className="btn btn-primary btn-sm"
              onClick={() => {
                setLaunching(true);
              }}
            >
              Run workflow
            </button>
          ) : null}
          <button
            type="button"
            className="btn btn-sm"
            onClick={() => {
              onViewRuns(workflow.id);
            }}
          >
            Runs
          </button>
        </div>
      </div>
    </article>
  );
}
