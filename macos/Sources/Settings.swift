import AppKit
import EventKit
import ServiceManagement

/// Sources the person can switch off. Names match the engine's (sources.off).
enum SourceSwitch {
    static let all: [(name: String, title: String, detail: String)] = [
        ("claude-code", "Claude Code", "Session titles from ~/.claude"),
        ("codex", "Codex", "Session titles from ~/.codex"),
        ("git", "Git commits", "Repos in your work folders"),
        ("github", "GitHub pull requests", "Needs the gh CLI, signed in"),
        ("docs", "Documents", "Decks, docs and sheets you edited"),
        ("web", "Browser history", "Chrome, Brave, Safari (Safari needs Full Disk Access)"),
        ("meetings", "Calendar", "Meeting titles for the day"),
        ("apps", "Screen time", "Which app is in front, counted by EOD"),
    ]
    private static var file: URL { Paths.support.appendingPathComponent("sources.off") }

    static var off: Set<String> {
        guard let s = try? String(contentsOf: file, encoding: .utf8) else { return [] }
        return Set(s.split(separator: "\n").map { $0.trimmingCharacters(in: .whitespaces).lowercased() }.filter { !$0.isEmpty })
    }

    static func set(_ name: String, on: Bool) {
        var o = off
        if on { o.remove(name) } else { o.insert(name) }
        let text = o.sorted().joined(separator: "\n")
        if text.isEmpty { try? FileManager.default.removeItem(at: file) }
        else { try? (text + "\n").write(to: file, atomically: true, encoding: .utf8) }
    }
}

/// Calendar through macOS's own permission (EventKit), so nobody needs Homebrew
/// (audit F26). Only titles and start times are written for the engine; attendee
/// names are other people's data and are never read here.
final class CalendarBridge {
    static let shared = CalendarBridge()
    private let store = EKEventStore()
    private var marker: URL { Paths.cacheFile("calendar-enabled") }

    var enabled: Bool { FileManager.default.fileExists(atPath: marker.path) }

    var authorized: Bool {
        let s = EKEventStore.authorizationStatus(for: .event)
        if #available(macOS 14.0, *) { return s == .fullAccess }
        return s == .authorized
    }

    func enable(done: @escaping (Bool) -> Void) {
        let finish: (Bool, Error?) -> Void = { ok, _ in
            DispatchQueue.main.async {
                if ok { FileManager.default.createFile(atPath: self.marker.path, contents: Data()) }
                done(ok)
            }
        }
        if #available(macOS 14.0, *) { store.requestFullAccessToEvents(completion: finish) }
        else { store.requestAccess(to: .event, completion: finish) }
    }

    func disable() { try? FileManager.default.removeItem(at: marker) }

    /// Write cache/calendar-<date>.json for the engine. Timed events only.
    func export(date: String) {
        guard enabled, authorized, let day = Day.fmt.date(from: date),
              let end = Calendar.current.date(byAdding: .day, value: 1, to: day) else { return }
        let pred = store.predicateForEvents(withStart: day, end: end, calendars: nil)
        let f = DateFormatter(); f.dateFormat = "HH:mm"
        let events = store.events(matching: pred).filter { !$0.isAllDay }.sorted { $0.startDate < $1.startDate }
            .map { ["title": $0.title ?? "", "time": f.string(from: $0.startDate)] }
        if let data = try? JSONSerialization.data(withJSONObject: events) {
            try? data.write(to: Paths.cacheFile("calendar-\(date).json"), options: .atomic)
        }
    }
}

/// The Settings window (audit F22, F25): everything that used to be a dotfile.
final class SettingsWindow: NSObject, NSWindowDelegate {
    private static var current: SettingsWindow?
    private let window: NSWindow
    private weak var app: AppDelegate?

    static func show(app: AppDelegate) {
        if let c = current { c.window.makeKeyAndOrderFront(nil); NSApp.activate(ignoringOtherApps: true); return }
        current = SettingsWindow(app: app)
    }

