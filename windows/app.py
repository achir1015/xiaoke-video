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
import urllib.request
import uuid
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
        self.forced_save_dir: Path | None = None  # 自我測試時不跳對話框，直接存到這裡

    def attach(self, window):
        self._window = window
        self._updater.window = window

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
            # 網頁和程式的版本號要一致；更新檢查只記錄結果（沒網路時不算失敗）
            report["version_match"] = self.window.evaluate_js("APP_VERSION") == APP_VERSION
            report["update_check"] = self.bridge.check_update()
            self.window.evaluate_js(self.JS_STT)
            for _ in range(240):   # 最多等 120 秒（第一次要下載約 40MB 的模型）
                time.sleep(0.5)
                report["stt_check"] = self.window.evaluate_js("window.__stt || null")
                if report["stt_check"]:
                    break
            report["ok"] = bool(report["edit"] and report["edit"].get("ok") and report["export_file_ok"] and report["version_match"])
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
    window = webview.create_window(
        APP_NAME, url=str(index), js_api=bridge,
        width=1440, height=900, min_size=(1024, 640),
        background_color="#111417", maximized=selftest_path is None,
    )
    bridge.attach(window)
    try:
        webview.settings["ALLOW_DOWNLOADS"] = True
    except Exception:
        pass

    tester = SelfTest(window, bridge, selftest_path) if selftest_path is not None else None

    def on_start():
        if not IS_MAC:
            DisplayScale.fit(window)
        if tester:
            threading.Thread(target=tester.run, daemon=True).start()

    func = on_start

    # Windows 用 Edge WebView2；Mac 用系統內建的 WebKit（和 Safari 同一個引擎）
    webview.start(
        func, gui=None if IS_MAC else "edgechromium", http_server=True, http_port=HTTP_PORT,
        private_mode=False, storage_path=str(AppInfo.data_dir() / "webview"),
        debug=False,
    )


if __name__ == "__main__":
    main()
