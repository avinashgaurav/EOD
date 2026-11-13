import AppKit
import EventKit
import ServiceManagement
import UserNotifications

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
        return Set(s.split(separator: "\n").map { $0.trimmingCharacters(in: .whitespaces).lowercased() }
            .filter { !$0.isEmpty && !$0.hasPrefix("#") })
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

    /// Off means off: the marker and every exported day go, so nothing stale is served.
    func disable() {
        try? FileManager.default.removeItem(at: marker)
        let fm = FileManager.default
        for n in (try? fm.contentsOfDirectory(atPath: Paths.cache.path)) ?? [] where n.hasPrefix("calendar-") && n.hasSuffix(".json") {
            try? fm.removeItem(at: Paths.cacheFile(n))
        }
    }

    /// Write cache/calendar-<date>.json for the engine. Timed events only; no
    /// cancelled or declined ones; titles and start times, never attendees.
    /// Called off the main thread.
    func export(date: String) {
        let file = Paths.cacheFile("calendar-\(date).json")
        guard enabled, !SourceSwitch.off.contains("meetings") else { return }
        guard authorized else {               // access was revoked: drop the stale marker and data
            disable(); return
        }
        guard let day = Day.fmt.date(from: date),
              let end = Calendar.current.date(byAdding: .day, value: 1, to: day) else { return }
        store.refreshSourcesIfNecessary()
        let pred = store.predicateForEvents(withStart: day, end: end, calendars: nil)
        let f = DateFormatter(); f.dateFormat = "HH:mm"; f.locale = Locale(identifier: "en_US_POSIX")
        let events = store.events(matching: pred)
            .filter { e in
                guard !e.isAllDay, e.status != .canceled, e.startDate >= day,
                      !(e.title ?? "").trimmingCharacters(in: .whitespaces).isEmpty else { return false }
                let me = e.attendees?.first { $0.isCurrentUser }
                return me?.participantStatus != .declined
            }
            .sorted { $0.startDate < $1.startDate }
            .map { ["title": $0.title ?? "", "time": f.string(from: $0.startDate)] }
        if let data = try? JSONSerialization.data(withJSONObject: events) { try? data.write(to: file, options: .atomic) }
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
        tabs.drawsBackground = false          // let the carbon sheet show through
        for (title, view) in [("General", general()), ("Sources", sources()), ("AI", ai()), ("Send", sendTab()), ("Privacy", privacy())] {
            let item = NSTabViewItem(identifier: title); item.label = title; item.view = view
            tabs.addTabViewItem(item)
        }
        window.contentView = tabs
        Brand.style(window)
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
        l.font = Brand.body(11); l.textColor = Brand.ink2; l.preferredMaxLayoutWidth = 500
        return l
    }

    private func check(_ title: String, _ on: Bool, _ handler: @escaping (Bool) -> Void) -> NSButton {
        let b = ClosureButton(checkboxWithTitle: title, target: nil, action: nil)
        b.state = on ? .on : .off; Brand.ink(b)
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
            p.onChange = { [weak self, weak p] sel in
                let other = key == "keyToggle" ? (d.string(forKey: "keyCopy") ?? "C") : (d.string(forKey: "keyToggle") ?? "W")
                if sel == other {           // two shortcuts on one key would silently drop one
                    p?.selectItem(withTitle: d.string(forKey: key) ?? fallback)
                    let a = NSAlert(); a.messageText = "⌥⌃⌘\(sel) is already the other shortcut"; a.runModal(); return
                }
                d.set(sel, forKey: key); self?.app?.registerHotKeys()
            }
            return p
        }
        let row1 = NSStackView(views: [NSTextField(labelWithString: "Show or hide the receipt:  ⌥⌃⌘"), keyPopup("keyToggle", "W")])
        let row2 = NSStackView(views: [NSTextField(labelWithString: "Copy today's update:  ⌥⌃⌘"), keyPopup("keyCopy", "C")])
        let morning = check("Morning standup reminder, 9:00 on weekdays", d.bool(forKey: "morningOn")) { [weak self] on in
            d.set(on, forKey: "morningOn"); self?.app?.scheduleExtras()
            if on { UNUserNotificationCenter.current().requestAuthorization(options: [.alert, .sound]) { _, _ in } }
        }
        let friday = check("Friday weekly reminder, 16:00", d.bool(forKey: "fridayOn")) { [weak self] on in
            d.set(on, forKey: "fridayOn"); self?.app?.scheduleExtras()
            if on { UNUserNotificationCenter.current().requestAuthorization(options: [.alert, .sound]) { _, _ in } }
        }
        return stack([login, start, rem, remEdit, morning, friday, NSBox.separator(), row1, row2,
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
        let calOn = cal.enabled && cal.authorized
        let calBtn = button(calOn ? "Calendar access: on (turn off)" : "Use Calendar (asks permission)") { [weak self] in
            if calOn { cal.disable(); self?.app?.refreshFromSettings(); self?.reopen() }
            else { cal.enable { ok in
                if !ok, let u = URL(string: "x-apple.systempreferences:com.apple.preference.security?Privacy_Calendars") { NSWorkspace.shared.open(u) }
                self?.app?.refreshFromSettings(); self?.reopen()
            } }
        }
        let webFile = Paths.support.appendingPathComponent("brief-web.on")
        let webBrief = check("Show sites on the daily receipt (otherwise only in Full day)",
                             FileManager.default.fileExists(atPath: webFile.path)) { [weak self] on in
            if on { FileManager.default.createFile(atPath: webFile.path, contents: Data()) } else { try? FileManager.default.removeItem(at: webFile) }
            self?.app?.refreshFromSettings()
        }
        views.append(webBrief)
        let shareFile = Paths.support.appendingPathComponent("share-lines.off")
        views.append(check("Include work lines in the share image (otherwise totals only)",
                           !FileManager.default.fileExists(atPath: shareFile.path)) { on in
            if on { try? FileManager.default.removeItem(at: shareFile) } else { FileManager.default.createFile(atPath: shareFile.path, contents: Data()) }
        })
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
        let r3 = radio("Ollama on this Mac (nothing leaves it). Model:", isOllama) {}
        // One group: AppKit only links radios that share a parent, so the state is set by hand.
        let group = [r1, r2, r3]
        func select(_ b: NSButton) { group.forEach { $0.state = ($0 === b) ? .on : .off } }
        let applyOllama: () -> Void = { [weak self] in
            let m = field.stringValue.trimmingCharacters(in: .whitespacesAndNewlines)
            guard m.range(of: #"^[A-Za-z0-9._:/-]{1,80}$"#, options: .regularExpression) != nil else {
                let a = NSAlert(); a.messageText = "That model name won't work"
                a.informativeText = "Use the name Ollama shows in `ollama list`, for example llama3.1."; a.runModal()
                return
            }
            select(r3); Polish.set(.ollama(m)); self?.app?.refreshFromSettings()
        }
        (r1 as! ClosureButton).onClick = { [weak self] b in select(b); Polish.set(.off); self?.app?.refreshFromSettings() }
        (r2 as! ClosureButton).onClick = { [weak self] b in select(b); Polish.set(.claude); self?.app?.refreshFromSettings() }
        (r3 as! ClosureButton).onClick = { _ in applyOllama() }
        field.target = OllamaField.shared; OllamaField.shared.apply = { if r3.state == .on { applyOllama() } }
        field.action = #selector(OllamaField.fire)
        let prev = button("Preview exactly what is sent…") { [weak self] in self?.app?.previewPayload() }
        return stack([note("The AI step rewrites your work lines into a manager-ready update. Choose where it runs."),
                      r1, r2, NSStackView(views: [r3, field]), prev,
                      note("Claude sends session titles, a few prompts per session and meeting titles through your own login. Ollama keeps everything on this Mac.")])
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
        let redactFile = Paths.support.appendingPathComponent("redact.off")
        let redact = check("Redact secrets, emails, internal hosts and home paths before anything leaves",
                           !FileManager.default.fileExists(atPath: redactFile.path)) { on in
            if on { try? FileManager.default.removeItem(at: redactFile) } else { FileManager.default.createFile(atPath: redactFile.path, contents: Data()) }
        }
        let insFile = Paths.support.appendingPathComponent("insight.on")
        let insight = check("One gentle line about the day on the receipt", FileManager.default.fileExists(atPath: insFile.path)) { [weak self] on in
            if on { FileManager.default.createFile(atPath: insFile.path, contents: Data()) } else { try? FileManager.default.removeItem(at: insFile) }
            self?.app?.refreshFromSettings()
        }
        let del = button("Delete all EOD data…") { [weak self] in self?.app?.deleteAllFromSettings() }
        return stack([NSStackView(views: [NSTextField(labelWithString: "Keep history for"), pop]), hide, redact, insight, NSBox.separator(), del,
                      note("Uninstall: quit EOD, then remove /Applications/EOD.app and ~/Library/Application Support/EOD.")])
    }

    private func reopen() {
        let a = app, keep = self                // stay alive across the hop
        DispatchQueue.main.async {
            keep.window.close()
            if let a = a { SettingsWindow.show(app: a) }
        }
    }
}

/// Applies the Ollama model when you press Return in its field.
final class OllamaField: NSObject {
    static let shared = OllamaField()
    var apply: (() -> Void)?
    @objc func fire() { apply?() }
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