    private init(app: AppDelegate) {
        self.app = app
        window = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 560, height: 470),
                          styleMask: [.titled, .closable], backing: .buffered, defer: false)
        window.title = "EOD Settings"; window.isReleasedWhenClosed = false
        super.init()
        let tabs = NSTabView()
        for (title, view) in [("General", general()), ("Sources", sources()), ("AI", ai()), ("Send", sendTab()), ("Privacy", privacy())] {
            let item = NSTabViewItem(identifier: title); item.label = title; item.view = view
            tabs.addTabViewItem(item)
        }
        window.contentView = tabs
        window.delegate = self
        window.center()
        NSApp.activate(ignoringOtherApps: true)
        window.makeKeyAndOrderFront(nil)
    }

    func windowWillClose(_ n: Notification) { SettingsWindow.current = nil }

    // MARK: building blocks

    private func stack(_ views: [NSView]) -> NSView {
        let s = NSStackView(views: views)
        s.orientation = .vertical; s.alignment = .leading; s.spacing = 10
        s.edgeInsets = NSEdgeInsets(top: 18, left: 20, bottom: 18, right: 20)
        return s
    }

    private func note(_ t: String) -> NSTextField {
        let l = NSTextField(wrappingLabelWithString: t)
        l.font = .systemFont(ofSize: 11); l.textColor = .secondaryLabelColor; l.preferredMaxLayoutWidth = 500
        return l
    }

    private func check(_ title: String, _ on: Bool, _ handler: @escaping (Bool) -> Void) -> NSButton {
        let b = ClosureButton(checkboxWithTitle: title, target: nil, action: nil)
        b.state = on ? .on : .off
        b.onClick = { handler($0.state == .on) }
        return b
    }

    private func button(_ title: String, _ handler: @escaping () -> Void) -> NSButton {
        let b = ClosureButton(title: title, target: nil, action: nil)
        b.bezelStyle = .rounded; b.onClick = { _ in handler() }
        return b
    }

    // MARK: tabs

    private func general() -> NSView {
        let d = UserDefaults.standard
        let login = check("Open EOD at login", SMAppService.mainApp.status == .enabled) { on in
            do { if on { try SMAppService.mainApp.register() } else { try SMAppService.mainApp.unregister() } }
            catch { SMAppService.openSystemSettingsLoginItems() }
            if SMAppService.mainApp.status == .requiresApproval { SMAppService.openSystemSettingsLoginItems() }
        }
        let start = check("Show the receipt when EOD opens", d.bool(forKey: "showAtStart")) { d.set($0, forKey: "showAtStart") }
        let rem = check("End-of-day reminder", d.bool(forKey: "reminderOn")) { [weak self] on in
            d.set(on, forKey: "reminderOn"); self?.app?.reschedule()
        }
        let remEdit = button("Reminder time and days…") { [weak self] in ReminderSettings.edit { self?.app?.reschedule() } }
        let letters = (65...90).map { String(UnicodeScalar($0)!) }
        func keyPopup(_ key: String, _ fallback: String) -> NSPopUpButton {
            let p = ClosurePopUp(); p.addItems(withTitles: letters)
            p.selectItem(withTitle: d.string(forKey: key) ?? fallback)
            p.onChange = { [weak self] sel in d.set(sel, forKey: key); self?.app?.registerHotKeys() }
            return p
        }
        let row1 = NSStackView(views: [NSTextField(labelWithString: "Show or hide the receipt:  ⌥⌃⌘"), keyPopup("keyToggle", "W")])
        let row2 = NSStackView(views: [NSTextField(labelWithString: "Copy today's update:  ⌥⌃⌘"), keyPopup("keyCopy", "C")])
        return stack([login, start, rem, remEdit, NSBox.separator(), row1, row2,
                      note("Shortcuts need no Accessibility permission. If one is taken by another app, the menu says so.")])
    }

    private func sources() -> NSView {
        let off = SourceSwitch.off
        var views: [NSView] = [note("Turn off anything you don't want on the receipt. Off means EOD doesn't read it at all.")]
        for s in SourceSwitch.all {
            views.append(check("\(s.title)  ·  \(s.detail)", !off.contains(s.name)) { [weak self] on in
                SourceSwitch.set(s.name, on: on); self?.app?.refreshFromSettings()
            })
        }
        let cal = CalendarBridge.shared
        let calBtn = button(cal.enabled && cal.authorized ? "Calendar access: on (turn off)" : "Use Calendar (asks permission)") { [weak self] in
            if cal.enabled { cal.disable(); self?.reopen() }
            else { cal.enable { ok in
                if !ok, let u = URL(string: "x-apple.systempreferences:com.apple.preference.security?Privacy_Calendars") { NSWorkspace.shared.open(u) }
                self?.app?.refreshFromSettings(); self?.reopen()
            } }
        }
        let fda = button("Open Full Disk Access (for Safari history)") {
            if let u = URL(string: "x-apple.systempreferences:com.apple.preference.security?Privacy_AllFiles") { NSWorkspace.shared.open(u) }
        }
        views += [NSBox.separator(), NSStackView(views: [calBtn, fda])]
        return stack(views)
    }

    private func ai() -> NSView {
        let mode = Polish.mode
        var model = "llama3.1"; if case .ollama(let m) = mode { model = m }
        let field = NSTextField(string: model); field.placeholderString = "llama3.1"
        field.widthAnchor.constraint(equalToConstant: 180).isActive = true
        func radio(_ t: String, _ on: Bool, _ act: @escaping () -> Void) -> NSButton {
            let b = ClosureButton(radioButtonWithTitle: t, target: nil, action: nil)
            b.state = on ? .on : .off; b.onClick = { _ in act() }; return b
        }
        var isOff = false, isClaude = false, isOllama = false
        switch mode { case .off: isOff = true; case .claude: isClaude = true; case .ollama: isOllama = true }
        let r1 = radio("Off: fully offline, lines are tidied by simple rules", isOff) { [weak self] in Polish.set(.off); self?.app?.refreshFromSettings() }
        let r2 = radio("Claude, through my own claude CLI login", isClaude) { [weak self] in Polish.set(.claude); self?.app?.refreshFromSettings() }
        let r3 = radio("Ollama on this Mac (nothing leaves it). Model:", isOllama) { [weak self] in
            let m = field.stringValue.trimmingCharacters(in: .whitespacesAndNewlines)
            if m.range(of: #"^[A-Za-z0-9._:/-]{1,80}$"#, options: .regularExpression) != nil { Polish.set(.ollama(m)); self?.app?.refreshFromSettings() }
        }
        let prev = button("Preview exactly what is sent…") { [weak self] in self?.app?.previewPayload() }
        return stack([note("The AI step rewrites your work lines into a manager-ready update. Choose where it runs."),
                      r1, r2, NSStackView(views: [r3, field]), prev,
                      note("Claude sends session titles and a few prompts per session through your own login. Ollama keeps everything on this Mac.")])
    }

    private func sendTab() -> NSView {
        let edit = button("Edit send destinations…") { [weak self] in self?.app?.editDestinationsFromSettings() }
        return stack([note("Send posts your work update to Slack, Teams or Linear, after you confirm a preview. Destinations are stored in your macOS Keychain on this Mac."), edit])
    }

    private func privacy() -> NSView {
        let d = UserDefaults.standard
        let pop = ClosurePopUp()
        for (t, _) in Retention.choices { pop.addItem(withTitle: t) }
        let cur = d.integer(forKey: "keepDays")
        pop.selectItem(at: Retention.choices.firstIndex { $0.1 == cur } ?? 3)
        pop.onChange = { sel in
            let days = Retention.choices.first { $0.0 == sel }?.1 ?? 0
            d.set(days, forKey: "keepDays"); Retention.prune(days: days)
        }
        let hide = button("Edit hidden lines, sites and apps…") {
            let f = Paths.support.appendingPathComponent("hide.txt")
            let body = (try? String(contentsOf: f, encoding: .utf8)) ?? "# One rule per line:\n# line: dentist\n# site: news.example.com\n# app: Messages\n"
            _ = TextWindow(title: "Never show", body: body, note: "Things EOD never shows, sends or gives the AI step. Delete a line to bring it back.",
                           editable: true, saveTitle: "Save") { text in
                try? text.write(to: f, atomically: true, encoding: .utf8)
            }
        }
        let del = button("Delete all EOD data…") { [weak self] in self?.app?.deleteAllFromSettings() }
        return stack([NSStackView(views: [NSTextField(labelWithString: "Keep history for"), pop]), hide, NSBox.separator(), del,
                      note("Uninstall: quit EOD, then remove /Applications/EOD.app and ~/Library/Application Support/EOD.")])
    }

    private func reopen() {
        let a = app
        window.close()
        DispatchQueue.main.async { if let a = a { SettingsWindow.show(app: a) } }
    }
}

/// Small helpers so controls can take a closure instead of a target/selector.
final class ClosureButton: NSButton {
    var onClick: ((NSButton) -> Void)? { didSet { target = self; action = #selector(fire) } }
    @objc private func fire() { onClick?(self) }
}

final class ClosurePopUp: NSPopUpButton {
    var onChange: ((String) -> Void)? { didSet { target = self; action = #selector(fire) } }
    @objc private func fire() { onChange?(titleOfSelectedItem ?? "") }
}

extension NSBox {
    static func separator() -> NSBox { let b = NSBox(); b.boxType = .separator; return b }
}
