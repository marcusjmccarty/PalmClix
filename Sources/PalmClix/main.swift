import AppKit
import Foundation

// An authentic, fixed-size 538×480 reconstruction of the source BMP interface.
// The camera artwork IS the window: no title bar, no frame, transparent around
// the squiggly body. Every former "Import Studio" option lives in the macOS
// menu bar (File / Edit / View / Go / Camera / Window).
// USB is handled by the external Python/libusb helper; this UI never sends
// destructive or undocumented commands itself.
private let W: CGFloat = 538
private let H: CGFloat = 480

private struct RetroButton {
    let name: String
    let x: CGFloat
    let y: CGFloat
    let w: CGFloat
    let h: CGFloat
    var rect: NSRect { NSRect(x: x, y: H-y-h, width: w, height: h) }
}
private let buttons: [RetroButton] = [
    .init(name: "About", x: 466, y: 134, w: 36, h: 37),
    .init(name: "Minimize", x: 36, y: 170, w: 36, h: 37),
    .init(name: "Exit", x: 466, y: 176, w: 36, h: 37),
    .init(name: "Download", x: 173, y: 393, w: 42, h: 36),
    .init(name: "Save", x: 269, y: 393, w: 42, h: 36),
    .init(name: "Twain", x: 223, y: 393, w: 42, h: 36),
    .init(name: "SelectAll", x: 319, y: 399, w: 26, h: 24),
    .init(name: "ImageAdjust", x: 347, y: 399, w: 26, h: 24),
    .init(name: "PreviousPage", x: 61, y: 407, w: 87, h: 32),
    .init(name: "NextPage", x: 391, y: 407, w: 87, h: 32)
]

/// Borderless windows refuse key/main status by default, which would break
/// hover states and keyboard shortcuts. This one accepts both.
final class ShapedWindow: NSWindow {
    override var canBecomeKey: Bool { true }
    override var canBecomeMain: Bool { true }
}

final class CameraCanvas: NSView {
    var status = "Ready — connect PalmClix" { didSet { needsDisplay = true } }
    var progress = "Download →" { didSet { needsDisplay = true } }
    /// 0…1 fill of the original progress bar artwork.
    var fraction: Double = 0 { didSet { needsDisplay = true } }
    var photos: [URL] = [] { didSet { thumbnailCache.removeAll(); needsDisplay = true } }
    var selected: Set<Int> = [] { didSet { needsDisplay = true } }
    var page = 0 { didSet { needsDisplay = true } }
    var busy = false { didSet { needsDisplay = true } }
    var onButton: ((String) -> Void)?
    var onOpenPhoto: ((Int) -> Void)?
    private var hovered: String? { didSet { needsDisplay = true } }
    private var pressed: String? { didSet { needsDisplay = true } }
    private var cache: [String: NSImage] = [:]
    private var thumbnailCache: [URL: NSImage] = [:]
    override var isFlipped: Bool { false }
    override var isOpaque: Bool { false }
    override func acceptsFirstMouse(for event: NSEvent?) -> Bool { true }

