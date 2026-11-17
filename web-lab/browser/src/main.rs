//! Web Lab engine (`weblab`): embedded in-app browser windows with JavaScript
//! injection, controlled over a loopback HTTP API by the os-lab console.
//!
//! Usage:
//!   weblab serve [--port N]     run the engine (tao event loop + control API)
//!   weblab open URL [--port N]  ask a running engine to open a window
//!   weblab health [--port N]    ask a running engine for /healthz
//!   weblab version              print the version

mod app;
mod bootstrap;
mod capture;
mod protocol;
mod server;
mod state;

use std::path::PathBuf;
use std::process::ExitCode;
use std::sync::{Arc, Mutex};

use crate::protocol::DEFAULT_PORT;
use crate::state::SharedState;

fn main() -> ExitCode {
    let mut arguments = std::env::args().skip(1);
    let command = arguments.next().unwrap_or_else(|| "serve".to_string());
    let mut port: Option<u16> = None;
    let mut positionals: Vec<String> = Vec::new();
    let mut rest = arguments.peekable();
    while let Some(argument) = rest.next() {
        match argument.as_str() {
            "--port" | "-p" => match rest.next().and_then(|value| value.parse::<u16>().ok()) {
                Some(value) => port = Some(value),
                None => {
                    eprintln!("weblab: --port needs a number");
                    return ExitCode::from(2);
                }
            },
            value if value.starts_with('-') => {
                eprintln!("weblab: unknown option {value}");
                return ExitCode::from(2);
            }
            value => positionals.push(value.to_string()),
        }
    }
    let port = port
        .or_else(|| {
            std::env::var("WEBLAB_ENGINE_PORT")
                .ok()
                .and_then(|value| value.parse().ok())
        })
        .unwrap_or(DEFAULT_PORT);

    match command.as_str() {
        "serve" => serve(port),
        "open" => {
            let Some(url) = positionals.first() else {
                eprintln!("weblab: open needs a URL");
                return ExitCode::from(2);
            };
            command_running_engine(
                port,
                "/api/web/windows",
                &format!(r#"{{"url":"{url}"}}"#),
                "open",
            )
        }
        "health" => command_running_engine(port, "/healthz", "", "health"),
        "version" | "--version" => {
            println!("weblab {}", env!("CARGO_PKG_VERSION"));
            ExitCode::SUCCESS
        }
        other => {
            eprintln!("weblab: unknown command {other} (use serve, open, health or version)");
            ExitCode::from(2)
        }
    }
}

fn serve(port: u16) -> ExitCode {
    let state = Arc::new(Mutex::new(SharedState::new(port)));
    {
        let mut state = state.lock().expect("engine state poisoned");
        state.profiles = SharedState::default_profiles();
    }
    let data_root = data_root();
    let event_loop = tao::event_loop::EventLoopBuilder::<app::UserEvent>::with_user_event().build();
    let proxy = event_loop.create_proxy();

    // The control API lives on a worker thread; every webview is created and used
    // on the main thread inside the event loop, connected through the proxy.
    let server_state = Arc::clone(&state);
    std::thread::spawn(move || server::serve(port, server_state, proxy));

    println!(
        "weblab {} engine on http://127.0.0.1:{port} (data: {})",
        env!("CARGO_PKG_VERSION"),
        data_root.display()
    );
    let mut application = app::App::new(state, data_root);
    // `run` hijacks the main thread and only returns via ControlFlow::Exit.
    event_loop.run(move |event, target, control_flow| {
        *control_flow = tao::event_loop::ControlFlow::Wait;
        match event {
            tao::event::Event::UserEvent(user_event) => {
                application.handle_user_event(user_event, target, control_flow)
            }
            tao::event::Event::WindowEvent {
                window_id, event, ..
            } => application.handle_window_event(window_id, event),
            _ => {}
        }
    })
}

fn command_running_engine(port: u16, path: &str, body: &str, label: &str) -> ExitCode {
    let address = format!("http://127.0.0.1:{port}{path}");
    let client = match minimal_post(&address, body) {
        Ok(response) => response,
        Err(error) => {
            eprintln!("weblab: engine not reachable on 127.0.0.1:{port} ({error})");
            eprintln!("weblab: start it first with `weblab serve` or `./labctl web setup && ./labctl web up`");
            return ExitCode::FAILURE;
        }
    };
    println!("{label}: {client}");
    ExitCode::SUCCESS
}

/// Std-only JSON POST so the CLI subcommands avoid an HTTP client dependency.
fn minimal_post(address: &str, body: &str) -> Result<String, String> {
    let mut stream = std::net::TcpStream::connect(("127.0.0.1", address_port(address)?))
        .map_err(|error| error.to_string())?;
    let request = format!(
        "POST {path} HTTP/1.1\r\nHost: 127.0.0.1\r\nContent-Type: application/json\r\nContent-Length: {length}\r\nConnection: close\r\n\r\n{body}",
        path = address_path(address),
        length = body.len(),
    );
    use std::io::Write;
    stream
        .write_all(request.as_bytes())
        .map_err(|error| error.to_string())?;
    let mut response = String::new();
    use std::io::Read;
    stream
        .read_to_string(&mut response)
        .map_err(|error| error.to_string())?;
    Ok(response
        .split("\r\n\r\n")
        .nth(1)
        .unwrap_or_default()
        .to_string())
}

fn address_port(address: &str) -> Result<u16, String> {
    address
        .rsplit(':')
        .next()
        .and_then(|part| part.split('/').next())
        .and_then(|part| part.parse().ok())
        .ok_or_else(|| format!("cannot read port from {address}"))
}

fn address_path(address: &str) -> String {
    match address.split_once("127.0.0.1:") {
        Some((_, rest)) => match rest.split_once('/') {
            Some((_, path)) => format!("/{path}"),
            None => "/".to_string(),
        },
        None => "/".to_string(),
    }
}

/// Engine data root: profiles and logs live under the lab's `storage/` directory.
/// Defaults to `./storage` (the Makefile and the console run the engine with the
/// lab directory as the working directory); override with `WEBLAB_DATA_DIR`.
fn data_root() -> PathBuf {
    std::env::var("WEBLAB_DATA_DIR")
        .map(PathBuf::from)
        .unwrap_or_else(|_| PathBuf::from("storage"))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn address_parsing_reads_port_and_path() {
        assert_eq!(
            address_port("http://127.0.0.1:5077/api/web/windows"),
            Ok(5077)
        );
        assert_eq!(
            address_path("http://127.0.0.1:5077/api/web/windows"),
            "/api/web/windows"
        );
        assert_eq!(address_port("http://127.0.0.1:5077"), Ok(5077));
    }

    #[test]
    fn default_profiles_are_registered() {
        let profiles = SharedState::default_profiles();
        assert_eq!(profiles.len(), 2);
        assert!(profiles.iter().any(|profile| profile.ephemeral));
    }
}
