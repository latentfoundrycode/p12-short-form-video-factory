import { useEffect, useState } from "react";
import { fetchRunFiles } from "../api";
import type { RunDetail, RunFile, SseEnvelope, StepEvent, VideoRecord } from "../types";

type RunRecordViewProps = {
  run: RunDetail;
  events: SseEnvelope[];
  workflowId: string;
  runId: string;
};

type CheckKind = "pass" | "fail" | "skip";

type CheckRowModel = {
  kind: CheckKind;
  text: string;
};

type SelfReviewStructural = {
  duration_s: number | null;
  width: number | null;
  height: number | null;
  has_audio: boolean;
  has_captions: boolean;
};

type SelfReviewContent = {
  black: boolean;
  silent: boolean;
  clipping: boolean;
  slideshow: boolean;
  audio_mean_dbfs: number | null;
  motion_score: number | null;
};

type CompositionViolation = {
  kind: string;
  detail: string;
};

type SelfReviewComposition = {
  checked: number;
  violations: CompositionViolation[];
};

type SelfReview = {
  passed: boolean;
  structural: SelfReviewStructural | null;
  content: SelfReviewContent | null;
  composition: SelfReviewComposition;
  failures: string[];
};

type MeterTotals = {
  actual: number;
  uncached: number;
};

function messageOf(err: unknown, fallback: string): string {
  return err instanceof Error ? err.message : fallback;
}

function asRecord(value: unknown): Record<string, unknown> | null {
  if (typeof value === "object" && value !== null && !Array.isArray(value)) {
    return value as Record<string, unknown>;
  }
  return null;
}

function asBool(value: unknown): boolean | null {
  return typeof value === "boolean" ? value : null;
}

