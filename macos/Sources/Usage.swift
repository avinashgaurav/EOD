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
        let anyInput = CGEventType(rawValue: ~0)!
        if CGEventSource.secondsSinceLastEventType(.combinedSessionState, eventType: anyInput) > idleLimit { return }
        guard let name = NSWorkspace.shared.frontmostApplication?.localizedName, !name.isEmpty else { return }
        secs[name, default: 0] += Int(poll)
    }
}

/// ⌥⌃⌘W, registered with Carbon so it needs no Accessibility permission.
final class HotKey {
    private var ref: EventHotKeyRef?
    private static var action: (() -> Void)?

    init(action: @escaping () -> Void) {
        HotKey.action = action
        var spec = EventTypeSpec(eventClass: OSType(kEventClassKeyboard), eventKind: UInt32(kEventHotKeyPressed))
        InstallEventHandler(GetApplicationEventTarget(), { _, _, _ in
            DispatchQueue.main.async { HotKey.action?() }
            return noErr
        }, 1, &spec, nil, nil)
        let id = EventHotKeyID(signature: OSType(0x454F4420), id: 1)   // "EOD "
        RegisterEventHotKey(UInt32(kVK_ANSI_W), UInt32(cmdKey | optionKey | controlKey), id,
                            GetApplicationEventTarget(), 0, &ref)
    }
}
