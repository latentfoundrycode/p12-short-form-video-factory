import { useEffect, useMemo, useState, type FormEvent } from "react";
import { fetchEstimate, fetchProviderOptions, fetchVoices, startRun } from "../api";
import {
  isStartRunOk,
  type EstimateOut,
  type Param,
  type ProviderOption,
  type SettingsData,
  type Voice,
} from "../types";

type FieldValue = string | boolean | string[];

type RunLaunchFormProps = {
  workflowId: string;
  workflowName: string;
  params: Param[];
  maxVideos?: number | null;
  onStarted: (runId: string) => void;
  onCancel: () => void;
};

type RememberedLaunchRaw = {
  params?: unknown;
  video_count?: unknown;
  concurrency?: unknown;
  step_concurrency?: unknown;
  gates_auto?: unknown;
  voice?: unknown;
  dry_run?: unknown;
};

type LaunchFormRememberedFlags = {
  concurrency: boolean;
  stepConcurrency: boolean;
};

type LaunchFormInitial = {
  videoCount: number;
  concurrency: number;
  stepConcurrency: number;
  dryRun: boolean;
  voice: string;
  approvalMode: "manual" | "autonomous";
  values: Record<string, FieldValue>;
  remembered: LaunchFormRememberedFlags;
};

function launchFormStorageKey(workflowId: string): string {
  return `sfvf.launchForm.${workflowId}`;
}

function providerOptionsStorageKey(source: string): string {
  return `sfvf.providerOptions.${source}`;
}

function readRememberedLaunchRaw(workflowId: string): RememberedLaunchRaw | null {
  try {
    const raw = window.localStorage.getItem(launchFormStorageKey(workflowId));
    if (raw === null) {
      return null;
    }
    const parsed: unknown = JSON.parse(raw);
    if (typeof parsed !== "object" || parsed === null || Array.isArray(parsed)) {
      return null;
    }
    return parsed as RememberedLaunchRaw;
  } catch {
    return null;
  }
}

function rememberedPositiveInt(value: unknown): number | null {
  if (typeof value === "boolean") {
    return null;
  }
  if (typeof value !== "number" || !Number.isInteger(value) || value < 1) {
    return null;
  }
  return value;
}

function parseDecimalNumber(
  text: string,
): { ok: true; value: number } | { ok: false; reason: "comma" | "invalid" } {
  const trimmed = text.trim();
  if (trimmed === "") {
    return { ok: false, reason: "invalid" };
  }
  if (trimmed.includes(",")) {
    return { ok: false, reason: "comma" };
  }
  if (!/^-?(?:\d+(?:\.\d*)?|\.\d+)$/.test(trimmed)) {
    return { ok: false, reason: "invalid" };
  }
  const value = Number(trimmed);
  if (!Number.isFinite(value)) {
    return { ok: false, reason: "invalid" };
  }
  return { ok: true, value };
}

function rememberedParamValue(param: Param, raw: unknown): FieldValue | null {
  switch (param.type) {
    case "text":
    case "textarea":
    case "select":
    case "file":
      return typeof raw === "string" ? raw : null;
    case "number":
      return typeof raw === "number" && Number.isFinite(raw) ? String(raw) : null;
    case "bool":
      return typeof raw === "boolean" ? raw : null;
    case "multiselect":
      return isStringArray(raw) ? [...raw] : null;
    default:
      return null;
  }
}

