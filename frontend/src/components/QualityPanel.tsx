import { useEffect, useState, type FormEvent } from "react";
import { fetchWorkflows, submitQuality } from "../api";
import type { QualityFactor, VideoQualityInput, VideoRecord } from "../types";

type QualityPanelProps = {
  workflowId: string;
  runId: string;
  videos: VideoRecord[];
  onSaved: () => void;
};

type VideoDraft = {
  index: number;
  answers: Record<string, string>;
  accepted: boolean | null;
};

function asRecord(value: unknown): Record<string, unknown> | null {
  if (typeof value === "object" && value !== null && !Array.isArray(value)) {
    return value as Record<string, unknown>;
  }
  return null;
}

function parseAnswers(raw: unknown): Record<string, string> {
  const rec = asRecord(raw);
  if (rec === null) {
    return {};
  }
  const out: Record<string, string> = {};
  for (const [key, value] of Object.entries(rec)) {
    if (typeof value === "string") {
      out[key] = value;
    }
  }
  return out;
}

function parseAccepted(raw: unknown): boolean | null {
  return typeof raw === "boolean" ? raw : null;
}

function parseQuality(quality: Record<string, unknown> | null | undefined): {
  answers: Record<string, string>;
  accepted: boolean | null;
} {
  if (quality == null) {
    return { answers: {}, accepted: null };
  }
  return {
    answers: parseAnswers(quality.answers),
    accepted: parseAccepted(quality.accepted),
  };
}

function draftsFromVideos(videos: VideoRecord[], factors: QualityFactor[]): VideoDraft[] {
  return [...videos]
    .sort((a, b) => a.index - b.index)
    .map((video) => {
      const parsed = parseQuality(video.quality);
      const answers: Record<string, string> = {};
      for (const factor of factors) {
        answers[factor.key] = parsed.answers[factor.key] ?? "";
      }
      return { index: video.index, answers, accepted: parsed.accepted };
    });
}

function collectSubmission(drafts: VideoDraft[]): VideoQualityInput[] {
  const videos: VideoQualityInput[] = [];
  for (const draft of drafts) {
    const answers: Record<string, string> = {};
    for (const [key, text] of Object.entries(draft.answers)) {
      if (text.trim().length > 0) {
        answers[key] = text;
      }
    }
    if (Object.keys(answers).length === 0 && draft.accepted === null) {
      continue;
    }
    videos.push({ index: draft.index, answers, accepted: draft.accepted });
  }
  return videos;
}

function videoLabel(index: number): string {
  return `Video ${String(index).padStart(2, "0")}`;
}

export function QualityPanel({ workflowId, runId, videos, onSaved }: QualityPanelProps) {
  const [factors, setFactors] = useState<QualityFactor[] | null>(null);
  const [drafts, setDrafts] = useState<VideoDraft[]>([]);
  const [syncedVideos, setSyncedVideos] = useState(videos);
  const [syncedFactors, setSyncedFactors] = useState(factors);
  const [formError, setFormError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  if (videos !== syncedVideos || factors !== syncedFactors) {
    setSyncedVideos(videos);
    setSyncedFactors(factors);
    setDrafts(factors !== null && factors.length > 0 ? draftsFromVideos(videos, factors) : []);
  }

  useEffect(() => {
    let cancelled = false;
    void fetchWorkflows().then(
      (list) => {
        if (!cancelled) {
          const found = list.find((workflow) => workflow.id === workflowId);
          setFactors(found?.quality_factors ?? []);
        }
      },
      () => {
        if (!cancelled) {
          setFactors([]);
        }
      },
    );
    return () => {
      cancelled = true;
    };
  }, [workflowId]);

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    setFormError(null);
    setSubmitting(true);
    try {
      await submitQuality(workflowId, runId, { videos: collectSubmission(drafts) });
      onSaved();
    } catch (err) {
      setFormError(err instanceof Error ? err.message : "Could not save judgement");
    } finally {
      setSubmitting(false);
    }
  }

  function setAnswer(index: number, key: string, value: string) {
    setDrafts((prev) =>
      prev.map((draft) =>
        draft.index === index ? { ...draft, answers: { ...draft.answers, [key]: value } } : draft,
      ),
    );
  }

  function toggleVerdict(index: number, value: boolean) {
    setDrafts((prev) =>
      prev.map((draft) =>
        draft.index === index
          ? { ...draft, accepted: draft.accepted === value ? null : value }
          : draft,
      ),
    );
  }

  if (factors === null || factors.length === 0) {
    return null;
  }

  return (
    <div className="panel">
      <div className="panel-head">
        <span className="eyebrow">Your judgement</span>
        <span className="rq-meta">words, no scores</span>
      </div>
      <form className="panel-body" onSubmit={(e) => void onSubmit(e)}>
        {drafts.map((draft) => (
          <div className="q-video" key={draft.index}>
            <div className="eyebrow">{videoLabel(draft.index)}</div>
            {factors.map((factor) => (
              <label className="factor" key={factor.key}>
                <span className="factor-q">{factor.question}</span>
                <textarea
                  className="ta"
                  value={draft.answers[factor.key] ?? ""}
                  disabled={submitting}
                  onChange={(e) => {
                    setAnswer(draft.index, factor.key, e.target.value);
                  }}
                />
              </label>
            ))}
            <div className="verdict">
              <button
                type="button"
                className={draft.accepted === true ? "btn btn-primary btn-sm" : "btn btn-sm"}
                disabled={submitting}
                aria-pressed={draft.accepted === true}
                onClick={() => {
                  toggleVerdict(draft.index, true);
                }}
              >
                Accepted
              </button>
              <button
                type="button"
                className={draft.accepted === false ? "btn btn-primary btn-sm" : "btn btn-sm"}
                disabled={submitting}
                aria-pressed={draft.accepted === false}
                onClick={() => {
                  toggleVerdict(draft.index, false);
                }}
              >
                Reject
              </button>
            </div>
          </div>
        ))}
        {formError ? <div className="form-error">{formError}</div> : null}
        <div className="card-foot">
          <button type="submit" className="btn btn-primary btn-sm" disabled={submitting}>
            {submitting ? "Saving…" : "Save judgement"}
          </button>
        </div>
      </form>
    </div>
  );
}
