import { useEffect, useState, type FormEvent } from "react";
import { fetchProviderOptions, fetchVoices, startRun } from "../api";
import { isStartRunOk, type Param, type ProviderOption, type Voice } from "../types";

type FieldValue = string | boolean | string[];

type RunLaunchFormProps = {
  workflowId: string;
  workflowName: string;
  params: Param[];
  onStarted: (runId: string) => void;
  onCancel: () => void;
};

function isStringArray(value: unknown): value is string[] {
  return Array.isArray(value) && value.every((item) => typeof item === "string");
}

function usesManualInput(param: Param): boolean {
  if (param.type === "file") return true;
  if (param.type === "select" || param.type === "multiselect") {
    return param.options === null && param.options_from === null;
  }
  return false;
}

function seedValue(param: Param): FieldValue {
  if (usesManualInput(param)) {
    return String(param.default ?? "");
  }
  switch (param.type) {
    case "number":
      return typeof param.default === "number" && Number.isFinite(param.default)
        ? String(param.default)
        : "";
    case "bool":
      return Boolean(param.default);
    case "multiselect":
      return isStringArray(param.default) ? [...param.default] : [];
    case "text":
    case "textarea":
    case "select":
    case "file":
      return String(param.default ?? "");
  }
}

function initialValues(params: Param[]): Record<string, FieldValue> {
  const values: Record<string, FieldValue> = {};
  for (const param of params) {
    values[param.key] = seedValue(param);
  }
  return values;
}

function controlLabel(param: Param): string {
  const unit = param.unit ? ` (${param.unit})` : "";
  const required = param.required ? " *" : "";
  return `${param.label}${unit}${required}`;
}

function collectParams(
  declared: Param[],
  values: Record<string, FieldValue>,
): { ok: true; value: Record<string, unknown> } | { ok: false; error: string } {
  const result: Record<string, unknown> = {};
  for (const param of declared) {
    const raw = values[param.key];
    if (usesManualInput(param)) {
      const text = typeof raw === "string" ? raw : "";
      if (param.type === "multiselect") {
        const selected = text
          .split(",")
          .map((item) => item.trim())
          .filter((item) => item !== "");
        if (param.required && selected.length === 0) {
          return { ok: false, error: `${param.label} is required.` };
        }
        result[param.key] = selected;
        continue;
      }
      if (param.required && text.trim() === "") {
        return { ok: false, error: `${param.label} is required.` };
      }
      result[param.key] = text;
      continue;
    }
    switch (param.type) {
      case "text":
      case "textarea":
      case "select": {
        const text = typeof raw === "string" ? raw : "";
        if (param.required && text.trim() === "") {
          return { ok: false, error: `${param.label} is required.` };
        }
        result[param.key] = text;
        break;
      }
      case "number": {
        const text = typeof raw === "string" ? raw : "";
        if (text.trim() === "") {
          if (!param.required) {
            break;
          }
          return { ok: false, error: `${param.label} is required.` };
        }
        const parsed = Number(text);
        if (Number.isNaN(parsed)) {
          return { ok: false, error: `${param.label} is not a number.` };
        }
        result[param.key] = parsed;
        break;
      }
      case "bool":
        result[param.key] = Boolean(raw);
        break;
      case "multiselect": {
        const selected = isStringArray(raw) ? raw : [];
        if (param.required && selected.length === 0) {
          return { ok: false, error: `${param.label} is required.` };
        }
        result[param.key] = selected;
        break;
      }
      case "file":
        result[param.key] = typeof raw === "string" ? raw : "";
        break;
    }
  }
  return { ok: true, value: result };
}

function FieldHelp({ param, extra }: { param: Param; extra?: string }) {
  return (
    <>
      {param.help ? <span className="field-help">{param.help}</span> : null}
      {extra ? <span className="field-help">{extra}</span> : null}
    </>
  );
}

type RegistryOptionsState = {
  status: "loading" | "ready" | "error";
  options: ProviderOption[];
};

