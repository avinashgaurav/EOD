import AppKit
import WebKit

/// A borderless, transparent, floating panel that shows one of the engine's HTML
/// pages: only the paper is drawn, the desktop shows around it. It can take
/// keyboard focus (to edit work lines) without becoming the active app's window.
final class ReceiptPanel: NSPanel {
    override var canBecomeKey: Bool { true }
    override var canBecomeMain: Bool { false }
}

final class WebPanel: NSObject, WKScriptMessageHandler, WKNavigationDelegate {
    let panel: ReceiptPanel
    let web: WKWebView
    var onMessage: (([String: Any]) -> Void)?
    private var loadN = 0
    private var dragMonitor: Any?
    private var dragOffset = NSPoint.zero
    private var pendingHide: DispatchWorkItem?
    /// Where the person last left the panel; nil until they move it.
    var savedFrame: NSRect?

    init(frame: NSRect) {
        panel = ReceiptPanel(contentRect: frame, styleMask: [.borderless, .nonactivatingPanel],
                             backing: .buffered, defer: false)
        let cfg = WKWebViewConfiguration()
        let ucc = WKUserContentController()
        cfg.userContentController = ucc
        web = WKWebView(frame: NSRect(origin: .zero, size: frame.size), configuration: cfg)
        super.init()
        // The controller retains this handler: a cycle, acceptable because both
        // panels live as long as the app does.
        ucc.add(self, name: "eod")
        web.setValue(false, forKey: "drawsBackground")
        web.navigationDelegate = self
        web.autoresizingMask = [.width, .height]
        panel.isOpaque = false
        panel.backgroundColor = .clear
        panel.hasShadow = false                       // the paper draws its own shadow in CSS
        panel.level = .floating
        panel.collectionBehavior = [.canJoinAllSpaces, .stationary, .fullScreenAuxiliary]
        panel.hidesOnDeactivate = false
        panel.sharingType = .none                     // never shows up in Zoom, Meet or screen recordings
        panel.isReleasedWhenClosed = false
        panel.contentView = web
    }

    var isVisible: Bool { panel.isVisible }

    /// Load a file from the data folder. A changing ?n= forces a real reload, and
    /// #in plays the print-down animation (a fragment change alone would not reload).
    func load(path: String, animate: Bool) {
        loadN += 1
        var c = URLComponents()
        c.scheme = "file"; c.path = path
        c.queryItems = [URLQueryItem(name: "n", value: String(loadN))]
        if animate { c.fragment = "in" }
        guard let url = c.url else { return }
        web.loadFileURL(url, allowingReadAccessTo: Paths.support)
    }

    func js(_ s: String) { web.evaluateJavaScript(s, completionHandler: nil) }

    func show(at frame: NSRect) {
        pendingHide?.cancel(); pendingHide = nil       // a show beats a roll-up still in flight
        panel.setFrame(savedFrame ?? frame, display: true)
        panel.orderFrontRegardless()
    }

    /// Roll the paper up, then hide once the animation has played.
    func hide(animated: Bool = true) {
        guard panel.isVisible else { return }
        endDrag()
        pendingHide?.cancel()
        if animated {
            js("window.playOut&&playOut()")
            let w = DispatchWorkItem { [weak self] in self?.panel.orderOut(nil); self?.pendingHide = nil }
            pendingHide = w
            DispatchQueue.main.asyncAfter(deadline: .now() + 0.46, execute: w)
        } else { panel.orderOut(nil) }
    }

    /// Frameless window: follow the mouse from the masthead press until release.
    func startDrag() {
        let mouse = NSEvent.mouseLocation, f = panel.frame
        dragOffset = NSPoint(x: mouse.x - f.origin.x, y: mouse.y - f.origin.y)
        if let m = dragMonitor { NSEvent.removeMonitor(m) }
        dragMonitor = NSEvent.addLocalMonitorForEvents(matching: [.leftMouseDragged, .leftMouseUp]) { [weak self] e in
            guard let self = self else { return e }
            if e.type == .leftMouseUp {
                self.endDrag(); self.savedFrame = self.panel.frame
                return e
            }
            let p = NSEvent.mouseLocation
            self.panel.setFrameOrigin(NSPoint(x: p.x - self.dragOffset.x, y: p.y - self.dragOffset.y))
            return e
        }
    }

    private func endDrag() {
        if let m = dragMonitor { NSEvent.removeMonitor(m) }
        dragMonitor = nil
    }

    func userContentController(_ c: WKUserContentController, didReceive message: WKScriptMessage) {
        guard let body = message.body as? [String: Any] else { return }
        onMessage?(body)
    }

    /// Links in the receipt (a PR, a doc) open in the browser, never inside the panel.
    func webView(_ webView: WKWebView, decidePolicyFor action: WKNavigationAction,
                 decisionHandler: @escaping (WKNavigationActionPolicy) -> Void) {
        if let url = action.request.url, let scheme = url.scheme, scheme != "file", scheme != "about" {
            NSWorkspace.shared.open(url); decisionHandler(.cancel); return
        }
        decisionHandler(.allow)
    }
}
