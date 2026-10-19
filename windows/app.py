# -*- coding: utf-8 -*-
"""
小柯影音剪輯助手 — 桌面版（Windows 11 與 macOS 共用這支程式）

架構（以領域來切分）：
  AppInfo        應用程式的名稱、版本、資料夾位置
  SaveSession    一次「另存新檔」的過程（網頁把影片分段傳過來，Python 寫進檔案）
  DesktopBridge  網頁可以呼叫的 Python 功能（window.pywebview.api.xxx）
  Updater        版本更新：查 GitHub Releases 最新版、下載安裝程式、交給它安裝後自動重開
  SelfTest       安裝後自動測試：開啟 App、操作剪輯指令、匯出一小段影片、截圖、寫出報告
  main()         啟動視窗

比喻：網頁版是「剪輯桌」，這支 Python 程式是「工作室的房子」——
它把剪輯桌搬進 Windows 視窗裡，並提供網頁做不到的事，例如直接把檔案存到你指定的資料夾。
畫面使用 Windows 11 內建的 Microsoft Edge WebView2 顯示。
"""
import base64
import http.server
import json
import os
import platform
import subprocess
import sys
import tempfile
import threading
import time
import traceback
import urllib.error
import urllib.parse
import urllib.request
import uuid
from glob import escape as glob_escape
from pathlib import Path

import webview

APP_NAME = "小柯影音剪輯助手"
GITHUB_REPO = "achir1015/xiaoke-video"
HTTP_PORT = 48123  # 固定埠號，讓瀏覽器儲存的偏好設定每次開啟都還在


def _bundled_version() -> str:
    """版本號只寫在 version.json（建置時和網頁一起放進 web 資料夾）。"""
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    try:
        return json.loads((base / "web" / "version.json").read_text(encoding="utf-8"))["version"]
    except Exception:
        return "0.0.0"


APP_VERSION = _bundled_version()
IS_MAC = sys.platform == "darwin"
# Mac 版有 Apple 晶片與 Intel 兩種安裝檔（檔名裡的標記）
MAC_ARCH = "AppleSilicon" if IS_MAC and platform.machine() == "arm64" else "Intel"


class AppInfo:
    """應用程式資訊與資料夾。"""

    @staticmethod
    def resource_dir() -> Path:
        # PyInstaller 打包後，資源檔會放在 _MEIPASS（或執行檔旁的 _internal）
        return Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))

    @staticmethod
    def web_index() -> Path:
        return AppInfo.resource_dir() / "web" / "index.html"

    @staticmethod
    def data_dir() -> Path:
        if IS_MAC:
            base = Path.home() / "Library" / "Application Support"
        else:
            base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
        d = base / "XiaokeVideo"
        d.mkdir(parents=True, exist_ok=True)
        return d

    @staticmethod
    def default_save_dir() -> Path:
        # 預設存到「影片\小柯影音剪輯助手」（Mac 是「影片（Movies）/小柯影音剪輯助手」）
        d = Path.home() / ("Movies" if IS_MAC else "Videos") / APP_NAME
        try:
            d.mkdir(parents=True, exist_ok=True)
        except OSError:
            d = Path.home()
        return d


class SaveSession:
    """一次存檔：先選好路徑，再一段一段把資料寫進暫存檔，最後改名成正式檔案。"""

    def __init__(self, path: Path):
        self.path = path
        self.tmp = path.with_name(path.name + ".part")
        self.fh = open(self.tmp, "wb")
        self.size = 0

    def write(self, b64: str) -> int:
        data = base64.b64decode(b64)
        self.fh.write(data)
        self.size += len(data)
        return self.size

    def finish(self) -> Path:
        self.fh.close()
        if self.path.exists():
            self.path.unlink()
        self.tmp.rename(self.path)
        return self.path

    def abort(self):
        try:
            self.fh.close()
            self.tmp.unlink(missing_ok=True)
        except OSError:
            pass


