#!/data/data/com.termux/files/usr/bin/bash
# =====================================================================
#  YouTube 逐字稿工具 — Android (Termux) 一鍵安裝
#  用法：在 Termux 裡執行
#        pkg install -y git
#        git clone https://github.com/door410/transcript.git
#        bash transcript/android/android-setup.sh
#
#  之後要更新：進 transcript 資料夾執行 git pull，再跑一次這個腳本。
# =====================================================================
set -u

APP_DIR="$HOME/ytscript"
SHORTCUT_DIR="$HOME/.shortcuts"

echo
echo "======================================================"
echo "  YouTube 逐字稿工具 — Android 安裝"
echo "======================================================"
echo

# --- 1. 確認在 Termux 環境 ------------------------------------------
if [ ! -d "/data/data/com.termux" ]; then
    echo "  [錯誤] 這個腳本必須在 Termux App 裡執行。"
    exit 1
fi

# --- 2. 安裝系統套件 ------------------------------------------------
echo "[1/6] 安裝系統套件（首次約需 3～5 分鐘）…"
pkg update -y >/dev/null 2>&1
# ffmpeg 是必要的，不是可選的：手機端的 AI 聽寫走 whisper.cpp，
# 而它只吃 16kHz 單聲道 WAV，要靠 ffmpeg 轉檔。
pkg install -y python termux-api unzip ffmpeg >/dev/null 2>&1

if ! command -v python >/dev/null 2>&1; then
    echo "  [錯誤] Python 安裝失敗。請確認網路連線後重試。"
    exit 1
fi
echo "      Python $(python --version 2>&1 | awk '{print $2}') 已就緒"
if command -v ffmpeg >/dev/null 2>&1; then
    echo "      ffmpeg 已就緒"
else
    echo "      [警告] ffmpeg 安裝失敗 —— 沒有字幕的影片將無法聽寫。"
    echo "             稍後可手動執行：pkg install ffmpeg"
fi

# --- 3. 安裝 Python 套件 --------------------------------------------
echo "[2/6] 安裝必要套件…"
pip install --quiet --upgrade pip >/dev/null 2>&1
pip install --quiet --upgrade youtube-transcript-api yt-dlp
if ! python -c "import youtube_transcript_api, yt_dlp" >/dev/null 2>&1; then
    echo "  [錯誤] 套件安裝失敗。請執行以下指令看詳細訊息："
    echo "         pip install youtube-transcript-api yt-dlp"
    exit 1
fi
echo "      youtube-transcript-api 與 yt-dlp 已就緒"

# --- 2b. 聽寫引擎 ---------------------------------------------------
# Android 沒有 CTranslate2 的預編譯套件，所以 faster-whisper 用不了，
# 手機端改走 whisper.cpp。termux-stt 提供 ARM64 的預編譯執行檔。
# 少了這一步，手機上「沒有字幕的影片」會 100% 失敗，
# 而且錯誤訊息只會說「找不到 whisper.cpp 執行檔」，看不出是安裝沒做完。
echo "[3/6] 安裝 AI 聽寫引擎（沒有字幕的影片才會用到）…"
pip install --quiet --upgrade termux-stt 2>/dev/null
if python -c "import termux_stt" >/dev/null 2>&1; then
    echo "      whisper.cpp（termux-stt）已就緒"
else
    echo "      [警告] termux-stt 安裝失敗。"
    echo "             有字幕的影片仍然完全正常，只有「沒字幕的影片」"
    echo "             無法用 AI 聽寫。稍後可手動執行："
    echo "               pip install termux-stt"
fi

# --- 4. 找出並複製程式檔案 ------------------------------------------
echo "[4/6] 尋找程式檔案…"
SRC=""
HERE="$(cd "$(dirname "$0")" 2>/dev/null && pwd || echo .)"

