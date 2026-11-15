/**
 * CLN-18: the scheduled-scans settings section.
 *
 * A schedule fires a scan-only job on its cron — the same read-only catalog
 * scan the page runs, marked `scheduled-scan` in the jobs list. A schedule
 * can never clean: the runner spawns scans and nothing else, and a corrupt
 * store is shown here because due schedules are skipped until it is fixed.
 */
import { useState } from "react";
import { PlusIcon, TrashIcon } from "@phosphor-icons/react";
import { Badge, Empty, Section, Status } from "../../components/ui";
import { api, message, type SchedulesPayload } from "../../lib/api";

export function SchedulesSection({ schedules, reload }: {
  schedules: SchedulesPayload | null; reload: () => void;
}) {
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [adding, setAdding] = useState(false);
  const [cron, setCron] = useState("");

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

  function addSchedule() {
    if (!cron.trim()) return;
    void act(async () => {
      const response = await api.cleanupScheduleAdd(cron.trim());
      if (response.error) throw new Error(response.error);
      setCron(""); setAdding(false);
    });
  }

  const items = schedules?.schedules ?? [];

  return <Section id="cleanup-schedules" title="Scheduled scans"
    description="A schedule fires a scan-only job on its cron. A schedule can never clean.">
    {schedules?.error && <Status value={{ ok: false, text: schedules.error }} />}
    {error && <Status value={{ ok: false, text: error }} />}
    <div className="flex flex-wrap items-center gap-2">
      <button type="button" className="iux-btn" data-variant="primary" disabled={busy}
        onClick={() => setAdding((open) => !open)}>
        <PlusIcon size={14} className="inline" /> Add a schedule
      </button>
      <span className="text-xs text-(--iux-muted-foreground)">
        {items.length} {items.length === 1 ? "schedule" : "schedules"}
      </span>
    </div>
    {adding && <div className="mt-3 rounded-md border border-(--iux-border) p-3 text-sm">
      <p className="text-xs text-(--iux-muted-foreground)">
        Five fields: minute hour day-of-month month day-of-week — for example 30 2 * * *
      </p>
      <div className="mt-2 flex flex-wrap items-center gap-2">
        <input type="text" className="iux-input min-w-0 flex-1" placeholder="30 2 * * *" dir="ltr"
          translate="no" value={cron} disabled={busy} aria-label="Cron expression"
          onChange={(event) => setCron(event.target.value)} />
        <button type="button" className="iux-btn" data-variant="primary" disabled={busy || !cron.trim()}
          onClick={() => void addSchedule()}>Add schedule</button>
        <button type="button" className="iux-btn" disabled={busy} onClick={() => setAdding(false)}>Cancel</button>
      </div>
    </div>}
    {items.length ? <div className="mt-3 divide-y divide-(--iux-border)">
      {items.map((item) => <div key={item.id} className="flex flex-wrap items-center gap-2 py-2 text-sm">
        <Badge tone={item.enabled ? "success" : undefined}>{item.enabled ? "Enabled" : "Disabled"}</Badge>
        <span className="font-medium" dir="ltr" translate="no">{item.cron}</span>
        <span className="text-xs text-(--iux-muted-foreground)" title="Last run">
          last run {item.lastRunAt ? new Date(item.lastRunAt * 1000).toLocaleString() : "never"}
        </span>
        <label className="text-xs" title="Enable or disable this schedule">
          <input type="checkbox" className="iux-touch-target mr-1 size-3.5 accent-[#f36c21]" checked={item.enabled}
            disabled={busy} onChange={(event) => void act(() => api.cleanupScheduleToggle(item.id, event.target.checked))} />
          enabled
        </label>
        <button type="button" className="iux-btn" data-variant="ghost" title="Remove this schedule" disabled={busy}
          onClick={() => void act(() => api.cleanupScheduleRemove(item.id))}>
          <TrashIcon size={14} />
        </button>
      </div>)}
    </div> : <Empty>No schedules yet. Add a cron expression and the scan runs on it — nothing is ever cleaned.</Empty>}
  </Section>;
}