function RegistryOptionsField({
  param,
  value,
  disabled,
  onChange,
}: {
  param: Param;
  value: FieldValue;
  disabled: boolean;
  onChange: (value: FieldValue) => void;
}) {
  const label = controlLabel(param);
  const text = typeof value === "string" ? value : "";
  const selected = isStringArray(value) ? value : [];
  const [manualText, setManualText] = useState(() => selected.join(", "));
  const [optionsState, setOptionsState] = useState<RegistryOptionsState>({
    status: "loading",
    options: [],
  });
  const source = param.options_from;

  useEffect(() => {
    if (source === null) return;

    let ignore = false;
    void fetchProviderOptions(source).then(
      (options) => {
        if (!ignore) {
          setOptionsState({ status: "ready", options });
        }
      },
      () => {
        if (!ignore) {
          setOptionsState({ status: "error", options: [] });
        }
      },
    );
    return () => {
      ignore = true;
    };
  }, [source]);

  if (optionsState.status === "error") {
    const isMultiselect = param.type === "multiselect";
    return (
      <label className="field">
        <span className="field-label">{label}</span>
        <input
          className="field-input"
          type="text"
          placeholder={param.placeholder ?? ""}
          value={isMultiselect ? manualText : text}
          disabled={disabled}
          aria-required={param.required}
          onChange={(event) => {
            if (isMultiselect) {
              const nextText = event.target.value;
              setManualText(nextText);
              onChange(
                nextText
                  .split(",")
                  .map((item) => item.trim())
                  .filter((item) => item !== ""),
              );
            } else {
              onChange(event.target.value);
            }
          }}
        />
        <FieldHelp param={param} extra="Couldn't load options — enter the value manually." />
      </label>
    );
  }

  if (param.type === "multiselect") {
    if (optionsState.status === "loading") {
      return (
        <div className="field">
          <span className="field-label">{label}</span>
          <span className="field-help">Loading…</span>
          <FieldHelp param={param} />
        </div>
      );
    }
    return (
      <div className="field">
        <span className="field-label">{label}</span>
        {optionsState.options.map((option) => (
          <label className="field-check" key={option.id}>
            <input
              type="checkbox"
              checked={selected.includes(option.id)}
              disabled={disabled || !option.configured}
              onChange={() => {
                const next = selected.includes(option.id)
                  ? selected.filter((item) => item !== option.id)
                  : [...selected, option.id];
                onChange(next);
              }}
            />
            <span>
              {option.configured ? option.label : `${option.label} (not configured)`}
            </span>
          </label>
        ))}
        <FieldHelp param={param} />
      </div>
    );
  }

  if ((optionsState as RegistryOptionsState).status === "loading") {
    return (
      <label className="field">
        <span className="field-label">{label}</span>
        <select
          className="field-input"
          value={text}
          disabled
          aria-required={param.required}
          onChange={() => {}}
        >
          <option value={text}>Loading…</option>
        </select>
        <FieldHelp param={param} />
      </label>
    );
  }

  const currentWasRemoved =
    text !== "" && !optionsState.options.some((option) => option.id === text);

  return (
    <label className="field">
      <span className="field-label">{label}</span>
      <select
        className="field-input"
        value={text}
        disabled={disabled || optionsState.status === "loading"}
        aria-required={param.required}
        onChange={(event) => {
          onChange(event.target.value);
        }}
      >
        {param.required ? (
          <option value="" disabled>
            — select —
          </option>
        ) : (
          <option value="">— none —</option>
        )}
        {currentWasRemoved ? <option value={text}>{`${text} (removed)`}</option> : null}
        {optionsState.options.map((option) => (
          <option key={option.id} value={option.id} disabled={!option.configured}>
            {option.configured ? option.label : `${option.label} (not configured)`}
          </option>
        ))}
      </select>
      <FieldHelp param={param} />
    </label>
  );
}

