import SwiftUI
import UIKit
import WebKit
import UniformTypeIdentifiers

/// 小柯影音剪輯助手 — iPad 版與 Mac 版（Mac Catalyst，M 系列與 Intel 晶片都能執行）
/// WKWebView 開啟 App 內建的剪輯程式（和線上版、Windows 版同一份 index.html），由 LocalServer 在 127.0.0.1 提供。
/// 匯入素材用系統的檔案／照片選擇器；匯出的影片、專案檔、字幕交給 App：iPad 開分享選單（存到檔案、照片、AirDrop），Mac 開存檔視窗。
@main
struct XiaokeVideoApp: App {
    init() {
        LocalServer.shared.start()
        UIApplication.shared.isIdleTimerDisabled = true   // 匯出影片是即時錄製，螢幕不要自動變暗鎖定
    }

    var body: some Scene {
        WindowGroup {
            WebContainer()
                .background(Color(red: 0.067, green: 0.078, blue: 0.09))
                .ignoresSafeArea()
                .statusBarHidden(true)
                .persistentSystemOverlays(.hidden)
        }
    }
}

struct WebContainer: UIViewRepresentable {
    func makeUIView(context: Context) -> WKWebView {
        let v = Web.shared.view
        #if targetEnvironment(macCatalyst)
        DispatchQueue.main.async {   // Mac 視窗：剪輯畫面需要的最小尺寸
            v.window?.windowScene?.sizeRestrictions?.minimumSize = CGSize(width: 1280, height: 780)
        }
        #endif
        return v
    }
    func updateUIView(_ v: WKWebView, context: Context) {}
}

/// 網頁與 App 之間的橋：網頁呼叫 window.webkit.messageHandlers.xkv.postMessage({cmd, args})，回傳 Promise
final class Web: NSObject, WKScriptMessageHandlerWithReply, WKNavigationDelegate, WKUIDelegate, UIDocumentPickerDelegate {
    static let shared = Web()
    let view: WKWebView
    private var saves: [String: (url: URL, handle: FileHandle, name: String)] = [:]
    private var pickerDone: ((Bool) -> Void)?
    private let selfTesting = ProcessInfo.processInfo.environment["XK_SELFTEST"] != nil
    static let isMac = ProcessInfo.processInfo.isMacCatalystApp

