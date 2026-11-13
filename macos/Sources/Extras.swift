import AppKit

/// Local usage counts (audit F20). They never leave the Mac: there is no server.
/// The menu shows them and copies them, so a person can paste them into
/// feedback if they want to.
enum Counts {
    private static let d = UserDefaults.standard

    static func mark(_ key: String) {
        if d.string(forKey: "count." + key) == nil { d.set(ISO8601DateFormatter().string(from: Date()), forKey: "count." + key) }
    }

    static func activeToday() {
        var days = Set(d.stringArray(forKey: "count.activeDays") ?? [])
        days.insert(Day.today())
        // suffix() is an ArraySlice, which UserDefaults rejects with an exception that
        // aborted show() (and every way of opening the receipt). Store a real Array.
        d.set(Array(Array(days).sorted().suffix(400)), forKey: "count.activeDays")
    }

    static func summary() -> String {
        let days = d.stringArray(forKey: "count.activeDays") ?? []
        func v(_ k: String) -> String { d.string(forKey: "count." + k).map { String($0.prefix(10)) } ?? "not yet" }
        let version = Bundle.main.object(forInfoDictionaryKey: "CFBundleShortVersionString") as? String ?? "?"
        return """
        EOD \(version) on macOS \(ProcessInfo.processInfo.operatingSystemVersionString)
        Installed: \(v("installed"))
        First receipt: \(v("firstReceipt"))
        First copy or send: \(v("firstCopy"))
        Days used: \(days.count) (last 7 days: \(days.filter { $0 >= (Day.shift(Day.today(), by: -6) ?? "") }.count))
        """
    }
}

/// Reminder time and days (audit F17), chosen in a small sheet.
enum ReminderSettings {
    static let d = UserDefaults.standard
    static var hour: Int { d.object(forKey: "reminderHour") as? Int ?? 18 }
    static var minute: Int { d.object(forKey: "reminderMinute") as? Int ?? 30 }
    /// Calendar weekdays, 1 = Sunday ... 7 = Saturday. Default Monday to Friday.
    static var days: Set<Int> { Set(d.array(forKey: "reminderDays") as? [Int] ?? [2, 3, 4, 5, 6]) }

    static func edit(onChange: @escaping () -> Void) {
        NSApp.activate(ignoringOtherApps: true)
        let a = NSAlert()
        a.messageText = "End-of-day reminder"
        a.informativeText = "EOD reminds you once, when your update is ready. It stays quiet on days with no work, or after you've already copied or sent the update."
        let picker = NSDatePicker()
        picker.datePickerElements = .hourMinute; picker.datePickerStyle = .textFieldAndStepper
        var c = DateComponents(); c.hour = hour; c.minute = minute
        picker.dateValue = Calendar.current.date(from: c) ?? Date()
        let names = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]
        let boxes = names.enumerated().map { i, n -> NSButton in
            let b = NSButton(checkboxWithTitle: n, target: nil, action: nil)
            b.state = days.contains(i + 1) ? .on : .off; return b
        }
        let row = NSStackView(views: boxes); row.spacing = 8
        let stack = NSStackView(views: [picker, row]); stack.orientation = .vertical; stack.alignment = .leading; stack.spacing = 10
        stack.frame = NSRect(x: 0, y: 0, width: 420, height: 64)
        a.accessoryView = stack
        a.addButton(withTitle: "Save"); a.addButton(withTitle: "Cancel")
        guard a.runModal() == .alertFirstButtonReturn else { return }
        if !boxes.contains(where: { $0.state == .on }) {
            let w = NSAlert(); w.messageText = "Pick at least one day"
            w.informativeText = "To stop the reminder, turn off 'End-of-day reminder' in the menu instead."
            w.runModal(); return
        }
        let t = Calendar.current.dateComponents([.hour, .minute], from: picker.dateValue)
        d.set(t.hour ?? 18, forKey: "reminderHour"); d.set(t.minute ?? 30, forKey: "reminderMinute")
        d.set(boxes.enumerated().compactMap { $1.state == .on ? $0 + 1 : nil }, forKey: "reminderDays")
        onChange()
    }

    static var label: String { String(format: "%02d:%02d", hour, minute) }
}

/// Manual update check against the latest GitHub release (audit F21). Nothing is
/// checked in the background: the request happens only when the person asks.
enum Updates {
    static func check(done: @escaping () -> Void = {}) {
        guard let url = URL(string: "https://api.github.com/repos/avinashgaurav/EOD/releases/latest") else { return }
        var req = URLRequest(url: url); req.setValue("application/vnd.github+json", forHTTPHeaderField: "Accept")
        req.timeoutInterval = 15
        URLSession.shared.dataTask(with: req) { data, _, err in
            let tag = (data.flatMap { try? JSONSerialization.jsonObject(with: $0) as? [String: Any] })?["tag_name"] as? String
            DispatchQueue.main.async { show(latest: tag, error: err); done() }
        }.resume()
    }

    private static func newer(_ a: String, than b: String) -> Bool {
        let x = a.split(separator: ".").map { Int($0) ?? 0 }, y = b.split(separator: ".").map { Int($0) ?? 0 }
        for i in 0..<max(x.count, y.count) {
            let p = i < x.count ? x[i] : 0, q = i < y.count ? y[i] : 0
            if p != q { return p > q }
        }
        return false
    }

    private static func show(latest: String?, error: Error?) {
        NSApp.activate(ignoringOtherApps: true)
        let current = Bundle.main.object(forInfoDictionaryKey: "CFBundleShortVersionString") as? String ?? "0"
        let a = NSAlert()
        guard let tag = latest else {
            a.messageText = "Couldn't check for updates"
            a.informativeText = "GitHub didn't answer. Check your connection and try again."
            a.runModal(); return
        }
        let v = tag.hasPrefix("v") ? String(tag.dropFirst()) : tag
        if newer(v, than: current) {
            a.messageText = "EOD \(v) is available"
            a.informativeText = "You have \(current). Run the install command again in Terminal to update; your data and settings stay."
            a.addButton(withTitle: "Copy install command"); a.addButton(withTitle: "Later")
            if a.runModal() == .alertFirstButtonReturn {
                NSPasteboard.general.clearContents()
                NSPasteboard.general.setString("curl -fsSL https://eodreceipt.vercel.app/install.sh | bash", forType: .string)
            }
        } else {
            a.messageText = "EOD is up to date"; a.informativeText = "You have the latest version, \(current)."
            a.runModal()
        }
    }
}
