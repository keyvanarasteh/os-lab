//! The `oslab://` command bridge (AGQ-01).
//!
//! aBigQ-style command buttons and the widget extension drive the host with
//! one URL form: the **host segment is the command** and the path is its
//! argument — `oslab://open/scan`, `oslab://panic-stop`. URL parsers put the
//! token after the scheme in the host, so the widget's documented form
//! `oslab://scan` reads `host=scan` with an **empty path**; the previous code
//! read `url.path()` and therefore matched no route at all. Both spellings
//! parse to the same command here.
//!
//! The surface mirrors what the widget intents and the dashboard already do:
//! navigation plus two actions the dashboard owns. Nothing here can delete,
//! arm control or run a lab command — cleanup stays on the
//! plan → confirm → run flow, and the console validates every request again.

use url::Url;

// @lat: [[lat.md/cleanup-lab#Cleaner Widgets (CLW)#Command bridge (AGQ-01)]]

/// Cleanup routes a widget may open (CLW-03). Values match the overview card
/// targets and the cleanup island's tab paths; the island router handles them
/// in place, so the settings sections land on the Settings page.
pub const CLEANUP_ROUTES: [&str; 10] = [
    "dashboard", "scan", "results", "leftovers", "history", "space",
    "cleanup-bookmarks", "cleanup-monitor", "cleanup-permissions", "cleanup-widgets",
];

/// Plain dashboard pages the bridge may open, as `/<route>/` paths. Each one
/// is a static page the sidebar already links to; `labs/<id>` covers the labs
/// that have a page of their own.
pub const PAGE_ROUTES: [&str; 18] = [
    "host", "jobs", "health", "contribute", "content", "feedback", "how-to-use", "mcp",
    "labs/android", "labs/windows", "labs/winapps", "labs/linux", "labs/ios",
    "labs/macos", "labs/source", "labs/web", "firewall", "web-lab",
];

/// The two actions a command may trigger. Both are safe by construction:
/// `panic-stop` disarms and is idempotent (`macos_panic_stop`), and
/// `quick-clean` only opens the dashboard's plan → confirm dialog.
pub const ACTIONS: [&str; 2] = ["panic-stop", "quick-clean"];

/// MCP servers os-lab offers (MCP-01), by the id `console/mcp_clients.py` uses.
pub const MCP_SERVERS: [&str; 1] = ["macos"];
/// MCP clients the dashboard can register a server with.
pub const MCP_CLIENTS: [&str; 4] = ["claude-code", "codex", "claude-desktop", "cursor"];

/// The console endpoint an action may reach, if it is one that calls one.
/// Whitelisted exactly like the routes: a command name maps to at most one
/// `/api/...` path, and no URL text can become a different request.
pub fn endpoint(action: &str) -> Option<&'static str> {
    match action {
        "panic-stop" => Some("/api/labs/macos/stop"),
        _ => None,
    }
}

