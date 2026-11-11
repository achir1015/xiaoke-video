#!/bin/bash
# 封存 App Store 版：iPad 版（XiaokeVideo）與 Mac 版（XiaokeVideoMac，原生 macOS，M 系列與 Intel 晶片）。
# 要在 Mac 的登入畫面裡（終端機 App）執行，SSH 進來的話鑰匙圈是鎖的、會簽章失敗：
#   osascript ios/run-in-terminal.applescript "bash ~/Developer/xiaoke-video/ios/build-appstore.sh"
# 封存檔放在 Xcode 的 Archives 資料夾，完成後會打開 Xcode Organizer：選封存 → Distribute App → App Store Connect → Upload。
# 進度寫在 ios/build/appstore.log，完成會留下 ios/build/appstore.done（內容 ok 或 fail）
cd "$(dirname "$0")"
mkdir -p build
rm -f build/appstore.done
exec > >(tee build/appstore.log) 2>&1
set -o pipefail
fail() { echo "fail" > build/appstore.done; exit 1; }
bash sync.sh || fail
DIR="$HOME/Library/Developer/Xcode/Archives/$(date +%Y-%m-%d)"
mkdir -p "$DIR"
STAMP=$(date +%H%M%S)
arc() {   # $1 scheme  $2 destination  $3 名稱
  xcodebuild -project XiaokeVideo.xcodeproj -scheme "$1" -configuration Release \
    -destination "$2" -archivePath "$DIR/XiaokeVideo-$3-$STAMP.xcarchive" \
    -allowProvisioningUpdates archive | grep -E 'error:|warning: .*sign|ARCHIVE' || fail
}
arc XiaokeVideo "generic/platform=iOS" iPad
arc XiaokeVideoMac "generic/platform=macOS" Mac
lipo -archs "$DIR/XiaokeVideo-Mac-$STAMP.xcarchive/Products/Applications/"*.app/Contents/MacOS/* || true
ls -d "$DIR"/XiaokeVideo-*-$STAMP.xcarchive
open -a Xcode; sleep 3; open "$DIR/XiaokeVideo-Mac-$STAMP.xcarchive"   # 打開 Organizer 的封存清單
echo "ok" > build/appstore.done