function ParamField({
  param,
  value,
  disabled,
  onChange,
}: {
  param: Param;
  value: FieldValue;
  disabled: boolean;
  onChange: (value: FieldValue) => void;
}) {
  const label = controlLabel(param);
  const text = typeof value === "string" ? value : "";
  const extraHelp = usesManualInput(param) ? "Enter value(s) manually." : undefined;

  if (
    (param.type === "select" || param.type === "multiselect") &&
    param.options === null &&
    param.options_from !== null
  ) {
    return (
      <RegistryOptionsField
        key={param.options_from}
        param={param}
        value={value}
        disabled={disabled}
        onChange={onChange}
      />
    );
  }

  if (usesManualInput(param)) {
    return (
      <label className="field">
        <span className="field-label">{label}</span>
        <input
          className="field-input"
          type="text"
          placeholder={param.placeholder ?? ""}
          value={text}
          disabled={disabled}
          aria-required={param.required}
          onChange={(event) => {
            onChange(event.target.value);
          }}
        />
        <FieldHelp param={param} extra={extraHelp} />
      </label>
    );
  }

  switch (param.type) {
    case "text":
      return (
        <label className="field">
          <span className="field-label">{label}</span>
          <input
            className="field-input"
            type="text"
            placeholder={param.placeholder ?? ""}
            value={text}
            disabled={disabled}
            aria-required={param.required}
            onChange={(event) => {
              onChange(event.target.value);
            }}
          />
          <FieldHelp param={param} />
        </label>
      );
    case "textarea":
      return (
        <label className="field">
          <span className="field-label">{label}</span>
          <textarea
            className="field-input field-textarea"
            rows={4}
            value={text}
            disabled={disabled}
            aria-required={param.required}
            onChange={(event) => {
              onChange(event.target.value);
            }}
          />
          <FieldHelp param={param} />
        </label>
      );
    case "number":
      return (
        <label className="field">
          <span className="field-label">{label}</span>
          <input
            className="field-input"
            type="number"
            min={param.min ?? undefined}
            max={param.max ?? undefined}
            step={param.step ?? undefined}
            value={text}
            disabled={disabled}
            aria-required={param.required}
            onChange={(event) => {
              onChange(event.target.value);
            }}
          />
          <FieldHelp param={param} />
        </label>
      );
    case "bool":
      return (
        <div className="field">
          <label className="field-check">
            <input
              type="checkbox"
              checked={typeof value === "boolean" ? value : false}
              disabled={disabled}
              onChange={(event) => {
                onChange(event.target.checked);
              }}
            />
            <span>{label}</span>
          </label>
          <FieldHelp param={param} />
        </div>
      );
    case "select":
      return (
        <label className="field">
          <span className="field-label">{label}</span>
          <select
            className="field-input"
            value={text}
            disabled={disabled}
            aria-required={param.required}
            onChange={(event) => {
              onChange(event.target.value);
            }}
          >
            {param.required ? (
              <option value="" disabled>
                — select —
              </option>
            ) : (
              <option value="">— none —</option>
            )}
            {(param.options ?? []).map((option, index) => {
              const optionText = String(option);
              return (
                <option key={`${optionText}-${index}`} value={optionText}>
                  {optionText}
                </option>
              );
            })}
          </select>
          <FieldHelp param={param} />
        </label>
      );
    case "multiselect": {
      const selected = isStringArray(value) ? value : [];
      return (
        <div className="field">
          <span className="field-label">{label}</span>
          {(param.options ?? []).map((option, index) => {
            const optionText = String(option);
            return (
              <label className="field-check" key={`${optionText}-${index}`}>
                <input
                  type="checkbox"
                  checked={selected.includes(optionText)}
                  disabled={disabled}
                  onChange={() => {
                    const next = selected.includes(optionText)
                      ? selected.filter((item) => item !== optionText)
                      : [...selected, optionText];
                    onChange(next);
                  }}
                />
                <span>{optionText}</span>
              </label>
            );
          })}
          <FieldHelp param={param} />
        </div>
      );
    }
    case "file":
      return null;
  }
}

