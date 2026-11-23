// ax-helper — the macOS Lab's native accessibility reader/actor.
//
// One-shot CLI: every invocation prints JSON to stdout and exits 0, or prints
// {"error": …, "code": …} to stdout and exits 1. It replaces the System Events
// osascript path for tree reads (MIR-09): full attribute trees in milliseconds,
// values and focus included, windows and menu bars enumerable, elements
// addressable by a stable child-index path with an identity hash that fails
// closed (STALE_PATH) instead of acting on the wrong node.
//
// Build: swiftc -O ax-helper.swift -o build/ax-helper  (Xcode command line tools)
// Needs the Accessibility permission for the calling console (same as mac2).

import ApplicationServices
import CoreFoundation
import Foundation

// ── Error codes (mirrors console/oslab.py's taxonomy) ────────────────────────

let CODES = ["PERMISSION_DENIED", "APP_QUIT", "INVALID_PATH", "STALE_PATH",
             "NOT_SETTABLE", "ACTION_UNAVAILABLE", "TIMEOUT", "INVALID_ARGS", "INTERNAL"]

func fail(_ code: String, _ message: String) -> Never {
    let payload: [String: String] = ["error": message, "code": CODES.contains(code) ? code : "INTERNAL"]
    let data = try! JSONSerialization.data(withJSONObject: payload)
    FileHandle.standardOutput.write(data)
    FileHandle.standardOutput.write(Data("\n".utf8))
    exit(1)
}

// ── AX plumbing ──────────────────────────────────────────────────────────────

let kPosition = kAXPositionAttribute as CFString
let kSize = kAXSizeAttribute as CFString

func axAttr(_ element: AXUIElement, _ name: String) -> CFTypeRef? {
    var value: CFTypeRef?
    let result = AXUIElementCopyAttributeValue(element, name as CFString, &value)
    if result != .success { return nil }
    return value
}

func axChildren(_ element: AXUIElement) -> [AXUIElement] {
    guard let value = axAttr(element, kAXChildrenAttribute as String) else { return [] }
    return (value as! [AXUIElement])
}

func axNames(_ element: AXUIElement, _ attribute: String) -> [String] {
    var names: CFArray?
    let getter: CFString = attribute as CFString
    let result = attribute == "actions"
        ? AXUIElementCopyActionNames(element, &names)
        : AXUIElementCopyAttributeNames(element, &names)
    guard result == .success, let list = names as? [String] else { return [] }
    _ = getter
    return list
}

func axRect(_ element: AXUIElement) -> [String: CGFloat]? {
    guard let pos = axAttr(element, kPosition as String), let size = axAttr(element, kSize as String),
          CFGetTypeID(pos) == AXValueGetTypeID(), CFGetTypeID(size) == AXValueGetTypeID() else { return nil }
    var point = CGPoint.zero, cgSize = CGSize.zero
    AXValueGetValue(pos as! AXValue, .cgPoint, &point)
    AXValueGetValue(size as! AXValue, .cgSize, &cgSize)
    return ["x": point.x, "y": point.y, "w": cgSize.width, "h": cgSize.height]
}

/// Stringify any AX value: strings as-is, numbers/booleans via description,
/// arrays joined, other references summarised so the tree stays JSON-safe.
func axString(_ value: CFTypeRef?) -> String? {
    guard let value else { return nil }
    let typeID = CFGetTypeID(value)
    if typeID == CFStringGetTypeID() { return value as! String }
    if typeID == CFNumberGetTypeID() || typeID == CFBooleanGetTypeID() { return "\(value)" }
    if typeID == CFArrayGetTypeID() {
        let items = (value as! [CFTypeRef]).compactMap { axString($0) }
        return items.isEmpty ? nil : items.joined(separator: ", ")
    }
    if typeID == AXUIElementGetTypeID() { return nil }  // a reference, not a display value
    if typeID == AXValueGetTypeID() { return nil }      // position/size, already in rect
    return nil
}

