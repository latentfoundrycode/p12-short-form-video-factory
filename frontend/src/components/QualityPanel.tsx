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

function parseRankings(raw: unknown): Record<string, number> {
  const rec = asRecord(raw);
  if (rec === null) {
    return {};
  }
  const out: Record<string, number> = {};
  for (const [key, value] of Object.entries(rec)) {
    if (typeof value === "number" && Number.isInteger(value) && value > 0) {
      out[key] = value;
    }
  }
  return out;
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

function rankingsFromVideos(
  videos: VideoRecord[],
  factors: QualityFactor[],
): Record<string, number[]> {
  const parsed = [...videos]
    .sort((a, b) => a.index - b.index)
    .map((video) => ({
      index: video.index,
      rankings: parseRankings(video.quality?.rankings),
    }));
  const rankings: Record<string, number[]> = {};
  for (const factor of factors) {
    rankings[factor.key] = [...parsed]
      .sort((a, b) => {
        const aPosition = a.rankings[factor.key];
        const bPosition = b.rankings[factor.key];
        if (aPosition !== undefined && bPosition !== undefined) {
          return aPosition - bPosition || a.index - b.index;
        }
        if (aPosition !== undefined) {
          return -1;
        }
        if (bPosition !== undefined) {
          return 1;
        }
        return a.index - b.index;
      })
      .map((video) => video.index);
  }
  return rankings;
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
  const [rankings, setRankings] = useState<Record<string, number[]>>({});
  const [syncedVideos, setSyncedVideos] = useState(videos);
  const [syncedFactors, setSyncedFactors] = useState(factors);
  const [formError, setFormError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  if (videos !== syncedVideos || factors !== syncedFactors) {
    setSyncedVideos(videos);
    setSyncedFactors(factors);
    setDrafts(factors !== null && factors.length > 0 ? draftsFromVideos(videos, factors) : []);
    setRankings(factors !== null && factors.length > 0 ? rankingsFromVideos(videos, factors) : {});
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
      await submitQuality(workflowId, runId, {
        videos: collectSubmission(drafts),
        ...(drafts.length >= 2 ? { rankings } : {}),
      });
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

  function moveRanking(factorKey: string, videoIndex: number, direction: -1 | 1) {
    setRankings((prev) => {
      const current = prev[factorKey];
      if (current === undefined) {
        return prev;
      }
      const position = current.indexOf(videoIndex);
      const target = position + direction;
      if (position < 0 || target < 0 || target >= current.length) {
        return prev;
      }
      const next = current.map((value, index) => {
        if (index === position) {
          return current[target] ?? value;
        }
        if (index === target) {
          return current[position] ?? value;
        }
        return value;
      });
      return { ...prev, [factorKey]: next };
    });
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
        {drafts.length >= 2
          ? factors.map((factor) => {
              const order = rankings[factor.key] ?? [];
              return (
                <div className="rank" key={factor.key}>
                  <div className="rank-label">Rank the {drafts.length} videos of this request</div>
                  <div className="factor-q">{factor.question}</div>
                  <div className="rank-list">
                    {order.map((videoIndex, position) => {
                      const label = videoLabel(videoIndex);
                      return (
                        <div className="rank-item" key={videoIndex}>
                          <span className="rank-pos">{position + 1}</span>
                          <span>{label}</span>
                          <button
                            type="button"
                            className="btn btn-sm"
                            disabled={submitting || position === 0}
                            aria-label={`Move ${label} up for ${factor.key}`}
                            onClick={() => {
                              moveRanking(factor.key, videoIndex, -1);
                            }}
                          >
                            Move up
                          </button>
                          <button
                            type="button"
                            className="btn btn-sm"
                            disabled={submitting || position === order.length - 1}
                            aria-label={`Move ${label} down for ${factor.key}`}
                            onClick={() => {
                              moveRanking(factor.key, videoIndex, 1);
                            }}
                          >
                            Move down
                          </button>
                        </div>
                      );
                    })}
                  </div>
                </div>
              );
            })
          : null}
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