    private func image(_ name: String) -> NSImage? {
        if let cached = cache[name] { return cached }
        guard let url = Bundle.module.url(forResource: name, withExtension: "png", subdirectory: "Assets"),
              let pic = NSImage(contentsOf: url) else { return nil }
        cache[name] = pic
        return pic
    }
    private func thumbnail(for url: URL) -> NSImage? {
        if let cached = thumbnailCache[url] { return cached }
        guard let picture = NSImage(contentsOf: url) else { return nil }
        thumbnailCache[url] = picture
        return picture
    }
    private func drawAsset(_ name: String, _ r: NSRect) {
        image(name)?.draw(in: r, from: .zero, operation: .sourceOver, fraction: 1)
    }
    private func label(_ str: String, x: CGFloat, top: CGFloat, width: CGFloat, size: CGFloat = 10) {
        let para = NSMutableParagraphStyle()
        para.alignment = .center
        para.lineBreakMode = .byTruncatingMiddle
        let attrs: [NSAttributedString.Key: Any] = [
            .font: NSFont.monospacedSystemFont(ofSize: size, weight: .bold),
            .foregroundColor: NSColor.white,
            .paragraphStyle: para,
            .shadow: { let s = NSShadow(); s.shadowColor = NSColor.black; s.shadowBlurRadius = 2; return s }()
        ]
        (str as NSString).draw(in: NSRect(x: x, y: H-top-20, width: width, height: 20), withAttributes: attrs)
    }
    private func cellRect(_ cell: Int) -> NSRect {
        let column = cell % 4
        let row = cell / 4
        let x = 95 + CGFloat(column) * 89.5
        let top = 122 + CGFloat(row) * 77
        return NSRect(x: x, y: H-top-58, width: 77, height: 58)
    }
    private func photoIndex(at point: NSPoint) -> Int? {
        for cell in 0..<12 {
            if cellRect(cell).contains(point) {
                let index = page*12 + cell
                return index < photos.count ? index : nil
            }
        }
        return nil
    }
    private func isGalleryCell(_ point: NSPoint) -> Bool {
        (0..<12).contains { cellRect($0).contains(point) }
    }
    override func draw(_ dirtyRect: NSRect) {
        NSColor.clear.set()
        bounds.fill()
        // Transparent cut-out of the camera body; falls back to the original
        // rectangular artwork if the shaped asset is ever missing.
        if image("MainShaped") != nil { drawAsset("MainShaped", bounds) } else { drawAsset("Main", bounds) }
        for cell in 0..<12 {
            let r = cellRect(cell)
            let index = page*12 + cell
            drawAsset(index < photos.count && selected.contains(index) ? "ImageFrame2" : "ImageFrame1", r)
            if index < photos.count, let thumb = thumbnail(for: photos[index]) {
                // ImageFrame assets have opaque centers: draw the photograph *over*
                // the inset center, keeping the outer 3-pixel original frame.
                thumb.draw(in: r.insetBy(dx: 4, dy: 4), from: .zero, operation: .sourceOver, fraction: 1)
            }
        }
        for b in buttons {
            let variant = busy && b.name == "Download" ? 4 : (pressed == b.name ? 3 : (hovered == b.name ? 2 : 1))
            drawAsset("\(b.name)\(variant)", b.rect)
        }
        // Original progress artwork: Progress2 = empty trough, Progress1 = lit bar.
        let bar = NSRect(x: 192, y: H-365-22, width: 144, height: 22)
        drawAsset("Progress2", bar)
        let fill = max(0, min(1, fraction))
        if fill > 0, let lit = image("Progress1") {
            let w = bar.width * CGFloat(fill)
            let src = NSRect(x: 0, y: 0, width: lit.size.width * CGFloat(fill), height: lit.size.height)
            lit.draw(in: NSRect(x: bar.minX, y: bar.minY, width: w, height: bar.height),
                     from: src, operation: .sourceOver, fraction: 1)
        }
        label("\(selected.count) selected", x: 230, top: 444, width: 119)
        label("Page \(photos.isEmpty ? 0 : page+1) / \(photos.isEmpty ? 0 : (photos.count+11)/12)", x: 414, top: 444, width: 110)
        label(status, x: 95, top: 53, width: 350, size: 10)
        label(progress, x: 90, top: 348, width: 355, size: 10)
    }
    override func updateTrackingAreas() {
        super.updateTrackingAreas()
        for area in trackingAreas { removeTrackingArea(area) }
        addTrackingArea(NSTrackingArea(rect: bounds,
            options: [.mouseMoved, .mouseEnteredAndExited, .activeAlways],
            owner: self, userInfo: nil))
    }
    private func button(at p: NSPoint) -> RetroButton? { buttons.first { $0.rect.contains(p) } }
    override func mouseMoved(with e: NSEvent) {
        hovered = button(at: convert(e.locationInWindow, from: nil))?.name
        let tips: [String: String] = [
            "Download": "Import photographs directly from PalmClix (⌘D)",
            "Save": "Save selected photographs to a folder (⌘S)",
            "ImageAdjust": "Open selected photographs in Preview (⌘O)",
            "SelectAll": "Select or deselect every photograph (⌘A)",
            "PreviousPage": "Previous gallery page (⌘[)",
            "NextPage": "Next gallery page (⌘])",
            "Twain": "About the legacy Windows TWAIN feature",
            "About": "About PalmClix for Mac",
            "Minimize": "Minimize PalmClix (⌘M)", "Exit": "Quit PalmClix (⌘Q)"
        ]
        toolTip = hovered.flatMap { tips[$0] }
    }
    override func mouseExited(with e: NSEvent) { hovered = nil }
    override func mouseDown(with e: NSEvent) {
        let p = convert(e.locationInWindow, from: nil)
        pressed = button(at: p)?.name
        // With no title bar, grabbing the camera body (anything that isn't a
        // button or a photo slot) drags the whole window.
        if pressed == nil && !isGalleryCell(p) {
            window?.performDrag(with: e)
        }
    }
    override func mouseUp(with e: NSEvent) {
        let p = convert(e.locationInWindow, from: nil)
        if let name = pressed {
            if button(at: p)?.name == name { onButton?(name) }
        } else if let index = photoIndex(at: p) {
            if e.clickCount >= 2 {
                selected.insert(index)
                onOpenPhoto?(index)
                pressed = nil
                return
            }
            if selected.contains(index) { selected.remove(index) } else { selected.insert(index) }
        }
        pressed = nil
    }
}

final class AppController: NSObject, NSApplicationDelegate, NSMenuItemValidation {
    private var window: ShapedWindow!
    private var canvas: CameraCanvas!
    private var outputFolder: URL?
    private var runningProcess: Process?
    private var lastBackendError: String?
    private var currentFormat = UserDefaults.standard.string(forKey: "PalmClixFormat") ?? "png"
    private var currentProfile = UserDefaults.standard.string(forKey: "PalmClixColorProfile") ?? "dsc-matched"
    // Advanced forensic read: OFF by default and consumed by the next LIVE import only.
    private var probeNextLiveImport = false
    private var recoveryCandidateSaved = false
    private var importParent: URL?
    private var folderInfoItem: NSMenuItem?
    private var currentImportCount = 0
    private var lastLogLines: [String] = []
    private var priorPhotos: [URL] = []
    private var priorSelected: Set<Int> = []
    private var priorPage = 0
    private var excludedSlots = 0
    private var lastSuccessfulImport: URL?

    private var defaultImportParent: URL {
        FileManager.default.homeDirectoryForCurrentUser.appendingPathComponent("Pictures", isDirectory: true)
    }
    private var pageCount: Int { canvas.photos.isEmpty ? 0 : (canvas.photos.count + 11) / 12 }

    func applicationDidFinishLaunching(_ note: Notification) {
        canvas = CameraCanvas(frame: NSRect(x: 0, y: 0, width: W, height: H))
        canvas.onButton = { [weak self] in self?.handle($0) }
        canvas.onOpenPhoto = { [weak self] index in self?.openInPreview(indices: [index]) }
        window = ShapedWindow(contentRect: canvas.bounds,
                              styleMask: [.borderless, .miniaturizable],
                              backing: .buffered, defer: false)
        window.title = "PalmClix"
        window.isOpaque = false
        window.backgroundColor = .clear
        window.hasShadow = true
        window.isReleasedWhenClosed = false
        window.contentView = canvas
        window.center()
        window.makeKeyAndOrderFront(nil)
        window.invalidateShadow()
        NSApp.activate(ignoringOtherApps: true)
        if let savedPath = UserDefaults.standard.string(forKey: "PalmClixLastImport"),
           FileManager.default.fileExists(atPath: savedPath) {
            lastSuccessfulImport = URL(fileURLWithPath: savedPath, isDirectory: true)
            canvas.photos = photoURLs(in: lastSuccessfulImport!)
            if !canvas.photos.isEmpty {
                canvas.status = "Last import — \(canvas.photos.count) photos"
                canvas.progress = "Download for a new session • ⌘O: Preview"
                canvas.fraction = 1
            }
        }
        if let prior = UserDefaults.standard.string(forKey: "PalmClixImportParent") {
            importParent = URL(fileURLWithPath: prior, isDirectory: true)
        }
        installMenus()
        checkUSB(announce: false)
    }
    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool { true }
    func applicationShouldHandleReopen(_ sender: NSApplication, hasVisibleWindows flag: Bool) -> Bool {
        if window.isMiniaturized { window.deminiaturize(nil) }
        window.makeKeyAndOrderFront(nil)
        return true
    }
    func applicationShouldTerminate(_ sender: NSApplication) -> NSApplication.TerminateReply {
        if canvas.busy {
            alert("Transfer in progress", "Let the camera transfer finish before quitting. Abrupt interruption may leave the camera in an unknown state.")
            return .terminateCancel
        }
        return .terminateNow
    }

