import Foundation
import Network

/// App 內的小型網頁伺服器（只聽 127.0.0.1）：提供 App 裡的 web 資料夾（和線上版同一份剪輯程式）。
/// 用 http://127.0.0.1 載入才算「安全來源」：ES 模組、Worker、WebAssembly、IndexedDB 都能用。
/// 固定埠號（和其他小柯 App 錯開），網頁資料（最近開啟、偏好設定、下載過的語音模型）綁在這個網址上，每次開啟都還在。
final class LocalServer {
    static let shared = LocalServer()
    private(set) var port: UInt16 = 48341
    private var listener: NWListener?
    private let queue = DispatchQueue(label: "xkv.server", attributes: .concurrent)
    private let root = Bundle.main.url(forResource: "web", withExtension: nil)!

    var url: URL { URL(string: "http://127.0.0.1:\(port)/index.html")! }

    func start() {
        for p in [UInt16(48341), 48342, 48343, 0] {
            do {
                let params = NWParameters.tcp
                params.requiredLocalEndpoint = NWEndpoint.hostPort(host: "127.0.0.1", port: NWEndpoint.Port(rawValue: p)!)
                params.allowLocalEndpointReuse = true
                let l = try NWListener(using: params)
                let ready = DispatchSemaphore(value: 0)
                var ok = false
                l.stateUpdateHandler = { st in
                    switch st {
                    case .ready: ok = true; ready.signal()
                    case .failed, .cancelled: ready.signal()
                    default: break
                    }
                }
                l.newConnectionHandler = { [weak self] c in self?.handle(c) }
                l.start(queue: queue)
                _ = ready.wait(timeout: .now() + 2)
                if ok { listener = l; port = l.port?.rawValue ?? p; return }
                l.cancel()
            } catch { continue }
        }
    }

    private func handle(_ c: NWConnection) {
        c.start(queue: queue)
        var buf = Data()
        func read() {
            c.receive(minimumIncompleteLength: 1, maximumLength: 65536) { [weak self] data, _, done, err in
                guard let self else { return }
                if let data { buf.append(data) }
                if let end = buf.range(of: Data("\r\n\r\n".utf8)) {
                    let head = String(decoding: buf[..<end.lowerBound], as: UTF8.self)
                    self.respond(c, head: head)
                } else if done || err != nil || buf.count > 1_000_000 {
                    c.cancel()
                } else { read() }
            }
        }
        read()
    }

    private func respond(_ c: NWConnection, head: String) {
        let lines = head.components(separatedBy: "\r\n")
        let parts = (lines.first ?? "").split(separator: " ")
        var path = parts.count > 1 ? String(parts[1]) : "/"
        if let q = path.firstIndex(of: "?") { path = String(path[..<q]) }
        path = path.removingPercentEncoding ?? path
        if path == "/" { path = "/index.html" }
        var range: String?
        for l in lines.dropFirst() where l.lowercased().hasPrefix("range:") { range = l.dropFirst(6).trimmingCharacters(in: .whitespaces) }

        guard !path.contains(".."), let body = try? Data(contentsOf: root.appendingPathComponent(String(path.dropFirst())), options: .mappedIfSafe) else {
            send(c, "HTTP/1.1 404 Not Found\r\nContent-Length: 0\r\nConnection: close\r\n\r\n", nil)
            return
        }
        let type = Self.mime((path as NSString).pathExtension.lowercased())
        let total = body.count
        // Range: bytes=start-end
        if let range, range.hasPrefix("bytes="), total > 0 {
            let spec = range.dropFirst(6).split(separator: ",").first.map(String.init) ?? ""
            let se = spec.split(separator: "-", omittingEmptySubsequences: false).map { String($0).trimmingCharacters(in: .whitespaces) }
            var start = 0, end = total - 1
            if se.count == 2 {
                if se[0].isEmpty, let n = Int(se[1]) { start = max(0, total - n) }
                else { start = Int(se[0]) ?? 0; if let e = Int(se[1]) { end = min(e, total - 1) } }
            }
            if start > end || start >= total {
                send(c, "HTTP/1.1 416 Range Not Satisfiable\r\nContent-Range: bytes */\(total)\r\nContent-Length: 0\r\nConnection: close\r\n\r\n", nil)
                return
            }
            let h = "HTTP/1.1 206 Partial Content\r\nContent-Type: \(type)\r\nAccept-Ranges: bytes\r\nContent-Range: bytes \(start)-\(end)/\(total)\r\nContent-Length: \(end - start + 1)\r\nCache-Control: no-store\r\nConnection: close\r\n\r\n"
            send(c, h, body.subdata(in: start..<(end + 1)))
            return
        }
        let h = "HTTP/1.1 200 OK\r\nContent-Type: \(type)\r\nAccept-Ranges: bytes\r\nContent-Length: \(total)\r\nCache-Control: no-store\r\nConnection: close\r\n\r\n"
        send(c, h, body)
    }

    private func send(_ c: NWConnection, _ head: String, _ body: Data?) {
        var out = Data(head.utf8)
        if let body { out.append(body) }
        c.send(content: out, completion: .contentProcessed { _ in c.cancel() })
    }

    static func mime(_ ext: String) -> String {
        switch ext {
        case "html": return "text/html; charset=utf-8"
        case "js", "mjs": return "text/javascript; charset=utf-8"
        case "css": return "text/css; charset=utf-8"
        case "json": return "application/json; charset=utf-8"
        case "svg": return "image/svg+xml"
        case "png": return "image/png"
        case "wasm": return "application/wasm"
        case "ttf": return "font/ttf"
        case "webmanifest": return "application/manifest+json"
        case "ico": return "image/x-icon"
        case "txt": return "text/plain; charset=utf-8"
        default: return "application/octet-stream"
        }
    }
}