class DesktopBridge:
    """網頁端透過 window.pywebview.api 呼叫的功能。"""

    def __init__(self):
        self._window = None
        self._sessions: dict[str, SaveSession] = {}
        self._updater = Updater()
        self._stt: dict[str, bytearray] = {}
        self._media = MediaServer()
        self._projects = ProjectStore()
        self.startup_path = ""   # 從檔案總管雙擊 .xkp 開啟時的專案路徑
        self.forced_save_dir: Path | None = None  # 自我測試時不跳對話框，直接存到這裡

    def attach(self, window):
        self._window = window
        self._updater.window = window

    # ---- 專案檔（.xkp）與最近開啟 ----
    PROJECT_TYPES = ("小柯專案 (*.xkp)", "舊版專案 (*.json)", "所有檔案 (*.*)")
    MEDIA_TYPES = ("影片、音樂與圖片 (*.mp4;*.m4v;*.mov;*.webm;*.mkv;*.mp3;*.wav;*.m4a;*.aac;*.ogg;*.flac;*.opus;*.png;*.jpg;*.jpeg;*.gif;*.webp;*.bmp)", "所有檔案 (*.*)")

    def _last_dir(self) -> Path:
        for it in self._projects.recent():
            if it.get("exists"):
                return Path(it["path"]).parent
        return AppInfo.default_save_dir()

    def project_open(self, path: str = ""):
        try:
            if not path:
                if self.forced_save_dir is not None:
                    return {"status": "declined"}
                r = self._window.create_file_dialog(webview.OPEN_DIALOG, directory=str(self._last_dir()), file_types=self.PROJECT_TYPES)
                if not r:
                    return {"status": "declined"}
                path = r if isinstance(r, str) else r[0]
            p = Path(path)
            return {"status": "ok", "path": str(p), "text": p.read_text(encoding="utf-8")}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    def project_save(self, text: str, name: str, path: str = "", save_as: bool = False):
        try:
            safe = "".join(c for c in str(name) if c not in '\\/:*?"<>|').strip() or "我的專案"
            if path and not save_as:
                p = Path(path)
            elif self.forced_save_dir is not None:
                p = self.forced_save_dir / (safe + ProjectStore.EXT)
            else:
                start = Path(path).parent if path else self._last_dir()
                r = self._window.create_file_dialog(webview.SAVE_DIALOG, directory=str(start), save_filename=safe + ProjectStore.EXT, file_types=(self.PROJECT_TYPES[0],))
                if not r:
                    return {"status": "declined"}
                p = Path(r if isinstance(r, str) else r[0])
                if p.suffix.lower() != ProjectStore.EXT:
                    p = p.with_name(p.name + ProjectStore.EXT)
            tmp = p.with_name(p.name + ".part")
            tmp.write_text(text, encoding="utf-8")
            os.replace(tmp, p)
            self._projects.touch(str(p), name)
            return {"status": "ok", "path": str(p)}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    def set_title(self, title: str):
        try:
            self._window.set_title(str(title))
        except Exception:
            pass
        return True

    def project_touch(self, path: str, name: str):
        self._projects.touch(str(path), str(name))
        return True

    def project_recent(self):
        return self._projects.recent()

    def project_recent_remove(self, path: str):
        self._projects.remove(str(path))
        return True

    def project_startup(self):
        p, self.startup_path = self.startup_path, ""
        return p

    # ---- 素材檔：用電腦的「開啟」視窗選檔，記住完整路徑，專案開啟時自動載回 ----
    def media_pick(self):
        r = self._window.create_file_dialog(webview.OPEN_DIALOG, allow_multiple=True, file_types=self.MEDIA_TYPES)
        return [self._media.register(x) for x in (r or [])]

    def media_register(self, path: str):
        return self._media.register(str(path))

    def media_find(self, name: str, folder: str):
        """素材搬家了：在專案所在資料夾（含兩層子資料夾）找同名的檔案。"""
        try:
            base = Path(folder)
            for depth in ("", "*/", "*/*/"):
                for p in base.glob(depth + glob_escape(name)):
                    if p.is_file():
                        return self._media.register(str(p))
        except Exception:
            pass
        return {"exists": False, "name": name}

    # ---- 本機 stt 服務（jianchang512/stt，faster-whisper）：網頁把 16kHz WAV 分段傳來，Python 轉送給 http://127.0.0.1:9977/api ----
    def stt_begin(self):
        token = uuid.uuid4().hex
        self._stt[token] = bytearray()
        return token

    def stt_chunk(self, token: str, b64: str):
        if token not in self._stt:
            return {"status": "error", "message": "工作不存在"}
        self._stt[token] += base64.b64decode(b64)
        return {"status": "ok"}

    def stt_run(self, token: str, model: str, language: str):
        data = self._stt.pop(token, None)
        if data is None:
            return {"status": "error", "message": "工作不存在"}
        return SttClient.transcribe(bytes(data), str(model), str(language))

    def check_update(self):
        return self._updater.check()

    def install_update(self, url: str, version: str):
        return self._updater.install(str(url), str(version))

    def update_status(self):
        return self._updater.status

    def app_info(self):
        return {"name": APP_NAME, "version": APP_VERSION, "platform": sys.platform,
                "saveDir": str(AppInfo.default_save_dir())}

    def begin_save(self, filename: str):
        try:
            filename = "".join(c for c in str(filename) if c not in '\\/:*?"<>|').strip() or "小柯作品"
            if self.forced_save_dir is not None:
                path = self.forced_save_dir / filename
            else:
                ext = Path(filename).suffix.lstrip(".") or "*"
                result = self._window.create_file_dialog(
                    webview.SAVE_DIALOG,
                    directory=str(AppInfo.default_save_dir()),
                    save_filename=filename,
                    file_types=(f"{ext.upper()} 檔案 (*.{ext})", "所有檔案 (*.*)"),
                )
                if not result:
                    return {"status": "declined"}
                path = Path(result if isinstance(result, str) else result[0])
            token = uuid.uuid4().hex
            self._sessions[token] = SaveSession(path)
            return {"status": "ok", "token": token, "path": str(path)}
        except Exception as e:  # 回傳錯誤給網頁顯示，不讓程式當掉
            return {"status": "error", "message": str(e)}

    def write_chunk(self, token: str, b64: str):
        s = self._sessions.get(token)
        if not s:
            return {"status": "error", "message": "存檔工作不存在"}
        return {"status": "ok", "size": s.write(b64)}

    def end_save(self, token: str):
        s = self._sessions.pop(token, None)
        if not s:
            return {"status": "error", "message": "存檔工作不存在"}
        p = s.finish()
        return {"status": "ok", "path": str(p), "size": s.size}

    def open_folder(self, path: str = ""):
        target = Path(path) if path else AppInfo.default_save_dir()
        if target.is_file():
            target = target.parent
        if IS_MAC:
            subprocess.Popen(["open", str(target)])
        else:
            os.startfile(str(target))  # noqa: S606 — 只開啟資料夾
        return True


