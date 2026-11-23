/**
 * The "Other volumes" part of the storage card: every other mounted volume as a small card (name,
 * mount path, used/free bar, sizes, kind), grouped so a machine with 20+ mounts stays scannable.
 * Disks open by default; system, simulator and temporary mounts stay closed. Mounts that report the
 * same device collapse into one card with their paths listed under it. Display only: nothing here
 * cleans anything.
 */
import { Badge } from "../../components/ui";
import { formatBytes, type CleanupVolume } from "../../lib/api";

type GroupId = "disks" | "system" | "simulators" | "temporary";

const GROUPS: { id: GroupId; title: string; open: boolean }[] = [
  { id: "disks", title: "Disks", open: true },
  { id: "system", title: "System", open: false },
  { id: "simulators", title: "Simulators and devices", open: false },
  { id: "temporary", title: "Temporary", open: false },
];

function groupOf(mountPoint: string): GroupId {
  if (/^\/private\/(var\/folders|tmp)\b/.test(mountPoint) || /^\/(tmp|var\/tmp)\b/.test(mountPoint)) return "temporary";
  if (/CoreSimulator|SimulatorRuntime|CoreDevice|cryptexd/.test(mountPoint)) return "simulators";
  if (/^\/System\/Volumes\/(?!Data$)/.test(mountPoint)) return "system";
  return "disks";
}

function nameOf(volume: CleanupVolume): string {
  const segments = volume.mountPoint.split(/[\\/]/).filter(Boolean);
  return segments[segments.length - 1] || volume.name || volume.mountPoint;
}

type Card = { key: string; volume: CleanupVolume; mounts: CleanupVolume[] };

/** APFS volumes of one container (/dev/disk7s1 ... /dev/disk7s8) share one capacity, so they are one card. */
const containerOf = (device: string) => device.replace(/^\/dev\//, "").replace(/s\d+$/, "");

/** One card per container/device (or per identical size/kind when the device is not reported). */
function cardsOf(volumes: CleanupVolume[]): Card[] {
  const byKey = new Map<string, Card>();
  for (const volume of volumes) {
    const key = volume.device ? `${containerOf(volume.device)}|${volume.totalBytes}|${volume.freeBytes}` : `${volume.totalBytes}|${volume.freeBytes}|${volume.kind}`;
    const card = byKey.get(key);
    if (card) card.mounts.push(volume);
    else byKey.set(key, { key, volume, mounts: [volume] });
  }
  return [...byKey.values()].sort((a, b) => (b.volume.totalBytes ?? 0) - (a.volume.totalBytes ?? 0));
}

function VolumeCard({ card }: { card: Card }) {
  const { volume, mounts } = card;
  const total = volume.totalBytes ?? 0;
  const free = volume.freeBytes ?? 0;
  const used = volume.usedBytes ?? Math.max(0, total - free);
  const usedPercent = total > 0 ? Math.min(100, (used / total) * 100) : 0;
  const warning = volume.pressure === "warning";
  return <li className="rounded-md border border-(--iux-border) p-3 text-xs" translate="no">
    <div className="flex items-center gap-2">
      <span className="min-w-0 flex-1 truncate text-sm font-medium" title={volume.mountPoint}>{mounts.length > 1 && volume.device ? containerOf(volume.device) : nameOf(volume)}</span>
      <Badge tone={warning ? "danger" : undefined}>{volume.kind}</Badge>
    </div>
    <div className="mt-0.5 truncate text-(--iux-muted-foreground)" dir="ltr" title={volume.mountPoint}>{volume.mountPoint}</div>
    {total > 0 && <div className="mt-2 flex h-1.5 overflow-hidden rounded-full bg-[#f36c21]" aria-hidden="true">
      <span className="bg-[#7a7a72]" style={{ width: `${usedPercent}%` }} />
    </div>}
    <dl className="mt-2 grid grid-cols-3 gap-2 tabular-nums" dir="ltr">
      <div><dt className="text-(--iux-muted-foreground)">Free</dt><dd>{formatBytes(volume.freeBytes)}</dd></div>
      <div><dt className="text-(--iux-muted-foreground)">Used</dt><dd>{total > 0 ? formatBytes(used) : "—"}</dd></div>
      <div><dt className="text-(--iux-muted-foreground)">Total</dt><dd>{formatBytes(volume.totalBytes)}</dd></div>
    </dl>
    {mounts.length > 1 && <details className="mt-2">
      <summary className="cursor-pointer text-(--iux-muted-foreground)">{mounts.length} mount points</summary>
      <ul className="mt-1 space-y-0.5" dir="ltr">{mounts.map((mount) =>
        <li key={mount.mountPoint} className="truncate" title={mount.mountPoint}>{mount.mountPoint}</li>)}</ul>
    </details>}
  </li>;
}

export function OtherVolumes({ volumes }: { volumes: CleanupVolume[] }) {
  if (!volumes.length) return null;
  return <details className="mt-1 text-xs">
    <summary className="cursor-pointer text-(--iux-muted-foreground)">Other volumes ({volumes.length})</summary>
    <div className="mt-2 space-y-2">
      {GROUPS.map((group) => {
        const cards = cardsOf(volumes.filter((volume) => groupOf(volume.mountPoint) === group.id));
        if (!cards.length) return null;
        const count = cards.reduce((sum, card) => sum + card.mounts.length, 0);
        return <details key={group.id} open={group.open}>
          <summary className="cursor-pointer text-(--iux-muted-foreground)">{group.title} ({count})</summary>
          <ul className="mt-2 grid gap-2 sm:grid-cols-2 lg:grid-cols-3">{cards.map((card) => <VolumeCard key={card.key} card={card} />)}</ul>
        </details>;
      })}
    </div>
  </details>;
}