/// One parsed `oslab://` URL.
#[derive(Clone, Debug, Eq, PartialEq)]
pub enum Command {
    /// Open a route: `oslab://open/scan`, `oslab://scan`, `oslab:///scan`,
    /// `oslab://open/labs/macos`.
    Navigate(String),
    /// Run a dashboard action: `oslab://panic-stop`, `oslab://quick-clean`.
    Action(&'static str),
    /// Open the MCP page's connect dialog (MCP-01):
    /// `oslab://mcp/connect/macos`, `oslab://mcp/connect/macos?client=cursor`.
    /// It only opens the dialog; the user confirms the change there.
    McpConnect { server: &'static str, client: Option<&'static str> },
    /// Refused: reported to the user instead of guessed at.
    Unknown,
}

fn normalize(token: &str) -> String {
    token.trim().trim_matches('/').to_ascii_lowercase()
}

/// A known route, from either family.
fn known_route(route: &str) -> Option<&str> {
    let cleanup = CLEANUP_ROUTES.iter().any(|known| *known == route);
    if cleanup || PAGE_ROUTES.iter().any(|known| *known == route) {
        Some(route)
    } else {
        None
    }
}

/// `oslab://mcp/...`: the MCP page, a server's status on it, or its connect
/// dialog. Unlike the other commands this one reads a query key, so it is
/// strict about it: `client` is the only key, its value must be a known
/// client, and anything else refuses the whole URL instead of being ignored.
fn parse_mcp(raw: &Url, path: &str) -> Command {
    let segments: Vec<&str> = path.split('/').filter(|s| !s.is_empty()).collect();
    let server = |id: &str| MCP_SERVERS.iter().copied().find(|known| *known == id);
    let mut client = None;
    for (key, value) in raw.query_pairs() {
        match (key.as_ref(), MCP_CLIENTS.iter().copied().find(|known| value.eq_ignore_ascii_case(known))) {
            ("client", Some(known)) if client.is_none() => client = Some(known),
            _ => return Command::Unknown,
        }
    }
    match segments.as_slice() {
        [] | ["status"] if client.is_none() => Command::Navigate("mcp".into()),
        ["status", id] if client.is_none() => server(id).map(|_| Command::Navigate("mcp".into())).unwrap_or(Command::Unknown),
        ["connect", id] => server(id).map(|server| Command::McpConnect { server, client }).unwrap_or(Command::Unknown),
        _ => Command::Unknown,
    }
}

/// The dashboard path an `McpConnect` opens. Built from the whitelisted ids
/// only, so no URL text reaches the page.
pub fn mcp_connect_path(server: &str, client: Option<&str>) -> String {
    match client {
        Some(client) => format!("mcp/?connect={server}&client={client}"),
        None => format!("mcp/?connect={server}"),
    }
}

/// Parse one `oslab://` URL. Parsing never navigates or executes anything;
/// the caller decides what to do with the result, refusals included.
pub fn parse_command(raw: &Url) -> Command {
    let host = normalize(raw.host_str().unwrap_or(""));
    // Query and fragment are not part of the grammar: only path segments are,
    // and `labs/macos` needs two of them.
    let path = normalize(raw.path());
    let path = path.trim_matches('/');
    match host.as_str() {
        "mcp" => parse_mcp(raw, path),
        "open" | "show" | "goto" => match path {
            "" => Command::Navigate("dashboard".into()),
            route => known_route(route).map(|r| Command::Navigate(r.to_string())).unwrap_or(Command::Unknown),
        },
        // Actions take no argument: `oslab://panic-stop/scan` must not
        // silently run the stop when the button meant something else.
        "panic-stop" | "quick-clean" => match (path.is_empty(), ACTIONS.iter().find(|a| **a == host)) {
            (true, Some(action)) => Command::Action(action),
            _ => Command::Unknown,
        },
        // Bare routes, from either spelling: `oslab://scan` (host) and
        // `oslab:///labs/macos` (path).
        _ => {
            let route = if host.is_empty() { path } else { host.as_str() };
            known_route(route).map(|r| Command::Navigate(r.to_string())).unwrap_or(Command::Unknown)
        }
    }
}

/// The dashboard path a route opens, mirroring the island router: cleanup tabs
/// are `/cleanup/<tab>/`, every other route is its own page.
pub fn dashboard_path(route: &str) -> String {
    match route {
        "scan" | "results" | "leftovers" | "history" | "space" => format!("cleanup/{route}/"),
        "dashboard" => "cleanup/".to_string(),
        route if route.starts_with("cleanup-") => "cleanup/".to_string(),
        route => format!("{route}/"),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn parse(s: &str) -> Command {
        parse_command(&Url::parse(s).unwrap())
    }

    #[test]
    fn widget_routes_navigate_from_both_spellings() {
        // The widget's documented form puts the route in the host. Before this
        // module the host was ignored, so none of these matched a route.
        assert_eq!(parse("oslab://scan"), Command::Navigate("scan".into()));
        assert_eq!(parse("oslab://dashboard"), Command::Navigate("dashboard".into()));
        // The path spelling parses to the same command.
        assert_eq!(parse("oslab:///scan"), Command::Navigate("scan".into()));
        assert_eq!(parse("oslab:///cleanup-bookmarks"), Command::Navigate("cleanup-bookmarks".into()));
        // Case and trailing slashes are noise.
        assert_eq!(parse("oslab://SCAN/"), Command::Navigate("scan".into()));
    }

    #[test]
    fn open_takes_a_whitelisted_route_argument() {
        assert_eq!(parse("oslab://open/scan"), Command::Navigate("scan".into()));
        assert_eq!(parse("oslab://open/cleanup-widgets"), Command::Navigate("cleanup-widgets".into()));
        assert_eq!(parse("oslab://open/labs/macos"), Command::Navigate("labs/macos".into()));
        assert_eq!(parse("oslab://open"), Command::Navigate("dashboard".into()));
        assert_eq!(parse("oslab://open/"), Command::Navigate("dashboard".into()));
        // Anything that is not a whitelisted route is refused, not navigated.
        assert_eq!(parse("oslab://open/not-a-route"), Command::Unknown);
        assert_eq!(parse("oslab://open/labs/pentest"), Command::Unknown);
        // Query and fragment are not part of the grammar.
        assert_eq!(parse("oslab://open/scan?x=1"), Command::Navigate("scan".into()));
    }

    #[test]
    fn the_two_actions_are_exactly_the_safe_ones() {
        assert_eq!(parse("oslab://panic-stop"), Command::Action("panic-stop"));
        assert_eq!(parse("oslab://PANIC-STOP/"), Command::Action("panic-stop"));
        assert_eq!(parse("oslab://quick-clean"), Command::Action("quick-clean"));
        // An argument would silently change what the button does.
        assert_eq!(parse("oslab://panic-stop/scan"), Command::Unknown);
        assert_eq!(parse("oslab://quick-clean/all"), Command::Unknown);
        // Only the stop reaches an endpoint; quick-clean is a page flow.
        assert_eq!(endpoint("panic-stop"), Some("/api/labs/macos/stop"));
        assert_eq!(endpoint("quick-clean"), None);
        assert_eq!(endpoint("clean"), None);
        assert_eq!(endpoint("/etc/passwd"), None);
        // Nothing that could delete or arm is reachable from a URL.
        for refused in ["clean", "delete", "arm", "control", "click", "run"] {
            assert_eq!(parse(&format!("oslab://{refused}")), Command::Unknown, "{refused} must be refused");
        }
    }

    #[test]
    fn unknown_commands_are_refused_rather_than_guessed() {
        assert_eq!(parse("oslab://rm-rf"), Command::Unknown);
        assert_eq!(parse("oslab://"), Command::Unknown);
        assert_eq!(parse("oslab://open/../etc/passwd"), Command::Unknown);
    }

    #[test]
    fn mcp_opens_the_page_or_the_connect_dialog_and_nothing_else() {
        assert_eq!(parse("oslab://mcp"), Command::Navigate("mcp".into()));
        assert_eq!(parse("oslab://mcp/status/macos"), Command::Navigate("mcp".into()));
        assert_eq!(parse("oslab://open/mcp"), Command::Navigate("mcp".into()));
        assert_eq!(parse("oslab://mcp/connect/macos"), Command::McpConnect { server: "macos", client: None });
        assert_eq!(
            parse("oslab://MCP/connect/MACOS/?client=Cursor"),
            Command::McpConnect { server: "macos", client: Some("cursor") }
        );
        // Unknown servers, clients, keys and extra segments refuse the URL.
        for refused in [
            "oslab://mcp/connect/linux",
            "oslab://mcp/connect",
            "oslab://mcp/connect/macos?client=evil",
            "oslab://mcp/connect/macos?client=cursor&client=codex",
            "oslab://mcp/connect/macos?command=/bin/sh",
            "oslab://mcp/connect/macos/extra",
            "oslab://mcp/status/linux",
            "oslab://mcp?client=cursor",
            "oslab://mcp/run/macos_click",
        ] {
            assert_eq!(parse(refused), Command::Unknown, "{refused} must be refused");
        }
        assert_eq!(mcp_connect_path("macos", Some("cursor")), "mcp/?connect=macos&client=cursor");
        assert_eq!(mcp_connect_path("macos", None), "mcp/?connect=macos");
        assert_eq!(dashboard_path("mcp"), "mcp/");
    }

    #[test]
    fn dashboard_paths_match_the_island_router() {
        assert_eq!(dashboard_path("scan"), "cleanup/scan/");
        assert_eq!(dashboard_path("history"), "cleanup/history/");
        assert_eq!(dashboard_path("space"), "cleanup/space/");
        assert_eq!(dashboard_path("dashboard"), "cleanup/");
        assert_eq!(dashboard_path("labs/macos"), "labs/macos/");
        assert_eq!(dashboard_path("host"), "host/");
        for section in ["cleanup-bookmarks", "cleanup-monitor", "cleanup-permissions", "cleanup-widgets"] {
            assert_eq!(dashboard_path(section), "cleanup/", "{section} lives on Settings");
        }
    }
}
