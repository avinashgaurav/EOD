import AppKit
import CoreText

/// The carbon-copy look (design direction 02) for the native windows: blue carbon
/// ink on the pink duplicate sheet, Archivo Narrow for headings, Courier Prime for
/// text. The faces are the ones bundled with the engine, registered for this
/// process only. Dark mode keeps the same ink-on-copy idea with a dark sheet.
enum Brand {
    private static func dyn(_ light: NSColor, _ dark: NSColor) -> NSColor {
        NSColor(name: nil) { $0.bestMatch(from: [.darkAqua, .aqua]) == .darkAqua ? dark : light }
    }
    private static func hex(_ v: UInt32) -> NSColor {
        NSColor(srgbRed: CGFloat((v >> 16) & 0xFF) / 255, green: CGFloat((v >> 8) & 0xFF) / 255,
                blue: CGFloat(v & 0xFF) / 255, alpha: 1)
    }
    static let paper = dyn(hex(0xF6D9DC), hex(0x231C21))
    static let ink = dyn(hex(0x24357A), hex(0xC9D2F5))
    static let ink2 = dyn(hex(0x4A5590), hex(0xB7AFC2))
    static let stamp = dyn(hex(0xA82A33), hex(0xF07A82))

    static func registerFonts() {
        guard let dir = Bundle.main.resourceURL?.appendingPathComponent("engine/eod/render/fonts") else { return }
        for f in ["ArchivoNarrow.ttf", "CourierPrime-Regular.ttf", "CourierPrime-Bold.ttf"] {
            CTFontManagerRegisterFontsForURL(dir.appendingPathComponent(f) as CFURL, .process, nil)
        }
    }

    /// Archivo Narrow at a weight, falling back to the system face.
    static func head(_ size: CGFloat) -> NSFont {
        let d = NSFontDescriptor(fontAttributes: [.family: "Archivo Narrow",
                                                  .traits: [NSFontDescriptor.TraitKey.weight: NSFont.Weight.bold]])
        return NSFont(descriptor: d, size: size) ?? .boldSystemFont(ofSize: size)
    }
    static func body(_ size: CGFloat, bold: Bool = false) -> NSFont {
        NSFont(name: bold ? "CourierPrime-Bold" : "CourierPrime-Regular", size: size)
            ?? .monospacedSystemFont(ofSize: size, weight: bold ? .bold : .regular)
    }

    /// The pink sheet as the window's background.
    static func style(_ w: NSWindow) {
        w.backgroundColor = paper
        w.titlebarAppearsTransparent = true
    }

    /// Checkbox and button titles in carbon ink and Courier Prime.
    static func ink(_ b: NSButton, size: CGFloat = 12.5) {
        b.attributedTitle = NSAttributedString(string: b.title, attributes: [.font: body(size), .foregroundColor: ink])
    }
}
