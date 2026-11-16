/**
 * Update prompt: a modal that opens on its own when the desktop app or the signed content pack has a
 * newer version. "Later" remembers the offered versions, so it asks again only for something newer.
 * The inline panels on the Host page stay as the manual route.
 */
import { useEffect, useRef, useState } from "react";
import { ArrowsClockwiseIcon, DownloadSimpleIcon, XIcon } from "@phosphor-icons/react";
import { Status } from "../components/ui";
import { api, message, type AppUpdateState, type ContentState } from "../lib/api";
import { keepModalFocus } from "./modal-focus";

const DISMISSED = "oslab.update.dismissed";
const FRESH_SECONDS = 900;
const fresh = (checkedAt: number | null) => Boolean(checkedAt && Date.now() / 1000 - checkedAt < FRESH_SECONDS);

const readDismissed = () => {
  try { return window.localStorage.getItem(DISMISSED) ?? ""; } catch { return ""; }
};
const writeDismissed = (value: string) => {
  try { window.localStorage.setItem(DISMISSED, value); } catch { /* Private mode: the prompt returns next launch. */ }
};

const appOffered = (s: AppUpdateState | null) => (s?.supported && !s.offline && s.updateAvailable ? s : null);
const contentOffered = (s: ContentState | null) =>
  s && !s.offline && s.latest && s.latest.sequence > s.sequence ? s : null;
const offerKey = (app: AppUpdateState | null, content: ContentState | null) =>
  `${app ? `app:${app.latest}` : ""}|${content ? `content:${content.latest?.sequence}` : ""}`;

type Result = { ok: boolean; text: string } | null;

