import AppKit
import ServiceManagement
import UserNotifications

/// EOD as a native menu-bar app. It does what eod.lua does inside Hammerspoon:
/// runs the Python engine, shows the receipt in a frameless panel, keeps today's
/// cache warm, tracks screen time, rolls over at midnight and reminds you at 18:30
/// on weekdays. No Hammerspoon, no Accessibility permission.
final class AppDelegate: NSObject, NSApplicationDelegate, UNUserNotificationCenterDelegate, NSMenuDelegate {
    private var status: NSStatusItem!
    private var receipt: WebPanel!
    private var detail: WebPanel!
    private var hotkey: HotKey?
    private let usage = UsageTracker()
    private var curDate = Day.today()
    private var detailMode = ""                 // "full" or "weekly"
    private var weekStart: String?
    private var shown = false
    private var sharing = false, sending = false
    private var refreshTimer: Timer?, midnightTimer: Timer?, reminderTimer: Timer?
    private let defaults = UserDefaults.standard

    private let receiptSize = NSSize(width: 396, height: 660)
    private let margin: CGFloat = 24

    // MARK: lifecycle

    func applicationDidFinishLaunching(_ n: Notification) {
        defaults.register(defaults: ["reminderOn": true, "showAtStart": false, "keepDays": 0])
        EngineInstaller.installIfNeeded()
        if Secrets.importSendFileIfPresent() {
            Log.write("moved send.txt into the Keychain and removed the plain-text file")
        }
        Retention.prune(days: defaults.integer(forKey: "keepDays"))
        // Both versions at once overwrite each other's screen time and fight over
        // the hotkey. Say so once, plainly, instead of failing quietly.
        let hs = FileManager.default.homeDirectoryForCurrentUser.appendingPathComponent(".hammerspoon/eod.lua")
        if FileManager.default.fileExists(atPath: hs.path) && !defaults.bool(forKey: "warnedHammerspoon") {
            defaults.set(true, forKey: "warnedHammerspoon")
            NSApp.activate(ignoringOtherApps: true)
            let a = NSAlert()
            a.messageText = "You also have EOD in Hammerspoon"
            a.informativeText = "Running both mixes up screen time and the ⌥⌃⌘W shortcut. To switch to the app, remove the EOD lines from ~/.hammerspoon/init.lua and reload Hammerspoon. Your Hammerspoon files are not changed."
            a.addButton(withTitle: "Keep the app"); a.addButton(withTitle: "Quit the app")
            if a.runModal() == .alertSecondButtonReturn { NSApp.terminate(nil); return }
        }
        receipt = WebPanel(frame: receiptFrame())
        receipt.onMessage = { [weak self] in self?.onReceiptMessage($0) }
        detail = WebPanel(frame: detailFrame())
        detail.onMessage = { [weak self] in self?.onDetailMessage($0) }
        buildStatusItem()
        hotkey = HotKey { [weak self] in self?.toggle() }
        usage.start()
        refreshTimer = Timer.scheduledTimer(withTimeInterval: 600, repeats: true) { [weak self] _ in self?.tick() }
        scheduleMidnight()
        scheduleReminder()
        UNUserNotificationCenter.current().delegate = self
        if defaults.bool(forKey: "reminderOn") {   // ask now, not by surprise at 18:30
            UNUserNotificationCenter.current().requestAuthorization(options: [.alert, .sound]) { _, _ in }
        }
        if !FileManager.default.fileExists(atPath: Paths.cacheFile(".welcomed").path) {
            try? "1".write(to: Paths.cacheFile(".welcomed"), atomically: true, encoding: .utf8)
            Welcome.show { [weak self] in self?.show(animate: true) }
        } else if defaults.bool(forKey: "showAtStart") {
            show(animate: true)
        }
    }

    func applicationWillTerminate(_ n: Notification) { usage.stop() }

    // MARK: menu bar

    private func buildStatusItem() {
        status = NSStatusBar.system.statusItem(withLength: NSStatusItem.squareLength)
        if let img = Bundle.main.image(forResource: "MenuBarIconTemplate") {
            img.isTemplate = true
            img.size = NSSize(width: 18, height: 18)
            status.button?.image = img
        } else { status.button?.title = "EOD" }
        status.button?.toolTip = "EOD: today's work"
        let menu = NSMenu(); menu.delegate = self
        status.menu = menu
    }

