/**
 * CLN-26: the learning-ledger settings section.
 *
 * The ledger records what was really cleaned (bytes actually freed) and
 * softly suggests those entries at the next scan — ticked, never
 * default-selected, and never for high-risk, credential or privacy rows.
 * It stays in this computer's private state and is clearable here.
 */
import { useState } from "react";
import { Section, Status } from "../../components/ui";
import { api, message, type LedgerPayload } from "../../lib/api";
import { bytes } from "./format";

export function LedgerSection({ ledger, reload }: { ledger: LedgerPayload | null; reload: () => void }) {
  const [error, setError] = useState("");
  const [cleared, setCleared] = useState(false);
  const [busy, setBusy] = useState(false);

  async function clear() {
    setBusy(true); setError(""); setCleared(false);
    try {
      const response = await api.cleanupLedgerClear();
      if (response.error) throw new Error(response.error);
      setCleared(true);
      reload();
    } catch (e) {
      setError(message(e));
    } finally {
      setBusy(false);
    }
  }

  const stats = ledger?.stats;

  return <Section id="cleanup-ledger" title="Learning"
    description="The ledger remembers what you actually cleaned and softly suggests those entries at the next scan — ticked, never forced, and never for high-risk, credential or privacy rows.">
    {ledger?.error && <Status value={{ ok: false, text: ledger.error }} />}
    {error && <Status value={{ ok: false, text: error }} />}
    {cleared && <p role="status" className="text-sm text-(--iux-muted-foreground)">Ledger cleared.</p>}
    <div className="flex flex-wrap items-center gap-2">
      {stats && <span className="text-xs text-(--iux-muted-foreground)">
        <span className="tabular-nums">{stats.runs}</span> runs · <span className="tabular-nums">{stats.entries}</span> entries · <span dir="ltr" className="tabular-nums">{bytes(stats.bytes)}</span> cleaned so far
      </span>}
      <button type="button" className="iux-btn" disabled={busy || !stats || !stats.runs}
        title="Forget everything the ledger learned" onClick={() => void clear()}>
        Clear ledger
      </button>
    </div>
  </Section>;
}