# 優先使用單一 zip 安裝包（只要下載一個檔案，最省事）
for z in /sdcard/Download/手機安裝包.zip \
         /storage/emulated/0/Download/手機安裝包.zip \
         "$HERE/手機安裝包.zip" ; do
    if [ -f "$z" ]; then
        echo "      找到安裝包：$z"
        TMP="$HOME/.ytscript_unzip"
        rm -rf "$TMP"; mkdir -p "$TMP"
        if unzip -oq "$z" -d "$TMP" 2>/dev/null; then
            SRC="$TMP"; echo "      已解壓縮"
        else
            echo "      解壓縮失敗，改用個別檔案"
        fi
        break
    fi
done

# 沒有 zip 時，才逐一尋找個別檔案
# "$HERE/.." 要排最前面：這個腳本住在 android/ 子目錄，程式檔在上一層，
# 所以 git clone 或解壓 GitHub 原始碼 zip 之後，正確的來源是父目錄。
if [ -z "$SRC" ]; then
for d in "$HERE/.." "$HERE" \
         /sdcard/Download /storage/emulated/0/Download \
         /sdcard/Documents /storage/emulated/0/Documents \
         /sdcard/Download/YouTube逐字稿工具 \
         /storage/emulated/0/Download/YouTube逐字稿工具 \
         /sdcard ; do
    if [ -f "$d/ytscript.py" ] && [ -f "$d/ui.html" ] && [ -f "$d/tokens.css" ]; then
        SRC="$d"; break
    fi
done
fi

if [ -z "$SRC" ]; then
    echo
    echo "  [錯誤] 找不到安裝檔案。"
    echo
    echo "  最簡單的做法（建議）："
    echo "    pkg install -y git"
    echo "    git clone https://github.com/door410/transcript.git"
    echo "    bash transcript/android/android-setup.sh"
    echo
    echo "  或者用檔案傳輸的方式："
    echo "    1. 在 Termux 執行：termux-setup-storage   （然後按「允許」）"
    echo "    2. 把「手機安裝包.zip」放到手機的「下載」資料夾"
    echo
    echo "  完成後重新執行這個腳本。"
    exit 1
fi
echo "      找到了：$SRC"

mkdir -p "$APP_DIR"
cp "$SRC/ytscript.py" "$SRC/ui.html" "$SRC/tokens.css" "$APP_DIR/"
# PWA 圖示與 manifest（有了才能「加到主畫面」變成真正的 App 圖示）
for f in manifest.json icon-192.png icon-512.png icon-maskable.png; do
    [ -f "$SRC/$f" ] && cp "$SRC/$f" "$APP_DIR/"
done
echo "[5/6] 已安裝到 $APP_DIR"

# --- 5. 建立桌面捷徑（Termux:Widget）--------------------------------
mkdir -p "$SHORTCUT_DIR"
cat > "$SHORTCUT_DIR/YouTube-Transcript.sh" <<'LAUNCHER'
#!/data/data/com.termux/files/usr/bin/bash
# 保持 CPU 喚醒，避免手機休眠時伺服器被系統殺掉
termux-wake-lock 2>/dev/null
cd "$HOME/ytscript" || exit 1
python ytscript.py
termux-wake-unlock 2>/dev/null
LAUNCHER
chmod +x "$SHORTCUT_DIR/YouTube-Transcript.sh"

cat > "$APP_DIR/start.sh" <<'STARTER'
#!/data/data/com.termux/files/usr/bin/bash
termux-wake-lock 2>/dev/null
cd "$HOME/ytscript" || exit 1
python ytscript.py
termux-wake-unlock 2>/dev/null
STARTER
chmod +x "$APP_DIR/start.sh"

echo "[6/6] 捷徑已建立"
echo
echo "======================================================"
echo "  安裝完成！"
echo "======================================================"
echo
echo "  現在就啟動：   bash ~/ytscript/start.sh"
echo
echo "  做成桌面圖示（建議）："
echo "    1. 從 F-Droid 安裝「Termux:Widget」"
echo "    2. 長按手機桌面 → 小工具 → Termux → 拖到桌面"
echo "    3. 點選 YouTube-Transcript"
echo
echo "  之後要更新，重新執行這個腳本即可。"
echo
