/**
 * CLN-14: the secure-shred settings section.
 *
 * The policy (off / 1-pass / 3-pass) gates the engine's shred plan mode: off
 * refuses shred plans, and a corrupt store refuses them too — shred fails
 * closed while Trash and delete never read this store. Trash stays the
 * default; the card states the physical limits honestly, in line with the
 * confirmation copy a shred plan shows.
 */
import { useState } from "react";
import { Section, Status } from "../../components/ui";
import { api, message, type CleanupSettingsPayload, type ShredPolicy } from "../../lib/api";

const POLICIES: { value: ShredPolicy; label: string }[] = [
  { value: "off", label: "Off" },
  { value: "1-pass", label: "1-pass overwrite" },
  { value: "3-pass", label: "3-pass overwrite" },
];

export function ShredSection({ settings, reload }: {
  settings: CleanupSettingsPayload | null; reload: () => void;
}) {
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const policy = settings?.settings.shredPolicy ?? "off";

  async function choose(next: ShredPolicy) {
    setBusy(true); setError("");
    try {
      const response = await api.cleanupSettingsSet(next);
      if (response.error) throw new Error(response.error);
      reload();
    } catch (e) {
      setError(message(e));
    } finally {
      setBusy(false);
    }
  }

  return <Section id="cleanup-shred" title="Secure shred"
    description="Overwrites files in place before deletion. Trash stays the default; this policy only unlocks shred as an explicit per-plan choice.">
    {settings?.error && <Status value={{ ok: false, text: settings.error }} />}
    {error && <Status value={{ ok: false, text: error }} />}
    <div className="flex flex-wrap gap-2" role="group" aria-label="Shred policy">
      {POLICIES.map((option) => <button type="button" key={option.value} className="iux-btn"
        data-variant={policy === option.value ? "primary" : "outline"} aria-pressed={policy === option.value}
        disabled={busy} onClick={() => void choose(option.value)}>{option.label}</button>)}
    </div>
    <p className="mt-3 text-sm text-(--iux-muted-foreground)">
      Overwriting is not a guarantee on SSD, APFS or copy-on-write filesystems —
      wear levelling and copies can leave the original blocks elsewhere on the device.
    </p>
    {policy !== "off" && <p className="text-sm text-(--iux-muted-foreground)">
      The policy is on, but nothing is shredded until a plan explicitly chooses shred mode.
    </p>}
  </Section>;
}
