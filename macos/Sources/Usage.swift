import AppKit
import Carbon.HIToolbox

/// SCREEN TIME: samples the frontmost app every 15 s and adds the seconds to
/// cache/usage-YYYY-MM-DD.json ({"App": secs}), the same file and format the
/// Hammerspoon widget wrote and extract.py reads. Idle time (no input for 2 min)
/// is not counted. Needs no permission: the frontmost app's name is public.
final class UsageTracker {
    private let poll: TimeInterval = 15, idleLimit: TimeInterval = 120
    private var date: String?
    private var secs: [String: Int] = [:]
    private var sampleTimer: Timer?, flushTimer: Timer?

    func start() {
        date = Day.today(); secs = load(date!)
        sampleTimer = Timer.scheduledTimer(withTimeInterval: poll, repeats: true) { [weak self] _ in self?.sample() }
        flushTimer = Timer.scheduledTimer(withTimeInterval: 60, repeats: true) { [weak self] _ in self?.flush() }
    }

    func stop() { sampleTimer?.invalidate(); flushTimer?.invalidate(); flush() }

    private func url(_ d: String) -> URL { Paths.cacheFile("usage-\(d).json") }

    private func load(_ d: String) -> [String: Int] {
        guard let data = try? Data(contentsOf: url(d)),
              let obj = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else { return [:] }
        return obj.compactMapValues { ($0 as? NSNumber)?.intValue }
    }

    func flush() {
        guard let d = date, let data = try? JSONSerialization.data(withJSONObject: secs) else { return }
        try? data.write(to: url(d), options: .atomic)
    }

    private func sample() {
        let d = Day.today()
        if d != date { flush(); date = d; secs = load(d) }      // crossed midnight
        if SourceSwitch.off.contains("apps") { return }          // switched off: not even sampled
        let anyInput = CGEventType(rawValue: ~0)!
        if CGEventSource.secondsSinceLastEventType(.combinedSessionState, eventType: anyInput) > idleLimit { return }
        guard let name = NSWorkspace.shared.frontmostApplication?.localizedName, !name.isEmpty else { return }
        secs[name, default: 0] += Int(poll)
    }
}

/// Global shortcuts, registered with Carbon so they need no Accessibility
/// permission: ⌥⌃⌘W shows or hides the receipt, ⌥⌃⌘C copies today's update.
final class HotKey {
    private var ref: EventHotKeyRef?
    private(set) var ok = false
    func unregister() { if let r = ref { UnregisterEventHotKey(r); ref = nil } }
    private static var actions: [UInt32: () -> Void] = [:]
    private static var installed = false

    init(key: Int, id: UInt32, name: String, action: @escaping () -> Void) {
        HotKey.actions[id] = action
        if !HotKey.installed {
            HotKey.installed = true
            var spec = EventTypeSpec(eventClass: OSType(kEventClassKeyboard), eventKind: UInt32(kEventHotKeyPressed))
            InstallEventHandler(GetApplicationEventTarget(), { _, event, _ in
                var hk = EventHotKeyID()
                let st = GetEventParameter(event, EventParamName(kEventParamDirectObject), EventParamType(typeEventHotKeyID),
                                           nil, MemoryLayout<EventHotKeyID>.size, nil, &hk)
                guard st == noErr, hk.signature == OSType(0x454F4420) else { return OSStatus(eventNotHandledErr) }
                let id = hk.id
                DispatchQueue.main.async { HotKey.actions[id]?() }
                return noErr
            }, 1, &spec, nil, nil)
        }
        let hid = EventHotKeyID(signature: OSType(0x454F4420), id: id)   // "EOD "
        let st = RegisterEventHotKey(UInt32(key), UInt32(cmdKey | optionKey | controlKey), hid,
                                     GetApplicationEventTarget(), 0, &ref)
        ok = (st == noErr)
        if !ok { Log.write("\(name) is taken by another app (status \(st)); use the menu-bar icon") }
    }
}
