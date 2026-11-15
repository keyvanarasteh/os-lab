/**
 * CLN-17: the ignore-rules settings section.
 *
 * Rules are typed data (path / glob / extension) the engine enforces at scan
 * and plan time: an ignored path is never scanned and never planned, and a
 * folder holding an ignored path is refused too. The section lists the rules,
 * adds one and removes one. A store that cannot be read is shown here — the
 * engine refuses scans and plans until it is fixed, so the error must stay
 * visible (docs/UX_READINESS.md).
 */
import { useState } from "react";
import { PlusIcon, TrashIcon } from "@phosphor-icons/react";
import { Badge, Empty, Section, Status } from "../../components/ui";
import { api, message, type IgnoreRuleType, type IgnoreRulesPayload } from "../../lib/api";

const RULE_TYPES: IgnoreRuleType[] = ["path", "glob", "extension"];

/** The per-type explanation and placeholder, both user-visible copy. */
const TYPE_HINTS: Record<IgnoreRuleType, { hint: string; placeholder: string }> = {
  path: {
    hint: "A path rule covers the folder and everything inside it.",
    placeholder: "/absolute/path — for example /Users/you/keep",
  },
  glob: {
    hint: "A pattern matches a name at any depth; * and ? never cross a folder boundary. A folder matched by the pattern covers everything inside it.",
    placeholder: "Pattern — for example node_modules*",
  },
  extension: {
    hint: "A file type matches every file with that suffix, case-insensitively.",
    placeholder: "File type — for example log",
  },
};

export function IgnoreSection({ rules, reload }: { rules: IgnoreRulesPayload | null; reload: () => void }) {
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [adding, setAdding] = useState(false);
  const [type, setType] = useState<IgnoreRuleType>("path");
  const [value, setValue] = useState("");
  const [note, setNote] = useState("");

  async function act(action: () => Promise<unknown>) {
    setBusy(true); setError("");
    try {
      await action();
      reload();
    } catch (e) {
      setError(message(e));
    } finally {
      setBusy(false);
    }
  }

  function addRule() {
    if (!value.trim()) return;
    void act(async () => {
      const response = await api.cleanupIgnoreAdd(type, value.trim(), note.trim() || undefined);
      if (response.error) throw new Error(response.error);
      setValue(""); setNote(""); setAdding(false);
    });
  }

  const items = rules?.rules ?? [];
  const hint = TYPE_HINTS[type];

  return <Section id="cleanup-ignore" title="Ignore rules"
    description="Paths, patterns and file types the cleaner never touches — enforced during scans and plans.">
    {rules?.error && <Status value={{ ok: false, text: rules.error }} />}
    {error && <Status value={{ ok: false, text: error }} />}
    <div className="flex flex-wrap items-center gap-2">
      <button type="button" className="iux-btn" data-variant="primary" disabled={busy}
        onClick={() => setAdding((open) => !open)}>
        <PlusIcon size={14} className="inline" /> Add a rule
      </button>
      <span className="text-xs text-(--iux-muted-foreground)">
        {items.length} {items.length === 1 ? "rule" : "rules"}
      </span>
    </div>
    {adding && <div className="mt-3 rounded-md border border-(--iux-border) p-3 text-sm">
      <p className="text-xs text-(--iux-muted-foreground)">{hint.hint}</p>
      <div className="mt-2 flex flex-wrap items-center gap-2">
        <select className="iux-input w-36" aria-label="Rule type" value={type} disabled={busy}
          onChange={(event) => setType(event.target.value as IgnoreRuleType)}>
          {RULE_TYPES.map((option) => <option key={option} value={option}>{option}</option>)}
        </select>
        <input type="text" className="iux-input min-w-0 flex-1" placeholder={hint.placeholder} dir="ltr"
          translate="no" value={value} disabled={busy} aria-label="Rule value"
          onChange={(event) => setValue(event.target.value)} />
        <input type="text" className="iux-input w-44" placeholder="Note (optional)" value={note} disabled={busy}
          aria-label="Rule note" onChange={(event) => setNote(event.target.value)} />
        <button type="button" className="iux-btn" data-variant="primary" disabled={busy || !value.trim()}
          onClick={() => void addRule()}>Add rule</button>
        <button type="button" className="iux-btn" disabled={busy} onClick={() => setAdding(false)}>Cancel</button>
      </div>
    </div>}
    {items.length ? <div className="mt-3 divide-y divide-(--iux-border)">
      {items.map((rule) => <div key={rule.id} className="flex flex-wrap items-center gap-2 py-2 text-sm">
        <Badge>{rule.type}</Badge>
        <span className="min-w-0 flex-1 break-all font-medium" dir="ltr" translate="no">{rule.value}</span>
        {rule.note && <span className="text-xs text-(--iux-muted-foreground)" title="Rule note">{rule.note}</span>}
        <button type="button" className="iux-btn" data-variant="ghost" title="Remove this rule" disabled={busy}
          onClick={() => void act(() => api.cleanupIgnoreRemove(rule.id))}>
          <TrashIcon size={14} />
        </button>
      </div>)}
    </div> : <Empty>No ignore rules yet. Add a path, pattern or file type the cleaner should never touch.</Empty>}
  </Section>;
}