    func menuNeedsUpdate(_ menu: NSMenu) {
        menu.removeAllItems()
        func item(_ t: String, _ sel: Selector, _ key: String = "", _ mods: NSEvent.ModifierFlags = []) -> NSMenuItem {
            let i = NSMenuItem(title: t, action: sel, keyEquivalent: key); i.keyEquivalentModifierMask = mods
            i.target = self; return i
        }
        menu.addItem(item(shown ? "Hide receipt" : "Show receipt", #selector(toggleMenu), "w", [.command, .option, .control]))
        if hotkey?.ok == false {
            let warn = NSMenuItem(title: "⌥⌃⌘W is in use by another app", action: nil, keyEquivalent: "")
            warn.isEnabled = false; menu.addItem(warn)
        }
        menu.addItem(item("Jump to today", #selector(jumpToday)))
        menu.addItem(item("Refresh now", #selector(refreshNow)))
        menu.addItem(.separator())
        menu.addItem(item("This week's report", #selector(showWeeklyMenu)))
        menu.addItem(item("Open work history", #selector(openHistory)))
        menu.addItem(item("Open data folder", #selector(openData)))
        menu.addItem(.separator())
        let ai = NSMenuItem(title: "AI tidy-up", action: nil, keyEquivalent: ""); let aiMenu = NSMenu()
        let mode = Polish.mode
        let off = item("Off (fully offline)", #selector(aiOff)); off.state = { if case .off = mode { return .on }; return .off }()
        let cl = item("Claude, through my claude CLI", #selector(aiClaude)); cl.state = { if case .claude = mode { return .on }; return .off }()
        let ol = item("Ollama on this Mac…", #selector(aiOllama)); ol.state = { if case .ollama = mode { return .on }; return .off }()
        [off, cl, ol].forEach { aiMenu.addItem($0) }
        aiMenu.addItem(.separator()); aiMenu.addItem(item("Preview exactly what is sent…", #selector(aiPreview)))
        ai.submenu = aiMenu; menu.addItem(ai)
        menu.addItem(item("Send destinations…", #selector(editDestinations)))
        let keep = NSMenuItem(title: "Keep history", action: nil, keyEquivalent: ""); let keepMenu = NSMenu()
        for (t, d) in Retention.choices {
            let i = item(t, #selector(setKeep(_:))); i.tag = d
            i.state = defaults.integer(forKey: "keepDays") == d ? .on : .off; keepMenu.addItem(i)
        }
        keep.submenu = keepMenu; menu.addItem(keep)
        menu.addItem(item("Delete all EOD data…", #selector(deleteAll)))
        menu.addItem(.separator())
        let login = item("Open at login", #selector(toggleLogin))
        login.state = SMAppService.mainApp.status == .enabled ? .on
            : (SMAppService.mainApp.status == .requiresApproval ? .mixed : .off)
        menu.addItem(login)
        let rem = item("End-of-day reminder (18:30)", #selector(toggleReminder))
        rem.state = defaults.bool(forKey: "reminderOn") ? .on : .off
        menu.addItem(rem)
        let start = item("Show receipt when EOD opens", #selector(toggleShowAtStart))
        start.state = defaults.bool(forKey: "showAtStart") ? .on : .off
        menu.addItem(start)
        menu.addItem(.separator())
        menu.addItem(item("About EOD", #selector(about)))
        menu.addItem(item("Quit EOD", #selector(quit), "q", [.command]))
    }

    @objc private func toggleMenu() { toggle() }
    @objc private func jumpToday() { curDate = Day.today(); show(animate: true) }
    @objc private func refreshNow() { rebuild(curDate, force: true) }
    @objc private func showWeeklyMenu() { showWeekly(force: false) }
    @objc private func openHistory() {
        let f = Paths.cacheFile("worklog-history.md")
        if FileManager.default.fileExists(atPath: f.path) { NSWorkspace.shared.open(f) }
        else { alert("No history yet", "Your work history appears after EOD has summarised its first day.") }
    }
    @objc private func openData() { NSWorkspace.shared.open(Paths.support) }
    @objc private func toggleReminder() {
        defaults.set(!defaults.bool(forKey: "reminderOn"), forKey: "reminderOn"); scheduleReminder()
    }
    @objc private func aiOff() { Polish.set(.off); rebuild(curDate, force: true) }
    @objc private func aiClaude() { Polish.set(.claude); rebuild(curDate, force: true) }
    @objc private func aiOllama() {
        NSApp.activate(ignoringOtherApps: true)
        let a = NSAlert(); a.messageText = "Use a local Ollama model"
        a.informativeText = "The AI step runs on this Mac and nothing leaves it. Ollama must be installed and running. Model name:"
        let f = NSTextField(frame: NSRect(x: 0, y: 0, width: 240, height: 24))
        if case .ollama(let m) = Polish.mode { f.stringValue = m } else { f.stringValue = "llama3.1" }
        a.accessoryView = f; a.addButton(withTitle: "Use Ollama"); a.addButton(withTitle: "Cancel")
        guard a.runModal() == .alertFirstButtonReturn else { return }
        let m = f.stringValue.trimmingCharacters(in: .whitespacesAndNewlines)
        guard m.range(of: #"^[A-Za-z0-9._:/-]{1,80}$"#, options: .regularExpression) != nil else {
            alert("That model name won't work", "Use the name Ollama shows in `ollama list`, for example llama3.1."); return
        }
        Polish.set(.ollama(m)); rebuild(curDate, force: true)
    }
    @objc private func aiPreview() {
        Engine.run(["--date", curDate, "--show-polish-payload"]) { r in
            let body = r.err.trimmingCharacters(in: .whitespacesAndNewlines) + "\n\n" + r.out
            _ = TextWindow(title: "What the AI step sends for \(self.curDate)",
                           body: body, note: "Nothing is sent by opening this. This is the exact text, for the selected day.", editable: false)
        }
    }
    @objc private func editDestinations() {
        let current = Secrets.sendTargets() ?? "# One destination per line. Saved in your macOS Keychain, never in a file.\n# slack  https://hooks.slack.com/services/...\n# teams  https://example.webhook.office.com/...\n# linear lin_api_...  ENG-123\n"
        _ = TextWindow(title: "Send destinations", body: current,
                       note: "Where ↗ Send posts your update. Stored in the macOS Keychain on this Mac only.",
                       editable: true) { [weak self] text in
            guard Secrets.setSendTargets(text) else {      // comments are kept; the engine skips them
                self?.alert("Couldn't save to the Keychain", "Your destinations were not saved. Try again, and allow access if macOS asks.")
                return
            }
            if let self = self { self.rebuild(self.curDate, force: true) }
        }
    }
    @objc private func setKeep(_ sender: NSMenuItem) {
        defaults.set(sender.tag, forKey: "keepDays"); Retention.prune(days: sender.tag)
    }
    @objc private func deleteAll() {
        NSApp.activate(ignoringOtherApps: true)
        let a = NSAlert(); a.alertStyle = .warning
        a.messageText = "Delete all EOD data on this Mac?"
        a.informativeText = "This removes every saved receipt, weekly report, screen-time record, your settings files, hide rules and the send destinations in the Keychain. It can't be undone. The app stays installed."
        a.addButton(withTitle: "Delete everything"); a.addButton(withTitle: "Cancel")
        guard a.runModal() == .alertFirstButtonReturn else { return }
        hide(); usage.stop(); let ok = Retention.deleteAll(); usage.start()
        rebuild(curDate, force: true, cacheOnly: true)
        if ok { alert("Deleted", "EOD starts fresh. AI tidy-up is off until you turn it on.") }
        else { alert("Some data could not be deleted", "Open the data folder from the menu to remove what is left, and check Keychain Access for \"com.avinashgaurav.eod\".") }
    }

    @objc private func toggleShowAtStart() { defaults.set(!defaults.bool(forKey: "showAtStart"), forKey: "showAtStart") }
    @objc private func toggleLogin() {
        do {
            switch SMAppService.mainApp.status {
            case .enabled: try SMAppService.mainApp.unregister()
            case .requiresApproval: SMAppService.openSystemSettingsLoginItems()
            default:
                try SMAppService.mainApp.register()
                if SMAppService.mainApp.status == .requiresApproval { SMAppService.openSystemSettingsLoginItems() }
            }
        } catch {
            alert("Couldn't change Open at login", "Move EOD to your Applications folder and try again. (\(error.localizedDescription))")
        }
    }
    @objc private func about() {
        NSApp.activate(ignoringOtherApps: true)
        NSApp.orderFrontStandardAboutPanel(options: [.credits: NSAttributedString(
            string: "Your work day, as a receipt. Built from files already on your Mac.\nData folder: \(Paths.support.path)")])
    }
    @objc private func quit() { NSApp.terminate(nil) }

    private func alert(_ title: String, _ text: String) {
        NSApp.activate(ignoringOtherApps: true)
        let a = NSAlert(); a.messageText = title; a.informativeText = text; a.runModal()
    }

    // MARK: panels

    private var screen: NSRect { (NSScreen.main ?? NSScreen.screens[0]).visibleFrame }

    private func receiptFrame() -> NSRect {
        NSRect(x: screen.maxX - receiptSize.width - margin, y: screen.maxY - margin - receiptSize.height,
               width: receiptSize.width, height: receiptSize.height)
    }

    private func detailFrame() -> NSRect {
        let w: CGFloat = 580
        var x = screen.maxX - receiptSize.width - margin - w - 16
        if x < screen.minX + margin { x = screen.minX + margin }
        return NSRect(x: x, y: screen.minY + margin, width: w, height: screen.height - margin * 2)
    }

    func toggle() { shown ? hide() : show(animate: true) }

    func show(animate: Bool) {
        let path = Paths.cacheFile("\(curDate).html").path
        if FileManager.default.fileExists(atPath: path) { receipt.load(path: path, animate: animate) }
        else { rebuild(curDate, force: true, animate: animate) }
        receipt.show(at: receipt.panel.isVisible ? receipt.panel.frame : receiptFrame())
        shown = true
        if curDate == Day.today() {           // refresh quietly after the print-down plays
            DispatchQueue.main.asyncAfter(deadline: .now() + 1.3) { [weak self] in
                guard let self = self, self.shown else { return }
                self.rebuild(self.curDate)
            }
        }
    }

    func hide() { hideDetail(); receipt.hide(); shown = false }

    private func hideDetail() { detail.hide(); detailMode = "" }

    private func showFull() {
        detailMode = "full"
        let fp = Paths.cacheFile("\(curDate)-full.html").path
        if FileManager.default.fileExists(atPath: fp) { detail.load(path: fp, animate: true) }
        else { rebuild(curDate, force: true) }
        detail.show(at: detailFrame())
    }

    private func showWeekly(force: Bool) {
        detailMode = "weekly"
        var args = ["--date", curDate, "--weekly"]
        if force { args.append("--repolish") }
        Engine.run(args) { [weak self] r in
            guard let self = self else { return }
            guard r.code == 0, let t = r.tagged, t.tag == "WEEKLY" else {
                Log.write("weekly build failed (\(r.code)): \(r.err.suffix(400))")
                self.hideDetail()
                self.receipt.js("window.toast&&toast('Couldn’t build the weekly report. Try Refresh, or open the data folder for details.')")
                return
            }
            if let m = t.rest.range(of: #"weekly-(\d{4}-\d{2}-\d{2})"#, options: .regularExpression) {
                self.weekStart = String(t.rest[m].dropFirst(7))
            }
            self.detail.load(path: t.rest, animate: true)
            self.detail.show(at: self.detailFrame())
        }
    }

    // MARK: engine

    private func rebuild(_ date: String, force: Bool = false, animate: Bool = false,
                         repolish: Bool = false, cacheOnly: Bool = false) {
        var args = ["--date", date]
        if repolish { args.append("--repolish") }
        Engine.run(args) { [weak self] r in
            guard let self = self else { return }
            guard r.code == 0, let t = r.tagged else {
                Log.write("extract failed (\(r.code)): \(r.err.suffix(600))"); return
            }
            if cacheOnly || !(force || t.tag != "UNCHANGED") { return }
            // A slow earlier run must not replace the day the person has moved to.
            guard date == self.curDate else { return }
            self.receipt.load(path: t.rest, animate: animate)
            if self.detailMode == "full", t.rest.hasSuffix(".html") {
                self.detail.load(path: String(t.rest.dropLast(5)) + "-full.html", animate: false)
            }
        }
    }

    private func tick() {
        let t = Day.today()
        if shown && curDate == t { rebuild(t) } else { rebuild(t, cacheOnly: true) }
    }

    private func scheduleMidnight() {
        guard let fire = Calendar.current.nextDate(after: Date(), matching: DateComponents(hour: 0, minute: 0, second: 30),
                                                   matchingPolicy: .nextTime) else { return }
        midnightTimer = Timer(fire: fire, interval: 0, repeats: false) { [weak self] _ in
            guard let self = self else { return }
            self.curDate = Day.today()
            Retention.prune(days: self.defaults.integer(forKey: "keepDays"))
            self.rebuild(self.curDate, force: true, cacheOnly: !self.shown)
            self.scheduleMidnight()
        }
        RunLoop.main.add(midnightTimer!, forMode: .common)
    }

    private func scheduleReminder() {
        reminderTimer?.invalidate()
        guard defaults.bool(forKey: "reminderOn") else { return }
        guard let fire = Calendar.current.nextDate(after: Date(), matching: DateComponents(hour: 18, minute: 30, second: 0),
                                                   matchingPolicy: .nextTime) else { return }
        reminderTimer = Timer(fire: fire, interval: 0, repeats: false) { [weak self] _ in
            guard let self = self else { return }
            let wd = Calendar.current.component(.weekday, from: Date())   // 1 = Sun, 7 = Sat
            let late = Date().timeIntervalSince(fire) > 1800              // the Mac slept through 18:30
            if wd != 1 && wd != 7 && !late {
                self.rebuild(Day.today(), force: true, cacheOnly: !self.shown)
                self.notify()
            }
            self.scheduleReminder()
        }
        RunLoop.main.add(reminderTimer!, forMode: .common)
    }

    private func notify() {
        let center = UNUserNotificationCenter.current()
        center.requestAuthorization(options: [.alert, .sound]) { ok, _ in
            guard ok else { return }
            let c = UNMutableNotificationContent()
            c.title = "EOD"; c.body = "Your work update is ready. Review it and send."
            center.add(UNNotificationRequest(identifier: "eod-reminder", content: c, trigger: nil))
        }
    }

    func userNotificationCenter(_ c: UNUserNotificationCenter, willPresent n: UNNotification,
                                withCompletionHandler done: @escaping (UNNotificationPresentationOptions) -> Void) {
        done([.banner, .sound])
    }

    func userNotificationCenter(_ c: UNUserNotificationCenter, didReceive r: UNNotificationResponse,
                                withCompletionHandler done: @escaping () -> Void) {
        DispatchQueue.main.async { self.curDate = Day.today(); self.show(animate: true) }
        done()
    }

    // MARK: messages from the page

    private func onReceiptMessage(_ b: [String: Any]) {
        switch b["action"] as? String ?? "" {
        case "copy": copy(b["text"] as? String ?? "")
        case "dragStart": receipt.startDrag()
        case "hide": hide()
        case "full": showFull()
        case "share": shareImage()
        case "refresh": rebuild(curDate, force: true)
        case "regen": rebuild(curDate, force: true, repolish: true)
        case "saveEdits": saveEdits(b["items"], file: "polish-\(curDate).json", keep: ["detailed"]) {
            self.rebuild(self.curDate, force: true)
        }
        case "post": post()
        case "neverShow":
            let kind = b["kind"] as? String ?? "", value = b["value"] as? String ?? ""
            guard ["line", "site", "app"].contains(kind), !value.isEmpty else { return }
            Engine.run(["--date", curDate, "--hide", kind, value]) { [weak self] r in
                guard let self = self else { return }
                guard r.code == 0, let t = r.tagged else {
                    self.receipt.js("window.toast&&toast('Couldn’t hide that. Try again.')"); return
                }
                self.receipt.load(path: t.rest, animate: false)
            }
        case "nav":
            let delta = (b["delta"] as? NSNumber)?.intValue ?? 0
            if let c = Day.shift(curDate, by: delta), c <= Day.today() { curDate = c; rebuild(c, force: true) }
        case "goDate":
            let c = b["date"] as? String ?? ""
            if c.range(of: #"^\d{4}-\d{2}-\d{2}$"#, options: .regularExpression) != nil, c <= Day.today() {
                curDate = c; rebuild(c, force: true)
            }
        default: break
        }
    }

    private func onDetailMessage(_ b: [String: Any]) {
        switch b["action"] as? String ?? "" {
        case "copy": copy(b["text"] as? String ?? "")
        case "dragStart": detail.startDrag()
        case "saveEdits":
            if detailMode == "weekly", let ws = weekStart {
                saveEdits(b["items"], file: "weekly-\(ws).json", keep: ["detailed", "report"]) { self.showWeekly(force: false) }
            }
        case "regen": if detailMode == "weekly" { showWeekly(force: true) }
        case "hide": hideDetail()
        default: break
        }
    }

    private func copy(_ s: String) {
        NSPasteboard.general.clearContents(); NSPasteboard.general.setString(s, forType: .string)
    }

    /// Hand-edited lines are saved with edited=true, which the engine honours on
    /// every rebuild. The detailed breakdown (and the weekly report) are kept.
    private func saveEdits(_ raw: Any?, file: String, keep: [String], then: @escaping () -> Void) {
        guard let list = raw as? [Any] else { return }       // malformed message: never wipe lines
        let items = list.compactMap { $0 as? String }.filter { !$0.isEmpty }
        let url = Paths.cacheFile(file)
        var out: [String: Any] = ["key": "edited", "highlights": items, "edited": true]
        if let d = try? Data(contentsOf: url), let prev = try? JSONSerialization.jsonObject(with: d) as? [String: Any] {
            for k in keep { if let v = prev[k] { out[k] = v } }
        }
        do {
            try JSONSerialization.data(withJSONObject: out).write(to: url, options: .atomic)
            then()
        } catch { Log.write("could not save edits to \(file): \(error)") }
    }

    private func shareImage() {
        if sharing { receipt.js("window.toast&&toast('Already drawing…')"); return }
        sharing = true
        Engine.run(["--date", curDate, "--share"]) { [weak self] r in
            guard let self = self else { return }
            self.sharing = false
            guard r.code == 0, let t = r.tagged, t.tag == "SHARE", let img = NSImage(contentsOfFile: t.rest) else {
                Log.write("share failed (\(r.code)): \(r.err.suffix(400))")
                self.receipt.js("window.toast&&toast('No image, see app.log in the data folder')"); return
            }
            NSPasteboard.general.clearContents(); NSPasteboard.general.writeObjects([img])
            self.receipt.js("window.toast&&toast('Image copied ✓')")
        }
    }

    private func post() {
        if sending { sendResult("Already sending"); return }
        sending = true
        Engine.run(["--date", curDate, "--send"], timeout: 90) { [weak self] r in
            guard let self = self else { return }
            self.sending = false
            if r.code == 0 {
                let names = r.out.components(separatedBy: "\n").first { $0.hasPrefix("SENT ") }?.dropFirst(5)
                self.sendResult("Sent to \(names.map(String.init) ?? "chat") ✓")
            } else {
                let last = r.err.split(separator: "\n").last.map(String.init)
                Log.write("send failed (\(r.code)): \(last ?? "")")
                self.sendResult(last ?? "Send failed (exit \(r.code))")
            }
        }
    }

    private func sendResult(_ msg: String) {
        guard let data = try? JSONSerialization.data(withJSONObject: [msg]),
              let arr = String(data: data, encoding: .utf8) else { return }
        receipt.js("window.sendResult&&sendResult(\(arr.dropFirst().dropLast()))")
    }
}