// ── Path addressing ──────────────────────────────────────────────────────────

/// The path is a child-index chain from the app element: "0.3.1" follows
/// children[0] → children[3] → children[1]. "" is the app element itself.
func resolve(_ app: AXUIElement, _ path: String) -> (AXUIElement, String) {
    var element = app
    let indices = path.isEmpty ? [] : path.split(separator: ".").map { Int($0) }
    for (depth, index) in indices.enumerated() {
        guard let index, index >= 0 else { fail("INVALID_PATH", "path component \(depth + 1) is not an index") }
        let children = axChildren(element)
        guard index < children.count else {
            fail("INVALID_PATH", "path \(path) leaves the tree at depth \(depth + 1) (child \(index) of \(children.count))")
        }
        element = children[index]
    }
    return (element, path)
}

/// Identity hash of the addressed element (role + title + rect): set/perform/
/// read re-check it so a re-laid-out tree fails closed instead of acting on
/// whatever now sits at the same indices.
func identityHash(_ element: AXUIElement) -> String {
    let role = axString(axAttr(element, kAXRoleAttribute as String)) ?? ""
    let title = axString(axAttr(element, kAXTitleAttribute as String)) ?? ""
    let rect = axRect(element).map { "\($0["x"] ?? 0),\($0["y"] ?? 0),\($0["w"] ?? 0),\($0["h"] ?? 0)" } ?? ""
    let digest = "\(role)|\(title)|\(rect)"
    var hash: UInt64 = 1469598103934665603
    for byte in digest.utf8 {
        hash ^= UInt64(byte)
        hash = hash &* 1099511628211
    }
    return String(format: "%016llx", hash)
}

func checkIdentity(_ element: AXUIElement, _ expect: String?) {
    guard let expect, !expect.isEmpty else { return }
    let actual = identityHash(element)
    guard actual == expect else {
        fail("STALE_PATH", "the element at that path changed since the tree was read (identity \(actual), expected \(expect)); read the tree again")
    }
}

// ── Node building ────────────────────────────────────────────────────────────

func nodeDict(_ element: AXUIElement, _ path: String, depth: Int, max: Int) -> [String: Any] {
    var node: [String: Any] = ["path": path, "identity": identityHash(element)]
    if let role = axString(axAttr(element, kAXRoleAttribute as String)) { node["role"] = role }
    if let subrole = axString(axAttr(element, kAXSubroleAttribute as String)), !subrole.isEmpty { node["subrole"] = subrole }
    if let title = axString(axAttr(element, kAXTitleAttribute as String)), !title.isEmpty { node["title"] = title }
    if let label = axString(axAttr(element, kAXDescriptionAttribute as String)), !label.isEmpty { node["label"] = String(label.prefix(200)) }
    if let value = axString(axAttr(element, kAXValueAttribute as String)) { node["value"] = String(value.prefix(500)) }
    if let placeholder = axString(axAttr(element, kAXPlaceholderValueAttribute as String)), !placeholder.isEmpty { node["placeholder"] = placeholder }
    if let rect = axRect(element) { node["rect"] = rect }
    let focused = axAttr(element, kAXFocusedAttribute as String)
    if let focused, focused as! Bool == true { node["focused"] = true }
    let enabled = axAttr(element, kAXEnabledAttribute as String)
    if let enabled, enabled as! Bool == false { node["enabled"] = false }
    let actions = axNames(element, "actions")
    if !actions.isEmpty { node["actions"] = actions }
    if depth > 0 {
        let children = axChildren(element).prefix(max == 0 ? Int.max : max)
        node["children"] = children.enumerated().map { (index, child) in
            nodeDict(child, path.isEmpty ? "\(index)" : "\(path).\(index)", depth: depth - 1, max: max)
        }
    }
    return node
}

