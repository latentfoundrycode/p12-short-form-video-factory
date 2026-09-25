import { useEffect, useRef, useState } from "react";
import {
  deactivateLibraryAsset,
  fetchLibraryAssets,
  fetchLibraryWorkflows,
  reactivateLibraryAsset,
  setLibraryGrant,
  updateLibraryAsset,
  uploadLibraryAsset,
} from "../api";
import type { LibraryAsset, LibraryGrant, LibraryWorkflow } from "../types";

type LoadStatus = "loading" | "ready" | "error";

function isAllGrant(grant: LibraryGrant): grant is { all: true } {
  return "all" in grant && grant.all === true;
}

function accessSummary(grant: LibraryGrant, workflows: LibraryWorkflow[]): string {
  if (isAllGrant(grant)) {
    return "All workflows";
  }
  const ids = grant.workflows;
  if (ids.length === 0) {
    return "—";
  }
  if (ids.length === 1) {
    const match = workflows.find((workflow) => workflow.id === ids[0]);
    return match?.label ?? ids[0];
  }
  return `${ids.length} workflows`;
}

function displayName(asset: LibraryAsset): string {
  return asset.name ?? asset.id.slice(0, 12);
}

function kindClass(kind: string): string {
  if (kind === "music" || kind === "sfx" || kind === "voice") {
    return kind;
  }
  return "idle";
}

function facetLine(asset: LibraryAsset): string[] {
  const parts: string[] = [];
  if (asset.mood.length > 0) {
    for (const mood of asset.mood) {
      parts.push(`mood: ${mood}`);
    }
  } else if (asset.kind !== "voice") {
    parts.push("mood: —");
  }
  if (asset.energy.length > 0) {
    for (const energy of asset.energy) {
      parts.push(`energy: ${energy}`);
    }
  }
  if (asset.kind === "voice") {
    parts.push("reference clip");
  }
  return parts;
}

type TagInputProps = {
  tags: string[];
  placeholder: string;
  onChange: (tags: string[]) => void;
};

