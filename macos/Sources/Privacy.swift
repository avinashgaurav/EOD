import AppKit
import Security

/// Send destinations (Slack and Teams webhooks, Linear keys) live in the macOS
/// Keychain, not in a text file. The engine gets them in EOD_SEND_TARGETS for the
/// runs that need them, in the same one-per-line format send.txt used.
enum Secrets {
    private static let service = "com.avinashgaurav.eod", account = "send-destinations"

    private static var query: [String: Any] {
        [kSecClass as String: kSecClassGenericPassword,
         kSecAttrService as String: service, kSecAttrAccount as String: account]
    }

    static func sendTargets() -> String? {
        var q = query
        q[kSecReturnData as String] = true; q[kSecMatchLimit as String] = kSecMatchLimitOne
        var out: CFTypeRef?
        guard SecItemCopyMatching(q as CFDictionary, &out) == errSecSuccess, let d = out as? Data else { return nil }
        let s = String(decoding: d, as: UTF8.self)
        return s.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty ? nil : s
    }

    @discardableResult
    static func setSendTargets(_ text: String) -> Bool {
        let trimmed = text.trimmingCharacters(in: .whitespacesAndNewlines)
        if trimmed.isEmpty { return SecItemDelete(query as CFDictionary) == errSecSuccess || true }
        let data = Data(trimmed.utf8)
        let st = SecItemUpdate(query as CFDictionary, [kSecValueData as String: data] as CFDictionary)
        if st == errSecItemNotFound {
            var add = query; add[kSecValueData as String] = data
            add[kSecAttrAccessible as String] = kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly
            return SecItemAdd(add as CFDictionary, nil) == errSecSuccess
        }
        return st == errSecSuccess
    }

    /// A send.txt in the data folder (copied over from Hammerspoon) moves into the
    /// Keychain once, and the plain-text file is removed only after that worked.
    static func importSendFileIfPresent() -> Bool {
        let f = Paths.support.appendingPathComponent("send.txt")
        guard let text = try? String(contentsOf: f, encoding: .utf8) else { return false }
        let merged = [sendTargets(), text].compactMap { $0 }.joined(separator: "\n")
        guard setSendTargets(merged) else { Log.write("could not move send.txt into the Keychain"); return false }
        try? FileManager.default.removeItem(at: f)
        return true
    }
}

/// History retention and the delete-everything switch (audit F06).
enum Retention {
    static let choices: [(String, Int)] = [("30 days", 30), ("90 days", 90), ("1 year", 365), ("Forever", 0)]

    /// Delete cached days older than the chosen window. Files carry their date in
    /// the name (2026-11-12.json, polish-2026-11-12.json, usage-..., weekly-...).
    static func prune(days: Int) {
        guard days > 0, let cutoff = Calendar.current.date(byAdding: .day, value: -days, to: Date()) else { return }
        let fm = FileManager.default
        guard let names = try? fm.contentsOfDirectory(atPath: Paths.cache.path) else { return }
        for n in names {
            guard let r = n.range(of: #"\d{4}-\d{2}-\d{2}"#, options: .regularExpression),
                  let d = Day.fmt.date(from: String(n[r])), d < cutoff else { continue }
            try? fm.removeItem(at: Paths.cacheFile(n))
        }
    }

    /// Everything EOD has stored: cache, settings files, hide rules and the
    /// Keychain item. The app and its engine stay, so it starts fresh.
    static func deleteAll() {
        let fm = FileManager.default
        try? fm.removeItem(at: Paths.cache)
        for f in ["exclude.txt", "repos.txt", "hide.txt", "send.txt", "signature.txt", "ollama.txt", "polish.off"] {
            try? fm.removeItem(at: Paths.support.appendingPathComponent(f))
        }
        Secrets.setSendTargets("")
        try? fm.createDirectory(at: Paths.cache, withIntermediateDirectories: true)
        // Start fully offline again until the person opts back in.
        fm.createFile(atPath: Paths.support.appendingPathComponent("polish.off").path, contents: Data())
    }
}

/// AI tidy-up: off, through the person's own claude CLI, or a local Ollama model.
enum Polish {
    enum Mode { case off, claude, ollama(String) }
    private static var offFile: URL { Paths.support.appendingPathComponent("polish.off") }
    private static var ollamaFile: URL { Paths.support.appendingPathComponent("ollama.txt") }

    static var mode: Mode {
        if FileManager.default.fileExists(atPath: offFile.path) { return .off }
        if let m = try? String(contentsOf: ollamaFile, encoding: .utf8),
           !m.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
            return .ollama(m.trimmingCharacters(in: .whitespacesAndNewlines))
        }
        return .claude
    }

    static func set(_ m: Mode) {
        let fm = FileManager.default
        switch m {
        case .off: fm.createFile(atPath: offFile.path, contents: Data())
        case .claude: try? fm.removeItem(at: offFile); try? fm.removeItem(at: ollamaFile)
        case .ollama(let model):
            try? fm.removeItem(at: offFile)
            try? (model + "\n").write(to: ollamaFile, atomically: true, encoding: .utf8)
        }
    }
}

/// A plain window holding monospaced text: the AI payload preview, or the
/// editable list of send destinations.
final class TextWindow: NSObject, NSWindowDelegate {
    private static var open: [TextWindow] = []
    let window: NSWindow
    let text: NSTextView
    private var onSave: ((String) -> Void)?

    init(title: String, body: String, note: String, editable: Bool, onSave: ((String) -> Void)? = nil) {
        window = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 620, height: 460),
                          styleMask: [.titled, .closable, .resizable], backing: .buffered, defer: false)
        window.title = title; window.isReleasedWhenClosed = false
        let scroll = NSTextView.scrollableTextView()
        text = scroll.documentView as! NSTextView
        text.string = body; text.isEditable = editable; text.isRichText = false
        text.font = .monospacedSystemFont(ofSize: 12, weight: .regular)
        text.isAutomaticQuoteSubstitutionEnabled = false; text.isAutomaticDashSubstitutionEnabled = false
        self.onSave = onSave
        super.init()
        let label = NSTextField(wrappingLabelWithString: note)
        label.font = .systemFont(ofSize: 12); label.textColor = .secondaryLabelColor
        let stack = NSStackView(views: [label, scroll])
        stack.orientation = .vertical; stack.alignment = .leading; stack.spacing = 10
        stack.edgeInsets = NSEdgeInsets(top: 14, left: 16, bottom: 14, right: 16)
        scroll.translatesAutoresizingMaskIntoConstraints = false
        scroll.widthAnchor.constraint(equalTo: stack.widthAnchor, constant: -32).isActive = true
        if onSave != nil {
            let save = NSButton(title: "Save to Keychain", target: self, action: #selector(save))
            save.keyEquivalent = "s"; save.keyEquivalentModifierMask = [.command]
            stack.addArrangedSubview(save)
        }
        window.contentView = stack
        window.delegate = self
        window.center()
        TextWindow.open.append(self)
        NSApp.activate(ignoringOtherApps: true)
        window.makeKeyAndOrderFront(nil)
    }

    @objc private func save() { onSave?(text.string); window.close() }
    func windowWillClose(_ n: Notification) { TextWindow.open.removeAll { $0 === self } }
}