/// The element paths are addressed against: the app itself, or — matching the pinned
/// tree reads — one AX window chosen by index (MIR-09). Without --window the paths run
/// from the app element.
func pinnedRoot(_ app: AXUIElement, _ windowArg: String?) -> AXUIElement {
    guard let windowArg, let windowIndex = Int(windowArg), windowIndex >= 0 else { return app }
    let windows = axChildren(app)
    guard windowIndex < windows.count else {
        fail("INVALID_PATH", "window \(windowIndex) does not exist (the app shows \(windows.count))")
    }
    return windows[windowIndex]
}

func appElement(_ pid: Int32) -> AXUIElement {
    guard AXIsProcessTrusted() else {
        fail("PERMISSION_DENIED", "the console needs Accessibility permission (System Settings > Privacy & Security > Accessibility)")
    }
    let app = AXUIElementCreateApplication(pid)
    var probe: CFTypeRef?
    let result = AXUIElementCopyAttributeValue(app, kAXRoleAttribute as CFString, &probe)
    guard result == .success || result == .attributeUnsupported else {
        fail(result == .cannotComplete ? "TIMEOUT" : "APP_QUIT",
             "no accessibility element for pid \(pid) (\(result.rawValue)); the app may have quit")
    }
    AXUIElementSetMessagingTimeout(app, 3.0)
    return app
}

func emit(_ payload: [String: Any]) -> Never {
    let data = try! JSONSerialization.data(withJSONObject: payload)
    FileHandle.standardOutput.write(data)
    FileHandle.standardOutput.write(Data("\n".utf8))
    exit(0)
}

func arg(_ name: String) -> String? {
    guard let index = CommandLine.arguments.firstIndex(of: name), index + 1 < CommandLine.arguments.count else { return nil }
    return CommandLine.arguments[index + 1]
}

// ── Commands ─────────────────────────────────────────────────────────────────

let arguments = CommandLine.arguments
guard arguments.count >= 2 else { fail("INVALID_ARGS", "usage: ax-helper tree|windows|menubar|read|set|perform|focused --pid N … | trusted | request-access") }

// Permission commands need no pid: `trusted` reports the Accessibility grant, `request-access`
// fires the system consent dialog (the grant belongs to the app that launched this helper).
if arguments[1] == "trusted" {
    emit(["trusted": AXIsProcessTrusted()])
}
if arguments[1] == "request-access" {
    let options = ["AXTrustedCheckOptionPrompt": true] as CFDictionary
    emit(["trusted": AXIsProcessTrustedWithOptions(options)])
}

let pid = Int32(arg("--pid") ?? "") ?? -1
guard pid > 0 else { fail("INVALID_ARGS", "--pid must be a process id") }
let app = appElement(pid)

