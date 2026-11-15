import Foundation
import WebKit
import UniformTypeIdentifiers

/// Mac 版：用自訂網址 xiaoke://app/… 直接把 App 裡的 web 資料夾交給 WKWebView，
/// 不開任何網路伺服器（Mac App Store 沙盒不需要 com.apple.security.network.server）。
/// 支援 Range（影音元素分段讀取）。
final class AppSchemeHandler: NSObject, WKURLSchemeHandler {
    static let scheme = "xiaoke"
    static let start = URL(string: "xiaoke://app/index.html")!
    private let root = Bundle.main.url(forResource: "web", withExtension: nil)!

    func webView(_ w: WKWebView, start task: WKURLSchemeTask) {
        guard let url = task.request.url else { task.didFailWithError(URLError(.badURL)); return }
        var path = url.path.removingPercentEncoding ?? url.path
        if path.isEmpty || path == "/" { path = "/index.html" }
        let file = root.appendingPathComponent(String(path.dropFirst())).standardizedFileURL
        guard file.path.hasPrefix(root.standardizedFileURL.path), !path.contains(".."),
              let body = try? Data(contentsOf: file, options: .mappedIfSafe) else {
            let r = HTTPURLResponse(url: url, statusCode: 404, httpVersion: "HTTP/1.1", headerFields: ["Content-Length": "0"])!
            task.didReceive(r); task.didFinish(); return
        }
        let type = Self.mime(file.pathExtension.lowercased())
        var status = 200, data = body
        var headers = ["Content-Type": type, "Accept-Ranges": "bytes", "Cache-Control": "no-store", "Access-Control-Allow-Origin": "*"]
        if let range = task.request.value(forHTTPHeaderField: "Range"), range.hasPrefix("bytes="), !body.isEmpty {
            let se = range.dropFirst(6).split(separator: ",").first.map(String.init)?
                .split(separator: "-", omittingEmptySubsequences: false).map { $0.trimmingCharacters(in: .whitespaces) } ?? []
            var s = 0, e = body.count - 1
            if se.count == 2 {
                if se[0].isEmpty, let n = Int(se[1]) { s = max(0, body.count - n) }
                else { s = Int(se[0]) ?? 0; if let x = Int(se[1]) { e = min(x, body.count - 1) } }
            }
            if s <= e && s < body.count {
                status = 206; data = body.subdata(in: s..<(e + 1))
                headers["Content-Range"] = "bytes \(s)-\(e)/\(body.count)"
            }
        }
        headers["Content-Length"] = String(data.count)
        task.didReceive(HTTPURLResponse(url: url, statusCode: status, httpVersion: "HTTP/1.1", headerFields: headers)!)
        task.didReceive(data)
        task.didFinish()
    }

    func webView(_ w: WKWebView, stop task: WKURLSchemeTask) {}

    static func mime(_ ext: String) -> String {
        switch ext {
        case "html": return "text/html; charset=utf-8"
        case "js", "mjs": return "text/javascript; charset=utf-8"
        case "css": return "text/css; charset=utf-8"
        case "json": return "application/json; charset=utf-8"
        case "webmanifest": return "application/manifest+json"
        case "svg": return "image/svg+xml"
        case "png": return "image/png"
        case "ico": return "image/x-icon"
        case "wasm": return "application/wasm"
        case "txt": return "text/plain; charset=utf-8"
        default: return UTType(filenameExtension: ext)?.preferredMIMEType ?? "application/octet-stream"
        }
    }
}
