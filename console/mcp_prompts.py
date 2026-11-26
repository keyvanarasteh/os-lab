"""MCP prompts for the os-lab stdio server (prompts/list + prompts/get).

Standard prompts steer hosts through guarded lab flows and through the
verification registry in mcp_verification.json. Arguments are declared so
students and contributors can fill proof slots without inventing tool names.
"""
from __future__ import annotations

import json
import os

VERIFICATION_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "mcp_verification.json")

PROMPTS = [
    {
        "name": "cleanup_review_flow",
        "description": "One-click Cleanup Lab path: review (scan→suggest→Trash plan), show the plan, then clean only with confirm: true.",
        "arguments": [
            {"name": "entryIds", "description": "Optional catalog ids to force into the plan", "required": False},
        ],
    },
    {
        "name": "macos_observe_act_verify",
        "description": "macOS Lab loop: observe (apps/state/screenshot), act only while armed from the dashboard, verify, panic-stop if needed. Never arm from the agent.",
        "arguments": [
            {"name": "windowId", "description": "Optional window id from macos_apps", "required": False},
            {"name": "goal", "description": "What the human asked to verify on screen", "required": True},
        ],
    },
    {
        "name": "websec_scoped_scan",
        "description": "Web Sec Lab: review the target against the scope guard, then passive scan (or active only with confirm: true and written authorization).",
        "arguments": [
            {"name": "target", "description": "Host name listed in scope.json", "required": True},
            {"name": "preset", "description": "quick | standard | full", "required": False},
            {"name": "active", "description": "true only with written authorization", "required": False},
        ],
    },
    {
        "name": "mcp_coverage_status",
        "description": "Summarize MCP verification status for one section (or all): engineUsage, widgets, apps, and open TODOs from the gap plan.",
        "arguments": [
            {"name": "section", "description": "macos | cleanup | websec | winapps | android | ios | linux | web | source | firewall | all", "required": False},
        ],
    },
    {
        "name": "mcp_verify_tool",
        "description": "Guide a contributor to exercise one MCP tool against the engine and fill the verification proof slot (engineUsage / widget / app).",
        "arguments": [
            {"name": "tool", "description": "Exact tools/list name, e.g. cleanup_review", "required": True},
            {"name": "field", "description": "engineUsage | widget | app", "required": False},
        ],
    },
    {
        "name": "mcp_gap_plan",
        "description": "List lab capabilities that exist in os-lab but are still missing from the MCP server, using the coverage plan.",
        "arguments": [],
    },
]


def list_prompts() -> list[dict]:
    return [{"name": p["name"], "description": p["description"], "arguments": p.get("arguments") or []} for p in PROMPTS]


def _load_verification() -> dict:
    with open(VERIFICATION_PATH, encoding="utf-8") as handle:
        return json.load(handle)


def _messages(text: str) -> dict:
    return {"description": text.split("\n", 1)[0][:120], "messages": [
        {"role": "user", "content": {"type": "text", "text": text}}
    ]}


def get_prompt(name: str, arguments: dict | None = None) -> dict:
    args = arguments if isinstance(arguments, dict) else {}
    if name == "cleanup_review_flow":
        extra = ""
        if args.get("entryIds"):
            extra = f" Prefer entryIds={args['entryIds']!r}."
        return _messages(
            "Run the Cleanup Lab one-click path via MCP.\n"
            "1. Call cleanup_app_review or cleanup_review (never cleans).\n"
            "2. Show the suggestion and Trash plan to the user.\n"
            "3. Only after approval call cleanup_clean with confirm: true.\n"
            "4. Refuse raw paths; use catalog ids only." + extra
        )
    if name == "macos_observe_act_verify":
        goal = args.get("goal") or "verify the on-screen state"
        wid = args.get("windowId")
        focus = f" Focus windowId={wid}." if wid not in (None, "") else ""
        return _messages(
            f"macOS Lab observe → act → verify for: {goal}.{focus}\n"
            "1. macos_apps / macos_get_app_state / macos_screenshot as needed.\n"
            "2. Check macos_control_state; if disarmed, ask the human to arm from the dashboard (no arm tool).\n"
            "3. Act with macos_click / type / key / paste only while armed; submit-class needs confirm: true.\n"
            "4. Re-observe to verify. Call macos_stop on panic."
        )
    if name == "websec_scoped_scan":
        target = args.get("target") or "<target>"
        preset = args.get("preset") or "standard"
        active = str(args.get("active", False)).lower()
        return _messages(
            f"Web Sec Lab for target {target!r} (preset={preset}, active={active}).\n"
            "1. websec_review — show scope and checks; send nothing yet.\n"
            "2. Passive: websec_scan without active.\n"
            "3. Intrusive only if active is true AND the user confirmed written authorization; then confirm: true.\n"
            "4. Prefer websec_report / websec_compare for results."
        )
    if name == "mcp_coverage_status":
        data = _load_verification()
        section = (args.get("section") or "all").lower()
        if section == "all":
            body = json.dumps(data.get("sections", {}), indent=2)
        else:
            body = json.dumps(data.get("sections", {}).get(section, {"error": "unknown section"}), indent=2)
        return _messages(
            f"MCP verification status for section={section}.\n"
            "Statuses are none | pending | verified | n/a. Proof slots start null — contributors fill them in PRs.\n"
            f"```json\n{body}\n```\n"
            "Also see docs/PLAN-mcp-coverage.md for lab gaps still missing MCP tools."
        )
    if name == "mcp_verify_tool":
        tool = args.get("tool") or ""
        field = args.get("field") or "engineUsage"
        data = _load_verification()
        entry = data.get("tools", {}).get(tool)
        if entry is None:
            return _messages(f"Unknown tool {tool!r}. Call tools/list and pick an exact name.")
        return _messages(
            f"Verify MCP tool {tool!r} field={field}.\n"
            f"Current registry entry:\n```json\n{json.dumps(entry, indent=2)}\n```\n"
            "1. Call the tool against a safe fixture or read-only path.\n"
            "2. Record the test name or artifact.\n"
            "3. Open a PR that sets status to verified and fills proof in console/mcp_verification.json.\n"
            "If the tool has a widget/app resourceUri, also exercise a UI host and fill that field."
        )
    if name == "mcp_gap_plan":
        plan_path = os.path.join(os.path.dirname(VERIFICATION_PATH), "..", "docs", "PLAN-mcp-coverage.md")
        try:
            with open(os.path.realpath(plan_path), encoding="utf-8") as handle:
                plan = handle.read()
        except OSError:
            plan = "(docs/PLAN-mcp-coverage.md not found in this checkout)"
        return _messages(
            "Lab capabilities that exist in os-lab but are missing or partial on the MCP server.\n"
            "Use this plan when adding the next mcp_*.py module.\n\n" + plan
        )
    raise KeyError(name)
