import { useEffect, useState } from "react";
import { deleteSecret, fetchSettings, putDefaults, putSecret } from "../api";
import type { SettingsData, SettingsDefaultKey, SettingsProvider } from "../types";

type LoadStatus = "loading" | "ready" | "error";

const DEFAULT_FIELDS: { key: SettingsDefaultKey; label: string }[] = [
  { key: "silence_limit_seconds", label: "Step silence limit (seconds)" },
  { key: "default_concurrency", label: "Default concurrency" },
  { key: "default_step_concurrency", label: "Default step concurrency" },
  { key: "cache_max_bytes", label: "Max cache size (bytes)" },
];

function messageOf(err: unknown, fallback: string): string {
  return err instanceof Error ? err.message : fallback;
}

function secretRowLabel(name: string, providers: SettingsProvider[]): string {
  for (const provider of providers) {
    if (provider.secret_names.includes(name)) {
      return provider.label;
    }
  }
  return name;
}

function defaultStringsFrom(data: SettingsData): Record<SettingsDefaultKey, string> {
  return {
    silence_limit_seconds: String(data.defaults.silence_limit_seconds.effective),
    default_concurrency: String(data.defaults.default_concurrency.effective),
    default_step_concurrency: String(data.defaults.default_step_concurrency.effective),
    cache_max_bytes: String(data.defaults.cache_max_bytes.effective),
  };
}

