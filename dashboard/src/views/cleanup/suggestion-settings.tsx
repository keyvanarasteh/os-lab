/**
 * CUX-08: the suggestion preferences editor. One compact panel: a mode, an optional free-space
 * target, a smallest worthwhile size and, per entry, Auto / Always / Never. It saves through
 * `/api/cleanup/preferences` (a small JSON file in the private state folder), so the choices
 * survive restarts and app updates, and Scan & review applies them on the server.
 * Unsafe entries (high risk, credentials, privileged, measured-only) are not listed: they are never suggested.
 */
import { useEffect, useMemo, useState } from "react";
import { Status } from "../../components/ui";
import { api, formatBytes, message, type CleanupEntry, type CleanupSuggestionPrefs } from "../../lib/api";

const GIB = 1024 ** 3;
const MIB = 1024 ** 2;
const MODES: { id: CleanupSuggestionPrefs["mode"]; label: string; hint: string }[] = [
  { id: "auto", label: "Auto", hint: "Recommended items, plus the safest large ones while the disk is low." },
  { id: "recommended", label: "Recommended", hint: "Only the catalog's default set, whatever the disk state." },
  { id: "extended", label: "Extended", hint: "Every safe item that was measured." },
];

type Choice = "auto" | "always" | "never";

export function suggestable(entry: CleanupEntry): boolean {
  return !["high", "privacy", "credentials"].includes(entry.risk) && !entry.needsPrivilege && entry.cleanable !== false;
}

export function SuggestionSettings({ entries, sizes, onSaved }: { entries: CleanupEntry[]; sizes: Map<string, number>; onSaved?: (prefs: CleanupSuggestionPrefs) => void }) {
  const [saved, setSaved] = useState<CleanupSuggestionPrefs | null>(null);
  const [draft, setDraft] = useState<CleanupSuggestionPrefs | null>(null);
  const [loadError, setLoadError] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [find, setFind] = useState("");

  useEffect(() => {
    let alive = true;
    void api.cleanupPreferences().then((value) => {
      if (!alive) return;
      setSaved(value.suggestion); setDraft(value.suggestion);
      if (value.configError) setLoadError(value.configError);
    }).catch((e) => { if (alive) setLoadError(message(e)); });
    return () => { alive = false; };
  }, []);

  const rows = useMemo(() => entries.filter(suggestable)
    .filter((entry) => !find.trim() || entry.name.toLowerCase().includes(find.trim().toLowerCase()) || entry.id.toLowerCase().includes(find.trim().toLowerCase()))
    .sort((a, b) => (sizes.get(b.id) ?? 0) - (sizes.get(a.id) ?? 0) || a.name.localeCompare(b.name)), [entries, find, sizes]);

  if (!draft || !saved) return loadError ? <Status value={{ ok: false, text: loadError }} /> : <p role="status" className="text-xs">Loading…</p>;
  const dirty = JSON.stringify(draft) !== JSON.stringify(saved);
  const choiceOf = (id: string): Choice => draft.include.includes(id) ? "always" : draft.exclude.includes(id) ? "never" : "auto";
  function setChoice(id: string, choice: Choice) {
    setDraft((old) => old && ({
      ...old,
      include: choice === "always" ? [...old.include.filter((item) => item !== id), id] : old.include.filter((item) => item !== id),
      exclude: choice === "never" ? [...old.exclude.filter((item) => item !== id), id] : old.exclude.filter((item) => item !== id),
    }));
  }
  async function save(next: CleanupSuggestionPrefs) {
    setBusy(true); setError("");
    try { const result = await api.cleanupPreferencesSave(next); setSaved(result.suggestion); setDraft(result.suggestion); onSaved?.(result.suggestion); }
    catch (e) { setError(message(e)); }
    finally { setBusy(false); }
  }
  const mode = MODES.find((item) => item.id === draft.mode) ?? MODES[0];
  return <div className="space-y-3 text-sm">
    {loadError && <Status value={{ ok: false, text: loadError }} />}
    <div role="group" aria-label="Suggestion mode" className="flex flex-wrap gap-1">
      {MODES.map((item) => <button key={item.id} type="button" className="iux-btn" data-variant={draft.mode === item.id ? "primary" : "outline"} aria-pressed={draft.mode === item.id}
        onClick={() => setDraft({ ...draft, mode: item.id })}>{item.label}</button>)}
    </div>
    <p className="text-xs text-(--iux-muted-foreground)">{mode.hint}</p>
    <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
      <label className="text-xs">Keep free{" "}
        <input type="number" min={0} dir="ltr" className="iux-input w-20" aria-label="Free space to aim for (GB)" placeholder="auto"
          value={draft.targetFreeBytes ? Math.round(draft.targetFreeBytes / GIB) : ""}
          onChange={(event) => setDraft({ ...draft, targetFreeBytes: Number(event.target.value) > 0 ? Number(event.target.value) * GIB : null })} /> GB
      </label>
      <label className="text-xs">Ignore under{" "}
        <input type="number" min={0} dir="ltr" className="iux-input w-20" aria-label="Smallest item worth suggesting (MB)"
          value={Math.round(draft.minEntryBytes / MIB)}
          onChange={(event) => setDraft({ ...draft, minEntryBytes: Math.max(0, Number(event.target.value) || 0) * MIB })} /> MB
      </label>
    </div>
    <details>
      <summary className="cursor-pointer text-xs text-(--iux-muted-foreground)"><span>Per item</span> <span dir="ltr" className="tabular-nums">{draft.include.length}</span> <span>always</span> · <span dir="ltr" className="tabular-nums">{draft.exclude.length}</span> <span>never</span></summary>
      <input type="search" className="iux-input mt-2 w-full" aria-label="Find an item" placeholder="Find an item" value={find} onChange={(event) => setFind(event.target.value)} />
      <ul className="iux-scroll mt-2 max-h-56 divide-y divide-(--iux-border) overflow-auto rounded-md border border-(--iux-border)">
        {rows.map((entry) => <li key={entry.id} className="flex items-center gap-2 px-2 py-1">
          <span className="min-w-0 flex-1 truncate text-xs" title={entry.name}>{entry.name}</span>
          <span dir="ltr" className="text-xs tabular-nums text-(--iux-muted-foreground)">{sizes.has(entry.id) ? formatBytes(sizes.get(entry.id)!) : ""}</span>
          <select className="iux-input" aria-label={`Suggest ${entry.name}`} value={choiceOf(entry.id)} onChange={(event) => setChoice(entry.id, event.target.value as Choice)}>
            <option value="auto">Auto</option><option value="always">Always</option><option value="never">Never</option>
          </select>
        </li>)}
        {!rows.length && <li className="px-2 py-2 text-xs">No items match.</li>}
      </ul>
      <p className="mt-1 text-xs text-(--iux-muted-foreground)">High-risk, credential, administrator-only and measured-only items are never suggested, so they are not listed.</p>
    </details>
    {error && <p role="alert" className="text-xs text-(--iux-danger)">{error}</p>}
    <div className="flex flex-wrap items-center gap-2">
      <button type="button" className="iux-btn" data-variant="primary" disabled={busy || !dirty} onClick={() => void save(draft)}>Save</button>
      <button type="button" className="iux-btn" data-variant="ghost" disabled={busy} onClick={() => void save({ mode: "auto", include: [], exclude: [], minEntryBytes: MIB, targetFreeBytes: null })}>Reset</button>
      {!dirty && <span role="status" className="text-xs text-(--iux-muted-foreground)">Saved on this computer</span>}
    </div>
  </div>;
}
