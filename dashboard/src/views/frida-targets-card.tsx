/** Jobs view card: the devices and processes Frida can attach to right now. It only lists them. */
import { useCallback, useEffect, useState } from "react";
import { CrosshairIcon } from "@phosphor-icons/react";
import { Badge, Empty, Field, Section, Skeleton } from "../components/ui";
import { api, message, type FridaDevice, type FridaInventory } from "../lib/api";

function DeviceRow({ device }: { device: FridaDevice }) {
  const processes = device.processes ?? [];
  return (
    <li className="py-2.5" data-device={device.id}>
      <div className="flex flex-wrap items-center gap-3 text-sm">
        <span className="min-w-0 flex-1" data-no-translate>
          <span className="font-medium">{device.name}</span>
          <span className="block truncate font-mono text-xs text-(--iux-muted-foreground)">{device.id}</span>
        </span>
        {device.processes ? (
          <span className="text-xs text-(--iux-muted-foreground)">
            <span data-no-translate>{processes.length}</span> <span>processes</span>
          </span>
        ) : null}
        <Badge tone={device.transport === "USB" ? "success" : undefined}>
          <span data-no-translate>{device.transport}</span>
        </Badge>
      </div>
      {device.error ? <p className="mt-1 text-xs text-red-400" data-no-translate>{device.error}</p> : null}
      {processes.length > 0 ? (
        <details className="mt-2">
          <summary className="cursor-pointer text-xs text-(--iux-muted-foreground)">Show processes</summary>
          <ul className="apk-code-scroll mt-2 max-h-64 overflow-y-auto rounded-md border border-(--iux-border) p-3 font-mono text-xs" data-no-translate>
            {processes.map((process, i) => (
              <li key={i} className="flex gap-3">
                <span className="w-14 shrink-0 text-right text-(--iux-muted-foreground)">{process.pid ?? "-"}</span>
                <span className="min-w-0 break-all">{process.identifier ? `${process.name} (${process.identifier})` : process.name}</span>
              </li>
            ))}
          </ul>
        </details>
      ) : null}
    </li>
  );
}

export function FridaTargetsCard() {
  const [host, setHost] = useState("");
  const [state, setState] = useState<{ data?: FridaInventory; error?: string; busy: boolean }>({ busy: true });
  const load = useCallback(async (target: string) => {
    setState((current) => ({ ...current, busy: true }));
    try {
      setState({ data: await api.fridaInventory(target), busy: false });
    } catch (error) {
      setState({ error: message(error), busy: false });
    }
  }, []);
  useEffect(() => {
    void load("");
  }, [load]);

  const devices = state.data?.devices ?? [];
  // Per-device failures are shown on their row; the rest (no tools, no listing) go under the list.
  const problems = (state.data?.errors ?? []).filter((problem) => !problem.device);
  return (
    <Section
      id="frida-targets"
      icon={<CrosshairIcon size={16} />}
      title="Frida targets"
      description="Devices and processes Frida can attach to right now. This card only lists them; nothing is attached or started."
    >
      <form
        className="mb-4 flex flex-wrap items-end gap-3"
        onSubmit={(event) => {
          event.preventDefault();
          void load(host.trim());
        }}
      >
        <div className="min-w-0 flex-1">
          <Field label="Lab target address" hint="Optional. The loopback or private IP of a lab frida-server; any other address is refused.">
            <input className="iux-input font-mono" value={host} onChange={(event) => setHost(event.target.value)} placeholder="127.0.0.1:27042" spellCheck={false} autoComplete="off" />
          </Field>
        </div>
        <button type="submit" className="iux-btn" data-variant="outline" disabled={state.busy}>
          {state.busy ? "Checking…" : "Check"}
        </button>
      </form>
      {state.error ? (
        <p role="alert" className="text-sm text-red-400"><span>Could not list Frida targets:</span> <span data-no-translate>{state.error}</span></p>
      ) : !state.data ? (
        <Skeleton rows={2} />
      ) : (
        <>
          {devices.length === 0 ? <Empty>No Frida device found.</Empty> : (
            <ul className="divide-y divide-(--iux-border)">
              {devices.map((device) => <DeviceRow key={device.id} device={device} />)}
            </ul>
          )}
          {problems.map((problem, i) => (
            <p key={i} className="mt-2 text-xs text-amber-400" data-no-translate>{problem.message}</p>
          ))}
        </>
      )}
    </Section>
  );
}
