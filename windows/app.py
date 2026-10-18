# -*- coding: utf-8 -*-
"""
小柯影音剪輯助手 — Windows 11 桌面版

架構（以領域來切分）：
  AppInfo        應用程式的名稱、版本、資料夾位置
  SaveSession    一次「另存新檔」的過程（網頁把影片分段傳過來，Python 寫進檔案）
  DesktopBridge  網頁可以呼叫的 Python 功能（window.pywebview.api.xxx）
  SelfTest       安裝後自動測試：開啟 App、操作剪輯指令、匯出一小段影片、截圖、寫出報告
  main()         啟動視窗

比喻：網頁版是「剪輯桌」，這支 Python 程式是「工作室的房子」——
它把剪輯桌搬進 Windows 視窗裡，並提供網頁做不到的事，例如直接把檔案存到你指定的資料夾。
畫面使用 Windows 11 內建的 Microsoft Edge WebView2 顯示。
"""
import base64
import json
import os
import sys
import threading
import time
import traceback
import uuid
from pathlib import Path

import webview

APP_NAME = "小柯影音剪輯助手"
APP_VERSION = "1.0.0"
HTTP_PORT = 48123  # 固定埠號，讓瀏覽器儲存的偏好設定每次開啟都還在


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
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
        d = base / "XiaokeVideo"
        d.mkdir(parents=True, exist_ok=True)
        return d

    @staticmethod
    def default_save_dir() -> Path:
        # 預設存到「影片\小柯影音剪輯助手」
        d = Path.home() / "Videos" / APP_NAME
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
        self.forced_save_dir: Path | None = None  # 自我測試時不跳對話框，直接存到這裡

    def attach(self, window):
        self._window = window

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
        os.startfile(str(target))  # noqa: S606 — 只開啟資料夾
        return True


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
      exec('text.add', { text: '匯出測試', start: 0, duration: 2 });
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
            for _ in range(60):
                ready = self.window.evaluate_js("typeof exec === 'function' && !!(window.pywebview && window.pywebview.api && window.pywebview.api.begin_save)")
                if ready:
                    break
                time.sleep(0.5)
            time.sleep(1.5)
            report["edit"] = json.loads(self.window.evaluate_js(self.JS_EDIT))
            self.screenshot("selftest-editor.png")
            self.window.evaluate_js(self.JS_EXPORT_START)
            state = {}
            for _ in range(90):  # 最多等 45 秒
                time.sleep(0.5)
                state = self.window.evaluate_js("window.__kkTest") or {}
                if state.get("state") in ("done", "error"):
                    break
            report["export"] = state
            exported = Path(state.get("path") or "")
            report["export_file_ok"] = bool(state.get("state") == "done" and exported.is_file() and exported.stat().st_size > 1000)
            self.screenshot("selftest-export.png")
            report["ok"] = bool(report["edit"] and report["edit"].get("ok") and report["export_file_ok"])
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

    func = None
    if selftest_path is not None:
        tester = SelfTest(window, bridge, selftest_path)
        func = lambda: threading.Thread(target=tester.run, daemon=True).start()  # noqa: E731

    webview.start(
        func, gui="edgechromium", http_server=True, http_port=HTTP_PORT,
        private_mode=False, storage_path=str(AppInfo.data_dir() / "webview"),
        debug=False,
    )


if __name__ == "__main__":
    main()
