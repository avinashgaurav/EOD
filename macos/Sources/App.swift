import AppKit
import Carbon.HIToolbox
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
    private var copyKey: HotKey?
    private let usage = UsageTracker()
    private var curDate = Day.today()
    private var detailMode = ""                 // "full" or "weekly"
    private var weekStart: String?
    private var shown = false
    private var sharing = false, sending = false
    private var refreshTimer: Timer?, midnightTimer: Timer?, reminderTimer: Timer?
    private let defaults = UserDefaults.standard
    private var manualRefresh = false
    private var discarding = false
    private var updateCheckRunning = false
    static func hm() -> String { let f = DateFormatter(); f.dateFormat = "HH:mm"; return f.string(from: Date()) }

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
        registerHotKeys()
        usage.start()
        Counts.mark("installed")
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

    // MARK: settings hooks

    private static let keyCodes: [String: Int] = ["A": kVK_ANSI_A, "B": kVK_ANSI_B, "C": kVK_ANSI_C, "D": kVK_ANSI_D,
        "E": kVK_ANSI_E, "F": kVK_ANSI_F, "G": kVK_ANSI_G, "H": kVK_ANSI_H, "I": kVK_ANSI_I, "J": kVK_ANSI_J,
        "K": kVK_ANSI_K, "L": kVK_ANSI_L, "M": kVK_ANSI_M, "N": kVK_ANSI_N, "O": kVK_ANSI_O, "P": kVK_ANSI_P,
        "Q": kVK_ANSI_Q, "R": kVK_ANSI_R, "S": kVK_ANSI_S, "T": kVK_ANSI_T, "U": kVK_ANSI_U, "V": kVK_ANSI_V,
        "W": kVK_ANSI_W, "X": kVK_ANSI_X, "Y": kVK_ANSI_Y, "Z": kVK_ANSI_Z]

    /// (Re)register both shortcuts from Settings (audit F25).
    func registerHotKeys() {
        hotkey?.unregister(); copyKey?.unregister()
        let t = defaults.string(forKey: "keyToggle") ?? "W", c = defaults.string(forKey: "keyCopy") ?? "C"
        hotkey = HotKey(key: Self.keyCodes[t] ?? kVK_ANSI_W, id: 1, name: "⌥⌃⌘\(t)") { [weak self] in self?.toggle() }
        copyKey = c == t ? nil : HotKey(key: Self.keyCodes[c] ?? kVK_ANSI_C, id: 2, name: "⌥⌃⌘\(c)") { [weak self] in self?.copyTodayUpdate() }
    }
    func reschedule() { scheduleReminder() }
    func refreshFromSettings() { rebuild(curDate, force: true, cacheOnly: !shown) }
    func previewPayload() { aiPreview() }
    func editDestinationsFromSettings() { editDestinations() }
    func deleteAllFromSettings() { deleteAll() }
    @objc private func openSettings() { SettingsWindow.show(app: self) }

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
        menu.addItem(item(shown ? "Hide receipt" : "Show receipt", #selector(toggleMenu),
                          (defaults.string(forKey: "keyToggle") ?? "W").lowercased(), [.command, .option, .control]))
        if copyKey?.ok == false {
            let warn = NSMenuItem(title: "⌥⌃⌘\(defaults.string(forKey: "keyCopy") ?? "C") is in use by another app (change it in Settings)", action: nil, keyEquivalent: "")
            warn.isEnabled = false; menu.addItem(warn)
        }
        if hotkey?.ok == false {
            let warn = NSMenuItem(title: "⌥⌃⌘\(defaults.string(forKey: "keyToggle") ?? "W") is in use by another app (change it in Settings)", action: nil, keyEquivalent: "")
            warn.isEnabled = false; menu.addItem(warn)
        }
        menu.insertItem(item("Copy today's update", #selector(copyTodayUpdate),
                             (defaults.string(forKey: "keyCopy") ?? "C").lowercased(), [.command, .option, .control]), at: 0)
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
        let rem = item("End-of-day reminder (\(ReminderSettings.label))", #selector(toggleReminder))
        rem.state = defaults.bool(forKey: "reminderOn") ? .on : .off
        menu.addItem(rem)
        menu.addItem(item("Reminder time and days…", #selector(editReminder)))
        let start = item("Show receipt when EOD opens", #selector(toggleShowAtStart))
        start.state = defaults.bool(forKey: "showAtStart") ? .on : .off
        menu.addItem(start)
        menu.addItem(.separator())
        menu.addItem(item("Settings…", #selector(openSettings), ",", [.command]))
        menu.addItem(item("Check for updates…", #selector(checkUpdates)))
        menu.addItem(item("Usage counts (stay on this Mac)…", #selector(showCounts)))
        menu.addItem(item("Send feedback…", #selector(feedback)))
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

    @objc private func editReminder() { ReminderSettings.edit { [weak self] in self?.scheduleReminder() } }
    @objc private func feedback() {
        if let u = URL(string: "https://github.com/avinashgaurav/EOD/issues/new") { NSWorkspace.shared.open(u) }
    }
    @objc private func checkUpdates() {
        guard !updateCheckRunning else { return }
        updateCheckRunning = true
        Updates.check { [weak self] in self?.updateCheckRunning = false }
    }
    @objc private func showCounts() {
        _ = TextWindow(title: "Usage counts", body: Counts.summary(),
                       note: "Kept only on this Mac. EOD has no server and sends nothing. Copy these into feedback if you'd like to help.",
                       editable: false)
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

    /// The display the pointer is on, so the receipt opens where you are looking.
    private var screen: NSRect {
        let m = NSEvent.mouseLocation
        return (NSScreen.screens.first { NSMouseInRect(m, $0.frame, false) } ?? NSScreen.main ?? NSScreen.screens[0]).visibleFrame
    }

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
        Counts.activeToday()
        // Full print-down on the first open of the day; every other open is quick (F27).
        let first = animate && defaults.string(forKey: "lastPrintDay") != Day.today()
        let path = Paths.cacheFile("\(curDate).html").path
        let exists = FileManager.default.fileExists(atPath: path)
        // A page with unsaved edits is shown as it is, never reloaded (F14).
        receipt.isEditing { [weak self] editing in
            guard let self = self else { return }
            if editing { return }
            if exists {
                self.receipt.load(path: path, animate: first, quick: animate && !first)
                if first { self.defaults.set(Day.today(), forKey: "lastPrintDay") }   // only once it really played
            }
            else { self.rebuild(self.curDate, force: true, animate: animate) }
        }
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

    private func showWeekly(force: Bool, offerUndo: Bool = false) {
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
            let bak = self.weekStart.map { FileManager.default.fileExists(atPath: Paths.cacheFile("weekly-\($0).json.bak").path) } ?? false
            if offerUndo && bak { self.detail.afterLoad = "window.showUndo&&showUndo('Re-summarized.',function(){send({action:'undoRegen'})})" }
            self.detail.load(path: t.rest, animate: !offerUndo)
            self.detail.show(at: self.detailFrame())
        }
    }

    // MARK: engine

    private func rebuild(_ date: String, force: Bool = false, animate: Bool = false,
                         repolish: Bool = false, cacheOnly: Bool = false) {
        var args = ["--date", date]
        if repolish { args.append("--repolish") }
        // EventKit is synchronous and can be slow with many calendars: read it off
        // the main thread, then run the engine (F26).
        DispatchQueue.global(qos: .utility).async {
            CalendarBridge.shared.export(date: date)
            DispatchQueue.main.async { self.runEngine(args, date: date, force: force, animate: animate, repolish: repolish, cacheOnly: cacheOnly) }
        }
    }

    private func runEngine(_ args: [String], date: String, force: Bool, animate: Bool, repolish: Bool, cacheOnly: Bool) {
        Engine.run(args) { [weak self] r in
            guard let self = self else { return }
            let wasManual = self.manualRefresh, wasDiscard = self.discarding
            if force { self.manualRefresh = false; self.discarding = false }
            guard r.code == 0, let t = r.tagged else {
                Log.write("extract failed (\(r.code)): \(r.err.suffix(600))")
                if self.shown && !cacheOnly {        // say it on the receipt (F11), with a Retry
                    self.receipt.js("window.setStatus&&setStatus('Couldn’t refresh at \(Self.hm()). ',true)")
                }
                return
            }
            Counts.mark("firstReceipt")
            if cacheOnly || !(force || t.tag != "UNCHANGED") { return }
            // A slow earlier run must not replace the day the person has moved to.
            guard date == self.curDate else { return }
            if !force {
                // Never reload under someone mid-edit (F14): unsaved lines would vanish.
                self.receipt.isEditing { editing in
                    if editing { Log.write("refresh skipped: editing"); return }
                    self.receipt.load(path: t.rest, animate: animate)
                }
                return
            }
            // Offer Undo only when there is something to go back to and the summary changed.
            let hasBackup = FileManager.default.fileExists(atPath: Paths.cacheFile("polish-\(date).json.bak").path)
            if repolish && hasBackup && t.tag == "CHANGED" {
                self.receipt.afterLoad = "window.showUndo&&showUndo('Re-summarized.',function(){send({action:'undoRegen'})})"
            } else if repolish && t.tag != "CHANGED" {
                self.receipt.afterLoad = "window.toast&&toast('Same summary as before')"
            } else if wasDiscard {
                self.receipt.afterLoad = "window.toast&&toast('Edits discarded')"
            } else if wasManual {
                self.receipt.afterLoad = "window.toast&&toast('Up to date \(Self.hm())')"
            }
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
        guard let fire = Calendar.current.nextDate(after: Date(),
                matching: DateComponents(hour: ReminderSettings.hour, minute: ReminderSettings.minute, second: 0),
                matchingPolicy: .nextTime) else { return }
        reminderTimer = Timer(fire: fire, interval: 0, repeats: false) { [weak self] _ in
            guard let self = self else { return }
            let wd = Calendar.current.component(.weekday, from: Date())   // 1 = Sun, 7 = Sat
            let late = Date().timeIntervalSince(fire) > 1800              // the Mac slept through it
            if ReminderSettings.days.contains(wd) && !late { self.remindIfNeeded() }
            self.scheduleReminder()
        }
        RunLoop.main.add(reminderTimer!, forMode: .common)
    }

    private func notify(after seconds: TimeInterval = 0) {
        let center = UNUserNotificationCenter.current()
        // Act from the banner (F18): copy the update without opening anything, open
        // the receipt, or be reminded again in 30 minutes.
        let copy = UNNotificationAction(identifier: "copy", title: "Copy update", options: [])
        let open = UNNotificationAction(identifier: "open", title: "Open", options: [.foreground])
        let snooze = UNNotificationAction(identifier: "snooze", title: "In 30 minutes", options: [])
        center.setNotificationCategories([UNNotificationCategory(identifier: "eod", actions: [copy, open, snooze],
                                                                 intentIdentifiers: [], options: [])])
        center.requestAuthorization(options: [.alert, .sound]) { ok, _ in
            guard ok else { return }
            let c = UNMutableNotificationContent()
            c.title = "EOD"; c.body = "Your update for today is ready."; c.categoryIdentifier = "eod"
            let trigger = seconds > 0 ? UNTimeIntervalNotificationTrigger(timeInterval: seconds, repeats: false) : nil
            center.add(UNNotificationRequest(identifier: "eod-reminder", content: c, trigger: trigger))
        }
    }

    /// The update as text, straight to the clipboard: no window needed (B2, F18).
    @objc func copyTodayUpdate() {
        Engine.run(["--date", Day.today(), "--standup"]) { [weak self] r in
            guard let self = self else { return }
            if r.code == 0, !r.out.isEmpty {
                self.copy(r.out); self.markShared()
                self.flash("Update copied")
            } else { self.flash("No work recorded today yet") }
        }
    }

    /// A one-line confirmation in the menu-bar button's tooltip area.
    private var flashItem: DispatchWorkItem?
    private func flash(_ text: String) {
        flashItem?.cancel()
        status.button?.title = " " + text
        status.length = NSStatusItem.variableLength
        let w = DispatchWorkItem { [weak self] in
            self?.status.button?.title = ""; self?.status.length = NSStatusItem.squareLength
        }
        flashItem = w
        DispatchQueue.main.asyncAfter(deadline: .now() + 1.6, execute: w)
    }

    func userNotificationCenter(_ c: UNUserNotificationCenter, willPresent n: UNNotification,
                                withCompletionHandler done: @escaping (UNNotificationPresentationOptions) -> Void) {
        done([.banner, .sound])
    }

    func userNotificationCenter(_ c: UNUserNotificationCenter, didReceive r: UNNotificationResponse,
                                withCompletionHandler done: @escaping () -> Void) {
        DispatchQueue.main.async {
            switch r.actionIdentifier {
            case "copy": self.copyTodayUpdate()
            case "snooze":
                // Re-checked when it fires: no reminder if you copied or sent meanwhile.
                self.snoozeTimer?.invalidate()
                self.snoozeTimer = Timer.scheduledTimer(withTimeInterval: 1800, repeats: false) { [weak app = self] _ in app?.remindIfNeeded() }
            default: self.curDate = Day.today(); self.show(animate: true)
            }
            done()
        }
    }

    // MARK: messages from the page

    private func onReceiptMessage(_ b: [String: Any]) {
        switch b["action"] as? String ?? "" {
        case "copy":
            copy(b["text"] as? String ?? "")
            if ["updText", "workText"].contains(b["what"] as? String ?? "") { markShared() }
        case "dragStart": receipt.startDrag()
        case "hide": hide()
        case "full": showFull()
        case "share": shareImage()
        case "refresh": manualRefresh = true; rebuild(curDate, force: true)
        case "discard": discarding = true; rebuild(curDate, force: true)
        case "regen":
            backup("polish-\(curDate).json")
            rebuild(curDate, force: true, repolish: true)
        case "undoRegen":
            if restore("polish-\(curDate).json") { rebuild(curDate, force: true) }
            else { receipt.js("window.toast&&toast('Nothing to undo')") }
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
        case "regen":
            if detailMode == "weekly", let ws = weekStart {
                backup("weekly-\(ws).json"); showWeekly(force: true, offerUndo: true)
            }
        case "undoRegen":
            if detailMode == "weekly", let ws = weekStart {
                if restore("weekly-\(ws).json") { showWeekly(force: false) } else { detail.js("window.toast&&toast('Nothing to undo')") }
            }
        case "hide": hideDetail()
        default: break
        }
    }

    /// Keep the previous summary so a re-summarize can be undone (F15).
    private func backup(_ file: String) {
        let f = Paths.cacheFile(file), b = Paths.cacheFile(file + ".bak")
        try? FileManager.default.removeItem(at: b)
        try? FileManager.default.copyItem(at: f, to: b)
    }

    private func restore(_ file: String) -> Bool {
        let f = Paths.cacheFile(file), b = Paths.cacheFile(file + ".bak")
        guard FileManager.default.fileExists(atPath: b.path) else { return false }
        _ = try? FileManager.default.replaceItemAt(f, withItemAt: b)
        return true
    }

    /// The update left the Mac today (copied or sent): the reminder stays quiet.
    private func markShared() {
        defaults.set(Day.today(), forKey: "sharedOn"); Counts.mark("firstCopy")
        snoozeTimer?.invalidate(); snoozeTimer = nil
        UNUserNotificationCenter.current().removePendingNotificationRequests(withIdentifiers: ["eod-reminder"])
    }
    private var snoozeTimer: Timer?

    /// Build today fresh, then remind only if there is work and it hasn't left the Mac yet.
    private func remindIfNeeded() {
        guard defaults.string(forKey: "sharedOn") != Day.today() else { return }
        Engine.run(["--date", Day.today()]) { [weak self] _ in
            Engine.run(["--date", Day.today(), "--standup"]) { r in
                if r.code == 0 && !r.out.isEmpty { self?.notify() }
            }
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
                self.markShared()
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