function asFiniteNumber(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function asString(value: unknown): string | null {
  return typeof value === "string" ? value : null;
}

function parseStructural(raw: unknown): SelfReviewStructural | null {
  const rec = asRecord(raw);
  if (rec === null) {
    return null;
  }
  return {
    duration_s: asFiniteNumber(rec.duration_s),
    width: asFiniteNumber(rec.width),
    height: asFiniteNumber(rec.height),
    has_audio: asBool(rec.has_audio) ?? false,
    has_captions: asBool(rec.has_captions) ?? false,
  };
}

function parseContent(raw: unknown): SelfReviewContent | null {
  if (raw === null) {
    return null;
  }
  const rec = asRecord(raw);
  if (rec === null) {
    return null;
  }
  return {
    black: asBool(rec.black) ?? false,
    silent: asBool(rec.silent) ?? false,
    clipping: asBool(rec.clipping) ?? false,
    slideshow: asBool(rec.slideshow) ?? false,
    audio_mean_dbfs: asFiniteNumber(rec.audio_mean_dbfs),
    motion_score: asFiniteNumber(rec.motion_score),
  };
}

function parseViolations(raw: unknown): CompositionViolation[] {
  if (!Array.isArray(raw)) {
    return [];
  }
  const out: CompositionViolation[] = [];
  for (const item of raw) {
    const rec = asRecord(item);
    if (rec === null) {
      continue;
    }
    const kind = asString(rec.kind);
    const detail = asString(rec.detail);
    if (kind === null && detail === null) {
      continue;
    }
    out.push({ kind: kind ?? "", detail: detail ?? "" });
  }
  return out;
}

function parseComposition(raw: unknown): SelfReviewComposition {
  const rec = asRecord(raw);
  if (rec === null) {
    return { checked: 0, violations: [] };
  }
  return {
    checked: asFiniteNumber(rec.checked) ?? 0,
    violations: parseViolations(rec.violations),
  };
}

function parseFailures(raw: unknown): string[] {
  if (!Array.isArray(raw)) {
    return [];
  }
  return raw.filter((item): item is string => typeof item === "string" && item.length > 0);
}

function parseSelfReview(raw: Record<string, unknown> | null | undefined): SelfReview | null {
  if (raw == null) {
    return null;
  }
  return {
    passed: asBool(raw.passed) ?? false,
    structural: parseStructural(raw.structural),
    content: parseContent(raw.content),
    composition: parseComposition(raw.composition),
    failures: parseFailures(raw.failures),
  };
}

function parseMeterMap(raw: unknown): Record<string, number> {
  const rec = asRecord(raw);
  if (rec === null) {
    return {};
  }
  const out: Record<string, number> = {};
  for (const [meter, amount] of Object.entries(rec)) {
    const n = asFiniteNumber(amount);
    if (n !== null) {
      out[meter] = n;
    }
  }
  return out;
}

function formatSeconds(n: number): string {
  return Number.isInteger(n) ? `${n}s` : `${n.toFixed(1)}s`;
}

function formatDb(n: number): string {
  return n.toFixed(1);
}

function formatMeterAmount(n: number): string {
  if (Number.isInteger(n)) {
    return n.toLocaleString();
  }
  return n.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function formatSize(bytes: number): string {
  if (bytes < 1024) {
    return `${bytes} B`;
  }
  const kb = bytes / 1024;
  if (kb < 1024) {
    return `${kb >= 10 ? kb.toFixed(0) : kb.toFixed(1)} KB`;
  }
  const mb = kb / 1024;
  if (mb < 1024) {
    return `${mb >= 10 ? mb.toFixed(0) : mb.toFixed(1)} MB`;
  }
  const gb = mb / 1024;
  return `${gb >= 10 ? gb.toFixed(0) : gb.toFixed(1)} GB`;
}

function videoIndexFromPath(path: string): number | null {
  const match = /^(\d+)\//.exec(path);
  if (match === null) {
    return null;
  }
  return Number.parseInt(match[1], 10);
}

function stripVideoPrefix(path: string): string {
  const stripped = path.replace(/^\d+\//, "");
  return stripped.length > 0 ? stripped : path;
}

function isRunFile(item: unknown): item is RunFile {
  const rec = asRecord(item);
  return rec !== null && typeof rec.path === "string" && typeof rec.size === "number";
}

function isStepEvent(event: SseEnvelope["event"]): event is StepEvent {
  if (event.t !== "step") {
    return false;
  }
  return (
    typeof event.name === "string" &&
    typeof event.key === "string" &&
    typeof event.label === "string" &&
    typeof event.status === "string"
  );
}

function stepTag(status: string): "reused" | "gate" | null {
  if (status === "cached") {
    return "reused";
  }
  if (status === "gate") {
    return "gate";
  }
  return null;
}

function fileValidText(structural: SelfReviewStructural | null): string {
  if (structural === null) {
    return "File valid";
  }
  const parts: string[] = ["File valid"];
  if (structural.duration_s !== null) {
    parts.push(formatSeconds(structural.duration_s));
  }
  if (structural.width !== null && structural.height !== null) {
    parts.push(`${structural.width}×${structural.height}`);
  }
  return parts.join(" · ");
}

function audioPassText(content: SelfReviewContent): string {
  const bits: string[] = ["Audio"];
  if (content.audio_mean_dbfs !== null) {
    bits.push(`mean ${formatDb(content.audio_mean_dbfs)} dBFS`);
  }
  bits.push("no clipping");
  return bits.join(" · ");
}

function audioFailText(content: SelfReviewContent): string {
  const bits: string[] = ["Audio"];
  if (content.silent) {
    bits.push("silent");
  }
  if (content.clipping) {
    bits.push("clipping");
  }
  if (content.audio_mean_dbfs !== null) {
    bits.push(`mean ${formatDb(content.audio_mean_dbfs)} dBFS`);
  }
  return bits.length > 1 ? bits.join(" · ") : "Audio";
}

function motionText(content: SelfReviewContent, slideshow: boolean): string {
  const label = slideshow ? "slideshow" : "not a slideshow";
  const score = content.motion_score !== null ? `motion ${content.motion_score}` : null;
  return score === null
    ? `Motion / slideshow · ${label}`
    : `Motion / slideshow · ${label} · ${score}`;
}

function checkRows(review: SelfReview): CheckRowModel[] {
  const rows: CheckRowModel[] = [{ kind: "pass", text: fileValidText(review.structural) }];
  const content = review.content;
  const structural = review.structural;

  if (content === null) {
    rows.push({ kind: "skip", text: "No black or broken frames · not checked (dry run)" });
  } else if (content.black) {
    rows.push({ kind: "fail", text: "No black or broken frames" });
  } else {
    rows.push({ kind: "pass", text: "No black or broken frames" });
  }

  if (content === null) {
    rows.push({ kind: "skip", text: "Audio · not checked (dry run)" });
  } else if (structural !== null && !structural.has_audio) {
    rows.push({ kind: "skip", text: "Audio · no audio track" });
  } else if (!content.silent && !content.clipping) {
    rows.push({ kind: "pass", text: audioPassText(content) });
  } else {
    rows.push({ kind: "fail", text: audioFailText(content) });
  }

  if (structural !== null && structural.has_captions) {
    rows.push({ kind: "pass", text: "Captions · present" });
  } else {
    rows.push({ kind: "skip", text: "Captions · none" });
  }

  if (content === null) {
    rows.push({ kind: "skip", text: "Motion / slideshow · not checked (dry run)" });
  } else if (content.slideshow) {
    rows.push({ kind: "skip", text: motionText(content, true) });
  } else {
    rows.push({ kind: "pass", text: motionText(content, false) });
  }

  const composition = review.composition;
  if (composition.checked > 0) {
    if (composition.violations.length === 0) {
      rows.push({
        kind: "pass",
        text: `Composition · ${composition.checked} checked, no issues`,
      });
    } else {
      for (const violation of composition.violations) {
        const body = [violation.kind, violation.detail]
          .filter((part) => part.length > 0)
          .join(": ");
        rows.push({ kind: "fail", text: body });
      }
    }
  }

  return rows;
}

function CheckRow({ kind, text }: CheckRowModel) {
  const icon = kind === "pass" ? "✓" : kind === "fail" ? "✗" : "–";
  return (
    <div className={`check check-${kind}`}>
      <span className="check-ico" aria-hidden="true">
        {icon}
      </span>
      <span>{text}</span>
    </div>
  );
}

function SelfReviewPanel({ video }: { video: VideoRecord }) {
  const review = parseSelfReview(video.self_review);
  return (
    <div className="panel">
      <div className="panel-head">
        <span className="eyebrow">Self-review · #{video.index}</span>
        {review ? (
          <span className={review.passed ? "pill done" : "pill fail"}>
            {review.passed ? "Passed" : "Failed"}
          </span>
        ) : null}
      </div>
      <div className="panel-body check-body">
        {review === null ? (
          <div className="page-note">No self-review recorded</div>
        ) : (
          <>
            {checkRows(review).map((row, i) => (
              <CheckRow key={`${row.kind}-${i}`} kind={row.kind} text={row.text} />
            ))}
            {review.failures.length > 0 ? (
              <ul className="review-failures">
                {review.failures.map((failure, i) => (
                  <li key={`${i}-${failure}`} className="review-failure">
                    {failure}
                  </li>
                ))}
              </ul>
            ) : null}
          </>
        )}
      </div>
    </div>
  );
}

function StepsPanel({ events }: { events: SseEnvelope[] }) {
  const steps = events.map((envelope) => envelope.event).filter(isStepEvent);
  const reused = steps.filter((step) => step.status === "cached").length;
  return (
    <div className="panel">
      <div className="panel-head">
        <span className="eyebrow">Steps</span>
        <span className="rq-meta">
          {steps.length} step{steps.length === 1 ? "" : "s"}
          {reused > 0 ? ` · ${reused} reused` : ""}
        </span>
      </div>
      <div className="panel-body steps-body">
        {steps.length === 0 ? (
          <div className="page-note">No steps recorded.</div>
        ) : (
          <div className="steps">
            {steps.map((step, index) => {
              const tag = stepTag(step.status);
              const name = step.name.length > 0 ? step.name : step.label;
              return (
                <div key={`${step.key}-${index}`} className="step">
                  <span className="step-n">{String(index + 1).padStart(2, "0")}</span>
                  <span className="step-name">{name}</span>
                  {tag ? <span className="tag-cache">{tag}</span> : null}
                  <span className="step-t">{step.status}</span>
                </div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}

function aggregateCost(records: VideoRecord[]): Map<string, MeterTotals> {
  const meters = new Map<string, MeterTotals>();
  for (const video of records) {
    const rec = asRecord(video.cost);
    if (rec === null) {
      continue;
    }
    const uncached = parseMeterMap(rec.uncached);
    const actual = parseMeterMap(rec.actual);
    for (const [meter, amount] of Object.entries(uncached)) {
      const entry = meters.get(meter) ?? { actual: 0, uncached: 0 };
      entry.uncached += amount;
      meters.set(meter, entry);
    }
    for (const [meter, amount] of Object.entries(actual)) {
      const entry = meters.get(meter) ?? { actual: 0, uncached: 0 };
      entry.actual += amount;
      meters.set(meter, entry);
    }
  }
  return meters;
}

function unitsFromEvents(events: SseEnvelope[]): Map<string, string> {
  const units = new Map<string, string>();
  for (const envelope of events) {
    const event = envelope.event;
    if (event.t !== "cost") {
      continue;
    }
    const meter = "meter" in event ? event.meter : undefined;
    const unit = "unit" in event ? event.unit : undefined;
    if (typeof meter === "string" && typeof unit === "string" && unit.length > 0) {
      units.set(meter, unit);
    }
  }
  return units;
}

function CostPanel({ records, events }: { records: VideoRecord[]; events: SseEnvelope[] }) {
  const meters = aggregateCost(records);
  const units = unitsFromEvents(events);
  const names = [...meters.keys()];
  return (
    <div className="panel">
      <div className="panel-head">
        <span className="eyebrow">Cost</span>
      </div>
      <div className="panel-body">
        {names.length === 0 ? (
          <div className="page-note">No cost recorded.</div>
        ) : (
          <div className="meters">
            {names.map((name) => {
              const totals = meters.get(name);
              if (totals === undefined) {
                return null;
              }
              const unit = units.get(name);
              return (
                <div className="meter lg" key={name}>
                  <div className="meter-name">{name}</div>
                  <div className="meter-val">
                    {formatMeterAmount(totals.actual)}
                    {unit ? <span className="meter-unit">{unit}</span> : null}
                  </div>
                  <div className="meter-sub">
                    {formatMeterAmount(totals.uncached)} without cache
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}

function ArtifactList({ files }: { files: RunFile[] }) {
  if (files.length === 0) {
    return <div className="page-note">No artifacts recorded.</div>;
  }
  return (
    <div className="artifact-list">
      {files.map((file) => (
        <div className="artifact-row" key={file.path}>
          <b>{file.path}</b>
          <span>{formatSize(file.size)}</span>
        </div>
      ))}
    </div>
  );
}

function ArtifactsPanel({ title, files }: { title: string; files: RunFile[] }) {
  return (
    <div className="panel">
      <div className="panel-head">
        <span className="eyebrow">{title}</span>
        <span className="rq-meta">
          {files.length} file{files.length === 1 ? "" : "s"}
        </span>
      </div>
      <div className="panel-body">
        <ArtifactList files={files} />
      </div>
    </div>
  );
}

export function RunRecordView({ run, events, workflowId, runId }: RunRecordViewProps) {
  const [files, setFiles] = useState<RunFile[] | null>(null);
  const [filesError, setFilesError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    void fetchRunFiles(workflowId, runId).then(
      (data) => {
        if (!cancelled) {
          setFiles(data.files.filter(isRunFile));
          setFilesError(null);
        }
      },
      (err: unknown) => {
        if (!cancelled) {
          setFiles([]);
          setFilesError(messageOf(err, "Could not load artifacts"));
        }
      },
    );
    return () => {
      cancelled = true;
    };
  }, [workflowId, runId]);

  const runLevel: RunFile[] = [];
  const byVideo = new Map<number, RunFile[]>();
  for (const file of files ?? []) {
    const index = videoIndexFromPath(file.path);
    if (index === null) {
      runLevel.push(file);
      continue;
    }
    const group = byVideo.get(index) ?? [];
    group.push({ ...file, path: stripVideoPrefix(file.path) });
    byVideo.set(index, group);
  }

  const records = [...run.video_records].sort((a, b) => a.index - b.index);
  const extraIndexes = [...byVideo.keys()]
    .filter((index) => !records.some((video) => video.index === index))
    .sort((a, b) => a - b);

  return (
    <div className="run-record">
      <CostPanel records={records} events={events} />
      <div className="record-grid">
        <div className="stack">
          <StepsPanel events={events} />
          {filesError ? (
            <div className="panel">
              <div className="panel-head">
                <span className="eyebrow">Artifacts</span>
              </div>
              <div className="panel-body">
                <div className="page-note">{filesError}</div>
              </div>
            </div>
          ) : files === null ? (
            <div className="panel">
              <div className="panel-head">
                <span className="eyebrow">Artifacts</span>
              </div>
              <div className="panel-body">
                <div className="page-note">Loading artifacts…</div>
              </div>
            </div>
          ) : runLevel.length > 0 || byVideo.size === 0 ? (
            <ArtifactsPanel title="Artifacts" files={runLevel} />
          ) : null}
        </div>
        <div className="stack">
          {records.length === 0 ? (
            <div className="panel">
              <div className="panel-head">
                <span className="eyebrow">Self-review</span>
              </div>
              <div className="panel-body">
                <div className="page-note">No video records.</div>
              </div>
            </div>
          ) : (
            records.map((video) => (
              <div className="stack" key={video.index}>
                <SelfReviewPanel video={video} />
                {files !== null && !filesError && (byVideo.get(video.index)?.length ?? 0) > 0 ? (
                  <ArtifactsPanel
                    title={`Artifacts · #${video.index}`}
                    files={byVideo.get(video.index) ?? []}
                  />
                ) : null}
              </div>
            ))
          )}
          {files !== null && !filesError
            ? extraIndexes.map((index) => (
                <ArtifactsPanel
                  key={index}
                  title={`Artifacts · #${index}`}
                  files={byVideo.get(index) ?? []}
                />
              ))
            : null}
        </div>
      </div>
    </div>
  );
}
