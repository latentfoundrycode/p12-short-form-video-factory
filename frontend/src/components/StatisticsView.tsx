import { useEffect, useState } from "react";
import { fetchStatistics } from "../api";
import type { StatSeries, Statistics } from "../types";

const MONTH_ABBREV = [
  "JAN",
  "FEB",
  "MAR",
  "APR",
  "MAY",
  "JUN",
  "JUL",
  "AUG",
  "SEP",
  "OCT",
  "NOV",
  "DEC",
] as const;

type MonthsWindow = 6 | 12 | 24;

function messageOf(err: unknown, fallback: string): string {
  return err instanceof Error ? err.message : fallback;
}

function formatAmount(amount: number, unit: string): string {
  if (unit === "usd") {
    return `$${amount.toLocaleString(undefined, {
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
    })}`;
  }
  if (unit === "credits") {
    return `${amount.toLocaleString(undefined, { maximumFractionDigits: 0 })} cr`;
  }
  return `${amount.toLocaleString()} ${unit}`;
}

function monthAbbrev(month: string): string {
  const mm = Number.parseInt(month.slice(5, 7), 10);
  if (mm >= 1 && mm <= 12) {
    return MONTH_ABBREV[mm - 1];
  }
  return month;
}

function barHeight(amount: number, max: number): string {
  if (max <= 0) {
    return "2px";
  }
  const pct = Math.max(0, Math.min(100, (amount / max) * 100));
  return `${pct}%`;
}

function seriesEyebrow(series: StatSeries): string {
  return series.kind === "fiat" ? "Fiat currency" : `Credits · ${series.label}`;
}

function SeriesPanel({ series }: { series: StatSeries }) {
  const max = series.buckets.reduce((current, bucket) => Math.max(current, bucket.amount), 0);
  return (
    <div className="panel">
      <div className="panel-head">
        <div>
          <span className="eyebrow">{seriesEyebrow(series)}</span>
          <div style={{ fontFamily: "var(--font-mono)", fontSize: 17, marginTop: 3 }}>
            {formatAmount(series.total, series.unit)}
          </div>
        </div>
        {series.kind === "fiat" ? (
          <span className="pill">{series.providers.join(", ")}</span>
        ) : null}
      </div>
      <div className="panel-body">
        <div className="chart">
          {series.buckets.map((bucket) => (
            <div className="bar" key={bucket.month}>
              <i style={{ height: barHeight(bucket.amount, max) }} />
              <span>{monthAbbrev(bucket.month)}</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

export function StatisticsView() {
  const [months, setMonths] = useState<MonthsWindow>(6);
  const [reloadKey, setReloadKey] = useState(0);
  const [data, setData] = useState<Statistics | null>(null);
  const [status, setStatus] = useState<"loading" | "ready" | "error">("loading");
  const [error, setError] = useState<string | null>(null);

  // A single guarded fetch path: both a period change (via `months`) and Retry (via `reloadKey`)
  // re-run this effect. The `cancelled` flag makes the latest request win, so a slow response for a
  // no-longer-selected window can never paint stale data or set state after unmount. The "loading"
  // status is set by each trigger (initial state, the selector, Retry), not in the effect body.
  useEffect(() => {
    let cancelled = false;
    void fetchStatistics(months).then(
      (stats) => {
        if (!cancelled) {
          setData(stats);
          setStatus("ready");
        }
      },
      (err: unknown) => {
        if (!cancelled) {
          setData(null);
          setStatus("error");
          setError(messageOf(err, "Could not load statistics"));
        }
      },
    );
    return () => {
      cancelled = true;
    };
  }, [months, reloadKey]);

  const series = data?.series ?? [];

  return (
    <section className="view on">
      <div className="page-head">
        <div>
          <div className="page-title">Statistics</div>
          <div className="page-note">
            Meters are shown separately and never combined. Credits from different providers are not
            comparable.
          </div>
        </div>
        <select
          className="sel"
          aria-label="Statistics period"
          value={months}
          onChange={(event) => {
            const next = Number(event.target.value);
            if (next === 6 || next === 12 || next === 24) {
              setStatus("loading");
              setError(null);
              setMonths(next);
            }
          }}
        >
          <option value={6}>Last 6 months</option>
          <option value={12}>Last 12 months</option>
          <option value={24}>Last 24 months</option>
        </select>
      </div>

      {status === "loading" ? (
        <div className="panel">
          <div className="panel-body">
            <div className="page-note">Loading statistics…</div>
          </div>
        </div>
      ) : null}

      {status === "error" ? (
        <div className="panel">
          <div className="panel-body">
            <div className="page-note">{error}</div>
            <div className="card-foot">
              <button
                type="button"
                className="btn btn-sm"
                onClick={() => {
                  setStatus("loading");
                  setError(null);
                  setReloadKey((key) => key + 1);
                }}
              >
                Retry
              </button>
            </div>
          </div>
        </div>
      ) : null}

      {status === "ready" && series.length === 0 ? (
        <div className="panel">
          <div className="panel-body">
            <div className="page-note">No spend has been recorded yet.</div>
          </div>
        </div>
      ) : null}

      {status === "ready" && series.length > 0 ? (
        <div className="stack">
          {series.map((item) => (
            <SeriesPanel key={item.id} series={item} />
          ))}
        </div>
      ) : null}
    </section>
  );
}
