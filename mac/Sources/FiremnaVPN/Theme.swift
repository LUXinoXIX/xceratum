import SwiftUI

extension Color {
    init(hex: UInt32) {
        self.init(.sRGB,
                  red: Double((hex >> 16) & 0xFF) / 255,
                  green: Double((hex >> 8) & 0xFF) / 255,
                  blue: Double(hex & 0xFF) / 255,
                  opacity: 1)
    }
}

/// Farby podľa `dizajn-okna-v2.md` (svetlý aj tmavý vzhľad).
struct Palette {
    let dark: Bool
    init(_ scheme: ColorScheme) { dark = scheme == .dark }

    var window: Color { dark ? Color(hex: 0x0F2A50) : .white }
    var header: Color { dark ? Color(hex: 0x0F2A50) : Color(hex: 0x1F4A86) }
    var headerSub: Color { dark ? Color(hex: 0xB9C8DE) : Color(hex: 0xD5E0F0) }
    var text: Color { dark ? .white : Color(hex: 0x0F1E33) }
    var muted: Color { dark ? Color(hex: 0xB9C8DE) : Color(hex: 0x4F5F75) }
    var field: Color { dark ? Color(hex: 0x1B3A66) : Color(hex: 0xF4F7FB) }
    var fieldBorder: Color { dark ? Color(hex: 0x2E5287) : Color(hex: 0xCDD6E3) }
    var accent: Color { dark ? Color(hex: 0x6CC6BE) : Color(hex: 0x1F4A86) }
    var onAccent: Color { dark ? Color(hex: 0x0F2A50) : .white }
    var disabled: Color { dark ? Color(hex: 0x22436F) : Color(hex: 0xE3E8EF) }
    var onDisabled: Color { dark ? Color(hex: 0x9DB1CC) : Color(hex: 0x5C6878) }
    var line: Color { dark ? Color(hex: 0x24456F) : Color(hex: 0xEDEDED) }

    var redBg: Color { dark ? Color(hex: 0x4A1A22) : Color(hex: 0xFDF3F4) }
    var redBorder: Color { dark ? Color(hex: 0xC2566A) : Color(hex: 0xEEACB2) }
    var redText: Color { dark ? Color(hex: 0xFFD9DE) : Color(hex: 0x8A0B16) }
    var red: Color { dark ? Color(hex: 0xFF8A99) : Color(hex: 0xB10E1C) }
    var orBg: Color { dark ? Color(hex: 0x4A3612) : Color(hex: 0xFFF6E8) }
    var orBorder: Color { dark ? Color(hex: 0xC8963C) : Color(hex: 0xF0C27A) }
    var orText: Color { dark ? Color(hex: 0xFFE6B8) : Color(hex: 0x7A4300) }
    var okBg: Color { dark ? Color(hex: 0x163F35) : Color(hex: 0xF1FAF1) }
    var okBorder: Color { dark ? Color(hex: 0x4FA58C) : Color(hex: 0x9FD89F) }
    var okText: Color { dark ? Color(hex: 0xCFF5E6) : Color(hex: 0x0E5C0D) }
    var ok: Color { dark ? Color(hex: 0x7FE0C0) : Color(hex: 0x0E7A0D) }
}

enum BoxKind { case info, red, orange, ok }

struct NoticeBox<Content: View>: View {
    @Environment(\.colorScheme) var scheme
    let kind: BoxKind
    let icon: String
    @ViewBuilder var content: Content

    private var colors: [Color] {
        let p = Palette(scheme)
        switch kind {
        case .info: return [p.field, p.fieldBorder, p.text, p.accent]
        case .red: return [p.redBg, p.redBorder, p.redText, p.red]
        case .orange: return [p.orBg, p.orBorder, p.orText, p.orText]
        case .ok: return [p.okBg, p.okBorder, p.okText, p.ok]
        }
    }

    var body: some View {
        let c = colors
        HStack(alignment: .top, spacing: 10) {
            Image(systemName: icon).foregroundStyle(c[3]).font(.system(size: 15, weight: .semibold)).padding(.top, 1)
            VStack(alignment: .leading, spacing: 4) { content }
                .font(.system(size: 13))
                .foregroundStyle(c[2])
                .frame(maxWidth: .infinity, alignment: .leading)
                .fixedSize(horizontal: false, vertical: true)
        }
        .padding(12)
        .background(RoundedRectangle(cornerRadius: 8).fill(c[0]))
        .overlay(RoundedRectangle(cornerRadius: 8).stroke(c[1]))
    }
}

struct PrimaryButtonStyle: ButtonStyle {
    @Environment(\.colorScheme) var scheme
    @Environment(\.isEnabled) var enabled
    var secondary = false

    func makeBody(configuration: Configuration) -> some View {
        let p = Palette(scheme)
        configuration.label
            .font(.system(size: 16, weight: .semibold))
            .frame(maxWidth: .infinity, minHeight: 48)
            .foregroundStyle(secondary ? p.text : (enabled ? p.onAccent : p.onDisabled))
            .background(RoundedRectangle(cornerRadius: 8).fill(secondary ? Color.clear : (enabled ? p.accent : p.disabled)))
            .overlay(RoundedRectangle(cornerRadius: 8).stroke(secondary ? p.fieldBorder : .clear))
            .opacity(configuration.isPressed ? 0.85 : 1)
            .contentShape(Rectangle())
    }
}
