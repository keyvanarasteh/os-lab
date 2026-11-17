/**
 * The Full Disk Access guide: shows the app that needs the grant as a draggable tile, opens the
 * Settings pane, reveals the app in Finder, resets a stuck grant and relaunches the app so the
 * grant takes effect. The tile drags natively in the desktop app (the page calls one narrow
 * command with no path); in a browser it falls back to Reveal in Finder. A running process cannot
 * detect its own fresh grant: the page re-probes every few seconds, and when the toggle flips it
 * shows "You're ready" and, in the desktop app, relaunches it after a short countdown the user can
 * stop. In a browser the user reopens the app that started the console themselves.
 */
import { useEffect, useRef, useState } from "react";
import { ArrowClockwiseIcon, CheckCircleIcon, CheckIcon, FolderIcon, GearIcon, ShieldCheckIcon, SparkleIcon, TerminalWindowIcon } from "@phosphor-icons/react";
import { api } from "../../lib/api";

type Tauri = { invoke: (command: string, args?: Record<string, unknown>) => Promise<unknown> };
const tauri = (): Tauri | null => (typeof window !== "undefined" ? (window as unknown as { __TAURI_INTERNALS__?: Tauri }).__TAURI_INTERNALS__ ?? null : null);
const message = (error: unknown) => error instanceof Error ? error.message : String(error);
const RELAUNCH_SECONDS = 5;

/** A picture of the System Settings list, with this app's row showing the live grant state. */
function SettingsMock({ appName, granted }: { appName: string; granted: boolean }) {
  const Toggle = ({ on }: { on: boolean }) => <span className={`relative inline-block h-5 w-9 rounded-full transition-colors ${on ? "bg-[#34a853]" : "bg-[#5b5b60]"}`}>
    <span className={`absolute top-0.5 size-4 rounded-full bg-white shadow transition-[left] ${on ? "left-[18px]" : "left-0.5"}`} /></span>;
  const rows = [
    { name: "Finder", icon: <FolderIcon size={16} />, on: true, self: false },
    { name: appName, icon: <SparkleIcon size={16} weight="fill" className="text-[#5b8def]" />, on: granted, self: true },
    { name: "Terminal", icon: <TerminalWindowIcon size={16} />, on: true, self: false }
  ];
  return <figure className="mx-auto w-full max-w-md" data-testid="settings-mock">
    <div aria-hidden="true" className="overflow-hidden rounded-xl border border-white/10 bg-[#1e1e20] text-[#e8e8ea] shadow-lg">
      <div className="relative flex items-center gap-1.5 border-b border-white/10 px-3 py-2">
        <span className="size-2.5 rounded-full bg-[#ff5f57]" /><span className="size-2.5 rounded-full bg-[#febc2e]" /><span className="size-2.5 rounded-full bg-[#28c840]" />
        <span className="absolute inset-x-0 text-center text-xs text-white/70">Full Disk Access</span>
      </div>
      <ul className="divide-y divide-white/10">
        {rows.map((row) => <li key={row.name} className={`flex items-center gap-3 px-3 py-2.5 ${row.self ? "" : "opacity-60"}`}>
          <span className="grid size-7 place-items-center rounded-md bg-white/10">{row.icon}</span>
          <span className={`flex-1 truncate text-sm ${row.self ? "font-semibold" : ""}`} translate="no">{row.name}</span>
          {row.self && row.on && <CheckCircleIcon size={16} weight="fill" className="text-[#34a853]" />}
          <Toggle on={row.on} />
        </li>)}
      </ul>
    </div>
    <figcaption className="mt-2 flex items-center justify-center gap-1.5 text-xs text-(--iux-muted-foreground)">
      <ShieldCheckIcon size={13} aria-hidden="true" />Privacy &amp; Security → Full Disk Access
    </figcaption>
  </figure>;
}

