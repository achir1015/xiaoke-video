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
            if (only === 'shots') {   // App Store 截圖：示範專案（海邊旅行＋雙語字幕＋配樂＋貼圖），拍三個畫面
              const wait = ms => new Promise(r => setTimeout(r, ms));
              const snap = async n => { document.querySelectorAll('.toast').forEach(t => t.hidden = true); clearTimeout(toastTimer); await wait(300); await appCall('snap', n); };
              const B = (k, n) => [...Media.values()].find(m => m.builtin && (k ? m.cat === k : true) && (!n || m.name.includes(n)));
              projNew('20261111_海邊旅行_v01', 'hd1080', '30');
              const intro = B('intro'); if (intro) exec('media.place', { mediaId: intro.id });
              for (const n of ['海洋波浪', '夕陽', '星空']) { const m = B('basic', n); if (m) exec('media.place', { mediaId: m.id }); }
              const total = toSec(seqDur());
              exec('captions.addMany', { items: [{ start: 5.2, end: 9.6, text: '今天出發去海邊旅行' }, { start: 10, end: 14.6, text: '夕陽好美，一起拍照吧' }, { start: 15, end: 19.6, text: '晚上還有滿天星星' }], track: 'T1', y: 88, group: 'demo1' });
              exec('captions.addMany', { items: [{ start: 5.2, end: 9.6, text: 'Off to the beach today' }, { start: 10, end: 14.6, text: 'What a beautiful sunset!' }, { start: 15, end: 19.6, text: 'A sky full of stars tonight' }], track: 'T2', y: 78, group: 'demo2' });
              const mu = [...Media.values()].find(m => m.cat === 'music' && m.sub === 'happy'); if (mu) { exec('media.place', { mediaId: mu.id, track: 'A2', start: 0 }); exec('timeline.trim', { clipId: UI.sel, end: total }); }
              const stk = B('sticker'); if (stk) { exec('media.place', { mediaId: stk.id, track: 'V2', start: 10 }); }
              UI.pps = Math.max(20, Math.min(60, (document.getElementById('tlBody').clientWidth - 40) / total)); renderTimeline();
              const cap = doc.clips.find(c => c.text && c.text.content === '夕陽好美，一起拍照吧');
              UI.sel = cap.id; switchBinTab('intro'); switchTab('props'); seek(sec(11.5)); renderAll(); await wait(2500);
              await snap('shot1-editor');
              // 2：語音轉文字＋翻譯（雙語字幕）核對畫面
              Stt.sources = sttSources(null); if (!Stt.sources.length) Stt.sources = [{ id: 'x', label: 'A2 配樂', clips: [] }];
              openStt(null);
              Stt.result = { items: [
                { start: 5.2, end: 9.6, text: 'Off to the beach today', tr: '今天出發去海邊旅行' },
                { start: 10, end: 14.6, text: 'What a beautiful sunset!', tr: '夕陽好美，一起拍照吧' },
                { start: 15, end: 19.6, text: 'A sky full of stars tonight', tr: '晚上還有滿天星星' },
                { start: 20, end: 23.8, text: 'Thank you for watching', tr: '謝謝收看' },
                { start: 24, end: 27.5, text: 'See you next time', tr: '我們下次見' }], track: 'T1', applied: false, tr: 'zh-TW' };
              $('sttSrc').innerHTML = '<option>V1 主畫面（海邊旅行）</option>';
              $('sttLang').innerHTML = STT_LANGS.map(l => '<option value="' + l.id + '">' + l.name + '</option>').join('');
              $('sttTr').innerHTML = $('sttTrR').innerHTML = TR_LANGS.map(t => '<option value="' + t.id + '">' + t.name + '</option>').join('');
              $('sttLang').value = 'en'; $('sttTr').value = 'zh-TW'; $('sttTrR').value = 'zh-TW'; $('sttTrTrack').value = 'T2';
              $('sttOv').hidden = false; sttRenderReview(); $('sttBar').style.width = '100%';
              $('sttStat').textContent = '辨識完成，共 5 句，已翻譯成繁體中文（台灣）。核對後按「✓ 套用」：原文放 T1、翻譯放 T2。';
              await wait(1500); await snap('shot2-stt');
              $('sttOv').hidden = true; Stt.result = null;
              // 3：調色與素材箱（3D 立體字幕）
              const v = doc.clips.find(c => c.track === 'V1' && c.gen === undefined && Media.get(c.mediaId) && Media.get(c.mediaId).name === '夕陽') || doc.clips.find(c => c.track === 'V1');
              UI.sel = v.id; exec('color.set', { clipId: v.id, look: 'teal' }); switchBinTab('text'); switchTab('color'); seek(sec(12.5)); renderAll(); await wait(2500);
              await snap('shot3-color');
            }
            if (only === 'diag') {   // 匯出診斷：錄影功能、支援格式、播放有沒有前進
              R.mr = typeof MediaRecorder; R.cap = typeof HTMLCanvasElement.prototype.captureStream;
              R.mimes = typeof MediaRecorder !== 'undefined' ? ['video/mp4;codecs=avc1,mp4a', 'video/mp4', 'video/webm;codecs=vp8,opus', 'video/webm', 'video/mp4;codecs=hvc1'].filter(m => MediaRecorder.isTypeSupported(m)) : [];
              openExport(); startExport().catch(e => R.startErr = String(e));
              const ph = []; for (let i = 0; i < 8; i++) { await new Promise(r => setTimeout(r, 1000)); ph.push([toSec(UI.playhead).toFixed(2), UI.playing, UI.exporting, rec && rec.state, recChunks.length]); }
              R.ph = ph; R.stat = $('exStat') ? $('exStat').textContent : ''; R.ac = window.ac ? ac.state : (typeof AC !== 'undefined' ? AC.state : '?');
              R.hidden = document.hidden; R.vis = document.visibilityState;
            }
            if (only !== 'stt' && only !== 'diag' && only !== 'shots') {
            openExport(); const e0 = Date.now(); startExport().catch(e => st('export error ' + e));
            while (!recBlob && Date.now() - e0 < 150000) await new Promise(r => setTimeout(r, 300));
            R.exportBytes = recBlob ? recBlob.size : 0; R.exportType = recBlob ? recBlob.type : ''; R.exportMs = Date.now() - e0;
            await st('export ' + R.exportBytes + ' ' + R.exportType);
            R.saved = recBlob ? await saveFile('selftest-export.' + (recMime[2] || 'mp4'), recBlob) : false;
            $('exportOv').hidden = true;
            R.projSaved = await saveFile('selftest.xkp', projSerialize());
            await st('saved ' + R.saved + ' ' + R.projSaved);
            }
            if (only !== 'export' && only !== 'diag' && only !== 'shots' && !sttBlocked()) {
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
