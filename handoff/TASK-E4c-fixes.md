# TASK E-4c fixes — retry unmount-guard + Replay button icon

Apply these two edits only. Change nothing else. Do not edit tests, backend, docs, or add deps.
Do not touch `app/web/.gitkeep`.

## FIX A — `frontend/src/components/RunsListView.tsx`: route retry through the guarded effect
The `onRetry` refetch omits the effect's `cancelled` unmount guard (a latent state-after-unmount
write). Reuse the guarded effect via a reload counter.

1. Add a reload-counter state immediately after the existing `error` state declaration. Find:
```tsx
  const [error, setError] = useState<string | null>(null);
```
Replace with:
```tsx
  const [error, setError] = useState<string | null>(null);
  const [reload, setReload] = useState(0);
```

2. Add `reload` to the effect's dependency array. Find:
```tsx
  }, [workflowId]);
```
Replace with:
```tsx
  }, [workflowId, reload]);
```

3. Replace the entire `onRetry` function. Find:
```tsx
  function onRetry() {
    setStatus("loading");
    setError(null);
    void fetchRuns(workflowId).then(
      (data) => {
        setRuns(data.runs);
        setStatus("ready");
        setError(null);
      },
      (err: unknown) => {
        setRuns([]);
        setStatus("error");
        setError(messageOf(err, "Could not load runs"));
      },
    );
  }
```
Replace with:
```tsx
  function onRetry() {
    setStatus("loading");
    setError(null);
    setReload((n) => n + 1);
  }
```

## FIX B — `frontend/src/components/RunView.tsx`: add the approved replay icon to the button
The mockup's "Replay run" button carries a refresh icon. Add it. Find:
```tsx
                    disabled={replaying}
                    onClick={() => {
                      void onReplayClick();
                    }}
                  >
                    {replaying ? "Replaying…" : "Replay run"}
                  </button>
```
Replace with:
```tsx
                    disabled={replaying}
                    onClick={() => {
                      void onReplayClick();
                    }}
                  >
                    <span className="ico">
                      <svg
                        width="12"
                        height="12"
                        viewBox="0 0 16 16"
                        fill="none"
                        stroke="currentColor"
                        strokeWidth="1.4"
                      >
                        <path d="M2 8a6 6 0 1 0 1.8-4.3" />
                        <path d="M2 1.6V4.4h2.8" />
                      </svg>
                    </span>
                    {replaying ? "Replaying…" : "Replay run"}
                  </button>
```

## Scope
- `frontend/src/`

## Verify (from the worktree)
- `npm --prefix frontend run typecheck` → clean.
- `npm --prefix frontend run lint` → clean.
- `npm --prefix frontend run build` → succeeds.
