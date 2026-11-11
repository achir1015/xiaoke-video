#!/bin/bash
# 在 iPad 模擬器上跑自我測試（不用簽章、可以從 SSH 執行）：bash ios/selftest-sim.sh
# 結果：ios/build/sim-selftest.txt（JSON，ok 為 true 代表編輯、匯出、存檔、語音模型、翻譯都正常）與 sim-selftest.png
cd "$(dirname "$0")"
set -e
bash sync.sh
mkdir -p build
xcodebuild -project XiaokeVideo.xcodeproj -scheme XiaokeVideo -configuration Debug -sdk iphonesimulator \
  -destination 'generic/platform=iOS Simulator' -derivedDataPath build/sim CODE_SIGNING_ALLOWED=NO build | grep -E 'error:|BUILD' 
APP=build/sim/Build/Products/Debug-iphonesimulator/XiaokeVideo.app
DEV=$(xcrun simctl list devices available | grep -E 'iPad Pro 13-inch|iPad Air 13-inch|iPad Pro' | head -1 | grep -oE '[0-9A-F-]{36}')
xcrun simctl boot "$DEV" 2>/dev/null || true
xcrun simctl uninstall "$DEV" com.achir.xiaokevideo 2>/dev/null || true
xcrun simctl install "$DEV" "$APP"
SIMCTL_CHILD_XK_SELFTEST=1 xcrun simctl launch "$DEV" com.achir.xiaokevideo
DOCS=$(xcrun simctl get_app_container "$DEV" com.achir.xiaokevideo data)/Documents
for i in $(seq 1 300); do [ -s "$DOCS/selftest.txt" ] && break; sleep 2; done
sleep 2
cp "$DOCS/selftest.png" build/sim-selftest.png 2>/dev/null || true; cp "$DOCS/selftest-progress.txt" build/sim-progress.txt 2>/dev/null || true; cp "$DOCS/selftest.txt" build/sim-selftest.txt 2>/dev/null || echo "（逾時，沒有結果）" > build/sim-selftest.txt
xcrun simctl io "$DEV" screenshot build/sim-screen.png >/dev/null 2>&1 || true
cat build/sim-progress.txt 2>/dev/null; cat build/sim-selftest.txt; echo