class MediaServer:
    """把電腦裡的影片、音樂、圖片交給網頁播放（只開放使用者選過的檔案）。
    支援分段讀取（拖動播放頭、跳著看都順），並允許網頁讀取畫面（調色、去背、匯出需要）。"""

    TYPES = {".mp4": "video/mp4", ".m4v": "video/mp4", ".mov": "video/quicktime", ".webm": "video/webm", ".mkv": "video/x-matroska",
             ".mp3": "audio/mpeg", ".wav": "audio/wav", ".m4a": "audio/mp4", ".aac": "audio/aac", ".ogg": "audio/ogg", ".flac": "audio/flac", ".opus": "audio/ogg",
             ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".gif": "image/gif", ".webp": "image/webp", ".bmp": "image/bmp"}

    def __init__(self):
        self.files: dict[str, Path] = {}
        self.tokens: dict[str, str] = {}
        server = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_OPTIONS(self):
                self.send_response(204)
                self._cors()
                self.end_headers()

            def _cors(self):
                self.send_header("Access-Control-Allow-Origin", "*")
                self.send_header("Access-Control-Allow-Headers", "Range")
                self.send_header("Access-Control-Expose-Headers", "Content-Length, Content-Range, Accept-Ranges")

            def do_HEAD(self):
                self.do_GET(head=True)

            def do_GET(self, head=False):
                parts = self.path.split("/")
                p = server.files.get(parts[2]) if len(parts) > 2 and parts[1] == "m" else None
                if not p or not p.is_file():
                    self.send_response(404)
                    self._cors()
                    self.end_headers()
                    return
                size = p.stat().st_size
                start, end = 0, size - 1
                rng = self.headers.get("Range", "")
                if rng.startswith("bytes="):
                    a, _, b = rng[6:].split(",")[0].partition("-")
                    if a:
                        start, end = int(a), int(b) if b else size - 1
                    elif b:
                        start = max(0, size - int(b))
                    end = min(end, size - 1)
                    self.send_response(206)
                    self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
                else:
                    self.send_response(200)
                self.send_header("Content-Type", MediaServer.TYPES.get(p.suffix.lower(), "application/octet-stream"))
                self.send_header("Content-Length", str(end - start + 1))
                self.send_header("Accept-Ranges", "bytes")
                self._cors()
                self.end_headers()
                if head:
                    return
                try:
                    with open(p, "rb") as fh:
                        fh.seek(start)
                        left = end - start + 1
                        while left > 0:
                            chunk = fh.read(min(1024 * 1024, left))
                            if not chunk:
                                break
                            self.wfile.write(chunk)
                            left -= len(chunk)
                except (ConnectionError, OSError):
                    pass   # 播放器常常中途改讀別的位置，連線被關掉是正常的

        self.httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.httpd.daemon_threads = True
        self.port = self.httpd.server_address[1]
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def register(self, path: str) -> dict:
        p = Path(path)
        if not p.is_file():
            return {"exists": False, "path": str(p), "name": p.name}
        key = str(p.resolve())
        token = self.tokens.get(key)
        if not token:
            token = uuid.uuid4().hex
            self.tokens[key] = token
            self.files[token] = p
        return {"exists": True, "path": key, "name": p.name, "size": p.stat().st_size,
                "url": f"http://127.0.0.1:{self.port}/m/{token}/{urllib.parse.quote(p.name)}"}


