import AppKit

/// First run: say plainly what EOD reads, that it stays on this Mac, and let the
/// person switch the one step that can leave the Mac (AI polish) off before the
/// first receipt is built. Per-source switches come with the engine change in #37.
enum Welcome {
    private static var window: NSWindow?
    private static var key = 0

    static func show(done: @escaping () -> Void) {
        let w = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 540, height: 600),
                         styleMask: [.titled, .closable], backing: .buffered, defer: false)
        w.title = "Welcome to EOD"
        w.isReleasedWhenClosed = false

        let stack = NSStackView()
        stack.orientation = .vertical; stack.alignment = .leading; stack.spacing = 10
        stack.edgeInsets = NSEdgeInsets(top: 22, left: 24, bottom: 20, right: 24)

        func label(_ s: String, size: CGFloat = 13, bold: Bool = false, color: NSColor = .labelColor) -> NSTextField {
            let l = NSTextField(wrappingLabelWithString: s)
            l.font = bold ? .boldSystemFont(ofSize: size) : .systemFont(ofSize: size)
            l.textColor = color; l.preferredMaxLayoutWidth = 470
            return l
        }

        stack.addArrangedSubview(label("Your work day, as a receipt.", size: 20, bold: true))
        stack.addArrangedSubview(label("EOD builds the receipt from files already on this Mac. Nothing is uploaded and there is no account.", color: .secondaryLabelColor))
        stack.addArrangedSubview(label("What it reads (untick anything you don't want)", bold: true))
        var sourceBoxes: [(String, NSButton)] = []
        for src in SourceSwitch.all {
            let title = src.name == "meetings" ? "Calendar: meeting titles (macOS will ask)" : "\(src.title): \(src.detail)"
            let b = NSButton(checkboxWithTitle: title, target: nil, action: nil)
            b.state = .on
            sourceBoxes.append((src.name, b)); stack.addArrangedSubview(b)
        }
        stack.addArrangedSubview(label("Safari history needs Full Disk Access for EOD (System Settings, Privacy & Security). Everything else works without it.",
                                       size: 12, color: .secondaryLabelColor))

        // Opt-in: the one step that can leave the Mac starts off until the person ticks it.
        let ai = NSButton(checkboxWithTitle: "Tidy the lines with AI through my own claude CLI (sends session titles and prompts to Claude)",
                          target: nil, action: nil)
        ai.state = .off
        stack.addArrangedSubview(ai)

        let fda = NSButton(title: "Open Full Disk Access settings", target: nil, action: nil)
        fda.bezelStyle = .rounded
        let go = NSButton(title: "Show my receipt", target: nil, action: nil)
        go.bezelStyle = .rounded; go.keyEquivalent = "\r"
        let row = NSStackView(views: [fda, go]); row.spacing = 10
        stack.addArrangedSubview(row)
        stack.addArrangedSubview(label("Show or hide it any time with ⌥⌃⌘W or the menu-bar icon.", size: 12, color: .secondaryLabelColor))

        // Opt-in for real: AI polish is off on disk before the window even shows,
        // so closing it any way leaves it off.
        FileManager.default.createFile(atPath: Paths.support.appendingPathComponent("polish.off").path, contents: Data())
        let handler = Handler(ai: ai, window: w, sources: sourceBoxes, done: done)
        w.delegate = handler
        fda.target = handler; fda.action = #selector(Handler.openFDA)
        go.target = handler; go.action = #selector(Handler.finish)
        objc_setAssociatedObject(w, &Welcome.key, handler, .OBJC_ASSOCIATION_RETAIN)

        w.contentView = stack
        w.center()
        window = w
        NSApp.activate(ignoringOtherApps: true)
        w.makeKeyAndOrderFront(nil)
    }

    private final class Handler: NSObject, NSWindowDelegate {
        private var finished = false
        let ai: NSButton, window: NSWindow, done: () -> Void
        let sources: [(String, NSButton)]
        init(ai: NSButton, window: NSWindow, sources: [(String, NSButton)], done: @escaping () -> Void) {
            self.ai = ai; self.window = window; self.sources = sources; self.done = done
        }

        @objc func openFDA() {
            if let u = URL(string: "x-apple.systempreferences:com.apple.preference.security?Privacy_AllFiles") {
                NSWorkspace.shared.open(u)
            }
        }

        @objc func finish() {
            if ai.state == .on { try? FileManager.default.removeItem(at: Paths.support.appendingPathComponent("polish.off")) }
            for (name, box) in sources { SourceSwitch.set(name, on: box.state == .on) }
            if sources.first(where: { $0.0 == "meetings" })?.1.state == .on { CalendarBridge.shared.enable { _ in } }
            window.close()          // windowWillClose shows the receipt
        }

        func windowWillClose(_ n: Notification) {
            guard !finished else { return }
            finished = true
            done()
        }
    }
}