function buildLaunchFormInitial(
  workflowId: string,
  declared: Param[],
  maxVideos: number | null | undefined,
): LaunchFormInitial {
  const remembered = readRememberedLaunchRaw(workflowId);
  const flags: LaunchFormRememberedFlags = { concurrency: false, stepConcurrency: false };

  let videoCount = 1;
  const rememberedCount = remembered ? rememberedPositiveInt(remembered.video_count) : null;
  if (rememberedCount !== null) {
    if (typeof maxVideos !== "number" || rememberedCount <= maxVideos) {
      videoCount = rememberedCount;
    }
  }

  let concurrency = 1;
  const rememberedConcurrency = remembered ? rememberedPositiveInt(remembered.concurrency) : null;
  if (rememberedConcurrency !== null) {
    concurrency = rememberedConcurrency;
    flags.concurrency = true;
  }

  let stepConcurrency = 1;
  const rememberedStep = remembered ? rememberedPositiveInt(remembered.step_concurrency) : null;
  if (rememberedStep !== null) {
    stepConcurrency = rememberedStep;
    flags.stepConcurrency = true;
  }

  let dryRun = false;
  if (remembered && typeof remembered.dry_run === "boolean") {
    dryRun = remembered.dry_run;
  }

  let voice = "";
  if (remembered && typeof remembered.voice === "string") {
    voice = remembered.voice;
  }

  let approvalMode: "manual" | "autonomous" = "manual";
  if (remembered && typeof remembered.gates_auto === "boolean") {
    approvalMode = remembered.gates_auto ? "autonomous" : "manual";
  }

  const values = initialValues(declared);
  if (
    remembered &&
    typeof remembered.params === "object" &&
    remembered.params !== null &&
    !Array.isArray(remembered.params)
  ) {
    const rememberedParams = remembered.params as Record<string, unknown>;
    for (const param of declared) {
      if (!(param.key in rememberedParams)) {
        continue;
      }
      const applied = rememberedParamValue(param, rememberedParams[param.key]);
      if (applied !== null) {
        values[param.key] = applied;
      }
    }
  }

  return {
    videoCount,
    concurrency,
    stepConcurrency,
    dryRun,
    voice,
    approvalMode,
    values,
    remembered: flags,
  };
}

function storeRememberedLaunch(
  workflowId: string,
  payload: {
    params: Record<string, unknown>;
    video_count: number;
    concurrency: number;
    step_concurrency: number;
    gates_auto: boolean;
    voice: string;
    dry_run: boolean;
  },
): void {
  try {
    window.localStorage.setItem(launchFormStorageKey(workflowId), JSON.stringify(payload));
  } catch {
    /* untrusted or blocked storage */
  }
}

function loadStoredProviderOptions(source: string): ProviderOption[] | null {
  try {
    const raw = window.localStorage.getItem(providerOptionsStorageKey(source));
    if (raw === null) {
      return null;
    }
    const parsed: unknown = JSON.parse(raw);
    if (!Array.isArray(parsed)) {
      return null;
    }
    for (const item of parsed) {
      if (
        typeof item !== "object" ||
        item === null ||
        typeof (item as ProviderOption).id !== "string" ||
        typeof (item as ProviderOption).label !== "string" ||
        typeof (item as ProviderOption).configured !== "boolean"
      ) {
        return null;
      }
    }
    return parsed as ProviderOption[];
  } catch {
    return null;
  }
}

function storeProviderOptions(source: string, options: ProviderOption[]): void {
  try {
    window.localStorage.setItem(providerOptionsStorageKey(source), JSON.stringify(options));
  } catch {
    /* untrusted or blocked storage */
  }
}

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
        const parsed = parseDecimalNumber(text);
        if (!parsed.ok) {
          if (parsed.reason === "comma") {
            return {
              ok: false,
              error: `${param.label}: use a point (.) as the decimal separator.`,
            };
          }
          return { ok: false, error: `${param.label} is not a number.` };
        }
        if (param.min !== null && parsed.value < param.min) {
          return { ok: false, error: `${param.label} must be at least ${param.min}.` };
        }
        if (param.max !== null && parsed.value > param.max) {
          return { ok: false, error: `${param.label} must be at most ${param.max}.` };
        }
        result[param.key] = parsed.value;
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