export function UpdateModal() {
  const [app, setApp] = useState<AppUpdateState | null>(null);
  const [content, setContent] = useState<ContentState | null>(null);
  const [open, setOpen] = useState(false);
  const [appBusy, setAppBusy] = useState(false);
  const [contentBusy, setContentBusy] = useState(false);
  const [hooks, setHooks] = useState(false);
  const [appResult, setAppResult] = useState<Result>(null);
  const [contentResult, setContentResult] = useState<Result>(null);
  const box = useRef<HTMLDialogElement>(null);
  const started = useRef(false);

  useEffect(() => {
    if (started.current) return;
    started.current = true;
    let cancelled = false;
    const checkApp = async () => {
      const current = await api.appUpdateStatus();
      if (!current.supported || current.offline) return current;
      return fresh(current.checkedAt) ? current : api.appUpdateCheck();
    };
    const checkContent = async () => {
      const current = await api.contentStatus();
      if (current.offline) return current;
      return fresh(current.checkedAt) ? current : api.contentCheck();
    };
    // A failed check (offline, no console) just means no prompt; the Host page shows the details.
    Promise.allSettled([checkApp(), checkContent()]).then(([a, c]) => {
      if (cancelled) return;
      const nextApp = a.status === "fulfilled" ? appOffered(a.value) : null;
      const nextContent = c.status === "fulfilled" ? contentOffered(c.value) : null;
      setApp(nextApp);
      setContent(nextContent);
      const key = offerKey(nextApp, nextContent);
      if ((nextApp || nextContent) && readDismissed() !== key) setOpen(true);
    });
    return () => { cancelled = true; };
  }, []);

  useEffect(() => {
    const dialog = box.current;
    if (!dialog) return;
    if (open && !dialog.open) dialog.showModal();
    if (!open && dialog.open) dialog.close();
  }, [open]);

  // While the installer downloads, follow its progress through the console.
  useEffect(() => {
    if (!app?.installing) return;
    const timer = setInterval(async () => {
      try { setApp(await api.appUpdateStatus()); } catch { /* Keep the last progress; the next tick retries. */ }
    }, 1000);
    return () => clearInterval(timer);
  }, [app?.installing]);

  function later() {
    writeDismissed(offerKey(app, content));
    setOpen(false);
  }

  async function installApp() {
    setAppBusy(true);
    setAppResult(null);
    try {
      setApp(await api.appUpdateInstall());
    } catch (e) {
      setAppResult({ ok: false, text: message(e) });
    } finally {
      setAppBusy(false);
    }
  }

  async function installContent() {
    setContentBusy(true);
    setContentResult(null);
    try {
      const next = await api.contentUpdate(hooks);
      setContent(contentOffered(next));
      setContentResult({ ok: true, text: "Content updated." });
    } catch (e) {
      setContentResult({ ok: false, text: message(e) });
    } finally {
      setContentBusy(false);
    }
  }

  const phase = app?.install?.phase;
  const appWorking = appBusy || phase === "downloading" || phase === "opening";
  // Keep the dialog mounted while there is something to show, including an install result.
  if (!app && !content && !appResult && !contentResult) return null;

  return (
    <dialog
      ref={box}
      aria-labelledby="update-title"
      tabIndex={-1}
      className="iux iux-dialog iux-spotlight"
      onClose={() => setOpen(false)}
      onKeyDown={keepModalFocus}
      onMouseDown={(e) => {
        const rect = e.currentTarget.getBoundingClientRect();
        if (e.clientX < rect.left || e.clientX > rect.right || e.clientY < rect.top || e.clientY > rect.bottom) later();
      }}
    >
      <div className="flex flex-col gap-5 p-5">
        <header className="flex items-start justify-between gap-3">
          <div className="space-y-1">
            <h2 id="update-title" className="text-base font-semibold">Updates available</h2>
            <p className="text-xs text-(--iux-muted-foreground)">
              Both come from signed releases; each download is verified before it is installed.
            </p>
          </div>
          <button type="button" className="iux-btn shrink-0" data-variant="ghost" data-size="icon" aria-label="Remind me later" onClick={later}>
            <XIcon size={16} />
          </button>
        </header>

        {app ? (
          <section className="flex flex-col gap-3" aria-label="App update">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div className="space-y-1 text-sm">
                <p className="flex items-center gap-2 font-medium"><DownloadSimpleIcon size={16} /> <span>App update</span></p>
                <p className="text-xs text-(--iux-muted-foreground)" data-no-translate>{app.installed} → {app.latest}</p>
              </div>
              <button type="button" className="iux-btn bg-[#f36c21] text-white hover:bg-[#fa7b32]" disabled={appWorking} onClick={() => void installApp()}>
                {phase === "downloading" ? "Downloading…" : phase === "opening" ? "Opening installer…" : phase === "done" ? "Update again" : "Install update"}
              </button>
            </div>
            {phase === "downloading" ? <progress className="h-2 w-full accent-[#f36c21]" aria-label="Downloading the update" /> : null}
            {phase === "done" ? <Status value={{ ok: true, text: app.install?.path ? `Update opened from ${app.install.path}` : "Update opened." }} /> : null}
            {phase === "error" || appResult ? <Status value={{ ok: false, text: app.install?.error || appResult?.text || "The update could not be installed." }} /> : null}
            {app.releaseUrl ? <a className="text-xs underline" href={app.releaseUrl} target="_blank" rel="noreferrer">Release notes</a> : null}
          </section>
        ) : null}

        {content ? (
          <section className="flex flex-col gap-3" aria-label="Content update">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div className="space-y-1 text-sm">
                <p className="flex items-center gap-2 font-medium"><ArrowsClockwiseIcon size={16} /> <span>Content update</span></p>
                <p className="text-xs text-(--iux-muted-foreground)" data-no-translate>{content.version} → {content.latest?.version}</p>
              </div>
              <button type="button" className="iux-btn bg-[#f36c21] text-white hover:bg-[#fa7b32]" disabled={contentBusy} onClick={() => void installContent()}>
                {contentBusy ? "Installing…" : "Install update"}
              </button>
            </div>
            {contentBusy ? <progress className="h-2 w-full accent-[#f36c21]" aria-label="Installing the content pack" /> : null}
            {content.hooks ? (
              <label className="flex items-start gap-2 text-sm">
                <input type="checkbox" className="mt-1" checked={hooks} onChange={(e) => setHooks(e.target.checked)} disabled={contentBusy} />
                <span>
                  <span className="font-medium">Include Frida hooks</span>
                  <span className="block text-xs text-(--iux-muted-foreground)">Hooks are installed on this computer. They update only when you tick this box.</span>
                </span>
              </label>
            ) : null}
            {contentResult && !contentResult.ok ? <Status value={contentResult} /> : null}
          </section>
        ) : contentResult?.ok ? <Status value={contentResult} /> : null}

        <footer className="flex justify-end">
          <button type="button" className="iux-btn" data-variant="outline" onClick={later}>Later</button>
        </footer>
      </div>
    </dialog>
  );
}