class WebServer:
    """提供 App 的網頁（固定埠號，瀏覽器裡的偏好設定與下載過的語音模型才會一直在）。
    每次都要求瀏覽器重新確認檔案（no-cache），更新後馬上看到新版，不會用到舊的快取。"""

    def __init__(self, folder: Path, port: int):
        class Handler(http.server.SimpleHTTPRequestHandler):
            extensions_map = {**http.server.SimpleHTTPRequestHandler.extensions_map, ".webmanifest": "application/manifest+json", ".js": "text/javascript", ".json": "application/json", ".svg": "image/svg+xml"}

            def __init__(self, *a, **kw):
                super().__init__(*a, directory=str(folder), **kw)

            def end_headers(self):
                self.send_header("Cache-Control", "no-cache")
                super().end_headers()

            def log_message(self, *a):
                pass

        class Server(http.server.ThreadingHTTPServer):
            allow_reuse_address = False   # Windows 預設會讓兩個程式共用同一個埠，網頁可能被舊的小柯回應

        try:
            self.httpd = Server(("127.0.0.1", port), Handler)
        except OSError:   # 埠號被占用（例如已經開著另一個小柯）就換一個空的
            self.httpd = Server(("127.0.0.1", 0), Handler)
        self.httpd.daemon_threads = True
        self.port = self.httpd.server_address[1]
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()


class ProjectStore:
    """專案檔（.xkp）與「最近開啟」清單（記錄路徑、專案名稱、時間，存在使用者資料夾的 recent.json）。"""

    EXT = ".xkp"
    MAX_RECENT = 15

    def __init__(self):
        self.file = AppInfo.data_dir() / "recent.json"
        self.lock = threading.Lock()   # 網頁可能同時呼叫好幾次（各在自己的執行緒），讀寫要排隊

    def _read(self) -> list:
        try:
            return json.loads(self.file.read_text(encoding="utf-8"))
        except Exception:
            return []

    def _write(self, items: list):
        tmp = self.file.with_name(self.file.name + ".part")
        tmp.write_text(json.dumps(items, ensure_ascii=False, indent=1), encoding="utf-8")
        os.replace(tmp, self.file)   # 一次換掉整個檔案，讀的人不會讀到寫一半的內容

    def recent(self) -> list:
        with self.lock:
            items = self._read()
        for it in items:
            it["exists"] = Path(it.get("path", "")).is_file()
        return items

    def touch(self, path: str, name: str):
        with self.lock:
            items = [it for it in self._read() if it.get("path") != path]
            items.insert(0, {"path": path, "name": name or Path(path).stem, "time": time.strftime("%Y-%m-%d %H:%M")})
            self._write(items[: self.MAX_RECENT])

    def remove(self, path: str):
        with self.lock:
            self._write([it for it in self._read() if it.get("path") != path])