function TagInput({ tags, placeholder, onChange }: TagInputProps) {
  const [entry, setEntry] = useState("");
  const [editingIndex, setEditingIndex] = useState<number | null>(null);
  const [editValue, setEditValue] = useState("");
  const [chipMenu, setChipMenu] = useState<{ x: number; y: number; index: number } | null>(null);
  const menuRef = useRef<HTMLDivElement>(null);
  const editInputRef = useRef<HTMLInputElement>(null);
  const chipRefs = useRef<(HTMLSpanElement | null)[]>([]);
  const chipMenuRef = useRef<{ x: number; y: number; index: number } | null>(null);

  useEffect(() => {
    chipMenuRef.current = chipMenu;
  }, [chipMenu]);

  useEffect(() => {
    if (editingIndex === null) {
      return;
    }
    const input = editInputRef.current;
    if (input) {
      input.focus();
      input.select();
    }
  }, [editingIndex]);

  useEffect(() => {
    function closeMenu(): void {
      const menu = chipMenuRef.current;
      if (!menu) {
        return;
      }
      setChipMenu(null);
      chipRefs.current[menu.index]?.focus();
    }
    document.addEventListener("click", closeMenu);
    return () => document.removeEventListener("click", closeMenu);
  }, []);

  useEffect(() => {
    if (!chipMenu) {
      return;
    }
    const index = chipMenu.index;
    function onKeyDown(event: KeyboardEvent): void {
      if (event.key === "Escape") {
        setChipMenu(null);
        chipRefs.current[index]?.focus();
      }
    }
    document.addEventListener("keydown", onKeyDown);
    menuRef.current?.querySelector("button")?.focus();
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [chipMenu]);

  function removeTag(index: number): void {
    onChange(tags.filter((_, tagIndex) => tagIndex !== index));
  }

  function startEdit(index: number): void {
    setEditValue(tags[index] ?? "");
    setEditingIndex(index);
    setChipMenu(null);
  }

  function commitEntry(value: string): void {
    const trimmed = value.trim();
    if (!trimmed) {
      return;
    }
    onChange([...tags, trimmed]);
    setEntry("");
  }

  function finishEdit(index: number): void {
    const trimmed = editValue.trim();
    if (!trimmed) {
      onChange(tags.filter((_, tagIndex) => tagIndex !== index));
    } else {
      onChange(tags.map((tag, tagIndex) => (tagIndex === index ? trimmed : tag)));
    }
    setEditingIndex(null);
    setEditValue("");
  }

  return (
    <div
      className="taginput"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) {
          (event.currentTarget.querySelector(".tag-entry") as HTMLInputElement | null)?.focus();
        }
      }}
    >
      {tags.map((tag, index) =>
        editingIndex === index ? (
          <span className="chip" key={`edit-${index}`}>
            <input
              ref={editInputRef}
              className="chip-edit"
              value={editValue}
              size={Math.max(editValue.length, 3)}
              onChange={(event) => setEditValue(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === "Enter") {
                  event.preventDefault();
                  finishEdit(index);
                }
              }}
              onBlur={() => finishEdit(index)}
            />
          </span>
        ) : (
          <span
            ref={(element) => {
              chipRefs.current[index] = element;
            }}
            className="chip"
            key={`chip-${index}-${tag}`}
            tabIndex={0}
            onKeyDown={(event) => {
              if (event.key === "Enter" || event.key === "F2") {
                event.preventDefault();
                startEdit(index);
              } else if (event.key === "Delete" || event.key === "Backspace") {
                event.preventDefault();
                removeTag(index);
              }
            }}
            onContextMenu={(event) => {
              event.preventDefault();
              setChipMenu({ x: event.clientX, y: event.clientY, index });
            }}
          >
            <span className="chip-text">{tag}</span>
            <button
              type="button"
              className="chip-x"
              aria-label={`remove ${tag}`}
              onClick={(event) => {
                event.stopPropagation();
                removeTag(index);
              }}
            >
              &times;
            </button>
          </span>
        ),
      )}
      <input
        className="tag-entry"
        placeholder={placeholder}
        value={entry}
        onChange={(event) => {
          const value = event.target.value;
          if (value.includes(",")) {
            const parts = value.split(",");
            let next = tags;
            for (let i = 0; i < parts.length - 1; i += 1) {
              const piece = parts[i].trim();
              if (piece) {
                next = [...next, piece];
              }
            }
            onChange(next);
            setEntry(parts[parts.length - 1]);
            return;
          }
          setEntry(value);
        }}
        onKeyDown={(event) => {
          if (event.key === "Enter") {
            event.preventDefault();
            commitEntry(entry);
          } else if (event.key === "Backspace" && entry === "" && tags.length > 0) {
            onChange(tags.slice(0, -1));
          }
        }}
      />
      {chipMenu ? (
        <div
          ref={menuRef}
          className="ctxmenu"
          style={{
            left: Math.min(chipMenu.x, window.innerWidth - 130),
            top: chipMenu.y,
          }}
          onClick={(event) => event.stopPropagation()}
        >
          <button type="button" onClick={() => startEdit(chipMenu.index)}>
            Edit
          </button>
          <button type="button" onClick={() => removeTag(chipMenu.index)}>
            Delete
          </button>
        </div>
      ) : null}
    </div>
  );
}

type AccessPickerProps = {
  grant: LibraryGrant;
  workflows: LibraryWorkflow[];
  onChange: (grant: LibraryGrant) => void;
  compact?: boolean;
};