export function RunLaunchForm({
  workflowId,
  workflowName,
  params,
  onStarted,
  onCancel,
}: RunLaunchFormProps) {
  const [videoCount, setVideoCount] = useState(1);
  const [concurrency, setConcurrency] = useState(1);
  const [approvalMode, setApprovalMode] = useState<"manual" | "autonomous">("manual");
  const [perVideoBudget, setPerVideoBudget] = useState("");
  const [voice, setVoice] = useState("");
  const [voiceOptions, setVoiceOptions] = useState<Voice[]>([]);
  const [values, setValues] = useState<Record<string, FieldValue>>(() => initialValues(params));
  const [formError, setFormError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    let ignore = false;
    void fetchVoices().then(
      (voices) => {
        if (!ignore) {
          setVoiceOptions(voices.filter((row) => row.id !== ""));
        }
      },
      () => {
        if (!ignore) {
          setVoiceOptions([]);
        }
      },
    );
    return () => {
      ignore = true;
    };
  }, []);

  useEffect(() => {
    // This effect intentionally merges newly declared fields into user-owned form state.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setValues((current) => {
      let changed = false;
      const next = { ...current };
      for (const param of params) {
        if (!(param.key in current)) {
          next[param.key] = seedValue(param);
          changed = true;
        }
      }
      return changed ? next : current;
    });
  }, [params]);

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    setFormError(null);

    const parsed = collectParams(params, values);
    if (!parsed.ok) {
      setFormError(parsed.error);
      return;
    }
    if (!Number.isInteger(videoCount) || videoCount < 1) {
      setFormError("Video count must be an integer ≥ 1.");
      return;
    }
    if (!Number.isInteger(concurrency) || concurrency < 1) {
      setFormError("Concurrency must be an integer ≥ 1.");
      return;
    }

    const gates_auto = approvalMode === "autonomous";
    const budgetText = perVideoBudget.trim();
    if (budgetText !== "") {
      const budget = Number(budgetText);
      if (!Number.isFinite(budget) || budget <= 0) {
        setFormError("Per-video budget must be greater than 0.");
        return;
      }
    }

    setSubmitting(true);
    try {
      const result = await startRun(workflowId, {
        params: parsed.value,
        video_count: videoCount,
        concurrency,
        gates_auto,
        voice,
        ...(budgetText !== ""
          ? { per_video_budget: Number(budgetText) }
          : {}),
      });
      if (isStartRunOk(result)) {
        onStarted(result.run_id);
        return;
      }
      setFormError(result.error);
    } catch (err) {
      setFormError(err instanceof Error ? err.message : "Could not start run");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="panel launch-panel">
      <div className="panel-head">
        <div>
          <span className="eyebrow">Launch</span>
          <div className="launch-title">Start {workflowName}</div>
        </div>
        <button
          type="button"
          className="btn btn-ghost btn-sm"
          onClick={onCancel}
          disabled={submitting}
        >
          Cancel
        </button>
      </div>
      <form className="panel-body launch-form" onSubmit={(e) => void onSubmit(e)}>
        <label className="field">
          <span className="field-label">Video count</span>
          <input
            className="field-input"
            type="number"
            min={1}
            step={1}
            value={videoCount}
            disabled={submitting}
            onChange={(e) => {
              setVideoCount(Number(e.target.value));
            }}
          />
        </label>
        <label className="field">
          <span className="field-label">Concurrency</span>
          <input
            className="field-input"
            type="number"
            min={1}
            step={1}
            value={concurrency}
            disabled={submitting}
            onChange={(e) => {
              setConcurrency(Number(e.target.value));
            }}
          />
        </label>
        <label className="field">
          <span className="field-label">Approval mode</span>
          <select
            className="field-input"
            value={approvalMode}
            disabled={submitting}
            onChange={(e) => {
              setApprovalMode(e.target.value as "manual" | "autonomous");
            }}
          >
            <option value="manual">Require approval (approve before spending)</option>
            <option value="autonomous">Autonomous (no approval)</option>
          </select>
        </label>
        <label className="field">
          <span className="field-label">Per-video budget (USD)</span>
          <input
            className="field-input"
            type="number"
            min={0}
            step={0.01}
            placeholder="e.g. 6.00"
            value={perVideoBudget}
            disabled={submitting}
            onChange={(e) => {
              setPerVideoBudget(e.target.value);
            }}
          />
        </label>
        <label className="field">
          <span className="field-label">Voice</span>
          <select
            className="field-input"
            value={voice}
            disabled={submitting}
            onChange={(e) => {
              setVoice(e.target.value);
            }}
          >
            <option value="">Default voice</option>
            {voiceOptions.map((option) => (
              <option key={option.id} value={option.id}>
                {option.label}
              </option>
            ))}
          </select>
        </label>
        {params.map((param) => (
          <ParamField
            key={param.key}
            param={param}
            value={values[param.key] ?? seedValue(param)}
            disabled={submitting}
            onChange={(next) => {
              setValues((current) => ({ ...current, [param.key]: next }));
            }}
          />
        ))}
        {formError ? <div className="form-error">{formError}</div> : null}
        <div className="card-foot launch-actions">
          <button type="submit" className="btn btn-primary btn-sm" disabled={submitting}>
            {submitting ? "Starting…" : "Start run"}
          </button>
        </div>
      </form>
    </div>
  );
}