function costParams(
  declared: Param[],
  values: Record<string, FieldValue>,
): Record<string, unknown> {
  const result: Record<string, unknown> = {};
  for (const param of declared) {
    if (!param.affects_cost) {
      continue;
    }
    const raw = values[param.key] ?? seedValue(param);
    if (usesManualInput(param)) {
      const text = typeof raw === "string" ? raw : "";
      if (param.type === "multiselect") {
        result[param.key] = text
          .split(",")
          .map((item) => item.trim())
          .filter((item) => item !== "");
        continue;
      }
      result[param.key] = text;
      continue;
    }
    switch (param.type) {
      case "text":
      case "textarea":
      case "select":
        result[param.key] = typeof raw === "string" ? raw : "";
        break;
      case "number": {
        const text = typeof raw === "string" ? raw : "";
        if (text.trim() === "") {
          break;
        }
        const parsed = parseDecimalNumber(text);
        if (parsed.ok) {
          result[param.key] = parsed.value;
        }
        break;
      }
      case "bool":
        result[param.key] = Boolean(raw);
        break;
      case "multiselect":
        result[param.key] = isStringArray(raw) ? raw : [];
        break;
      case "file":
        result[param.key] = typeof raw === "string" ? raw : "";
        break;
    }
  }
  return result;
}

function formatEstimateAmount(amount: number): string {
  if (!Number.isFinite(amount)) {
    return "—";
  }
  if (Number.isInteger(amount)) {
    return String(amount);
  }
  return amount.toFixed(2);
}

