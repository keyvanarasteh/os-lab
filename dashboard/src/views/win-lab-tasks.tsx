/**
 * Windows Lab roadmap (WINMIR-xx): the Windows-application counterpart of the
 * macOS app mirror. The full architecture, permissions honesty rules and the
 * native / guest path split live in win-lab/APP_MIRROR_PLAN.md — these tasks
 * implement it phase by phase with the same guardrails (read-only first,
 * preview → confirm, armed control mode that disarms itself, localhost-only).
 */
import type { TodoTask } from "./contribute-page";

type WinLabTask = Omit<TodoTask, "category" | "categoryLabel" | "reference" | "suggestedBranch"> & {
  reference?: string;
};

const tasks: WinLabTask[] = [
  {
    id: "WINMIR-01",
    title: "Window inventory and capture through ctypes (native path)",
    priority: "High",
    effort: "Medium",
    summary:
      "Enumerate top-level visible windows with user32.EnumWindows via ctypes (owner pid and image, title, class, rect), capture one window with PrintWindow + PW_RENDERFULLCONTENT into a DIB, and expose the macOS-shaped read-only endpoints with per-monitor DPI awareness set once. Tool windows are filtered; elevation is marked, not hidden.",
    deliverables: [
      "GET /api/labs/winapps/apps and …/apps/<hwnd>/screenshot with the same shapes as the macOS mirror",
      "Minimal stdlib PNG encoder (zlib + chunks) for the capture path",
      "Doctor reports the desktop session, console elevation and a capture probe",
    ],
    targetPaths: ["console/oslab.py", "android-lab/lab/web_ui.py", "win-lab/", "dashboard/src/views/"],
  },
  {
    id: "WINMIR-02",
    title: "UIA hotspots through pywinauto in a user-folder venv",
    priority: "High",
    effort: "Medium",
    summary:
      "Install pywinauto into ~/.oslab/pywinauto (the user-folder pattern of ~/.oslab/appium, no global site-packages) and walk the UIA tree of the selected window bounded (150 elements, depth 14) with window-relative rects, roles, labels and IsPassword flagged. Elevated windows are listed but their hotspots are disabled with the elevation reason.",
    deliverables: [
      "Bootstrap script under win-lab/scripts/ that never touches global site-packages or PATH",
      "GET …/apps/<hwnd>/elements with bounded walks tested on recorded UIA dumps",
      "Panel renders hotspots with password fields marked and elevated ones disabled",
    ],
    targetPaths: ["console/oslab.py", "win-lab/scripts/", "dashboard/src/views/macos-app-mirror.tsx"],
  },
  {
    id: "WINMIR-03",
    title: "Input family via SendInput: preview first, armed parity",
    priority: "High",
    effort: "Medium",
    summary:
      "Implement click, double-click, right-click, type and key through user32.SendInput (KEYEVENTF_UNICODE for text), activated with the SetForegroundWindow + AttachThreadInput sequence. All variants preview with the app and the point named; typing never sends Return without an explicit confirm; armed control mode matches the macOS mirror (visible badge, self-expiring).",
    deliverables: [
      "winapps-click action family with typed, validated request fields and preview effects naming the app",
      "Arm/disarm endpoint with the ten-minute idle expiry and localhost-only guards",
      "e2e covering preview-then-arm on mocked endpoints, mirroring the macOS test",
    ],
    targetPaths: ["console/oslab.py", "ios-lab/mac/", "android-lab/lab/web_ui.py", "dashboard/src/views/"],
  },
  {
    id: "WINMIR-04",
    title: "Guest agent for the Windows-in-Docker path",
    priority: "Medium",
    effort: "Large",
    summary:
      "Deliver the same read-only three operations and the guarded input operation to the Windows Lab's guest: a single-file agent bound to the guest's loopback only, provisioned through win-lab/oem install.bat and updated through the Z: shared drive, proxied by the console over the compose network with the token guard. No new published ports; the agent runs as the logged-in user, never SYSTEM, and UAC secure desktop stays out of scope.",
    deliverables: [
      "Agent file with the same endpoint shapes and the X-OSLab guard set",
      "install.bat provisioning plus an update path through /shared (Z:)",
      "Console proxy with per-session tokens and compose network isolation documented",
    ],
    targetPaths: ["win-lab/oem/", "win-lab/shared/", "win-lab/scripts/", "console/oslab.py"],
  },
  {
    id: "WINMIR-05",
    title: "WinAppDriver deep-inspect mode with stable element ids",
    priority: "Medium",
    effort: "Medium",
    summary:
      "Route hotspot actions through an Appium windows-driver session for the selected application (through the existing Appium install), so actions survive windows that move; fall back to SendInput coordinates when no session is open. The session is visible in the panel, closable, and never left dangling — the mac2 deep-inspect plan mirrored one to one.",
    deliverables: [
      "Console session helper with create/find/close guarded by the same pid checks",
      "Hotspot actions carry element ids when a session is open; plans display that in effects",
      "Session cleanup on panel hide, tab unload and app quit, tested on mocks",
    ],
    targetPaths: ["console/oslab.py", "win-lab/", "dashboard/src/views/", "android-lab/lab/web_ui.py"],
  },
  {
    id: "WINMIR-06",
    title: "Streaming mirror and session audit log",
    priority: "Medium",
    effort: "Small–Medium",
    summary:
      "Bring the macOS MIR-04 and MIR-06 plans over: a multipart MJPEG streaming endpoint that pauses on hidden tabs and without clients, and a local audit log recording one JSON row per action (time, app, window, kind, coordinates or element, previewed vs armed) plus periodic frame thumbnails under artifacts/, downloadable from the panel and never uploaded.",
    deliverables: [
      "GET …/apps/<hwnd>/stream with correct multipart boundaries and a poll fallback",
      "Console-side bounded recorder including arm/disarm events",
      "Panel download producing one JSON file with embedded base64 thumbnails",
    ],
    targetPaths: ["console/oslab.py", "android-lab/lab/web_ui.py", "dashboard/src/views/"],
  },
];

export const WIN_LAB_TASKS: TodoTask[] = tasks.map((t) => ({
  ...t,
  category: "os",
  categoryLabel: "Windows Lab",
  reference: t.reference ?? "win-lab/APP_MIRROR_PLAN.md",
  deliverables: [
    ...t.deliverables,
    "VERIFY.md entry with commands and output; mirror screenshots taken by script for UI changes",
  ],
  suggestedBranch: `feat/${t.id.toLowerCase()}`,
}));
