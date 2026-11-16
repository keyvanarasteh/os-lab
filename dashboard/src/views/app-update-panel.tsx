/** App updates: the desktop app's signed release feed; shown only inside the app when a newer build exists. */
import { useEffect, useRef, useState } from "react";
import { DownloadSimpleIcon } from "@phosphor-icons/react";
import { Badge, Section, Status } from "../components/ui";
import { api, message, type AppUpdateState } from "../lib/api";

export function AppUpdatePanel() {
  const [state, setState] = useState<AppUpdateState | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const checked = useRef(false);

  useEffect(() => {
    if (checked.current) return;
    checked.current = true;
    let cancelled = false;
    (async () => {
      try {
        const current = await api.appUpdateStatus();
        if (cancelled) return;
        setState(current);
        if (!current.supported || current.offline) return;
        const fresh = current.checkedAt && Date.now() / 1000 - current.checkedAt < 900 ? current : await api.appUpdateCheck();
        if (!cancelled) setState(fresh);
      } catch (e) {
        if (!cancelled) setError(message(e));
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (!state?.installing) return;
    const timer = setInterval(async () => {
      try {
        setState(await api.appUpdateStatus());
      } catch {
        // Keep the last known progress; the next tick tries again.
      }
    }, 1000);
    return () => clearInterval(timer);
  }, [state?.installing]);

  async function installUpdate() {
    setBusy(true);
    setError(null);
    try {
      setState(await api.appUpdateInstall());
    } catch (e) {
      setError(message(e));
    } finally {
      setBusy(false);
    }
  }

  // Nothing to show outside the desktop app, or when this build is current.
  if (!state?.supported || state.offline || !state.updateAvailable) return null;

  const install = state.install;
  const phase = install?.phase;
  const working = busy || phase === "downloading" || phase === "opening";
  return (
    <Section
      id="app-update"
      icon={<DownloadSimpleIcon size={16} />}
      title="App update"
      description="A newer os-lab desktop app is available from the signed release feed."
      action={
        state.releaseUrl ? (
          <a className="text-xs underline" href={state.releaseUrl} target="_blank" rel="noreferrer">
            Release notes
          </a>
        ) : null
      }
    >
      <div className="flex flex-col gap-4">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="space-y-1 text-sm">
            <p className="font-medium">
              <span>Update available</span>:{" "}
              <span data-no-translate>
                {state.installed} → {state.latest}
              </span>
            </p>
            <p className="text-xs text-(--iux-muted-foreground)">
              The installer for this computer is downloaded, checked against its SHA-256 file, then opened so the
              operating system can finish the update.
            </p>
            <p className="text-xs text-(--iux-muted-foreground)" data-no-translate>
              {state.platform} · {state.asset?.name}
            </p>
          </div>
          <button
            type="button"
            className="iux-btn bg-[#f36c21] text-white hover:bg-[#fa7b32]"
            disabled={working}
            onClick={() => void installUpdate()}
          >
            {phase === "downloading" ? "Downloading…" : phase === "opening" ? "Opening installer…" : phase === "done" ? "Update again" : "Install update"}
          </button>
        </div>
        {phase === "downloading" ? (
          <div role="status" className="space-y-1 text-xs text-(--iux-muted-foreground)">
            <p>Downloading and verifying the update…</p>
            <progress className="h-2 w-full accent-[#f36c21]" />
          </div>
        ) : null}
        {phase === "done" ? (
          <Status value={{ ok: true, text: install?.path ? `Update opened from ${install.path}` : "Update opened." }} />
        ) : null}
        {phase === "error" || error ? (
          <Status value={{ ok: false, text: install?.error || error || "The update could not be installed." }} />
        ) : null}
        {state.kind === "appimage" && phase === "done" ? (
          <p className="text-xs text-(--iux-muted-foreground)">
            The new AppImage was saved beside your current one. Replace the running file with it, then start os-lab again.
          </p>
        ) : null}
        {state.asset ? <Badge>{state.asset.name}</Badge> : null}
      </div>
    </Section>
  );
}