function AccessPicker({ grant, workflows, onChange, compact = false }: AccessPickerProps) {
  const all = isAllGrant(grant);
  const selected = all ? [] : grant.workflows;

  return (
    <div className="access-picker">
      <label className={all ? "radio on" : "radio"}>
        <input
          type="radio"
          name="library-access"
          checked={all}
          onChange={() => onChange({ all: true })}
        />
        <span>
          <span className="r-title">All workflows</span>
          {compact ? null : (
            <span className="r-help">Every current and future workflow can use this asset.</span>
          )}
        </span>
      </label>
      <label className={all ? "radio" : "radio on"}>
        <input
          type="radio"
          name="library-access"
          checked={!all}
          onChange={() => onChange({ workflows: selected.length > 0 ? selected : [] })}
        />
        <span>
          <span className="r-title">{compact ? "Specific workflows…" : "Specific workflows"}</span>
          {compact ? null : (
            <span className="r-help">Only the ones you tick below.</span>
          )}
        </span>
      </label>
      {!all ? (
        <div className="wf-list">
          {workflows.map((workflow) => (
            <label className="wf" key={workflow.id}>
              <input
                type="checkbox"
                checked={selected.includes(workflow.id)}
                onChange={(event) => {
                  const next = event.target.checked
                    ? [...selected, workflow.id]
                    : selected.filter((id) => id !== workflow.id);
                  onChange({ workflows: next });
                }}
              />
              {workflow.label}
              <span className="muted">{workflow.id}</span>
            </label>
          ))}
          {workflows.length === 0 ? (
            <label className="wf" style={{ color: "var(--text-faint)" }}>
              <input type="checkbox" disabled />
              (future workflows appear here)
            </label>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}

type AssetDraft = {
  name: string;
  kind: string;
  mood: string[];
  energy: string[];
  caveats: string;
  grant: LibraryGrant;
};

function draftFromAsset(asset: LibraryAsset): AssetDraft {
  return {
    name: asset.name ?? "",
    kind: asset.kind,
    mood: [...asset.mood],
    energy: [...asset.energy],
    caveats: asset.description,
    grant: asset.grant,
  };
}

export function LibraryView() {
  const [reloadKey, setReloadKey] = useState(0);
  const [status, setStatus] = useState<LoadStatus>("loading");
  const [assets, setAssets] = useState<LibraryAsset[]>([]);
  const [workflows, setWorkflows] = useState<LibraryWorkflow[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [showAdd, setShowAdd] = useState(false);
  const [draft, setDraft] = useState<AssetDraft | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const addFileRef = useRef<HTMLInputElement>(null);
  const [addDraft, setAddDraft] = useState<AssetDraft>({
    name: "",
    kind: "music",
    mood: [],
    energy: [],
    caveats: "",
    grant: { all: true },
  });
  const [addFile, setAddFile] = useState<File | null>(null);

  useEffect(() => {
    let cancelled = false;
    void Promise.all([fetchLibraryAssets(), fetchLibraryWorkflows()])
      .then(([loadedAssets, loadedWorkflows]) => {
        if (cancelled) {
          return;
        }
        setAssets(loadedAssets);
        setWorkflows(loadedWorkflows);
        setStatus("ready");
      })
      .catch(() => {
        if (!cancelled) {
          setAssets([]);
          setWorkflows([]);
          setStatus("error");
        }
      });
    return () => {
      cancelled = true;
    };
  }, [reloadKey]);

  const selected = assets.find((asset) => asset.id === selectedId) ?? null;

  function selectAsset(asset: LibraryAsset): void {
    setSelectedId(asset.id);
    setDraft(draftFromAsset(asset));
    setActionError(null);
  }

  const hiddenCount = assets.filter((asset) => asset.status === "inactive").length;
  const activeCount = assets.length - hiddenCount;

  async function saveSelected(): Promise<void> {
    if (!selected || !draft) {
      return;
    }
    setSaving(true);
    setActionError(null);
    try {
      const updated = await updateLibraryAsset(selected.id, {
        name: draft.name.trim() || undefined,
        kind: draft.kind,
        mood: draft.mood,
        energy: draft.energy,
        caveats: draft.caveats,
      });
      const granted = await setLibraryGrant(selected.id, draft.grant);
      const merged = { ...updated, grant: granted.grant };
      setAssets((current) => current.map((asset) => (asset.id === merged.id ? merged : asset)));
      setDraft(draftFromAsset(merged));
    } catch {
      setActionError("Could not save changes. Try again.");
    } finally {
      setSaving(false);
    }
  }

  async function hideSelected(): Promise<void> {
    if (!selected) {
      return;
    }
    setSaving(true);
    setActionError(null);
    try {
      const updated =
        selected.status === "inactive"
          ? await reactivateLibraryAsset(selected.id)
          : await deactivateLibraryAsset(selected.id);
      setAssets((current) =>
        current.map((asset) =>
          asset.id === updated.id ? { ...asset, status: updated.status } : asset,
        ),
      );
    } catch {
      setActionError("Could not update asset visibility.");
    } finally {
      setSaving(false);
    }
  }

  async function uploadNew(): Promise<void> {
    if (!addFile) {
      setActionError("Choose an audio file to upload.");
      return;
    }
    setSaving(true);
    setActionError(null);
    try {
      const form = new FormData();
      form.append("file", addFile);
      form.append("name", addDraft.name.trim() || addFile.name);
      form.append("kind", addDraft.kind);
      form.append("grant", JSON.stringify(addDraft.grant));
      if (addDraft.mood.length > 0) {
        form.append("mood", JSON.stringify(addDraft.mood));
      }
      if (addDraft.energy.length > 0) {
        form.append("energy", JSON.stringify(addDraft.energy));
      }
      const created = await uploadLibraryAsset(form);
      if (addDraft.caveats.trim()) {
        await updateLibraryAsset(created.id, { caveats: addDraft.caveats });
      }
      const refreshed = await fetchLibraryAssets();
      setAssets(refreshed);
      const saved = refreshed.find((asset) => asset.id === created.id) ?? created;
      selectAsset(saved);
      setShowAdd(false);
      setAddFile(null);
      setAddDraft({
        name: "",
        kind: "music",
        mood: [],
        energy: [],
        caveats: "",
        grant: { all: true },
      });
    } catch {
      setActionError("Could not upload asset. Check the file and try again.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <section className="view on library-view">
      <div className="page-head">
        <div>
          <div className="page-title">Library</div>
          <div className="page-note">
            Reusable assets that outlive a run — background music, sound effects, and narrator
            voices. Choose which workflow(s) can use each one.
          </div>
        </div>
        {status === "ready" ? (
          <div className="page-head-actions">
            <button
              type="button"
              className="btn btn-primary"
              onClick={() => {
                setShowAdd(true);
                setSelectedId(null);
                setActionError(null);
              }}
            >
              + Add asset
            </button>
          </div>
        ) : null}
      </div>

      {status === "loading" ? (
        <div className="panel">
          <div className="panel-body">
            <div className="page-note">Loading library…</div>
          </div>
        </div>
      ) : null}

      {status === "error" ? (
        <div className="panel">
          <div className="panel-body">
            <div className="form-error">
              Couldn&apos;t load the library. Check that SFVF is running.
              <button
                type="button"
                className="btn btn-sm"
                style={{ marginLeft: 8 }}
                onClick={() => {
                  setStatus("loading");
                  setReloadKey((key) => key + 1);
                }}
              >
                Retry
              </button>
            </div>
          </div>
        </div>
      ) : null}

      {status === "ready" && showAdd ? (
        <div className="panel library-add-panel">
          <div className="panel-head">
            <span className="panel-title">Add asset</span>
          </div>
          <div className="panel-body library-form">
            <div
              className="drop"
              onDragOver={(event) => event.preventDefault()}
              onDrop={(event) => {
                event.preventDefault();
                const file = event.dataTransfer.files[0];
                if (file) {
                  setAddFile(file);
                }
              }}
            >
              {addFile ? (
                <span>{addFile.name}</span>
              ) : (
                <>
                  Drop an audio file here, or{" "}
                  <button
                    type="button"
                    className="btn btn-ghost btn-sm"
                    onClick={() => addFileRef.current?.click()}
                  >
                    browse
                  </button>
                </>
              )}
              <div className="tiny" style={{ marginTop: 6 }}>
                mp3 / wav / m4a / ogg · up to 25 MB
              </div>
              <input
                ref={addFileRef}
                type="file"
                accept="audio/*,.mp3,.wav,.m4a,.ogg"
                hidden
                onChange={(event) => {
                  const file = event.target.files?.[0] ?? null;
                  setAddFile(file);
                }}
              />
            </div>
            <div className="row2">
              <label className="field">
                <span className="field-label">Name</span>
                <input
                  className="field-input"
                  placeholder="e.g. Cosmic Drift"
                  value={addDraft.name}
                  onChange={(event) => setAddDraft({ ...addDraft, name: event.target.value })}
                />
              </label>
              <label className="field">
                <span className="field-label">Type</span>
                <select
                  className="field-input"
                  value={addDraft.kind}
                  onChange={(event) => setAddDraft({ ...addDraft, kind: event.target.value })}
                >
                  <option value="music">music</option>
                  <option value="sfx">sfx</option>
                  <option value="voice">voice — reference clip</option>
                </select>
              </label>
            </div>
            <div className="row2">
              <label className="field">
                <span className="field-label">Mood</span>
                <TagInput
                  tags={addDraft.mood}
                  placeholder="type, then comma"
                  onChange={(mood) => setAddDraft({ ...addDraft, mood })}
                />
              </label>
              <label className="field">
                <span className="field-label">Energy</span>
                <TagInput
                  tags={addDraft.energy}
                  placeholder="type, then comma"
                  onChange={(energy) => setAddDraft({ ...addDraft, energy })}
                />
              </label>
            </div>
            <div className="field">
              <span className="field-label">Access</span>
              <AccessPicker
                compact
                grant={addDraft.grant}
                workflows={workflows}
                onChange={(grant) => setAddDraft({ ...addDraft, grant })}
              />
            </div>
            <p className="field-help" style={{ marginBottom: 12 }}>
              A <strong>voice</strong> asset clones a narrator from a clip you upload: give it a{" "}
              <strong>clean ~20–60 s voice sample</strong> (one speaker, no music/noise). It becomes
              a voice you can pick per run; preview it on a sample line after upload.
            </p>
            {actionError ? <div className="form-error">{actionError}</div> : null}
            <div className="detail-actions">
              <button
                type="button"
                className="btn btn-sm"
                disabled={saving}
                onClick={() => {
                  setShowAdd(false);
                  setActionError(null);
                  if (assets.length > 0) {
                    selectAsset(assets[0]);
                  }
                }}
              >
                Cancel
              </button>
              <button
                type="button"
                className="btn btn-primary btn-sm"
                disabled={saving}
                onClick={() => void uploadNew()}
              >
                Upload &amp; save
              </button>
            </div>
          </div>
        </div>
      ) : null}

      {status === "ready" && !showAdd ? (
        <div className="two library-two">
          <div className="panel">
            <div className="panel-head">
              <span className="panel-title">Assets</span>
              {assets.length > 0 ? (
                <span className="tiny">
                  {activeCount} asset{activeCount === 1 ? "" : "s"}
                  {hiddenCount > 0 ? ` · ${hiddenCount} hidden` : ""}
                </span>
              ) : null}
            </div>
            {assets.length === 0 ? (
              <div className="empty">
                <div className="big">No assets yet</div>
                <div style={{ maxWidth: "38ch", margin: "0 auto 14px" }}>
                  Add background music, sound effects, or a narrator voice. Until then, videos play
                  with narration only.
                </div>
                <button
                  type="button"
                  className="btn btn-primary btn-sm"
                  onClick={() => {
                    setShowAdd(true);
                  }}
                >
                  + Add your first asset
                </button>
              </div>
            ) : (
              <div className="list library-list">
                {assets.map((asset) => {
                  const inactive = asset.status === "inactive";
                  const selectedRow = asset.id === selectedId;
                  return (
                    <button
                      type="button"
                      key={asset.id}
                      className={`li${selectedRow ? " sel" : ""}${inactive ? " inactive" : ""}`}
                      aria-label={displayName(asset)}
                      onClick={() => selectAsset(asset)}
                    >
                      <div className="li-main">
                        <div className="li-title">
                          <span className={`pill ${kindClass(asset.kind)}`}>{asset.kind}</span>
                          {displayName(asset)}
                          {inactive ? <span className="pill idle">hidden</span> : null}
                        </div>
                        <div className="li-sub">
                          {facetLine(asset).map((line) => (
                            <span key={line}>{line}</span>
                          ))}
                        </div>
                      </div>
                      <div className="li-access">
                        {inactive ? "—" : accessSummary(asset.grant, workflows)}
                      </div>
                    </button>
                  );
                })}
              </div>
            )}
          </div>

          {selected && draft ? (
            <div className="panel">
              <div className="panel-head">
                <span className="panel-title">{displayName(selected)}</span>
                <span className={`pill ${kindClass(selected.kind)}`}>{selected.kind}</span>
              </div>
              <div className="panel-body library-form">
                <div className="row2">
                  <label className="field">
                    <span className="field-label">Name</span>
                    <input
                      className="field-input"
                      value={draft.name}
                      onChange={(event) => setDraft({ ...draft, name: event.target.value })}
                    />
                  </label>
                  <label className="field">
                    <span className="field-label">Type</span>
                    <select
                      className="field-input"
                      value={draft.kind}
                      onChange={(event) => setDraft({ ...draft, kind: event.target.value })}
                    >
                      <option value="music">music</option>
                      <option value="sfx">sfx</option>
                      <option value="voice">voice</option>
                    </select>
                  </label>
                </div>
                <div className="row2">
                  <label className="field">
                    <span className="field-label">Mood</span>
                    <TagInput
                      tags={draft.mood}
                      placeholder="type, then comma"
                      onChange={(mood) => setDraft({ ...draft, mood })}
                    />
                    <span className="field-help">
                      Comma makes a tag · click &times; or press Delete to remove · Enter/F2 or
                      right-click to edit
                    </span>
                  </label>
                  <label className="field">
                    <span className="field-label">Energy</span>
                    <TagInput
                      tags={draft.energy}
                      placeholder="type, then comma"
                      onChange={(energy) => setDraft({ ...draft, energy })}
                    />
                  </label>
                </div>
                <div className="field">
                  <span className="field-label">Access — which workflows may use this</span>
                  <AccessPicker
                    grant={draft.grant}
                    workflows={workflows}
                    onChange={(grant) => setDraft({ ...draft, grant })}
                  />
                </div>
                <label className="field">
                  <span className="field-label">Notes / caveats</span>
                  <textarea
                    className="field-input field-textarea"
                    rows={4}
                    value={draft.caveats}
                    onChange={(event) => setDraft({ ...draft, caveats: event.target.value })}
                  />
                </label>
                {actionError ? <div className="form-error">{actionError}</div> : null}
                <div className="detail-actions">
                  <button
                    type="button"
                    className="btn btn-danger btn-sm"
                    disabled={saving}
                    onClick={() => void hideSelected()}
                  >
                    {selected.status === "inactive" ? "Restore asset" : "Hide asset"}
                  </button>
                  <button
                    type="button"
                    className="btn btn-sm"
                    disabled={saving}
                    onClick={() => {
                      if (selected) {
                        setDraft(draftFromAsset(selected));
                      }
                    }}
                  >
                    Cancel
                  </button>
                  <button
                    type="button"
                    className="btn btn-primary btn-sm"
                    disabled={saving}
                    onClick={() => void saveSelected()}
                  >
                    Save
                  </button>
                </div>
              </div>
            </div>
          ) : null}
        </div>
      ) : null}
    </section>
  );
}