    // MARK: - Menu bar (replaces the old Import Studio window)

    private func item(_ title: String, _ action: Selector, _ key: String = "",
                      _ modifiers: NSEvent.ModifierFlags = [.command], tag: Int = 0) -> NSMenuItem {
        let i = NSMenuItem(title: title, action: action, keyEquivalent: key)
        i.keyEquivalentModifierMask = modifiers
        i.target = self
        i.tag = tag
        return i
    }
    private func addMenu(_ title: String, to bar: NSMenu, _ items: [NSMenuItem]) -> NSMenu {
        let holder = NSMenuItem()
        bar.addItem(holder)
        let menu = NSMenu(title: title)
        items.forEach { menu.addItem($0) }
        holder.submenu = menu
        return menu
    }
    private func installMenus() {
        let bar = NSMenu()

        // PalmClix (application menu)
        let hideOthers = NSMenuItem(title: "Hide Others", action: #selector(NSApplication.hideOtherApplications(_:)), keyEquivalent: "h")
        hideOthers.keyEquivalentModifierMask = [.command, .option]
        _ = addMenu("PalmClix", to: bar, [
            item("About PalmClix", #selector(showAbout(_:))),
            .separator(),
            NSMenuItem(title: "Hide PalmClix", action: #selector(NSApplication.hide(_:)), keyEquivalent: "h"),
            hideOthers,
            NSMenuItem(title: "Show All", action: #selector(NSApplication.unhideAllApplications(_:)), keyEquivalent: ""),
            .separator(),
            item("Quit PalmClix", #selector(quitApplication(_:)), "q")
        ])

        // File — importing, saving, opening
        let folderInfo = NSMenuItem(title: "", action: nil, keyEquivalent: "")
        folderInfo.isEnabled = false
        folderInfoItem = folderInfo
        _ = addMenu("File", to: bar, [
            item("Import from Camera…", #selector(importFromCamera(_:)), "d"),
            item("Import Offline Demo", #selector(importDemo(_:)), "d", [.command, .shift]),
            .separator(),
            item("Open in Preview", #selector(openPreviewAction(_:)), "o"),
            item("Save Selected Photos…", #selector(exportSelected(_:)), "s"),
            item("Show Latest Import in Finder", #selector(revealImport(_:)), "r", [.command, .shift]),
            .separator(),
            folderInfo,
            item("Change Import Folder…", #selector(chooseImportFolder(_:))),
            item("Reset Import Folder to Pictures", #selector(resetImportFolder(_:)))
        ])

        // Edit — selection and diagnostics
        _ = addMenu("Edit", to: bar, [
            item("Select All Photos", #selector(selectAllPhotos(_:)), "a"),
            item("Deselect All", #selector(deselectAllPhotos(_:)), "a", [.command, .shift]),
            .separator(),
            item("Copy Diagnostics", #selector(copyDiagnostics(_:)), "c", [.command, .option])
        ])

        // View — output format and color processing (were pop-ups in the Studio)
        let formatMenu = NSMenu(title: "Output Format")
        formatMenu.addItem(item("PNG · lossless", #selector(setFormat(_:)), tag: 0))
        formatMenu.addItem(item("JPEG · compact", #selector(setFormat(_:)), tag: 1))
        formatMenu.addItem(item("PNG + JPEG · both", #selector(setFormat(_:)), tag: 2))
        let formatHolder = NSMenuItem(title: "Output Format", action: nil, keyEquivalent: "")
        formatHolder.submenu = formatMenu
        let profileMenu = NSMenu(title: "Color Processing")
        profileMenu.addItem(item("DSC-matched · improved", #selector(setProfile(_:)), tag: 0))
        profileMenu.addItem(item("Original v0.4 · legacy", #selector(setProfile(_:)), tag: 1))
        let profileHolder = NSMenuItem(title: "Color Processing", action: nil, keyEquivalent: "")
        profileHolder.submenu = profileMenu
        _ = addMenu("View", to: bar, [
            formatHolder,
            profileHolder,
            .separator(),
            item("Show Diagnostics Log", #selector(showDiagnosticsLog(_:)), "l", [.command, .option])
        ])

        // Go — gallery pages
        _ = addMenu("Go", to: bar, [
            item("Previous Page", #selector(previousPage(_:)), "["),
            item("Next Page", #selector(nextPage(_:)), "]"),
            .separator(),
            item("First Page", #selector(firstPage(_:)), "[", [.command, .option]),
            item("Last Page", #selector(lastPage(_:)), "]", [.command, .option])
        ])

        // Camera — connection checks and the opt-in Recovery Lab
        _ = addMenu("Camera", to: bar, [
            item("Check Camera Connection", #selector(checkCameraAction(_:)), "k"),
            item("Verify USB Access…", #selector(verifyUSBAccessAction(_:))),
            .separator(),
            item("Recovery Lab: Experimental Extra Frame…", #selector(recoveryLabAction(_:))),
            .separator(),
            item("About TWAIN…", #selector(twainAction(_:)))
        ])

        // Window
        let windowMenu = addMenu("Window", to: bar, [
            item("Minimize", #selector(minimizeAction(_:)), "m"),
            item("Center on Screen", #selector(centerWindow(_:)))
        ])
        NSApp.mainMenu = bar
        NSApp.windowsMenu = windowMenu
        refreshMenus()
    }
    private func refreshMenus() {
        folderInfoItem?.title = "Saving Imports To: " + displayPath(importParent ?? defaultImportParent)
    }
    private func displayPath(_ url: URL) -> String {
        let home = FileManager.default.homeDirectoryForCurrentUser.path
        return url.path.hasPrefix(home) ? "~" + String(url.path.dropFirst(home.count)) : url.path
    }
    func validateMenuItem(_ menuItem: NSMenuItem) -> Bool {
        guard let action = menuItem.action else { return false }
        switch action {
        case #selector(setFormat(_:)):
            let current = currentFormat == "jpeg" ? 1 : (currentFormat == "both" ? 2 : 0)
            menuItem.state = menuItem.tag == current ? .on : .off
            return !canvas.busy
        case #selector(setProfile(_:)):
            let current = currentProfile == "legacy" ? 1 : 0
            menuItem.state = menuItem.tag == current ? .on : .off
            return !canvas.busy
        case #selector(importFromCamera(_:)), #selector(importDemo(_:)),
             #selector(chooseImportFolder(_:)), #selector(resetImportFolder(_:)),
             #selector(verifyUSBAccessAction(_:)), #selector(recoveryLabAction(_:)):
            return !canvas.busy
        case #selector(openPreviewAction(_:)), #selector(exportSelected(_:)),
             #selector(selectAllPhotos(_:)):
            return !canvas.busy && !canvas.photos.isEmpty
        case #selector(deselectAllPhotos(_:)):
            return !canvas.busy && !canvas.selected.isEmpty
        case #selector(previousPage(_:)), #selector(firstPage(_:)):
            return !canvas.busy && canvas.page > 0
        case #selector(nextPage(_:)), #selector(lastPage(_:)):
            return !canvas.busy && canvas.page < pageCount - 1
        case #selector(revealImport(_:)):
            return lastSuccessfulImport != nil
        case #selector(copyDiagnostics(_:)), #selector(showDiagnosticsLog(_:)):
            return !lastLogLines.isEmpty
        default:
            return true
        }
    }

    @objc private func showAbout(_ sender: Any?) { handle("About") }
    @objc private func twainAction(_ sender: Any?) { handle("Twain") }
    @objc private func verifyUSBAccessAction(_ sender: Any?) { verifyUSBAccess() }
    @objc private func recoveryLabAction(_ sender: Any?) { offerRecoveryProbe() }
    @objc private func quitApplication(_ sender: Any?) { NSApp.terminate(nil) }
    @objc private func importFromCamera(_ sender: Any?) { handle("Download") }
    @objc private func importDemo(_ sender: Any?) { startTransfer(demo: true) }
    @objc private func openPreviewAction(_ sender: Any?) { handle("ImageAdjust") }
    @objc private func exportSelected(_ sender: Any?) { handle("Save") }
    @objc private func selectAllPhotos(_ sender: Any?) {
        guard !canvas.busy else { return }
        canvas.selected = Set(canvas.photos.indices)
    }
    @objc private func deselectAllPhotos(_ sender: Any?) {
        guard !canvas.busy else { return }
        canvas.selected = []
    }
    @objc private func previousPage(_ sender: Any?) { handle("PreviousPage") }
    @objc private func nextPage(_ sender: Any?) { handle("NextPage") }
    @objc private func firstPage(_ sender: Any?) { if !canvas.busy { canvas.page = 0 } }
    @objc private func lastPage(_ sender: Any?) { if !canvas.busy { canvas.page = max(0, pageCount - 1) } }
    @objc private func minimizeAction(_ sender: Any?) { handle("Minimize") }
    @objc private func centerWindow(_ sender: Any?) { window.center() }
    @objc private func revealImport(_ sender: Any?) { openImportFolder() }
    @objc private func checkCameraAction(_ sender: Any?) { checkUSB(announce: true) }
    @objc private func setFormat(_ sender: NSMenuItem) {
        guard !canvas.busy else { return }
        currentFormat = sender.tag == 1 ? "jpeg" : (sender.tag == 2 ? "both" : "png")
        UserDefaults.standard.set(currentFormat, forKey: "PalmClixFormat")
        canvas.progress = "Output format: " + sender.title
    }
    @objc private func setProfile(_ sender: NSMenuItem) {
        guard !canvas.busy else { return }
        currentProfile = sender.tag == 1 ? "legacy" : "dsc-matched"
        UserDefaults.standard.set(currentProfile, forKey: "PalmClixColorProfile")
        canvas.progress = "Color processing: " + sender.title
    }
    @objc private func chooseImportFolder(_ sender: Any?) {
        guard !canvas.busy else { return }
        let panel = NSOpenPanel()
        panel.title = "Choose where PalmClix saves imported photos"
        panel.canChooseDirectories = true
        panel.canChooseFiles = false
        panel.canCreateDirectories = true
        panel.prompt = "Use This Folder"
        panel.directoryURL = importParent ?? defaultImportParent
        if panel.runModal() == .OK, let selected = panel.url {
            importParent = selected
            UserDefaults.standard.set(selected.path, forKey: "PalmClixImportParent")
            refreshMenus()
            canvas.progress = "Imports save to " + displayPath(selected)
        }
    }
    @objc private func resetImportFolder(_ sender: Any?) {
        guard !canvas.busy else { return }
        importParent = nil
        UserDefaults.standard.removeObject(forKey: "PalmClixImportParent")
        refreshMenus()
        canvas.progress = "Imports save to ~/Pictures"
    }
    @objc private func copyDiagnostics(_ sender: Any?) {
        NSPasteboard.general.clearContents()
        NSPasteboard.general.setString(lastLogLines.joined(separator: "\n"), forType: .string)
        canvas.progress = "Diagnostics copied to clipboard"
    }
    @objc private func showDiagnosticsLog(_ sender: Any?) {
        let url = FileManager.default.temporaryDirectory.appendingPathComponent("PalmClix Diagnostics.log")
        do {
            try (lastLogLines.joined(separator: "\n") + "\n").write(to: url, atomically: true, encoding: .utf8)
            NSWorkspace.shared.open(url)
        } catch {
            alert("Could not show log", error.localizedDescription)
        }
    }

    private func openImportFolder() {
        guard let url = lastSuccessfulImport else {
            alert("No completed import yet", "Download photos to reveal the import folder in Finder.")
            return
        }
        NSWorkspace.shared.activateFileViewerSelecting([url])
    }
    private func alert(_ title: String, _ detail: String) {
        let a = NSAlert(); a.messageText = title; a.informativeText = detail
        a.addButton(withTitle: "OK"); a.runModal()
    }
    private func appendLog(_ message: String) {
        guard !message.isEmpty else { return }
        lastLogLines.append(message)
        if lastLogLines.count > 400 { lastLogLines.removeFirst(lastLogLines.count - 400) }
    }

    // MARK: - Preview

    /// Opens photographs explicitly in Preview (not whatever app happens to own
    /// PNG/JPEG), opening every selected photo together so Preview can page
    /// through them. Missing files are reported instead of failing silently.
    private func openInPreview(indices requested: [Int]? = nil) {
        guard !canvas.photos.isEmpty else {
            alert("No photographs yet", "Click Download (or File ▸ Import Offline Demo) first, then select a thumbnail and click this button to open it in Preview.")
            return
        }
        var indices = requested ?? canvas.selected.sorted()
        if indices.isEmpty {
            // Nothing selected: open the first photo on the visible page.
            indices = [min(canvas.page * 12, canvas.photos.count - 1)]
        }
        let fm = FileManager.default
        let urls = indices.filter { $0 >= 0 && $0 < canvas.photos.count }
                          .map { canvas.photos[$0] }
                          .filter { fm.fileExists(atPath: $0.path) }
        guard !urls.isEmpty else {
            alert("Photograph not found", "The selected photo file has been moved or deleted. Import again, or use File ▸ Show Latest Import in Finder.")
            return
        }
        let configuration = NSWorkspace.OpenConfiguration()
        configuration.activates = true
        let finish: (NSRunningApplication?, Error?) -> Void = { [weak self] _, error in
            guard let error = error else { return }
            DispatchQueue.main.async { self?.alert("Preview could not open the photo", error.localizedDescription) }
        }
        if let preview = NSWorkspace.shared.urlForApplication(withBundleIdentifier: "com.apple.Preview") {
            NSWorkspace.shared.open(urls, withApplicationAt: preview, configuration: configuration, completionHandler: finish)
        } else if let first = urls.first,
                  let viewer = NSWorkspace.shared.urlForApplication(toOpen: first) {
            NSWorkspace.shared.open(urls, withApplicationAt: viewer, configuration: configuration, completionHandler: finish)
        } else {
            alert("No image viewer", "macOS could not find Preview or another app to open PNG/JPEG photographs.")
            return
        }
        canvas.progress = urls.count == 1 ? "Opened \(urls[0].lastPathComponent) in Preview"
                                          : "Opened \(urls.count) photos in Preview"
    }

    // MARK: - Camera checks

    private func checkUSB(announce: Bool) {
        if announce { canvas.status = "Checking USB…" }
        DispatchQueue.global(qos: .utility).async { [weak self] in
            let process = Process()
            process.executableURL = URL(fileURLWithPath: "/usr/sbin/system_profiler")
            process.arguments = ["-json", "SPUSBDataType"]
            let pipe = Pipe(); process.standardOutput = pipe; process.standardError = Pipe()
            var status = "USB detection unavailable"
            do {
                try process.run()
                let content = pipe.fileHandleForReading.readDataToEndOfFile()
                process.waitUntilExit()
                if process.terminationStatus == 0, let object = try? JSONSerialization.jsonObject(with: content) {
                    status = Self.hasCamera(object) ? "PalmClix connected — 2770:9120" : "PalmClix not connected"
                }
            } catch { status = "USB detection unavailable" }
            DispatchQueue.main.async {
                guard let self = self else { return }
                if !self.canvas.busy { self.canvas.status = status }
                self.appendLog(status)
            }
        }
    }
    private static func hasCamera(_ object: Any) -> Bool {
        if let dict = object as? [String: Any] {
            let vendor = String(describing: dict["vendor_id"] ?? "").lowercased()
            let product = String(describing: dict["product_id"] ?? "").lowercased()
            if vendor.contains("0x2770") && product.contains("0x9120") { return true }
            return dict.values.contains(where: hasCamera)
        }
        if let array = object as? [Any] { return array.contains(where: hasCamera) }
        return false
    }
    private func helperCommand(_ extra: [String]) -> (URL, [String])? {
        let fm = FileManager.default
        let helper = Bundle.main.bundleURL.appendingPathComponent("Contents/Resources/BackendRuntime/palmclix_backend")
        if fm.isExecutableFile(atPath: helper.path) { return (helper, extra) }
        let project = URL(fileURLWithPath: fm.currentDirectoryPath)
        let python: URL
        if let custom = ProcessInfo.processInfo.environment["PALMCLIX_PYTHON"], !custom.isEmpty {
            python = URL(fileURLWithPath: custom)
        } else { python = project.appendingPathComponent(".venv/bin/python") }
        guard fm.isExecutableFile(atPath: python.path) else {
            alert("Python setup needed", "When running from source, run ./setup_mac.sh first. For a portable app, use ./build_app.sh once on this Mac to embed the Python helper.")
            return nil
        }
        guard let script = Bundle.module.url(forResource: "palmclix", withExtension: "py", subdirectory: "Backend") else {
            alert("Backend missing", "The Python USB backend could not be found in the Swift resource bundle.")
            return nil
        }
        return (python, [script.path] + extra)
    }
    // Uses standard USB setup only. Does NOT send SQ905 commands, request
    // photographs, clear memory, or reset the camera. Runs off the UI thread.
    private func verifyUSBAccess() {
        guard !canvas.busy, let command = helperCommand(["--ready-check"]) else { return }
        let process = Process()
        process.executableURL = command.0
        process.arguments = command.1
        let pipe = Pipe()
        process.standardOutput = pipe
        process.standardError = pipe
        canvas.status = "Verifying USB access…"
        appendLog("Checking camera USB configuration and interface access…")
        DispatchQueue.global(qos: .utility).async { [weak self] in
            do {
                try process.run()
                let message = String(decoding: pipe.fileHandleForReading.readDataToEndOfFile(), as: UTF8.self)
                    .trimmingCharacters(in: .whitespacesAndNewlines)
                process.waitUntilExit()
                DispatchQueue.main.async {
                    guard let self = self else { return }
                    let ok = process.terminationStatus == 0
                    let result = ok ? "PalmClix USB interface ready" : "USB interface unavailable"
                    self.appendLog(result + " — " + message)
                    if !self.canvas.busy { self.canvas.status = result }
                    self.alert(result, message.isEmpty ? (ok ? "The camera's USB interface can be claimed." : "The helper reported no details.") : message)
                }
            } catch {
                DispatchQueue.main.async {
                    self?.appendLog("USB check could not run: " + error.localizedDescription)
                    self?.canvas.status = "USB check could not run"
                    self?.alert("USB check could not run", error.localizedDescription)
                }
            }
        }
    }

    private func offerRecoveryProbe() {
        guard !canvas.busy else { return }
        let prompt = NSAlert()
        prompt.alertStyle = .warning
        prompt.messageText = "Experimental eighth-photo investigation"
        prompt.informativeText = "Windows DSC transferred seven frames, while the catalog reported eight slots. Slot 1 (0x01) has NO known decoding rule, and the captured USB traffic contains NO eighth frame. This one-time experiment reads at most ONE additional stream after saving the seven recognized photos. It cannot address slot 1 directly. It may time out, return duplicate data, or leave the camera requiring reconnection. Only proceed after backing up your photos through Windows XP. No erase command is included. This is NOT guaranteed recovery."
        prompt.addButton(withTitle: "Enable for Next Live Import")
        prompt.addButton(withTitle: "Cancel")
        if prompt.runModal() == .alertFirstButtonReturn {
            probeNextLiveImport = true
            appendLog("Recovery probe armed ONCE. Only the next LIVE import uses it.")
            canvas.progress = "Recovery probe armed for next live import"
            alert("Recovery Lab armed", "Back up your camera first. Click Download (or File ▸ Import from Camera) to run one bounded test. The normal seven photographs will be saved before any extra read. Do not repeat after a timeout.")
        }
    }

    // MARK: - Artwork buttons

    private func handle(_ name: String) {
        if canvas.busy && name != "Minimize" { return }
        switch name {
        case "Exit": NSApp.terminate(nil)
        case "Minimize":
            window.miniaturize(nil)
            // Some macOS versions ignore miniaturize on frameless windows;
            // fall back to hiding the app so the button always does something.
            DispatchQueue.main.asyncAfter(deadline: .now() + 0.4) { [weak self] in
                guard let self = self, !self.window.isMiniaturized, self.window.isVisible else { return }
                NSApp.hide(nil)
            }
        case "About": alert("PalmClix for macOS — v1.1", "Authentic 1990s PalmClix artwork, original raw-file preservation, PNG/JPEG conversion, and two validated camera-catalog variants. The leading 0x01 slot is excluded, not recovered. Supported mode: 640×480 uncompressed still photographs.\n\nDownload imports from the camera (⌘D). Save copies selected photos to a folder (⌘S). The picture button opens selected photos in Preview (⌘O). Drag the camera body to move it. Output format, color processing, import folder and camera checks are in the menu bar.")
        case "Download": startTransfer(demo: false)
        case "Save": saveSelected()
        case "SelectAll":
            if !canvas.photos.isEmpty && canvas.selected.count == canvas.photos.count { canvas.selected = [] }
            else { canvas.selected = Set(canvas.photos.indices) }
        case "PreviousPage": canvas.page = max(0, canvas.page - 1)
        case "NextPage": canvas.page = min(max(0, pageCount - 1), canvas.page + 1)
        case "Twain": alert("TWAIN", "TWAIN was part of the original Windows workflow. Use Download to import directly into macOS instead.")
        case "ImageAdjust": openInPreview()
        default: break
        }
    }

    // MARK: - Import

    private func photoURLs(in root: URL) -> [URL] {
        let photosFolder = root.appendingPathComponent("Photos", isDirectory: true)
        guard let all = try? FileManager.default.contentsOfDirectory(at: photosFolder,
                includingPropertiesForKeys: nil, options: [.skipsHiddenFiles]) else { return [] }
        // For "both" output, the gallery displays just PNG; JPEG exports remain on disk.
        var byStem: [String: URL] = [:]
        for url in all {
            let ext = url.pathExtension.lowercased()
            guard ext == "png" || ext == "jpg" || ext == "jpeg" else { continue }
            let stem = url.deletingPathExtension().lastPathComponent
            if byStem[stem] == nil || ext == "png" { byStem[stem] = url }
        }
        return Array(byStem.values).sorted {
            $0.lastPathComponent.localizedStandardCompare($1.lastPathComponent) == .orderedAscending
        }
    }
    private func saveImportLog(_ destination: URL) {
        let fm = FileManager.default
        let folder = destination.appendingPathComponent("Protocol", isDirectory: true)
        do {
            try fm.createDirectory(at: folder, withIntermediateDirectories: true)
            let text = lastLogLines.joined(separator: "\n") + "\n"
            try text.write(to: folder.appendingPathComponent("app_session.log"),
                           atomically: true, encoding: .utf8)
        } catch {
            appendLog("Unable to save session log: " + error.localizedDescription)
        }
    }
    private func startTransfer(demo: Bool) {
        guard !canvas.busy else { return }
        if !demo {
            let warning = NSAlert()
            warning.messageText = "Read photos from PalmClix?"
            warning.informativeText = "Photos will be saved to \(displayPath(importParent ?? defaultImportParent)) as \(currentFormat == "both" ? "PNG + JPEG" : currentFormat.uppercased()).\n\nThe application uses the USB commands observed in successful Windows XP transfers. The exact transfer has worked on this Mac, but this proprietary camera protocol is not guaranteed risk-free. Irreplaceable images should be backed up first. No erase operation is requested."
            warning.addButton(withTitle: "Import Photos")
            warning.addButton(withTitle: "Cancel")
            if warning.runModal() != .alertFirstButtonReturn { return }
        }
        let base = importParent ?? defaultImportParent
        let stamp = DateFormatter(); stamp.dateFormat = "yyyy-MM-dd_HH-mm-ss"
        let name = "PalmClix_\(stamp.string(from: Date()))_\(UUID().uuidString.prefix(6))"
        outputFolder = base.appendingPathComponent(name, isDirectory: true)
        lastLogLines = []
        appendLog("Mode: " + (demo ? "offline replay" : "live camera") + "  •  Format: " + currentFormat + "  •  Profile: " + currentProfile)
        appendLog("Destination: " + outputFolder!.path)
        runBackend(demo: demo)
    }
    private func runBackend(demo: Bool) {
        guard let destination = outputFolder else { return }
        let fm = FileManager.default
        var extra: [String] = []
        if demo {
            let embeddedDemo = Bundle.main.bundleURL.appendingPathComponent("Contents/Resources/Demo/reference_capture.pcap")
            let project = URL(fileURLWithPath: fm.currentDirectoryPath)
            var sample = fm.fileExists(atPath: embeddedDemo.path) ? embeddedDemo : project.appendingPathComponent("reference_capture.pcap")
            if !fm.fileExists(atPath: sample.path),
               let remembered = UserDefaults.standard.string(forKey: "PalmClixDemoCapture"),
               fm.fileExists(atPath: remembered) {
                sample = URL(fileURLWithPath: remembered)
            }
            if !fm.fileExists(atPath: sample.path) {
                // Public builds ship without private recordings: let the user pick one.
                let panel = NSOpenPanel()
                panel.title = "Choose a recorded PalmClix USB capture (.pcap)"
                panel.canChooseFiles = true
                panel.canChooseDirectories = false
                panel.allowsMultipleSelection = false
                panel.prompt = "Replay"
                guard panel.runModal() == .OK, let picked = panel.url else { return }
                sample = picked
                UserDefaults.standard.set(picked.path, forKey: "PalmClixDemoCapture")
            }
            extra += ["--simulate", sample.path]
        } else {
            extra += ["--download", "auto", "--i-accept-experimental-usb"]
            if probeNextLiveImport {
                extra += ["--probe-extra-frame", "--i-accept-experimental-probe"]
                appendLog("EXPERIMENTAL RECOVERY PROBE ENABLED for this import only.")
            }
            // This permission is never retained between imports or launches.
            probeNextLiveImport = false
        }
        extra += ["--profile", currentProfile, "--format", currentFormat,
                  "--output", destination.path, "--json-progress"]
        guard let command = helperCommand(extra) else { return }
        do {
            try fm.createDirectory(at: destination.deletingLastPathComponent(), withIntermediateDirectories: true)
        } catch {
            alert("Import folder unavailable", error.localizedDescription)
            return
        }
        let process = Process()
        process.executableURL = command.0
        process.currentDirectoryURL = destination.deletingLastPathComponent()
        process.arguments = command.1
        let pipe = Pipe()
        process.standardOutput = pipe
        process.standardError = pipe
        priorPhotos = canvas.photos
        priorSelected = canvas.selected
        priorPage = canvas.page
        canvas.busy = true
        canvas.fraction = 0
        currentImportCount = 0
        excludedSlots = 0
        recoveryCandidateSaved = false
        canvas.status = demo ? "Offline recording replay…" : "Reading PalmClix…"
        canvas.progress = "Starting transfer…"
        runningProcess = process
        lastBackendError = nil
        DispatchQueue.global(qos: .userInitiated).async { [weak self] in
            do {
                try process.run()
                var buffer = Data()
                let handle = pipe.fileHandleForReading
                while true {
                    let chunk = handle.readData(ofLength: 4096)
                    if chunk.isEmpty { break }
                    buffer.append(chunk)
                    while let newline = buffer.firstIndex(of: 10) {
                        let line = String(decoding: buffer[..<newline], as: UTF8.self)
                        buffer.removeSubrange(...newline)
                        DispatchQueue.main.async { self?.handleOutputLine(line) }
                    }
                }
                if !buffer.isEmpty {
                    let last = String(decoding: buffer, as: UTF8.self)
                    DispatchQueue.main.async { self?.handleOutputLine(last) }
                }
                process.waitUntilExit()
                DispatchQueue.main.async {
                    guard let self = self else { return }
                    self.runningProcess = nil
                    self.canvas.busy = false
                    if process.terminationStatus == 0 {
                        let importedPhotos = self.photoURLs(in: destination)
                        self.canvas.photos = importedPhotos
                        self.canvas.selected = []
                        self.canvas.page = 0
                        self.lastSuccessfulImport = destination
                        UserDefaults.standard.set(destination.path, forKey: "PalmClixLastImport")
                        self.canvas.status = "Imported \(self.canvas.photos.count) photos"
                        self.canvas.progress = self.excludedSlots > 0
                            ? "\(self.excludedSlots) unusable slot(s) excluded • ⇧⌘R: Finder"
                            : "Saved to \(self.displayPath(destination.deletingLastPathComponent()))"
                        self.canvas.fraction = 1
                        if self.recoveryCandidateSaved {
                            self.alert("Unverified extra stream saved", "A candidate raw sensor frame was stored in the Recovery folder. This does NOT confirm recovery of catalog slot 1. Compare its contents manually; the seven verified photos remain intact.")
                        }
                        self.appendLog("Complete: \(self.canvas.photos.count) images. Import folder: \(destination.path)")
                    } else {
                        self.canvas.photos = self.priorPhotos
                        self.canvas.selected = self.priorSelected
                        self.canvas.page = self.priorPage
                        self.canvas.fraction = 0
                        self.canvas.status = "Transfer failed — previous gallery retained"
                        self.appendLog("FAILED (exit \(process.terminationStatus)): " + (self.lastBackendError ?? "Unknown helper error"))
                        self.alert("PalmClix transfer failed", "\(self.lastBackendError ?? "The USB helper exited with code \(process.terminationStatus).")\n\nAny already saved raw photos have been preserved in \(destination.path). The previous gallery remains available. Avoid repeated attempts after unexpected USB failures.")
                    }
                    self.saveImportLog(destination)
                }
            } catch {
                DispatchQueue.main.async {
                    self?.runningProcess = nil
                    self?.canvas.busy = false
                    self?.canvas.status = "Cannot run backend"
                    self?.appendLog("Backend launch failed: " + error.localizedDescription)
                    self?.saveImportLog(destination)
                    self?.alert("Failed to start backend", error.localizedDescription)
                }
            }
        }
    }
    private func handleOutputLine(_ line: String) {
        if !line.hasPrefix("PALMCLIX_EVENT ") {
            if !line.isEmpty { print(line); appendLog(line) }
            return
        }
        let json = String(line.dropFirst("PALMCLIX_EVENT ".count))
        guard let data = json.data(using: .utf8),
              let payload = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
              let kind = payload["event"] as? String else { return }
        if kind == "error", let message = payload["message"] as? String {
            lastBackendError = message
            appendLog("Error: " + message)
        }
        let i = payload["index"] as? Int ?? 0
        let total = payload["total"] as? Int ?? 0
        switch kind {
        case "metadata":
            canvas.status = "Camera model identified"
            canvas.progress = "Model ID: \(payload["model_id"] as? String ?? "")"
            appendLog(canvas.progress)
            canvas.fraction = 0.03
        case "catalog":
            let count = payload["count"] as? Int ?? 0
            excludedSlots = payload["excluded_slots"] as? Int ?? 0
            canvas.status = "Camera: \(count) photos" + (excludedSlots > 0 ? " • \(excludedSlots) unavailable slot" : "")
            currentImportCount = count
            canvas.progress = count == 0 ? "No supported photographs" : "Reading \(count) supported photo(s)…"
            appendLog("Catalog: \(count) valid photos, \(excludedSlots) excluded slot(s)")
            canvas.fraction = count == 0 ? 1 : 0.07
        case "stage":
            let stage = payload["stage"] as? String ?? ""
            appendLog(stage == "decode" ? "USB transfer complete; decoding images…" : "Starting USB image transfer…")
        case "chunk":
            let completed = payload["completed_chunks"] as? Int ?? 0
            let all = max(1, payload["all_chunks"] as? Int ?? 1)
            canvas.fraction = 0.07 + 0.73 * Double(completed) / Double(all)
            canvas.progress = "Receiving photo \(payload["photo"] as? Int ?? 0)/\(payload["total_photos"] as? Int ?? 0) · block \(payload["chunk"] as? Int ?? 0)/10"
        case "transfer":
            canvas.progress = "Raw photo \(i) of \(total) saved safely"
            appendLog(canvas.progress)
        case "photo":
            canvas.progress = "Converted photo \(i) of \(total)"
            canvas.fraction = 0.8 + 0.2 * Double(i) / Double(max(1, total))
            appendLog(canvas.progress)
        case "done":
            canvas.progress = "Imported \(payload["count"] as? Int ?? currentImportCount) photographs"
            canvas.fraction = 1
        case "recovery":
            let state = payload["status"] as? String ?? "unknown"
            recoveryCandidateSaved = (state == "unverified-candidate-saved")
            appendLog("RECOVERY LAB: " + state + " · unverified, not part of the normal gallery")
        case "error":
            canvas.status = "USB error"
            canvas.progress = payload["message"] as? String ?? "Unknown error"
        default: break
        }
    }

    // MARK: - Save

    private func saveSelected() {
        guard !canvas.photos.isEmpty else { alert("No photographs yet", "Click Download (or File ▸ Import Offline Demo) first."); return }
        let chosen = canvas.selected.isEmpty ? canvas.photos : canvas.selected.sorted().map { canvas.photos[$0] }
        let panel = NSOpenPanel()
        panel.title = canvas.selected.isEmpty ? "Save all \(chosen.count) photos to…" : "Save \(chosen.count) selected photo(s) to…"
        panel.canChooseDirectories = true
        panel.canChooseFiles = false
        panel.canCreateDirectories = true
        panel.prompt = "Save Here"
        panel.directoryURL = lastSuccessfulImport ?? defaultImportParent
        if panel.runModal() != .OK { return }
        guard let dest = panel.url else { return }
        var written = 0
        for source in chosen {
            // Refuse to overwrite existing names; append a unique suffix.
            var target = dest.appendingPathComponent(source.lastPathComponent)
            if FileManager.default.fileExists(atPath: target.path) {
                target = dest.appendingPathComponent("\(source.deletingPathExtension().lastPathComponent)_\(UUID().uuidString.prefix(6)).\(source.pathExtension)")
            }
            do { try FileManager.default.copyItem(at: source, to: target); written += 1 }
            catch { alert("Save error", error.localizedDescription); break }
        }
        canvas.status = "Saved \(written) photo(s)"
        canvas.progress = "to " + displayPath(dest)
    }
}

let app = NSApplication.shared
let delegate = AppController()
app.delegate = delegate
app.setActivationPolicy(.regular)
app.run()
