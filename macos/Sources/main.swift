import AppKit

let app = NSApplication.shared
let delegate = AppDelegate()
app.delegate = delegate
app.setActivationPolicy(.accessory)

// An accessory app still needs an Edit menu, or ⌘C, ⌘V, ⌘X, ⌘A and ⌘Z do nothing
// while you edit a line on the receipt. It is never shown.
let mainMenu = NSMenu()
let editItem = NSMenuItem(); mainMenu.addItem(editItem)
let edit = NSMenu(title: "Edit"); editItem.submenu = edit
edit.addItem(withTitle: "Undo", action: Selector(("undo:")), keyEquivalent: "z")
let redo = edit.addItem(withTitle: "Redo", action: Selector(("redo:")), keyEquivalent: "z")
redo.keyEquivalentModifierMask = [.command, .shift]
edit.addItem(.separator())
edit.addItem(withTitle: "Cut", action: #selector(NSText.cut(_:)), keyEquivalent: "x")
edit.addItem(withTitle: "Copy", action: #selector(NSText.copy(_:)), keyEquivalent: "c")
edit.addItem(withTitle: "Paste", action: #selector(NSText.paste(_:)), keyEquivalent: "v")
edit.addItem(withTitle: "Select All", action: #selector(NSText.selectAll(_:)), keyEquivalent: "a")
app.mainMenu = mainMenu

app.run()
