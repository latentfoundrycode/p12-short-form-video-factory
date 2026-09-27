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

function secretRowLabel(name: string, providers: SettingsProvider[]): string {
  for (const provider of providers) {
    if (provider.secret_names.includes(name)) {
      return provider.label;
    }
  }
  return name;
}

function defaultsDraftFrom(data: SettingsData): Record<SettingsDefaultKey, number> {
  return {
    silence_limit_seconds: data.defaults.silence_limit_seconds.effective,
    default_concurrency: data.defaults.default_concurrency.effective,
    default_step_concurrency: data.defaults.default_step_concurrency.effective,
    cache_max_bytes: data.defaults.cache_max_bytes.effective,
  };
}

export function SettingsView() {
  const [reloadKey, setReloadKey] = useState(0);
  const [status, setStatus] = useState<LoadStatus>("loading");
  const [data, setData] = useState<SettingsData | null>(null);
  const [defaultDraft, setDefaultDraft] = useState<Record<SettingsDefaultKey, number> | null>(
    null,
  );
  const [secretDrafts, setSecretDrafts] = useState<Record<string, string>>({});

  useEffect(() => {
    let cancelled = false;
    void fetchSettings()
      .then((loaded) => {
        if (cancelled) {
          return;
        }
        setData(loaded);
        setDefaultDraft(defaultsDraftFrom(loaded));
        setStatus("ready");
      })
      .catch(() => {
        if (!cancelled) {
          setData(null);
          setDefaultDraft(null);
          setStatus("error");
        }
      });
    return () => {
      cancelled = true;
    };
  }, [reloadKey]);

  function refetch(): void {
    setStatus("loading");
    setReloadKey((key) => key + 1);
  }

  async function saveSecret(name: string): Promise<void> {
    const value = secretDrafts[name] ?? "";
    await putSecret(name, value);
    setSecretDrafts((current) => ({ ...current, [name]: "" }));
    refetch();
  }

  async function clearSecret(name: string): Promise<void> {
    await deleteSecret(name);
    refetch();
  }

  async function saveDefaults(): Promise<void> {
    if (!data || !defaultDraft) {
      return;
    }
    const changes: Partial<Record<SettingsDefaultKey, number>> = {};
    for (const { key } of DEFAULT_FIELDS) {
      if (data.defaults[key].source === "env") {
        continue;
      }
      const original = data.defaults[key].effective;
      const current = defaultDraft[key];
      if (current !== original) {
        changes[key] = current;
      }
    }
    if (Object.keys(changes).length === 0) {
      return;
    }
    await putDefaults(changes);
    refetch();
  }

  return (
    <section className="view on settings-view">
      <div className="page-head">
        <div>
          <div className="page-title">Settings</div>
          <div className="page-note">
            API keys, service connections, and global defaults used when starting runs.
          </div>
        </div>
      </div>

      {status === "loading" ? (
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
              <button type="button" className="btn btn-sm" style={{ marginLeft: 8 }} onClick={refetch}>
                Retry
              </button>
            </div>
          </div>
        </div>
      ) : null}

      {status === "ready" && data && defaultDraft ? (
        <div className="settings-sections">
          <div className="panel">
            <div className="panel-head">
              <span className="panel-title">API keys</span>
            </div>
            <div className="panel-body settings-form">
              {data.allowed_secret_names.map((name) => {
                const configured = data.configured_secret_names.includes(name);
                const label = secretRowLabel(name, data.providers);
                return (
                  <div className="settings-secret-row" key={name}>
                    <div className="settings-secret-head">
                      <span className="settings-secret-label">{label}</span>
                      <span className={`pill ${configured ? "music" : "idle"}`}>
                        {configured ? "configured" : "missing"}
                      </span>
                    </div>
                    <div className="settings-secret-actions">
                      <input
                        className="field-input"
                        type="password"
                        autoComplete="off"
                        aria-label={`Set ${name}`}
                        value={secretDrafts[name] ?? ""}
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
                        onClick={() => void saveSecret(name)}
                      >
                        Save {name}
                      </button>
                      {configured ? (
                        <button
                          type="button"
                          className="btn btn-sm"
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
              <span className="panel-title">Connections</span>
            </div>
            <div className="panel-body">
              <p className="page-note">No service connections require sign-in.</p>
            </div>
          </div>

          <div className="panel">
            <div className="panel-head">
              <span className="panel-title">Global defaults</span>
            </div>
            <div className="panel-body settings-form">
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
                      value={defaultDraft[key]}
                      onChange={(event) => {
                        const parsed = Number(event.target.value);
                        if (!Number.isFinite(parsed)) {
                          return;
                        }
                        setDefaultDraft((current) =>
                          current ? { ...current, [key]: parsed } : current,
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
                  onClick={() => void saveDefaults()}
                >
                  Save defaults
                </button>
              </div>
            </div>
          </div>
        </div>
      ) : null}
    </section>
  );
}
