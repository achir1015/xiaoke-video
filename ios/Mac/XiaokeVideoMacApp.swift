import SwiftUI
import AppKit
import WebKit
import UniformTypeIdentifiers

/// 小柯影音剪輯助手 — Mac App Store 版（原生 macOS App，M 系列與 Intel 晶片都能執行）
/// 用 macOS 的 WKWebView 開啟 App 內建的剪輯程式（和 iPad 版、線上版同一份 index.html），由 LocalServer 在 127.0.0.1 提供。
/// （不用 Mac Catalyst：Catalyst 的網頁引擎沒有影片錄製 MediaRecorder，無法匯出影片）
@main
struct XiaokeVideoMacApp: App {
    @NSApplicationDelegateAdaptor(AppDelegate.self) var delegate
    init() { LocalServer.shared.start() }

    var body: some Scene {
        WindowGroup("小柯影音剪輯助手") {
            WebContainer()
                .frame(minWidth: 1280, minHeight: 780)
                .background(Color(red: 0.067, green: 0.078, blue: 0.09))
        }
        .defaultSize(width: 1500, height: 920)
        .commands { CommandGroup(replacing: .newItem) {} }
    }
}

final class AppDelegate: NSObject, NSApplicationDelegate {
    func applicationShouldTerminateAfterLastWindowClosed(_ app: NSApplication) -> Bool { true }
    // 匯出影片是即時錄製：期間不要讓系統進入省電、App Nap
    private var activity: NSObjectProtocol?
    func applicationDidFinishLaunching(_ n: Notification) {
        activity = ProcessInfo.processInfo.beginActivity(options: [.userInitiated, .idleSystemSleepDisabled, .latencyCritical], reason: "影片剪輯與匯出")
    }
}

struct WebContainer: NSViewRepresentable {
    func makeNSView(context: Context) -> WKWebView { Web.shared.view }
    func updateNSView(_ v: WKWebView, context: Context) {}
}

/// 網頁與 App 之間的橋：網頁呼叫 window.webkit.messageHandlers.xkv.postMessage({cmd, args})，回傳 Promise
final class Web: NSObject, WKScriptMessageHandlerWithReply, WKNavigationDelegate, WKUIDelegate {
    static let shared = Web()
    #if arch(x86_64)
    static let cpu = "x86_64"
    #else
    static let cpu = "arm64"
    #endif
    let view: WKWebView
    private var saves: [String: (url: URL, handle: FileHandle, name: String)] = [:]
    private let selfTesting = ProcessInfo.processInfo.environment["XK_SELFTEST"] != nil
    private var testStarted = false

    override init() {
        let cfg = WKWebViewConfiguration()
        cfg.mediaTypesRequiringUserActionForPlayback = []
        cfg.websiteDataStore = .default()
        let shim = WKUserScript(source: """
            window.XiaokeAppStore = 'Mac'; window.XiaokeCPU = '\(Web.cpu)';
            (function () {
              function send(k, a) { try { window.webkit.messageHandlers.xkv.postMessage({ cmd: 'log', args: [k, Array.prototype.map.call(a, function (x) { return x && x.stack ? x.stack : String(x); }).join(' ')] }); } catch (e) {} }
              var ce = console.error.bind(console);
              console.error = function () { send('error', arguments); ce.apply(null, arguments); };
              window.addEventListener('error', function (e) { send('pageerror', [e.message + ' @' + e.filename + ':' + e.lineno]); });
              window.addEventListener('unhandledrejection', function (e) { send('rejection', [e.reason]); });
            })();
            """, injectionTime: .atDocumentStart, forMainFrameOnly: true)
        cfg.userContentController.addUserScript(shim)
        view = WKWebView(frame: .zero, configuration: cfg)
        super.init()
        cfg.userContentController.addScriptMessageHandler(self, contentWorld: .page, name: "xkv")
        view.navigationDelegate = self
        view.uiDelegate = self
        view.underPageBackgroundColor = NSColor(red: 0.067, green: 0.078, blue: 0.09, alpha: 1)
        if #available(macOS 13.3, *) { view.isInspectable = true }
        view.load(URLRequest(url: LocalServer.shared.url))
    }