export function PermissionGuide({ permissionId, granted }: { permissionId: string; granted: boolean }) {
  const [app, setApp] = useState<{ name: string; path: string } | null | undefined>(undefined);
  const [opened, setOpened] = useState(false);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState("");
  const native = tauri();
  // "Just granted": the guide was shown without the grant and the probe now reports it.
  const sawMissing = useRef(!granted);
  const justGranted = granted && sawMissing.current;
  const [countdown, setCountdown] = useState<number | null>(null);
  useEffect(() => { if (!granted) sawMissing.current = true; }, [granted]);
  useEffect(() => { if (justGranted && native) setCountdown(RELAUNCH_SECONDS); }, [justGranted, native]);
  useEffect(() => {
    if (countdown == null || !native) return;
    if (countdown <= 0) { void native.invoke("app_relaunch").catch((failure) => { setError(message(failure)); setCountdown(null); }); return; }
    const timer = window.setTimeout(() => setCountdown((value) => value == null ? null : value - 1), 1000);
    return () => window.clearTimeout(timer);
  }, [countdown, native]);

  useEffect(() => { void api.cleanupHostApp().then((value) => setApp(value.app)).catch(() => setApp(null)); }, []);

  const run = async (key: string, action: () => Promise<unknown>) => {
    setBusy(key); setError("");
    try { await action(); } catch (failure) { setError(message(failure)); } finally { setBusy(""); }
  };

  if (justGranted) return <div role="status" className="mb-3 flex flex-col items-center gap-2 rounded-lg border border-(--iux-border) px-4 py-8 text-center" data-testid="permission-ready">
    <span className="grid size-20 place-items-center rounded-full bg-(--iux-success)/15"><CheckIcon size={40} weight="bold" className="text-(--iux-success)" aria-hidden="true" /></span>
    <p className="mt-2 text-2xl font-semibold">You're ready</p>
    <p className="text-sm text-(--iux-muted-foreground)">Full Disk Access is on.</p>
    {native && countdown != null && <>
      <p className="text-sm text-(--iux-muted-foreground)" aria-live="polite">Reopening the app in {countdown} s so the grant takes effect…</p>
      <div className="flex gap-2">
        <button type="button" className="iux-btn" data-variant="primary" onClick={() => setCountdown(0)}><ArrowClockwiseIcon size={14} />Reopen now</button>
        <button type="button" className="iux-btn" data-variant="ghost" onClick={() => setCountdown(null)}>Not now</button>
      </div>
    </>}
    {native && countdown == null && <button type="button" className="iux-btn" onClick={() => setCountdown(0)}><ArrowClockwiseIcon size={14} />Quit &amp; Reopen</button>}
    {!native && <p className="text-xs text-(--iux-muted-foreground)">If a folder still reads as locked, quit and reopen <b translate="no">{app?.name ?? "the app that started the console"}</b>.</p>}
  </div>;

  if (granted) return <div role="status" className="mb-3 flex items-center gap-3 rounded-lg border border-(--iux-success)/40 bg-(--iux-success)/10 p-4">
    <CheckCircleIcon size={28} weight="fill" className="text-(--iux-success)" aria-hidden="true" />
    <div><p className="font-semibold">Full Disk Access is on</p><p className="text-sm text-(--iux-muted-foreground)">Scans can read protected folders.</p></div>
  </div>;

  return <div className="mb-3 rounded-lg border border-(--iux-border) p-4" data-testid="permission-guide">
    <div className="flex items-center gap-2"><ShieldCheckIcon size={18} aria-hidden="true" /><h3 className="font-semibold">One permission, then we're done</h3></div>
    <p className="mt-1 text-sm text-(--iux-muted-foreground)">macOS hides some folders from every app until you allow it. In System Settings, turn on <b translate="no">{app?.name ?? "this app"}</b> under Privacy &amp; Security → Full Disk Access.</p>
    <div className="mt-4"><SettingsMock appName={app?.name ?? "This app"} granted={false} /></div>
    <p className="mt-2 text-center text-xs text-(--iux-muted-foreground)" aria-live="polite">Waiting for the toggle… this page checks every few seconds.</p>
    <div className="mt-4 flex flex-wrap items-center gap-5">
      <div className="flex w-36 flex-col items-center gap-2 rounded-lg bg-(--iux-muted) p-4 text-center"
        draggable={!native} title={native ? "Drag to the Settings list" : "Reveal in Finder, then drag"}
        onPointerDown={native ? () => { void run("drag", () => native.invoke("app_drag_self")); } : undefined}
        style={{ cursor: native ? "grab" : "default" }}>
        <span className="grid size-14 place-items-center rounded-xl bg-(--iux-card)"><GearIcon size={28} aria-hidden="true" /></span>
        <span className="text-sm font-medium" translate="no">{app === undefined ? "…" : app ? `${app.name}.app` : "Unknown app"}</span>
        <span className="text-xs text-(--iux-muted-foreground)">{native ? "Drag to the Settings list" : "Drag it from Finder"}</span>
      </div>
      <div className="flex min-w-60 flex-1 flex-col gap-2">
        <button type="button" className="iux-btn" data-variant="primary" disabled={!!busy}
          onClick={() => void run("open", async () => { await api.cleanupPermissionsOpen(permissionId); setOpened(true); })}>
          <GearIcon size={14} />Open System Settings
        </button>
        <div className="flex flex-wrap gap-3 text-sm">
          <button type="button" className="iux-btn" data-variant="ghost" disabled={!!busy || !app} onClick={() => void run("reveal", () => api.cleanupRevealApp())}>Reveal app again</button>
          <button type="button" className="iux-btn" data-variant="ghost" disabled={!!busy || !app}
            onClick={() => { if (window.confirm("Reset the Full Disk Access record for this app? You will need to allow it again.")) void run("reset", () => api.cleanupResetPermission()); }}>Reset permissions</button>
        </div>
        {(opened || native) && <button type="button" className="iux-btn" disabled={!!busy || !native} onClick={() => void run("relaunch", () => native!.invoke("app_relaunch"))}
          title={native ? undefined : "Quit and reopen the app yourself"}>
          <ArrowClockwiseIcon size={14} />{native ? "I turned it on: Quit & Reopen" : "Turned it on? Quit and reopen the app yourself"}
        </button>}
      </div>
    </div>
    {error && <p role="alert" className="mt-3 text-sm text-(--iux-danger)">{error}</p>}
  </div>;
}