switch arguments[1] {
case "tree":
    let depth = Int(arg("--depth") ?? "") ?? 14
    let max = Int(arg("--max") ?? "") ?? 0
    let windows = axChildren(app)  // kAXChildren at app level starts with windows
    let root: AXUIElement
    if arg("--window") != nil {
        root = pinnedRoot(app, arg("--window"))
    } else if let main = axAttr(app, kAXMainWindowAttribute as String) {
        root = main as! AXUIElement
    } else {
        root = app
    }
    emit(["pid": Int(pid), "window": windows.count, "tree": nodeDict(root, "", depth: depth, max: max)])

case "windows":
    let windows = axChildren(app)
    var list: [[String: Any]] = []
    for (index, window) in windows.enumerated() {
        var entry: [String: Any] = ["index": index]
        if let rect = axRect(window) { entry["rect"] = rect }
        if let title = axString(axAttr(window, kAXTitleAttribute as String)), !title.isEmpty { entry["title"] = title }
        if let subrole = axString(axAttr(window, kAXSubroleAttribute as String)), !subrole.isEmpty {
            entry["subrole"] = subrole
            if subrole.contains("Sheet") || subrole.contains("Dialog") || subrole.contains("Alert") {
                entry["modal"] = true
            }
        }
        if let main = axAttr(window, kAXMainAttribute as String), main as! Bool == true { entry["main"] = true }
        if let focused = axAttr(window, kAXFocusedAttribute as String), focused as! Bool == true { entry["focused"] = true }
        if let minimized = axAttr(window, kAXMinimizedAttribute as String), minimized as! Bool == true { entry["minimized"] = true }
        list.append(entry)
    }
    emit(["pid": Int(pid), "windows": list])

case "menubar":
    guard let bar = axAttr(app, kAXMenuBarAttribute as String) else {
        fail("ACTION_UNAVAILABLE", "this app exposes no menu bar")
    }
    emit(["pid": Int(pid), "menubar": nodeDict(bar as! AXUIElement, "", depth: 4, max: 60)])

case "read":
    let path = arg("--path") ?? ""
    let (element, _) = resolve(pinnedRoot(app, arg("--window")), path)
    checkIdentity(element, arg("--identity"))
    let name = arg("--attr") ?? kAXValueAttribute as String
    guard let value = axAttr(element, name) else {
        fail("ACTION_UNAVAILABLE", "element \(path) has no \(name) attribute")
    }
    emit(["pid": Int(pid), "path": path, "attr": name, "value": axString(value) ?? NSNull()])

case "set":
    let path = arg("--path") ?? ""
    guard let value = arg("--value") else { fail("INVALID_ARGS", "--value is required") }
    let (element, _) = resolve(pinnedRoot(app, arg("--window")), path)
    checkIdentity(element, arg("--identity"))
    var settable: DarwinBoolean = false
    AXUIElementIsAttributeSettable(element, kAXValueAttribute as CFString, &settable)
    guard settable.boolValue else {
        fail("NOT_SETTABLE", "element \(path) does not accept a value (read its actions or click instead)")
    }
    let result = AXUIElementSetAttributeValue(element, kAXValueAttribute as CFString, value as CFString)
    guard result == .success else {
        fail(result == .cannotComplete ? "TIMEOUT" : "ACTION_UNAVAILABLE",
             "setting the value failed (\(result.rawValue)); the element may refuse strings")
    }
    var readBack: CFTypeRef?
    AXUIElementCopyAttributeValue(element, kAXValueAttribute as CFString, &readBack)
    var verify: [String: Any] = ["changed": (axString(readBack) ?? "") == value]
    if let after = axString(readBack) { verify["after"] = after } else { verify["after"] = NSNull() }
    emit(["pid": Int(pid), "path": path, "value": value, "verify": verify])

case "perform":
    let path = arg("--path") ?? ""
    guard let action = arg("--action") else { fail("INVALID_ARGS", "--action is required") }
    let (element, _) = resolve(pinnedRoot(app, arg("--window")), path)
    checkIdentity(element, arg("--identity"))
    let advertised = axNames(element, "actions")
    guard advertised.contains(action) else {
        fail("ACTION_UNAVAILABLE", "element \(path) advertises [\(advertised.joined(separator: ", "))], not \(action)")
    }
    let result = AXUIElementPerformAction(element, action as CFString)
    guard result == .success else { fail("ACTION_UNAVAILABLE", "performing \(action) failed (\(result.rawValue))") }
    emit(["pid": Int(pid), "path": path, "action": action, "performed": true])

case "focused":
    let scope = pinnedRoot(app, arg("--window"))
    guard let focused = axAttr(scope, kAXFocusedUIElementAttribute as String) else {
        emit(["pid": Int(pid), "focused": NSNull()])
    }
    let element = focused as! AXUIElement
    var node = nodeDict(element, "", depth: 0, max: 0)
    emit(["pid": Int(pid), "focused": node])

default:
    fail("INVALID_ARGS", "unknown command \(arguments[1]); use tree|windows|menubar|read|set|perform|focused")
}