    override init() {
        let cfg = WKWebViewConfiguration()
        cfg.allowsInlineMediaPlayback = true
        cfg.mediaTypesRequiringUserActionForPlayback = []
        cfg.websiteDataStore = .default()
        // 讓網頁知道自己在 App Store 版裡（存檔交給 App、程式庫用 App 內建的、不自己檢查更新）
        // 網頁的錯誤訊息轉到系統記錄（除錯：log show --predicate 'process == "XiaokeVideo"'）
        let shim = WKUserScript(source: """
            window.XiaokeAppStore = '\(Web.isMac ? "Mac" : "iPad")';
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
        view.isOpaque = false
        view.backgroundColor = UIColor(red: 0.067, green: 0.078, blue: 0.09, alpha: 1)
        view.scrollView.backgroundColor = view.backgroundColor
        view.scrollView.bounces = false
        view.scrollView.contentInsetAdjustmentBehavior = .never
        if #available(iOS 16.4, *) { view.isInspectable = true }
        view.load(URLRequest(url: LocalServer.shared.url))
    }

    // 自我測試在網頁載入完成後開始（只跑一次）
    private var testStarted = false
    func webView(_ w: WKWebView, didFinish n: WKNavigation!) {
        if selfTesting && !testStarted { testStarted = true; selfTest() }
    }

    // 外部連結（GitHub、說明網頁）用 Safari／預設瀏覽器開
    func webView(_ w: WKWebView, decidePolicyFor a: WKNavigationAction, decisionHandler: @escaping (WKNavigationActionPolicy) -> Void) {
        if let u = a.request.url, u.host != "127.0.0.1", u.scheme?.hasPrefix("http") == true, a.targetFrame?.isMainFrame != false {
            UIApplication.shared.open(u); decisionHandler(.cancel); return
        }
        decisionHandler(.allow)
    }
    func webView(_ w: WKWebView, createWebViewWith c: WKWebViewConfiguration, for a: WKNavigationAction, windowFeatures f: WKWindowFeatures) -> WKWebView? {
        if let u = a.request.url { UIApplication.shared.open(u) }
        return nil
    }
    // 網頁的 confirm()／alert()（例如「還沒儲存，確定要放棄嗎？」）用系統對話框顯示
    func webView(_ w: WKWebView, runJavaScriptConfirmPanelWithMessage message: String, initiatedByFrame frame: WKFrameInfo, completionHandler: @escaping (Bool) -> Void) {
        let a = UIAlertController(title: nil, message: message, preferredStyle: .alert)
        a.addAction(UIAlertAction(title: "取消", style: .cancel) { _ in completionHandler(false) })
        a.addAction(UIAlertAction(title: "確定", style: .default) { _ in completionHandler(true) })
        present(a) { completionHandler(false) }
    }
    func webView(_ w: WKWebView, runJavaScriptAlertPanelWithMessage message: String, initiatedByFrame frame: WKFrameInfo, completionHandler: @escaping () -> Void) {
        let a = UIAlertController(title: nil, message: message, preferredStyle: .alert)
        a.addAction(UIAlertAction(title: "好", style: .default) { _ in completionHandler() })
        present(a) { completionHandler() }
    }
    func webView(_ w: WKWebView, runJavaScriptTextInputPanelWithPrompt prompt: String, defaultText: String?, initiatedByFrame frame: WKFrameInfo, completionHandler: @escaping (String?) -> Void) {
        let a = UIAlertController(title: nil, message: prompt, preferredStyle: .alert)
        a.addTextField { $0.text = defaultText }
        a.addAction(UIAlertAction(title: "取消", style: .cancel) { _ in completionHandler(nil) })
        a.addAction(UIAlertAction(title: "確定", style: .default) { _ in completionHandler(a.textFields?.first?.text) })
        present(a) { completionHandler(nil) }
    }

    // 網頁被系統回收時（記憶體不足）自動重新載入
    func webViewWebContentProcessDidTerminate(_ w: WKWebView) { note("網頁程序被系統結束（記憶體不足？），重新載入"); w.reload() }

    /// 自我測試的進度記錄（Documents/selftest-progress.txt）
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
            // 存檔：先寫到暫存檔，寫完再讓使用者選要存到哪裡
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
                let docs = FileManager.default.urls(for: .documentDirectory, in: .userDomainMask)[0].appendingPathComponent(sv.name)
                try? FileManager.default.removeItem(at: docs)
                try? FileManager.default.copyItem(at: sv.url, to: docs)
                replyHandler(["status": "ok", "path": sv.name], nil); return
            }
            deliver(sv.url) { done in replyHandler(done ? ["status": "ok", "path": sv.name] : ["status": "declined"], nil) }
        case "log":
            NSLog("[web %@] %@", s(0), s(1))
            note("[\(s(0))] \(s(1))")
            replyHandler(true, nil)
        case "st":        // 自我測試：目前做到哪一步
            note(s(0))
            replyHandler(true, nil)
        case "st_done":   // 自我測試：最後結果與畫面
            let docs = FileManager.default.urls(for: .documentDirectory, in: .userDomainMask)[0]
            view.takeSnapshot(with: nil) { img, _ in
                if let d = img?.pngData() { try? d.write(to: docs.appendingPathComponent("selftest.png")) }
                try? s(0).write(to: docs.appendingPathComponent("selftest.txt"), atomically: true, encoding: .utf8)
            }
            replyHandler(true, nil)
        default:
            replyHandler(nil, "unknown command \(cmd)")
        }
    }

    /// iPad：分享選單（儲存影片到照片、存到檔案、AirDrop、LINE…）；Mac：存檔視窗
    private func deliver(_ url: URL, done: @escaping (Bool) -> Void) {
        if Web.isMac {
            let picker = UIDocumentPickerViewController(forExporting: [url], asCopy: true)
            picker.delegate = self
            pickerDone = done
            present(picker) { self.pickerDone = nil; done(false) }
            return
        }
        let vc = UIActivityViewController(activityItems: [url], applicationActivities: nil)
        vc.completionWithItemsHandler = { _, completed, _, _ in done(completed) }
        if let p = vc.popoverPresentationController {   // iPad：從畫面中央彈出
            p.sourceView = view
            p.sourceRect = CGRect(x: view.bounds.midX, y: view.bounds.midY, width: 1, height: 1)
            p.permittedArrowDirections = []
        }
        present(vc) { done(false) }
    }
    func documentPicker(_ c: UIDocumentPickerViewController, didPickDocumentsAt urls: [URL]) { pickerDone?(true); pickerDone = nil }
    func documentPickerWasCancelled(_ c: UIDocumentPickerViewController) { pickerDone?(false); pickerDone = nil }

    private func present(_ vc: UIViewController, fail: () -> Void) {
        let scene = UIApplication.shared.connectedScenes.compactMap { $0 as? UIWindowScene }.first
        var top = scene?.windows.first(where: { $0.isKeyWindow })?.rootViewController ?? scene?.windows.first?.rootViewController
        while let p = top?.presentedViewController { top = p }
        if let top { top.present(vc, animated: true) } else { fail() }
    }

    // 自我測試（啟動時帶環境變數 XK_SELFTEST=1 才跑）：編輯、匯出 2 秒影片、存檔、語音模型、翻譯；
    // 每一步記在 Documents/selftest-progress.txt，結果寫在 selftest.txt、畫面存成 selftest.png
    private func selfTest() {
        let script = selfTestScript(ProcessInfo.processInfo.environment["XK_SELFTEST"] ?? "all")
        view.evaluateJavaScript(script) { _, _ in }
    }
}