    func webView(_ w: WKWebView, didFinish n: WKNavigation!) {
        if selfTesting && !testStarted { testStarted = true; w.evaluateJavaScript(selfTestScript(ProcessInfo.processInfo.environment["XK_SELFTEST"] ?? "all")) { _, _ in } }
    }

    // 外部連結用預設瀏覽器開
    func webView(_ w: WKWebView, decidePolicyFor a: WKNavigationAction, decisionHandler: @escaping (WKNavigationActionPolicy) -> Void) {
        if let u = a.request.url, u.host != "127.0.0.1", u.scheme?.hasPrefix("http") == true, a.targetFrame?.isMainFrame != false {
            NSWorkspace.shared.open(u); decisionHandler(.cancel); return
        }
        decisionHandler(.allow)
    }
    func webView(_ w: WKWebView, createWebViewWith c: WKWebViewConfiguration, for a: WKNavigationAction, windowFeatures f: WKWindowFeatures) -> WKWebView? {
        if let u = a.request.url { NSWorkspace.shared.open(u) }
        return nil
    }
    // <input type="file">（選擇素材、開啟專案、匯入 SRT）：系統的開啟視窗
    func webView(_ w: WKWebView, runOpenPanelWith p: WKOpenPanelParameters, initiatedByFrame f: WKFrameInfo, completionHandler: @escaping ([URL]?) -> Void) {
        let panel = NSOpenPanel()
        panel.allowsMultipleSelection = p.allowsMultipleSelection
        panel.canChooseDirectories = false
        panel.canChooseFiles = true
        panel.beginSheetModal(for: w.window ?? NSApp.keyWindow ?? NSWindow()) { r in completionHandler(r == .OK ? panel.urls : nil) }
    }
    // 網頁的 confirm()／alert()／prompt()
    func webView(_ w: WKWebView, runJavaScriptConfirmPanelWithMessage message: String, initiatedByFrame frame: WKFrameInfo, completionHandler: @escaping (Bool) -> Void) {
        let a = NSAlert(); a.messageText = message; a.addButton(withTitle: "確定"); a.addButton(withTitle: "取消")
        completionHandler(a.runModal() == .alertFirstButtonReturn)
    }
    func webView(_ w: WKWebView, runJavaScriptAlertPanelWithMessage message: String, initiatedByFrame frame: WKFrameInfo, completionHandler: @escaping () -> Void) {
        let a = NSAlert(); a.messageText = message; a.addButton(withTitle: "好"); a.runModal(); completionHandler()
    }
    func webView(_ w: WKWebView, runJavaScriptTextInputPanelWithPrompt prompt: String, defaultText: String?, initiatedByFrame frame: WKFrameInfo, completionHandler: @escaping (String?) -> Void) {
        let a = NSAlert(); a.messageText = prompt; a.addButton(withTitle: "確定"); a.addButton(withTitle: "取消")
        let f = NSTextField(frame: NSRect(x: 0, y: 0, width: 280, height: 24)); f.stringValue = defaultText ?? ""; a.accessoryView = f
        completionHandler(a.runModal() == .alertFirstButtonReturn ? f.stringValue : nil)
    }
    func webViewWebContentProcessDidTerminate(_ w: WKWebView) { note("網頁程序被系統結束，重新載入"); w.reload() }

    private func note(_ line: String) {
        guard selfTesting else { return }
        let f = FileManager.default.urls(for: .documentDirectory, in: .userDomainMask)[0].appendingPathComponent("selftest-progress.txt")
        let row = Data("\(Date()) \(line)\n".utf8)
        if let h = try? FileHandle(forWritingTo: f) { h.seekToEndOfFile(); h.write(row); try? h.close() } else { try? row.write(to: f) }
    }

