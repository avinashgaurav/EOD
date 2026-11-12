import AppKit

/// The app side of the audit's features: morning standup (B1), brag doc (B4),
/// search and ask (B5), plan (B6), the week share card (B7) and the history
/// shelf (B14). The engine does the work; these are the windows and menus.
extension AppDelegate {

    @objc func copyMorningStandup() {
        Engine.run(["--date", Day.today(), "--morning"]) { r in
            if r.code == 0, !r.out.isEmpty {
                NSPasteboard.general.clearContents(); NSPasteboard.general.setString(r.out, forType: .string)
                self.flashMessage("Standup copied")
            } else { self.flashMessage("Nothing for a standup yet") }
        }
    }

    @objc func planToday() {
        NSApp.activate(ignoringOtherApps: true)
        let a = NSAlert()
        a.messageText = "What do you want to get done today?"
        a.informativeText = "One line each. Tonight's receipt marks what got done."
        let scroll = NSTextView.scrollableTextView()
        scroll.frame = NSRect(x: 0, y: 0, width: 360, height: 120)
        let tv = scroll.documentView as! NSTextView
        tv.font = .systemFont(ofSize: 13); tv.isRichText = false
        if let old = try? String(contentsOf: Paths.cacheFile("plan-\(Day.today()).txt"), encoding: .utf8) { tv.string = old }
        a.accessoryView = scroll
        a.addButton(withTitle: "Save plan"); a.addButton(withTitle: "Cancel")
        a.window.initialFirstResponder = tv
        guard a.runModal() == .alertFirstButtonReturn else { return }
        let f = Paths.cacheFile(".plan-\(UUID().uuidString).txt")
        guard (try? tv.string.write(to: f, atomically: true, encoding: .utf8)) != nil else { return }
        Engine.run(["--date", Day.today(), "--plan-file", f.path]) { _ in
            try? FileManager.default.removeItem(at: f)
            self.refreshFromSettings()
        }
    }

    @objc func searchHistory() {
        NSApp.activate(ignoringOtherApps: true)
        let a = NSAlert()
        a.messageText = "Search your work history"
        a.informativeText = "Words to find, or a question. Search stays on this Mac; Ask uses your AI tidy-up choice."
        let f = NSTextField(frame: NSRect(x: 0, y: 0, width: 320, height: 24))
        f.placeholderString = "webhook retries, or: when did I fix the coupon bug?"
        a.accessoryView = f
        a.addButton(withTitle: "Search"); a.addButton(withTitle: "Ask"); a.addButton(withTitle: "Cancel")
        a.window.initialFirstResponder = f
        let choice = a.runModal()
        let q = f.stringValue.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !q.isEmpty, choice != .alertThirdButtonReturn else { return }
        let ask = choice == .alertSecondButtonReturn
        Engine.run(["--date", Day.today(), ask ? "--ask" : "--search", q], timeout: 180) { r in
            let body = r.out.isEmpty ? "Nothing in your receipts matches that yet." : r.out
            _ = TextWindow(title: ask ? "Answer" : "Search: \(q)", body: body.replacingOccurrences(of: "\t", with: "  "),
                           note: ask ? "Built only from your own receipts." : "Newest first. Every line is from a day's receipt on this Mac.",
                           editable: false)
        }
    }

    @objc func bragDoc(_ sender: NSMenuItem) {
        let end = Day.today()
        guard let start = Day.shift(end, by: -sender.tag) else { return }
        flashMessage("Writing your summary…")
        Engine.run(["--date", end, "--brag", start, end], timeout: 300) { r in
            guard r.code == 0, let t = r.tagged, t.tag == "BRAG" else {
                self.flashMessage("No updates in that period"); return
            }
            let dl = FileManager.default.urls(for: .downloadsDirectory, in: .userDomainMask)[0]
            let dest = dl.appendingPathComponent((t.rest as NSString).lastPathComponent)
            try? FileManager.default.removeItem(at: dest)
            if (try? FileManager.default.copyItem(at: URL(fileURLWithPath: t.rest), to: dest)) != nil {
                NSWorkspace.shared.activateFileViewerSelecting([dest])
            }
        }
    }

    @objc func showHistory() { openHistory(month: String(Day.today().prefix(7))) }

    func openHistory(month: String) {
        Engine.run(["--date", Day.today(), "--history", month]) { r in
            guard r.code == 0, let t = r.tagged, t.tag == "HISTORY" else { return }
            self.showDetailPage(t.rest, mode: "history")
        }
    }

    func shareWeek() {
        Engine.run(["--date", Day.today(), "--share-week"], timeout: 120) { r in
            guard r.code == 0, let t = r.tagged, t.tag == "SHARE", let img = NSImage(contentsOfFile: t.rest) else {
                self.flashMessage("No week image"); return
            }
            NSPasteboard.general.clearContents(); NSPasteboard.general.writeObjects([img])
            self.flashMessage("Week image copied")
        }
    }

    /// Days the update was copied or sent, for the history shelf (B14).
    func recordSentDay() {
        let f = Paths.cacheFile("sent-days.json")
        var days = (try? JSONSerialization.jsonObject(with: Data(contentsOf: f)) as? [String]) ?? []
        if !days.contains(Day.today()) { days.append(Day.today()) }
        if let d = try? JSONSerialization.data(withJSONObject: Array(days.suffix(800))) { try? d.write(to: f, options: .atomic) }
    }
}
