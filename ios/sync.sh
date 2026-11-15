#!/bin/bash
# 把剪輯程式（專案根目錄的 index.html 等）複製到 ios/web，下載語音轉文字／翻譯用的程式庫到 web/vendor，
# 版本號跟著 version.json，再產生 Xcode 專案。在 Mac 上執行：bash ios/sync.sh
set -e
cd "$(dirname "$0")"
rm -rf web && mkdir -p web/vendor
cp ../index.html ../version.json ../favicon.svg ../favicon-32.png ../favicon-16.png ../apple-touch-icon.png ../manifest.webmanifest web/
cp -R ../icons web/icons
# 程式庫放進 App（App Store 規定不能從網路下載程式碼；模型資料第一次使用時才下載）
mkdir -p vendor-cache
get() { [ -s "vendor-cache/$2" ] || curl -fsSL --retry 3 -o "vendor-cache/$2" "$1"; cp "vendor-cache/$2" "web/vendor/$2"; }
TF=https://cdn.jsdelivr.net/npm/@huggingface/transformers@3.8.1/dist
get "$TF/transformers.min.js" transformers.min.js
get "$TF/ort-wasm-simd-threaded.jsep.mjs" ort-wasm-simd-threaded.jsep.mjs
get "$TF/ort-wasm-simd-threaded.jsep.wasm" ort-wasm-simd-threaded.jsep.wasm
get https://cdn.jsdelivr.net/npm/opencc-js@1.4.2/dist/esm/full.js opencc.js
V=$(python3 -c 'import json;print(json.load(open("../version.json"))["version"])')
# 版本號：1.7.2 → build 10702（每次送審都要比上一次大）
B=$(python3 -c "a,b,c=(int(x) for x in '$V'.split('.'));print(a*10000+b*100+c)")
# 同一版重新送審（例如只改 Mac 版）：XK_BUILD=2 bash sync.sh → build 10702.2
[ -n "$XK_BUILD" ] && B="$B.$XK_BUILD"
sed -i '' "s/MARKETING_VERSION: \".*\"/MARKETING_VERSION: \"$V\"/; s/CURRENT_PROJECT_VERSION: \".*\"/CURRENT_PROJECT_VERSION: \"$B\"/" project.yml
XG=$(command -v xcodegen || echo /usr/local/bin/xcodegen)
"$XG" generate --quiet
echo "web ok, version $V ($B)"
