// CLW-07: the widget-side mirror of the dashboard's design tokens. The
// extension cannot import the web UI, so the same names/values are kept in
// sync by hand — source of truth is dashboard/src/styles/iux.css (oklch) and
// the cleanup accent #f36c21; the hex values here are the sRGB conversions
// of those tokens.

import SwiftUI

public struct WidgetColors: Equatable, Sendable {
    public var bg: Color
    public var fg: Color
    public var accent: Color
    public var border: Color
    public var mutedFg: Color
    public var danger: Color
    public var warning: Color
    public var success: Color

    public static let light = WidgetColors(
        bg: Color(hex: 0xFFFFFF),
        fg: Color(hex: 0x0A0A0A),
        accent: Color(hex: 0xF36C21),
        border: Color(hex: 0xE5E5E5),
        mutedFg: Color(hex: 0x737373),
        danger: Color(hex: 0xE7000B),
        warning: Color(hex: 0xE17100),
        success: Color(hex: 0x009966)
    )

    public static let dark = WidgetColors(
        bg: Color(hex: 0x0A0A0A),
        fg: Color(hex: 0xFAFAFA),
        accent: Color(hex: 0xF36C21),
        border: Color(hex: 0x2A2A2A),
        mutedFg: Color(hex: 0xA1A1A1),
        danger: Color(hex: 0xFF6467),
        warning: Color(hex: 0xFFB900),
        success: Color(hex: 0x00D492)
    )

    public static func resolved(for scheme: ColorScheme) -> WidgetColors {
        scheme == .dark ? .dark : .light
    }

    public func riskTint(_ risk: String?) -> Color {
        switch risk {
        case "high": return danger
        case "medium": return warning
        case "low": return success
        default: return mutedFg
        }
    }
}

extension Color {
    init(hex: UInt64, opacity: Double = 1) {
        let r = Double((hex >> 16) & 0xFF) / 255.0
        let g = Double((hex >> 8) & 0xFF) / 255.0
        let b = Double(hex & 0xFF) / 255.0
        self.init(.sRGB, red: r, green: g, blue: b, opacity: opacity)
    }
}