    // MARK: 網頁呼叫的功能
    func userContentController(_ u: WKUserContentController, didReceive m: WKScriptMessage, replyHandler: @escaping (Any?, String?) -> Void) {
        guard let body = m.body as? [String: Any], let cmd = body["cmd"] as? String else { replyHandler(nil, "bad message"); return }
        let args = body["args"] as? [Any] ?? []
        let s = { (i: Int) -> String in args.count > i ? "\(args[i])" : "" }
        switch cmd {
        case "begin_save":
            let name = s(0).replacingOccurrences(of: "/", with: "_").replacingOccurrences(of: ":", with: "_")
            let dir = FileManager.default.temporaryDirectory.appendingPathComponent("export", isDirectory: true)
            try? FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
            let url = dir.appendingPathComponent(name.isEmpty ? "小柯影片.mp4" : name)
            try? FileManager.default.removeItem(at: url)
            FileManager.default.createFile(atPath: url.path, contents: nil)
            guard let h = try? FileHandle(forWritingTo: url) else { replyHandler(["status": "error", "message": "無法建立檔案"], nil); return }
            let token = UUID().uuidString
            saves[token] = (url, h, url.lastPathComponent)
            replyHandler(["status": "ok", "token": token], nil)
        case "write_chunk":
            guard let sv = saves[s(0)], let d = Data(base64Encoded: s(1)) else { replyHandler(["status": "error", "message": "no session"], nil); return }
            sv.handle.write(d)
            replyHandler(["status": "ok"], nil)
        case "end_save":
            guard let sv = saves.removeValue(forKey: s(0)) else { replyHandler(["status": "error", "message": "no session"], nil); return }
            try? sv.handle.close()
            if selfTesting {   // 自我測試：直接存到 App 的 Documents，不跳視窗
                let dst = FileManager.default.urls(for: .documentDirectory, in: .userDomainMask)[0].appendingPathComponent(sv.name)
                try? FileManager.default.removeItem(at: dst); try? FileManager.default.copyItem(at: sv.url, to: dst)
                replyHandler(["status": "ok", "path": sv.name], nil); return
            }
            // 存檔視窗：預設存到「影片」資料夾
            let panel = NSSavePanel()
            panel.nameFieldStringValue = sv.name
            panel.directoryURL = FileManager.default.urls(for: .moviesDirectory, in: .userDomainMask).first
            panel.canCreateDirectories = true
            panel.beginSheetModal(for: view.window ?? NSApp.keyWindow ?? NSWindow()) { r in
                guard r == .OK, let dst = panel.url else { replyHandler(["status": "declined"], nil); return }
                do {
                    try? FileManager.default.removeItem(at: dst)
                    try FileManager.default.copyItem(at: sv.url, to: dst)
                    try? FileManager.default.removeItem(at: sv.url)
                    replyHandler(["status": "ok", "path": dst.path], nil)
                } catch { replyHandler(["status": "error", "message": error.localizedDescription], nil) }
            }
        case "log":
            NSLog("[web %@] %@", s(0), s(1))
            note("[\(s(0))] \(s(1))")
            replyHandler(true, nil)
        case "st":
            note(s(0)); replyHandler(true, nil)
        case "st_done":
            let docs = FileManager.default.urls(for: .documentDirectory, in: .userDomainMask)[0]
            try? s(0).write(to: docs.appendingPathComponent("selftest.txt"), atomically: true, encoding: .utf8)
            view.takeSnapshot(with: nil) { img, _ in
                if let t = img?.tiffRepresentation, let r = NSBitmapImageRep(data: t), let d = r.representation(using: .png, properties: [:]) {
                    try? d.write(to: docs.appendingPathComponent("selftest.png"))
                }
            }
            replyHandler(true, nil)
        default:
            replyHandler(nil, "unknown command \(cmd)")
        }
    }
}
