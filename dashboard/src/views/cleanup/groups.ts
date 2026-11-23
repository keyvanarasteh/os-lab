/**
 * Catalog classification for the sidebar and the Catalogs page: every catalog entry belongs to one
 * tool group (Apple developer tools, JavaScript, Python, …) so a user finds "Docker" or "Xcode"
 * without scanning 90 flat cards. Matching is by entry id; anything unmatched falls into "Other".
 */
export type CatalogGroup = { id: string; label: string; hint: string; match: RegExp };

export const CATALOG_GROUPS: CatalogGroup[] = [
  { id: "apple", label: "Xcode & Apple", hint: "Derived data, simulators, device support, CocoaPods", match: /xcode|coresimulator|cocoapods|device-support/ },
  { id: "javascript", label: "Node & JavaScript", hint: "npm, pnpm, yarn, bun, deno and tool caches", match: /\.(npm|pnpm|yarn|bun|deno|nvm|jest|eslint|prettier|turbo|nx|playwright)$/ },
  { id: "python", label: "Python", hint: "pip, poetry, uv, pyenv and model caches", match: /\.(pip|poetry|uv|pyenv|virtualenvwrapper|rembg-models)$/ },
  { id: "jvm", label: "Java & JVM", hint: "Gradle, Maven, Ivy, Coursier", match: /\.(gradle|maven|ivy2|coursier)$/ },
  { id: "native", label: "Rust, Go & native", hint: "Cargo, rustup, Go, sccache, ccache, Composer, Ruby", match: /\.(cargo-.*|rustup.*|wasm-pack|sccache|ccache|go-.*|gopath|composer|rubygems-cache|rbenv)$/ },
  { id: "cloud", label: "Cloud & containers", hint: "Kubernetes, Terraform, cloud CLIs, Helm", match: /\.(aws|gcloud|azure|kubectl|minikube|helm|k9s|terraform|pulumi|ansible|gh)$/ },
  { id: "editors", label: "Editors & IDEs", hint: "VS Code extensions and user data", match: /vscode/ },
  { id: "agents", label: "AI agents & models", hint: "Agent homes and model runtimes", match: /^agents\.|codex-runtimes/ },
  { id: "homebrew", label: "Homebrew", hint: "Download cache and Cellar", match: /homebrew/ },
  { id: "apps", label: "Apps", hint: "Chat and desktop app caches", match: /\.(discord|slack|oslab-cache)$/ },
  { id: "browsers", label: "Browsers", hint: "Cache, history and extension traces", match: /^browser\./ },
  { id: "system", label: "System", hint: "Logs, crash reports, caches, trash", match: /^system\./ },
  { id: "other", label: "Other", hint: "Everything else", match: /./ }
];

export function groupIdOf(entryId: string): string {
  return (CATALOG_GROUPS.find((group) => group.match.test(entryId)) ?? CATALOG_GROUPS[CATALOG_GROUPS.length - 1]!).id;
}