export function SettingsView() {
  const [reloadKey, setReloadKey] = useState(0);
  const [status, setStatus] = useState<LoadStatus>("loading");
  const [data, setData] = useState<SettingsData | null>(null);
  const [defaultStrings, setDefaultStrings] = useState<Record<SettingsDefaultKey, string> | null>(
    null,
  );
  const [secretDrafts, setSecretDrafts] = useState<Record<string, string>>({});
  const [actionError, setActionError] = useState<string | null>(null);
  const [busySecret, setBusySecret] = useState<string | null>(null);
  const [savingDefaults, setSavingDefaults] = useState(false);

  useEffect(() => {
    let cancelled = false;
    void fetchSettings()
      .then((loaded) => {
        if (cancelled) {
          return;
        }
        setData(loaded);
        setDefaultStrings(defaultStringsFrom(loaded));
        setStatus("ready");
      })
      .catch(() => {
        if (!cancelled) {
          setData(null);
          setDefaultStrings(null);
          setStatus("error");
        }
      });
    return () => {
      cancelled = true;
    };
  }, [reloadKey]);

  function retryLoad(): void {
    setStatus("loading");
    setReloadKey((key) => key + 1);
  }

  function applyLoaded(loaded: SettingsData): void {
    setData(loaded);
    setDefaultStrings(defaultStringsFrom(loaded));
  }

  async function saveSecret(name: string): Promise<void> {
    const value = secretDrafts[name] ?? "";
    if (!value.trim()) {
      return;
    }
    setActionError(null);
    setBusySecret(name);
    try {
      await putSecret(name, value);
      setSecretDrafts((current) => ({ ...current, [name]: "" }));
      const loaded = await fetchSettings();
      applyLoaded(loaded);
    } catch (err) {
      setActionError(messageOf(err, "Could not save API key"));
    } finally {
      setBusySecret(null);
    }
  }

  async function clearSecret(name: string): Promise<void> {
    setActionError(null);
    setBusySecret(name);
    try {
      await deleteSecret(name);
      const loaded = await fetchSettings();
      applyLoaded(loaded);
    } catch (err) {
      setActionError(messageOf(err, "Could not clear API key"));
    } finally {
      setBusySecret(null);
    }
  }

  async function saveDefaults(): Promise<void> {
    if (!data || !defaultStrings) {
      return;
    }
    const changes: Partial<Record<SettingsDefaultKey, number>> = {};
    for (const { key } of DEFAULT_FIELDS) {
      if (data.defaults[key].source === "env") {
        continue;
      }
      const raw = defaultStrings[key].trim();
      if (raw === "") {
        continue;
      }
      const parsed = Number(raw);
      if (!Number.isFinite(parsed)) {
        continue;
      }
      const original = data.defaults[key].effective;
      if (parsed !== original) {
        changes[key] = parsed;
      }
    }
    if (Object.keys(changes).length === 0) {
      return;
    }
    setActionError(null);
    setSavingDefaults(true);
    try {
      await putDefaults(changes);
      const loaded = await fetchSettings();
      applyLoaded(loaded);
    } catch (err) {
      setActionError(messageOf(err, "Could not save defaults"));
    } finally {
      setSavingDefaults(false);
    }
  }

  const showInitialLoading = status === "loading" && data === null;

  return (
    <section className="view on">
      <div className="page-head">
        <div>
          <div className="page-title">Settings</div>
          <div className="page-note">
            API keys, service connections, and global defaults used when starting runs.
          </div>
        </div>
      </div>

      {showInitialLoading ? (
        <div className="panel">
          <div className="panel-body">
            <div className="page-note">Loading settings…</div>
          </div>
        </div>
      ) : null}

      {status === "error" ? (
        <div className="panel">
          <div className="panel-body">
            <div className="form-error">
              Couldn&apos;t load settings. Check that SFVF is running.
              <button type="button" className="btn btn-sm" style={{ marginLeft: 8 }} onClick={retryLoad}>
                Retry
              </button>
            </div>
          </div>
        </div>
      ) : null}

      {data && defaultStrings ? (
        <div className="stack">
          {actionError ? <div className="form-error">{actionError}</div> : null}

          <div className="panel">
            <div className="panel-head">
              <div>
                <span className="eyebrow">Secrets</span>
                <div className="panel-title">API keys</div>
              </div>
            </div>
            <div className="panel-body launch-form">
              {data.allowed_secret_names.map((name) => {
                const configured = data.configured_secret_names.includes(name);
                const label = secretRowLabel(name, data.providers);
                const draft = secretDrafts[name] ?? "";
                const rowBusy = busySecret === name;
                return (
                  <div className="field" key={name}>
                    <span className="field-label">
                      {label}{" "}
                      <span className={`pill ${configured ? "done" : "idle"}`}>
                        {configured ? "configured" : "missing"}
                      </span>
                    </span>
                    <div className="detail-actions" style={{ justifyContent: "flex-start", flexWrap: "wrap" }}>
                      <input
                        className="field-input"
                        type="password"
                        autoComplete="off"
                        aria-label={`Set ${name}`}
                        value={draft}
                        disabled={rowBusy}
                        onChange={(event) =>
                          setSecretDrafts((current) => ({
                            ...current,
                            [name]: event.target.value,
                          }))
                        }
                      />
                      <button
                        type="button"
                        className="btn btn-primary btn-sm"
                        disabled={rowBusy || draft.trim() === ""}
                        onClick={() => void saveSecret(name)}
                      >
                        {rowBusy ? "Saving…" : `Save ${name}`}
                      </button>
                      {configured ? (
                        <button
                          type="button"
                          className="btn btn-sm"
                          disabled={rowBusy}
                          onClick={() => void clearSecret(name)}
                        >
                          Clear {name}
                        </button>
                      ) : null}
                    </div>
                  </div>
                );
              })}
            </div>
          </div>

          <div className="panel">
            <div className="panel-head">
              <div>
                <span className="eyebrow">Integrations</span>
                <div className="panel-title">Connections</div>
              </div>
            </div>
            <div className="panel-body">
              <p className="page-note">No service connections require sign-in.</p>
            </div>
          </div>

          <div className="panel">
            <div className="panel-head">
              <div>
                <span className="eyebrow">Runs</span>
                <div className="panel-title">Global defaults</div>
              </div>
            </div>
            <div className="panel-body launch-form">
              {DEFAULT_FIELDS.map(({ key, label }) => {
                const field = data.defaults[key];
                const envLocked = field.source === "env";
                return (
                  <label className="field" key={key}>
                    <span className="field-label">{label}</span>
                    <input
                      className="field-input"
                      type="number"
                      readOnly={envLocked}
                      aria-label={label}
                      value={defaultStrings[key]}
                      disabled={savingDefaults}
                      onChange={(event) => {
                        if (envLocked) {
                          return;
                        }
                        const next = event.target.value;
                        setDefaultStrings((current) =>
                          current ? { ...current, [key]: next } : current,
                        );
                      }}
                    />
                    <span className="field-help">
                      Source: {field.source}
                      {envLocked ? " — overridden by an environment variable" : ""}
                    </span>
                  </label>
                );
              })}
              <div className="detail-actions">
                <button
                  type="button"
                  className="btn btn-primary btn-sm"
                  disabled={savingDefaults}
                  onClick={() => void saveDefaults()}
                >
                  {savingDefaults ? "Saving…" : "Save defaults"}
                </button>
              </div>
            </div>
          </div>
        </div>
      ) : null}
    </section>
  );
}
