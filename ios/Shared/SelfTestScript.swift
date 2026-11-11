import Foundation

/// 自我測試（iPad 版與 Mac 版共用）：編輯、匯出 2 秒影片、存檔、語音模型、翻譯。
/// 每一步用 appCall('st', …) 記進度，最後 appCall('st_done', 結果 JSON)。
/// only：all（全部）／export（只測匯出）／stt（只測語音與翻譯）／diag（匯出診斷）
func selfTestScript(_ only: String) -> String {
    return """
        (async () => {
          const st = (k) => appCall('st', k), R = { platform: window.XiaokeAppStore, inner: [innerWidth, innerHeight] };
          const only = '\(only)';   // all／export／stt
          try {
            const t0 = Date.now();
            while (typeof exec !== 'function' && Date.now() - t0 < 30000) await new Promise(r => setTimeout(r, 300));
            await st('page ready');
            document.querySelectorAll('.ov').forEach(o => o.hidden = true);
            window.confirm = () => true;
            projNew('App 自我測試', 'hd1080', '30');
            exec('media.place', { mediaId: 'g1' }); exec('timeline.trim', { clipId: UI.sel, end: 2 });
            exec('text.add', { text: '匯出測試', start: 0, duration: 2, preset: 'td1' });
            exec('media.place', { mediaId: 'mu_happy0', track: 'A2', start: 0 }); exec('timeline.trim', { clipId: UI.sel, end: 2 });
            R.clips = doc.clips.length; await st('edit ok ' + R.clips);
            if (only === 'diag') {   // 匯出診斷：錄影功能、支援格式、播放有沒有前進
              R.mr = typeof MediaRecorder; R.cap = typeof HTMLCanvasElement.prototype.captureStream;
              R.mimes = typeof MediaRecorder !== 'undefined' ? ['video/mp4;codecs=avc1,mp4a', 'video/mp4', 'video/webm;codecs=vp8,opus', 'video/webm', 'video/mp4;codecs=hvc1'].filter(m => MediaRecorder.isTypeSupported(m)) : [];
              openExport(); startExport().catch(e => R.startErr = String(e));
              const ph = []; for (let i = 0; i < 8; i++) { await new Promise(r => setTimeout(r, 1000)); ph.push([toSec(UI.playhead).toFixed(2), UI.playing, UI.exporting, rec && rec.state, recChunks.length]); }
              R.ph = ph; R.stat = $('exStat') ? $('exStat').textContent : ''; R.ac = window.ac ? ac.state : (typeof AC !== 'undefined' ? AC.state : '?');
              R.hidden = document.hidden; R.vis = document.visibilityState;
            }
            if (only !== 'stt' && only !== 'diag') {
            openExport(); const e0 = Date.now(); startExport().catch(e => st('export error ' + e));
            while (!recBlob && Date.now() - e0 < 150000) await new Promise(r => setTimeout(r, 300));
            R.exportBytes = recBlob ? recBlob.size : 0; R.exportType = recBlob ? recBlob.type : ''; R.exportMs = Date.now() - e0;
            await st('export ' + R.exportBytes + ' ' + R.exportType);
            R.saved = recBlob ? await saveFile('selftest-export.' + (recMime[2] || 'mp4'), recBlob) : false;
            $('exportOv').hidden = true;
            R.projSaved = await saveFile('selftest.xkp', projSerialize());
            await st('saved ' + R.saved + ' ' + R.projSaved);
            }
            if (only !== 'export' && only !== 'diag' && !sttBlocked()) {
            const t1 = Date.now();
            await sttWorker(); await sttCall({ type: 'load', model: 'tiny' });
            const a = new Float32Array(32000); for (let i = 0; i < a.length; i++) a[i] = Math.sin(i / 8) * .1;
            await sttCall({ type: 'run', audio: a, language: 'chinese' }, [a.buffer]);
            R.sttMs = Date.now() - t1; await st('stt ok ' + R.sttMs);
            R.translation = (await sttTranslate(['Once upon a time, there were three little pigs.'], 'en', TR_LANGS.find(x => x.id === 'zh-TW'), () => {}))[0];
            await st('translation ' + R.translation);
            }
            R.sttBlocked = sttBlocked();   // Intel Mac：語音轉文字停用，不算失敗
            R.ok = R.exportBytes > 1000 && !!R.saved && !!R.projSaved && (R.sttBlocked || /[\\u4e00-\\u9fff]/.test(R.translation || ''));
          } catch (e) { R.error = String(e && e.stack || e); }
          await appCall('st_done', JSON.stringify(R));
        })();
        """
}
