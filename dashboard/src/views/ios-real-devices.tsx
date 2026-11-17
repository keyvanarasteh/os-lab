import { useCallback, useEffect, useState } from "react";
import { ArrowClockwiseIcon, ArrowSquareOutIcon, DeviceMobileIcon, PlayIcon } from "@phosphor-icons/react";
import { Badge, Status } from "../components/ui";
import { api, message, usePoll, type IosDevicesInfo, type IosSimulatorInfo } from "../lib/api";

const DEVICES_INTERVAL = 30000;
const SIMULATORS_INTERVAL = 15000;
type DeviceCheck = Awaited<ReturnType<typeof api.iosDeviceCheck>>;

/** Compact device choices. Only verified connected phones and booted simulators open a frame. */
export function IosDeviceCards({ selectedTarget, onSelect }: {
  selectedTarget: string; onSelect: (target: string) => void;
}) {
  const { data, error, reload } = usePoll<IosDevicesInfo>(() => api.iosDevices(), DEVICES_INTERVAL);
  const { data: simulators, error: simulatorError, reload: reloadSimulators } =
    usePoll<IosSimulatorInfo>(() => api.iosSimulator(), SIMULATORS_INTERVAL);
  const [checks, setChecks] = useState<Record<string, DeviceCheck>>({});
  const [checking, setChecking] = useState<Record<string, boolean>>({});

  const checkDevice = useCallback(async (udid: string) => {
    setChecking((old) => ({ ...old, [udid]: true }));
    try {
      const result = await api.iosDeviceCheck(udid);
      setChecks((old) => ({ ...old, [udid]: result }));
    } catch (cause) {
      setChecks((old) => ({ ...old, [udid]: { reachable: false, reason: message(cause) } }));
    } finally {
      setChecking((old) => ({ ...old, [udid]: false }));
    }
  }, []);

  useEffect(() => {
    if (!data?.available || error) return;
    for (const device of data.devices) void checkDevice(device.udid);
  }, [data, error, checkDevice]);

  return <section className="border-t border-(--iux-border) pt-3" aria-label="Devices">
    <div className="mb-3 flex items-center justify-between gap-2">
      <h3 className="text-xs font-semibold tracking-wide uppercase">Devices</h3>
      <button type="button" className="iux-btn" data-variant="ghost" onClick={() => { reload(); reloadSimulators(); }} aria-label="Refresh devices">
        <ArrowClockwiseIcon size={14} aria-hidden /> Refresh
      </button>
    </div>
    <div className="grid gap-4 md:grid-cols-2">
      <div className="min-w-0">
        <div className="mb-2 flex items-center gap-2">
          <DeviceMobileIcon size={15} className="text-[#f36c21]" aria-hidden />
          <h4 className="text-xs font-semibold">Real devices</h4>
          {data?.available && <Badge>{data.devices.length}</Badge>}
        </div>
        {error ? <Status value={{ ok: false, text: error }} />
          : !data ? <p className="text-xs text-(--iux-muted-foreground)" role="status">Finding paired devices…</p>
          : !data.available ? <p className="text-xs text-(--iux-muted-foreground)">{data.reason || "Device listing is unavailable."}</p>
          : data.devices.length === 0 ? <p className="text-xs text-(--iux-muted-foreground)">No paired iPhones or iPads found.</p>
          : <ul className="grid gap-2">
            {data.devices.map((device) => {
              const check = checks[device.udid];
              const pending = checking[device.udid] || !check;
              const offline = !pending && !check.reachable;
              const connected = !pending && !!check.reachable;
              const label = check?.name || device.name;
              const target = `real:${device.udid}`;
              const summary = <span className="flex min-w-0 items-center gap-2">
                <span className="min-w-0 flex-1 truncate text-sm font-medium" translate="no">{label}</span>
                <span className="shrink-0 text-[11px] text-(--iux-muted-foreground)" dir="ltr">iOS {check?.osVersion || device.osVersion}</span>
                {connected && <ArrowSquareOutIcon size={14} className="shrink-0 text-(--iux-muted-foreground)" aria-hidden />}
              </span>;
              return <li key={device.udid} className={`min-w-0 rounded-lg border border-(--iux-border) bg-(--iux-card) p-2.5 ${offline ? "opacity-55" : ""} ${selectedTarget === target ? "ring-1 ring-[#f36c21]" : ""}`}>
                {connected ? <button type="button" className="w-full text-start" onClick={() => onSelect(target)}
                  aria-label={`Open ${label} in simulator frame`}>{summary}</button> : summary}
                <div className="mt-1 flex items-center gap-1.5">
                  {offline ? <span className="rounded-full border border-(--iux-border) px-1.5 py-0.5 text-[10px] leading-none" title={check.reason || undefined}>Offline</span>
                    : <Badge tone={pending ? undefined : "success"}>{pending ? "Checking…" : "Connected"}</Badge>}
                  {!pending && check.reachable && check.developerMode === false &&
                    <span className="text-[11px] text-(--iux-warning)">Real-device control needs Developer Mode and a signed WebDriverAgent.</span>}
                </div>
                <details className="mt-1 text-xs text-(--iux-muted-foreground)">
                  <summary className="w-fit cursor-pointer">Device details</summary>
                  {offline && check.reason && <p className="mt-1">{check.reason}</p>}
                  <p className="mt-1 break-all" dir="ltr" translate="no">{device.udid}</p>
                  {device.transport && <p>{device.transport === "localNetwork" ? "Wi-Fi" : "USB"}</p>}
                </details>
              </li>;
            })}
          </ul>}
      </div>
      <div className="min-w-0">
        <div className="mb-2 flex items-center gap-2">
          <PlayIcon size={15} className="text-[#f36c21]" aria-hidden />
          <h4 className="text-xs font-semibold">Running simulators</h4>
          {simulators?.available && <Badge>{simulators.booted?.length ?? 0}</Badge>}
        </div>
        {simulatorError ? <Status value={{ ok: false, text: simulatorError }} />
          : !simulators ? <p className="text-xs text-(--iux-muted-foreground)" role="status">Checking simulators…</p>
          : !simulators.available ? <p className="text-xs text-(--iux-muted-foreground)">{simulators.reason || "Simulator tooling is unavailable."}</p>
          : !simulators.booted?.length ? <p className="text-xs text-(--iux-muted-foreground)">No simulators are running.</p>
          : <ul className="grid gap-2">
            {simulators.booted.map((device) => {
              const target = `sim:${device.udid}`;
              return <li key={device.udid}>
                <button type="button" className={`w-full rounded-lg border border-(--iux-border) bg-(--iux-card) p-2.5 text-start hover:border-[#f36c21]/60 focus-visible:outline-2 focus-visible:outline-[#f36c21] ${selectedTarget === target ? "ring-1 ring-[#f36c21]" : ""}`}
                  onClick={() => onSelect(target)} aria-label={`Open ${device.name} in simulator frame`}>
                  <span className="flex min-w-0 items-center gap-2">
                    <span className="min-w-0 flex-1 truncate text-sm font-medium" translate="no">{device.name}</span>
                    <ArrowSquareOutIcon size={14} className="shrink-0 text-(--iux-muted-foreground)" aria-hidden />
                  </span>
                  <span className="mt-1 flex items-center gap-1.5">
                    <Badge tone="success">Running</Badge>
                    <span className="truncate text-[11px] text-(--iux-muted-foreground)" translate="no">{device.runtime}</span>
                  </span>
                </button>
              </li>;
            })}
          </ul>}
      </div>
    </div>
  </section>;
}