function estimateConfidenceLabel(confidence: string, matches: number): string {
  switch (confidence) {
    case "matched":
      return `matched · ${matches} runs`;
    case "crude":
      return "crude average";
    case "none":
      return "no data";
    default:
      return confidence;
  }
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
  lastKnown?: boolean;
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
          storeProviderOptions(source, options);
          setOptionsState({ status: "ready", options });
        }
      },
      () => {
        if (!ignore) {
          const stored = loadStoredProviderOptions(source);
          if (stored !== null) {
            setOptionsState({ status: "ready", options: stored, lastKnown: true });
          } else {
            setOptionsState({ status: "error", options: [] });
          }
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
        <FieldHelp
          param={param}
          extra={
            optionsState.lastKnown
              ? "Couldn't reach the provider — showing the last known options."
              : undefined
          }
        />
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
      <FieldHelp
        param={param}
        extra={
          optionsState.lastKnown
            ? "Couldn't reach the provider — showing the last known options."
            : undefined
        }
      />
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
            type="text"
            inputMode="decimal"
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
  maxVideos = null,
  onStarted,
  onCancel,
}: RunLaunchFormProps) {
  const [launchInitial] = useState(() => buildLaunchFormInitial(workflowId, params, maxVideos));
  const [videoCount, setVideoCount] = useState(launchInitial.videoCount);
  const [concurrency, setConcurrency] = useState(launchInitial.concurrency);
  const [stepConcurrency, setStepConcurrency] = useState(launchInitial.stepConcurrency);
  const [dryRun, setDryRun] = useState(launchInitial.dryRun);
  const [approvalMode, setApprovalMode] = useState<"manual" | "autonomous">(
    launchInitial.approvalMode,
  );
  const [perVideoBudget, setPerVideoBudget] = useState("");
  const [voice, setVoice] = useState(launchInitial.voice);
  const [voiceOptions, setVoiceOptions] = useState<Voice[]>([]);
  const [values, setValues] = useState<Record<string, FieldValue>>(() => launchInitial.values);
  const [formError, setFormError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [estimate, setEstimate] = useState<EstimateOut | null>(null);
  const [estimateUnavailable, setEstimateUnavailable] = useState(false);

  const estimateDepsKey = useMemo(
    () => JSON.stringify([videoCount, costParams(params, values)]),
    [params, values, videoCount],
  );

  useEffect(() => {
    let cancelled = false;
    const timer = window.setTimeout(() => {
      if (!Number.isInteger(videoCount) || videoCount < 1) {
        return;
      }
      const collectedParams = costParams(params, values);
      void fetchEstimate(workflowId, collectedParams, videoCount).then(
        (data) => {
          if (cancelled) {
            return;
          }
          setEstimate(data);
          setEstimateUnavailable(false);
        },
        () => {
          if (cancelled) {
            return;
          }
          setEstimateUnavailable(true);
        },
      );
    }, 300);
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
    // estimateDepsKey folds params, values, and videoCount; read them fresh here.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [workflowId, estimateDepsKey]);

  useEffect(() => {
    let ignore = false;
    void fetchVoices().then(
      (voices) => {
        if (!ignore) {
          const options = voices.filter((row) => row.id !== "");
          setVoiceOptions(options);
          setVoice((current) =>
            current !== "" && !options.some((row) => row.id === current) ? "" : current,
          );
        }
      },
      () => {
        if (!ignore) {
          setVoiceOptions([]);
          setVoice((current) => (current !== "" ? "" : current));
        }
      },
    );
    return () => {
      ignore = true;
    };
  }, []);

  useEffect(() => {
    let ignore = false;
    void import("../api").then((mod) => {
      try {
        const loadSettings = (mod as { fetchSettings?: () => Promise<SettingsData> }).fetchSettings;
        if (typeof loadSettings !== "function" || ignore) {
          return;
        }
        return loadSettings().then(
          (settings) => {
            if (!ignore) {
              if (!launchInitial.remembered.concurrency) {
                setConcurrency((current) =>
                  current === launchInitial.concurrency
                    ? settings.defaults.default_concurrency.effective
                    : current,
                );
              }
              if (!launchInitial.remembered.stepConcurrency) {
                setStepConcurrency((current) =>
                  current === launchInitial.stepConcurrency
                    ? settings.defaults.default_step_concurrency.effective
                    : current,
                );
              }
            }
          },
          () => {
            /* keep initial concurrency when settings cannot be loaded */
          },
        );
      } catch {
        /* api mock may omit fetchSettings in some contract tests */
      }
    });
    return () => {
      ignore = true;
    };
    // One-shot settings seed using the mount snapshot in launchInitial.
    // eslint-disable-next-line react-hooks/exhaustive-deps
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
    if (!Number.isInteger(stepConcurrency) || stepConcurrency < 1) {
      setFormError("Parallel steps per video must be an integer ≥ 1.");
      return;
    }
    if (typeof maxVideos === "number" && videoCount > maxVideos) {
      setFormError(`This workflow allows at most ${maxVideos} videos per request.`);
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
        dry_run: dryRun,
        step_concurrency: stepConcurrency,
        ...(budgetText !== ""
          ? { per_video_budget: Number(budgetText) }
          : {}),
      });
      if (isStartRunOk(result)) {
        storeRememberedLaunch(workflowId, {
          params: parsed.value,
          video_count: videoCount,
          concurrency,
          step_concurrency: stepConcurrency,
          gates_auto,
          voice,
          dry_run: dryRun,
        });
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
      <form className="panel-body launch-form" noValidate onSubmit={(e) => void onSubmit(e)}>
        <label className="field">
          <span className="field-label">Video count</span>
          <input
            className="field-input"
            type="number"
            min={1}
            max={typeof maxVideos === "number" ? maxVideos : undefined}
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
          <span className="field-label">Parallel steps per video</span>
          <input
            className="field-input"
            type="number"
            min={1}
            step={1}
            value={stepConcurrency}
            disabled={submitting}
            onChange={(e) => {
              setStepConcurrency(Number(e.target.value));
            }}
          />
        </label>
        <label className="field field-check">
          <input
            type="checkbox"
            checked={dryRun}
            disabled={submitting}
            onChange={(e) => {
              setDryRun(e.target.checked);
            }}
          />
          <span>Dry run</span>
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
        <div className="field">
          <span className="field-label">Estimated cost</span>
          {estimate && Object.keys(estimate.per_meter).length > 0 ? (
            <div className="meters">
              {Object.entries(estimate.per_meter).map(([meterId, meter]) => (
                <div className="meter" key={meterId}>
                  <div className="meter-name">{meterId}</div>
                  <div className="meter-val">
                    {formatEstimateAmount(meter.amount)}
                    <span className="meter-unit">{meter.unit}</span>
                  </div>
                </div>
              ))}
            </div>
          ) : estimateUnavailable ? null : (
            <span className="field-help">No estimate yet / no history</span>
          )}
          {estimate ? (
            <span className="field-help">
              {estimateConfidenceLabel(estimate.confidence, estimate.matches)}
            </span>
          ) : null}
          {estimateUnavailable ? (
            <span className="field-help">Couldn&apos;t load estimate.</span>
          ) : null}
        </div>
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