class SttClient:
    """呼叫本機 stt 服務的 /api（回傳 json：[{line, start_time "時:分:秒,毫秒", end_time, text}]），轉成秒數。"""

    URL = "http://127.0.0.1:9977/api"

    @staticmethod
    def _sec(t: str) -> float:
        h, m, s = str(t).replace(",", ".").split(":")
        return int(h) * 3600 + int(m) * 60 + float(s)

    @classmethod
    def transcribe(cls, wav: bytes, model: str, language: str):
        boundary = "----xiaoke" + uuid.uuid4().hex
        parts = []
        for k, v in (("model", model), ("language", language), ("response_format", "json")):
            parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode())
        parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="xiaoke.wav"\r\nContent-Type: audio/wav\r\n\r\n'.encode() + wav + b"\r\n")
        parts.append(f"--{boundary}--\r\n".encode())
        req = urllib.request.Request(cls.URL, data=b"".join(parts), headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
        try:
            with urllib.request.urlopen(req, timeout=3600) as r:
                res = json.load(r)
        except urllib.error.URLError as e:
            return {"status": "error", "message": f"連不到本機 stt 服務（{e.reason}）。請先執行 stt 的 start.exe，確認網址是 127.0.0.1:9977"}
        except Exception as e:
            return {"status": "error", "message": str(e)}
        if res.get("code") != 0:
            return {"status": "error", "message": f"stt 回報錯誤：{res.get('msg')}"}
        items = [{"start": cls._sec(x["start_time"]), "end": cls._sec(x["end_time"]), "text": x.get("text", "")} for x in (res.get("data") or [])]
        return {"status": "ok", "items": items}


class Updater:
    """版本更新：問 GitHub 最新版本 → 下載安裝程式 → 交給它安裝（裝好會自動重開），App 自己先關閉。
    Mac：下載對應晶片的 .dmg 並打開，使用者把 App 拖進「應用程式」覆蓋舊版（未簽章的 App 無法自動替換）。"""

    @staticmethod
    def wanted(name: str) -> bool:
        n = name.lower()
        return n.endswith(".dmg") and MAC_ARCH.lower() in n if IS_MAC else n.endswith(".exe")

    API = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
    DOWNLOAD_PREFIX = f"https://github.com/{GITHUB_REPO}/releases/download/"

    def __init__(self):
        self.window = None
        self.status = {"state": "idle", "pct": 0}

    def check(self):
        try:
            req = urllib.request.Request(self.API, headers={"Accept": "application/vnd.github+json", "User-Agent": "XiaokeVideo/" + APP_VERSION})
            with urllib.request.urlopen(req, timeout=15) as r:
                rel = json.load(r)
            asset = next((a for a in rel.get("assets", []) if self.wanted(a.get("name", ""))), None)
            notes = (rel.get("body") or "").split("## 下載安裝")[0].strip()   # 只留「更新內容」，安裝說明不顯示
            return {"status": "ok", "current": APP_VERSION, "platform": "mac" if IS_MAC else "windows", "latest": str(rel.get("tag_name", "")).lstrip("vV"),
                    "notes": notes, "date": (rel.get("published_at") or "")[:10],
                    "url": asset["browser_download_url"] if asset else "", "page": rel.get("html_url", "")}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    def install(self, url: str, version: str):
        if not url.startswith(self.DOWNLOAD_PREFIX):   # 只接受本專案 Releases 的安裝檔
            return {"status": "error", "message": "更新網址不正確"}
        if self.status["state"] in ("downloading", "launching"):
            return {"status": "ok"}
        self.status = {"state": "downloading", "pct": 0}
        threading.Thread(target=self._run, args=(url, version), daemon=True).start()
        return {"status": "ok"}

    def _run(self, url: str, version: str):
        try:
            name = url.rsplit("/", 1)[-1] or f"XiaokeVideo-Setup-{version}.exe"
            name = "".join(ch for ch in name if ch not in '\\/:*?"<>|')
            dest = Path(tempfile.gettempdir()) / name
            req = urllib.request.Request(url, headers={"User-Agent": "XiaokeVideo/" + APP_VERSION})
            with urllib.request.urlopen(req, timeout=60) as r, open(dest, "wb") as fh:
                total, done = int(r.headers.get("Content-Length") or 0), 0
                while chunk := r.read(256 * 1024):
                    fh.write(chunk)
                    done += len(chunk)
                    if total:
                        self.status = {"state": "downloading", "pct": int(done * 100 / total)}
            if dest.stat().st_size < 1_000_000:
                raise RuntimeError("下載的安裝檔不完整")
            if IS_MAC:
                subprocess.Popen(["open", str(dest)])   # 掛載 .dmg，出現「拖到應用程式」視窗
                self.status = {"state": "manual", "pct": 100}
                return
            self.status = {"state": "launching", "pct": 100}
            # /relaunch=1：安裝程式裝完後自動重新開啟小柯（見 installer.iss）
            subprocess.Popen([str(dest), "/SILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/CURRENTUSER", "/relaunch=1"],
                             creationflags=0x00000008 | 0x00000200, close_fds=True)   # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
            time.sleep(1.5)
            try:
                self.window.destroy()
            finally:
                time.sleep(.5)
                os._exit(0)
        except Exception as e:
            self.status = {"state": "error", "pct": 0, "message": str(e)}


class DisplayScale:
    """讓桌面版和線上版的版面一樣。

    Windows「協助工具 → 文字大小」（例如 210%）會讓 WebView2 把整頁放大，
    網頁寬度掉到 980px 以下就變成手機版單欄。這裡把放大倍率限制在
    「網頁寬度至少 MIN_CSS_WIDTH」的範圍內，維持三欄版面（1920 寬螢幕約 1.4 倍）。
    """

    MIN_CSS_WIDTH = 1366

    @staticmethod
    def fit(window):
        try:
            info = None
            for _ in range(40):
                info = window.evaluate_js("[innerWidth, devicePixelRatio]")
                if info:
                    break
                time.sleep(0.25)
            css_width, dpr = info
            physical = css_width * dpr
            target = max(1.0, min(dpr, physical / DisplayScale.MIN_CSS_WIDTH))
            zoom = round(target / dpr, 3)
            if abs(zoom - 1) < 0.01:
                return
            from System import Action  # pythonnet，pywebview 在 Windows 已載入
            form = window.native
            control = form.browser.webview
            form.Invoke(Action(lambda: setattr(control, "ZoomFactor", zoom)))
        except Exception:
            pass  # 調不了就維持原樣，不影響使用


class SelfTest:
    """安裝後測試：xiaoke.exe --selftest 報告路徑.json"""

    # 在網頁裡執行的測試步驟（同步，回傳 JSON 字串）
    JS_EDIT = r"""
    (function () {
      const r = { steps: [] };
      const step = (name, fn) => { try { const v = fn(); r.steps.push({ name, ok: true, info: String(v ?? '') }); } catch (e) { r.steps.push({ name, ok: false, info: String(e && e.message || e) }); } };
      step('載入範例專案', () => doc.clips.length + ' 個片段');
      step('素材庫數量', () => { const n = k => [...Media.values()].filter(m => m.cat === k).length; const s = `片頭${n('intro')} 片尾${n('outro')} 圖檔${n('sticker')} 基本${n('basic')}`; if (n('intro') !== 20 || n('outro') !== 20 || n('sticker') !== 30 || n('basic') !== 30) throw new Error(s); return s; });
      step('放上片頭', () => exec('media.place', { mediaId: 'intro4' }));
      step('改片頭標題', () => exec('gen.set', { title: 'Windows 11 測試' }));
      step('貼圖到疊加軌', () => { seek(sec(5)); return exec('media.place', { mediaId: 's8' }); });
      step('加字幕到空的軌', () => exec('text.add', { text: '桌面版字幕測試', start: 5 }));
      step('字幕動畫', () => exec('text.anim', { in: 'typewriter', out: 'fade' }));
      step('全部轉場', () => exec('clip.transition', { all: true, type: 'crossfade', duration: 1 }));
      step('分割', () => { seek(sec(2)); return exec('timeline.split', {}); });
      step('復原／重做', () => undo() + '／' + redo());
      step('新素材庫數量', () => { const n = k => [...Media.values()].filter(m => m.cat === k).length; const s = `蒙版${MASKS.length} 綠幕${n('green')} 配樂${n('music')} 字幕樣式${TEXT_PRESETS.length}`; if (MASKS.length !== 30 || n('green') !== 20 || n('music') !== 110 || TEXT_PRESETS.length !== 12) throw new Error(s); return s; });
      step('綠幕自動去背', () => { seek(sec(1)); const r = exec('media.place', { mediaId: 'gs3' }); if (!getClip(UI.sel).key?.on) throw new Error('沒有自動開啟去背'); draw(sec(1.5)); return r; });
      step('蒙版', () => { const r = exec('clip.mask', { clipId: UI.sel, mask: 'heart', feather: 10 }); draw(sec(1.5)); return r; });
      step('3D 立體字幕', () => { const r = exec('text.add', { text: '3D 測試', start: 1, preset: 'td3' }); draw(sec(2)); return r; });
      step('逐字稿批次字幕＋統一樣式', () => { exec('captions.addMany', { items: [{ start: 1, end: 2, text: '第一句' }, { start: 2.5, end: 4, text: '第二句' }], track: 'T3', group: 'selftest' }); const c = doc.clips.find(x => x.text?.group === 'selftest');
        exec('text.set', { clipId: c.id, size: 8, color: '#ffd400', bgColor: '#123456', bgOpacity: 70 }); const r = exec('text.applyStyle', { clipId: c.id, scope: 'group' });
        const g = doc.clips.filter(x => x.text?.group === 'selftest'); if (g.some(x => x.text.color !== '#ffd400' || x.text.bgColor !== '#123456') || g.map(x => x.text.content).join() !== '第一句,第二句') throw new Error('樣式或文字不對'); return r; });
      step('網頁版本號', () => APP_VERSION);
      step('畫面合成', () => { draw(sec(2)); const p = ctx.getImageData(cv.width / 2, cv.height / 2, 1, 1).data; return [...p].join(','); });
      step('錄影格式', () => { const ok = MIMES.filter(m => window.MediaRecorder && MediaRecorder.isTypeSupported(m[0])).map(m => m[1]); if (!ok.length) throw new Error('不支援錄影'); return ok.join('、'); });
      step('桌面存檔通道', () => { if (!(window.pywebview && window.pywebview.api && window.pywebview.api.begin_save)) throw new Error('沒有連上 Python'); return 'OK'; });
      r.ok = r.steps.every(s => s.ok);
      return JSON.stringify(r);
    })()
    """

    # 匯出測試：做一支 2 秒的小影片並透過桌面存檔通道寫到測試資料夾
    JS_EXPORT_START = r"""
    (function () {
      doc.clips = []; UI.sel = null;
      exec('media.place', { mediaId: 'g1' });
      exec('timeline.trim', { clipId: UI.sel, end: 2 });
      exec('text.add', { text: '匯出測試', start: 0, duration: 2, preset: 'td1' });
      exec('media.place', { mediaId: 'mu_happy0', track: 'A2', start: 0 });   // 程式合成的配樂也要錄進影片
      exec('timeline.trim', { clipId: UI.sel, end: 2 });
      openExport();
      window.__kkTest = { state: 'running' };
      startExport().catch(e => { window.__kkTest = { state: 'error', msg: String(e) }; });
      const iv = setInterval(async () => {
        if (recBlob && window.__kkTest.state === 'running') {
          clearInterval(iv); window.__kkTest.state = 'saving';
          try {
            const p = await desktopSave('selftest-export.' + recMime[2], recBlob);
            window.__kkTest = { state: 'done', size: recBlob.size, path: p, mime: recMime[1] };
          } catch (e) { window.__kkTest = { state: 'error', msg: String(e) }; }
        }
      }, 300);
      return 'started';
    })()
    """

    # 語音轉文字引擎：載入最小的 Whisper 模型並辨識 2 秒聲音（需要網路下載模型；只記錄結果，不影響測試通過與否）
    JS_STT = r"""
    (async () => { try { const t0 = performance.now(); await sttWorker(); await sttCall({ type: 'load', model: 'tiny' });
        const a = new Float32Array(32000); for (let i = 0; i < a.length; i++) a[i] = Math.sin(i / 8) * .1;
        const r = await sttCall({ type: 'run', audio: a, language: 'chinese' }, [a.buffer]); window.__stt = { ok: true, ms: Math.round(performance.now() - t0), chunks: r.chunks.length };
      } catch (e) { window.__stt = { ok: false, msg: String(e && e.message || e) }; } })(); 'started'
    """

    # 專案檔來回測試：用完整路徑匯入剛匯出的影片 → 編輯 → 另存 .xkp → 開新專案 → 重新開啟，檢查片段、素材、畫面狀態、最近開啟
    JS_PROJECT = r"""
    (async () => { const R = {}; try {
        const api = window.pywebview.api, info = await api.media_register(%PATH%);
        const [m] = await importPaths([info]); if (!m) throw new Error('用路徑匯入影片失敗');
        doc.clips = []; exec('media.place', { mediaId: m.id, track: 'V1', start: 0 }); const cid = UI.sel;
        exec('color.set', { clipId: cid, look: 'mono' }); exec('text.add', { text: '專案測試', start: 0, preset: 'td2' }); UI.sel = cid;
        seek(sec(1)); await new Promise(r => setTimeout(r, 800)); draw(UI.playhead); ctx.getImageData(0, 0, 1, 1);   // 本機檔案畫到畫布後仍可讀取
        const before = JSON.stringify(doc.clips); UI.pps = 123;
        if (!(await projSave(true))) throw new Error('儲存失敗'); const path = Proj.path; R.file = path.split(/[\\/]/).pop();
        Proj.dirty = false; projNew('空白專案', 'hd720'); if (doc.clips.length) throw new Error('新專案不是空的');
        await projOpenPath(path);
        R.clips = JSON.stringify(doc.clips) === before; R.media = Media.get(m.id)?.path === m.path; R.ui = UI.pps === 123 && UI.sel === cid;
        R.recent = (await api.project_recent()).some(x => x.path === path); await api.project_recent_remove(path);
        R.ok = R.clips && R.media && R.ui && R.recent && R.file.endsWith('.xkp');
      } catch (e) { R.ok = false; R.msg = String(e && e.message || e); } window.__proj = R; })(); 'started'
    """

    def __init__(self, window, bridge: DesktopBridge, report_path: Path):
        self.window = window
        self.bridge = bridge
        self.report_path = report_path
        self.out_dir = report_path.parent
        bridge.forced_save_dir = self.out_dir

    def run(self):
        report = {"app": APP_NAME, "version": APP_VERSION, "ok": False, "edit": None, "export": None, "error": None}
        try:
            # 等網頁與 pywebview API 都就緒
            for _ in range(180):   # 最多等 90 秒（慢的雲端電腦載入比較久）
                ready = self.window.evaluate_js("typeof exec === 'function' && !!(window.pywebview && window.pywebview.api && window.pywebview.api.begin_save)")
                if ready:
                    break
                time.sleep(0.5)
            time.sleep(1.5)
            edit = None
            for _ in range(3):     # 偶爾第一次呼叫拿不到結果，再試兩次
                edit = self.window.evaluate_js(self.JS_EDIT)
                if edit:
                    break
                time.sleep(3)
            report["edit"] = json.loads(edit) if edit else {"ok": False, "steps": [], "note": "網頁沒有回傳測試結果"}
            self.screenshot("selftest-editor.png")
            self.window.evaluate_js(self.JS_EXPORT_START)
            state = {}
            for _ in range(360):  # 最多等 180 秒（含產生配樂；Intel Mac 雲端電腦比較慢）
                time.sleep(0.5)
                state = self.window.evaluate_js("window.__kkTest") or {}
                if state.get("state") in ("done", "error"):
                    break
            report["export"] = state
            exported = Path(state.get("path") or "")
            report["export_file_ok"] = bool(state.get("state") == "done" and exported.is_file() and exported.stat().st_size > 1000)
            self.screenshot("selftest-export.png")
            report["project"] = {"ok": False, "msg": "沒有匯出檔可測"}
            if report["export_file_ok"]:
                self.window.evaluate_js(self.JS_PROJECT.replace("%PATH%", json.dumps(str(exported))))
                for _ in range(120):
                    time.sleep(0.5)
                    r = self.window.evaluate_js("window.__proj || null")
                    if r:
                        report["project"] = r
                        break
            # 網頁和程式的版本號要一致；更新檢查只記錄結果（沒網路時不算失敗）
            report["version_match"] = self.window.evaluate_js("APP_VERSION") == APP_VERSION
            report["update_check"] = self.bridge.check_update()
            self.window.evaluate_js(self.JS_STT)
            for _ in range(240):   # 最多等 120 秒（第一次要下載約 40MB 的模型）
                time.sleep(0.5)
                report["stt_check"] = self.window.evaluate_js("window.__stt || null")
                if report["stt_check"]:
                    break
            report["ok"] = bool(report["edit"] and report["edit"].get("ok") and report["export_file_ok"] and report["version_match"] and report["project"].get("ok"))
        except Exception:
            report["error"] = traceback.format_exc()
        finally:
            self.report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
            try:
                self.window.destroy()
            except Exception:
                os._exit(0 if report["ok"] else 1)

    def screenshot(self, name: str):
        try:
            from PIL import ImageGrab
            ImageGrab.grab().save(self.out_dir / name)
        except Exception as e:
            (self.out_dir / (name + ".txt")).write_text(str(e), encoding="utf-8")


def main():
    args = sys.argv[1:]
    selftest_path = None
    if "--selftest" in args:
        i = args.index("--selftest")
        selftest_path = Path(args[i + 1] if i + 1 < len(args) else "selftest.json").resolve()
        selftest_path.parent.mkdir(parents=True, exist_ok=True)
    if "--version" in args:
        print(f"{APP_NAME} {APP_VERSION}")
        return

    index = AppInfo.web_index()
    if not index.is_file():
        raise SystemExit(f"找不到網頁檔案：{index}")

    bridge = DesktopBridge()
    # 在檔案總管／Finder 雙擊 .xkp：專案路徑會當成參數傳進來
    bridge.startup_path = next((a for a in args if not a.startswith("--") and a.lower().endswith((ProjectStore.EXT, ".json")) and Path(a).is_file()), "")
    window = webview.create_window(
        APP_NAME, url=f"http://127.0.0.1:{WebServer(index.parent, HTTP_PORT).port}/index.html?v={APP_VERSION}", js_api=bridge,
        width=1440, height=900, min_size=(1024, 640),
        background_color="#111417", maximized=selftest_path is None,
    )
    bridge.attach(window)
    try:
        webview.settings["ALLOW_DOWNLOADS"] = True
    except Exception:
        pass

    tester = SelfTest(window, bridge, selftest_path) if selftest_path is not None else None

    # 拖曳檔案進視窗：pywebview 會補上完整路徑，交給網頁匯入（專案就能記住檔案位置）
    def on_loaded():
        try:
            from webview.dom import DOMEventHandler

            def on_drop(e):
                paths = [f.get("pywebviewFullPath") for f in (e.get("dataTransfer") or {}).get("files", []) if f.get("pywebviewFullPath")]
                if paths:
                    items = [bridge.media_register(p) for p in paths]
                    window.evaluate_js(f"window.kkDropPaths && kkDropPaths({json.dumps(items, ensure_ascii=False)})")

            window.dom.document.events.drop += DOMEventHandler(on_drop, prevent_default=True)
        except Exception:
            pass   # 舊版 pywebview 沒有這個功能：拖曳的檔案就不會記住路徑

    window.events.loaded += on_loaded

    def on_start():
        if not IS_MAC:
            DisplayScale.fit(window)
        if tester:
            threading.Thread(target=tester.run, daemon=True).start()

    func = on_start

    # Windows 用 Edge WebView2；Mac 用系統內建的 WebKit（和 Safari 同一個引擎）
    webview.start(
        func, gui=None if IS_MAC else "edgechromium",
        private_mode=False, storage_path=str(AppInfo.data_dir() / "webview"),
        debug=False,
    )


if __name__ == "__main__":
    main()
