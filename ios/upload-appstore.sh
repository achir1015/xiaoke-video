#!/bin/bash
# 把最近一次 build-appstore.sh 封存的 iPad 版與 Mac 版上傳到 App Store Connect（要在 Mac 的終端機 App 執行）：
#   osascript ios/run-in-terminal.applescript "bash ~/Developer/xiaoke-video/ios/upload-appstore.sh"
# 失敗（例如 session expired）時改用 Xcode Organizer：選封存 → Distribute App → App Store Connect → Upload
cd "$(dirname "$0")"
mkdir -p build
rm -f build/upload.done
exec > >(tee build/upload.log) 2>&1
DIR="$HOME/Library/Developer/Xcode/Archives"
R=ok
for TAG in iPad Mac; do
  A=$(ls -td "$DIR"/*/XiaokeVideo-$TAG-*.xcarchive | head -1)
  echo "== $TAG: $A"
  rm -rf "build/upload-$TAG"
  xcodebuild -exportArchive -archivePath "$A" -exportPath "build/upload-$TAG" \
    -exportOptionsPlist ExportOptions-AppStore.plist -allowProvisioningUpdates || R=fail
done
echo "$R" > build/upload.done
