#!/data/data/com.termux/files/usr/bin/bash
# =====================================================================
#  YouTube 逐字稿工具 — 手機版全新安裝腳本
#
#  用法：在 Termux 執行
#      pkg install -y git
#      git clone https://github.com/door410/transcript.git
#      bash transcript/android/install.sh
#
#  這支腳本會從零把整套環境裝好，可以重複執行（已完成的步驟會跳過）。
#  之後要更新：cd ~/transcript && git pull && bash android/install.sh
# =====================================================================
# 刻意不使用 set -e / set -u：任何一步失敗都要繼續跑完並在最後報告。

HERE="$(cd "$(dirname "$0")" && pwd)"
APP="$(cd "$HERE/.." && pwd)"   # 程式檔在 repo 根目錄
DEST="$HOME/ytscript"
WH="$HOME/whisper.cpp"
CLI="$WH/build/bin/whisper-cli"
MD="$HOME/.cache/whisper-cpp"
LOG="$HOME/install-log.txt"
HF="https://huggingface.co/ggerganov/whisper.cpp/resolve/main"
PI="$PREFIX/var/lib/dpkg/info/ffmpeg.postinst"

export DEBIAN_FRONTEND=noninteractive
APTOPT='-y -o Dpkg::Options::=--force-confold -o Dpkg::Options::=--force-confdef'

: > "$LOG"; mkdir -p "$MD"
say() { echo "$@" | tee -a "$LOG"; }
run() { "$@" >>"$LOG" 2>&1; }
NPROC=$(nproc 2>/dev/null || echo 4)
RAM=$(awk '/MemTotal/{printf "%d", $2/1024}' /proc/meminfo 2>/dev/null || echo 0)
FAIL=0

say "======================================================"
say "  逐字稿工具 — 全新安裝"
say "  $(date '+%Y-%m-%d %H:%M')｜CPU ${NPROC} 核｜記憶體 ${RAM} MB"
say "  完整記錄： $LOG"
say "======================================================"

if [ ! -f "$APP/ytscript.py" ]; then
  say "在 $APP 找不到 ytscript.py。"
  say "請確認是用 git clone 取得整個專案，並執行 android/install.sh。"
  exit 1
fi

# ---------------------------------------------------------------------
say ""
say "===== [1/8] 修復套件系統 ====="
# ffmpeg 的安裝後腳本失敗會卡住之後所有安裝。執行檔本身沒問題，
# 壞的只是 dpkg 的設定記錄，所以把該腳本換成 exit 0。
dpkg_fix() {
  for i in 1 2 3; do
    run dpkg --configure -a && return 0
    if [ -f "$PI" ]; then
      printf '#!/data/data/com.termux/files/usr/bin/sh\nexit 0\n' > "$PI"
      chmod +x "$PI"
    fi
  done
  run apt-get $APTOPT -f install
}
dpkg_fix
if dpkg --audit 2>/dev/null | grep -q .; then
  say "  dpkg 狀態 : 仍有未設定套件（見記錄檔）"
else
  say "  dpkg 狀態 : OK"
fi

# ---------------------------------------------------------------------
say ""
say "===== [2/8] 系統套件升級 ====="
# Termux 最常見的故障是「升級升到一半」：libc++ 落後於其他套件，
# 於是 ffmpeg 一啟動就因為找不到符號而被連結器擋下。整包升級可根治。
say "  更新索引與升級（幾分鐘，請用 WiFi 並插著電）…"
run apt-get update
run apt-get $APTOPT full-upgrade
dpkg_fix
say "  完成"

# ---------------------------------------------------------------------
say ""
say "===== [3/8] 安裝必要套件 ====="
for p in python git cmake make clang ffmpeg wget curl; do
  if command -v "$p" >/dev/null 2>&1; then
    say "  $(printf '%-8s' "$p") : 已有"
  else
    run apt-get $APTOPT install "$p"
    command -v "$p" >/dev/null 2>&1 \
      && say "  $(printf '%-8s' "$p") : 安裝成功" \
      || { say "  $(printf '%-8s' "$p") : 安裝失敗"; FAIL=1; }
  fi
done
dpkg_fix

# ffmpeg 光是存在不代表能跑，一定要實際執行一次確認
if ffmpeg -version >/dev/null 2>&1; then
  say "  ffmpeg 實測 : OK"
else
  say "  ffmpeg 實測 : 無法執行，嘗試重裝相依套件…"
  DEPS=$(apt-cache depends ffmpeg 2>/dev/null | awk '/Depends:/ {print $2}' | grep -v '^<' | tr '\n' ' ')
  run apt-get $APTOPT install --reinstall ffmpeg libc++ $DEPS
  dpkg_fix
  ffmpeg -version >/dev/null 2>&1 \
    && say "  ffmpeg 實測 : 修復成功" \
    || { say "  ffmpeg 實測 : 仍然失敗（見記錄檔最後幾行）"; FAIL=1; }
fi

# ---------------------------------------------------------------------
say ""
say "===== [4/8] 安裝 Python 套件 ====="
run pip install --upgrade pip
for m in yt-dlp youtube-transcript-api opencc-python-reimplemented; do
  run pip install "$m"
done
python -c "import yt_dlp" 2>/dev/null && say "  yt-dlp  : OK" || { say "  yt-dlp  : 失敗"; FAIL=1; }
python -c "import opencc" 2>/dev/null && say "  opencc  : OK" || say "  opencc  : 失敗（輸出可能是簡體）"

# ---------------------------------------------------------------------
say ""
say "===== [5/8] 建置 whisper.cpp（AI 聽寫引擎）====="
if [ -x "$CLI" ] && "$CLI" --help >/dev/null 2>&1; then
  say "  已建置，跳過"
else
  [ -d "$WH/.git" ] || { rm -rf "$WH"; say "  取得原始碼…"; \
    run git clone --depth 1 https://github.com/ggml-org/whisper.cpp "$WH"; }
  say "  編譯中，5～15 分鐘，請不要關掉 Termux…"
  # -march 指定 ARMv8.2 的 dotprod／fp16 指令。開與不開的差距是好幾倍，
  # 這是手機上影響聽寫速度最大的單一因素。
  ( cd "$WH" && rm -rf build && cmake -B build -DCMAKE_BUILD_TYPE=Release \
      -DGGML_NATIVE=ON \
      -DCMAKE_C_FLAGS="-O3 -march=armv8.2-a+dotprod+fp16" \
      -DCMAKE_CXX_FLAGS="-O3 -march=armv8.2-a+dotprod+fp16" ) >>"$LOG" 2>&1
  ( cd "$WH" && cmake --build build -j"$NPROC" --config Release ) >>"$LOG" 2>&1
  if [ ! -x "$CLI" ]; then
    say "  指定指令集失敗，改用保守設定重建…"
    ( cd "$WH" && rm -rf build && cmake -B build -DCMAKE_BUILD_TYPE=Release -DGGML_NATIVE=ON ) >>"$LOG" 2>&1
    ( cd "$WH" && cmake --build build -j"$NPROC" --config Release ) >>"$LOG" 2>&1
  fi
  if [ -x "$CLI" ]; then
    say "  建置成功"
  else
    say "  建置失敗（記錄檔最後 20 行）："
    tail -n 20 "$LOG" | sed 's/^/      /'
    FAIL=1
  fi
fi
[ -x "$CLI" ] && ln -sf "$CLI" "$PREFIX/bin/whisper-cli" 2>/dev/null

# ---------------------------------------------------------------------
say ""
say "===== [6/8] 下載辨識模型 ====="
get_model() {   # $1=檔名 $2=最小可接受位元組
  local f="$MD/$1"
  [ -s "$f" ] && [ "$(stat -c %s "$f")" -gt "$2" ] && { say "  $1 : 已有"; return 0; }
  say "  下載 $1 …"
  run curl -L --retry 3 -C - -o "$f.part" "$HF/$1"
  if [ -s "$f.part" ] && [ "$(stat -c %s "$f.part")" -gt "$2" ]; then
    mv "$f.part" "$f"
    say "  $1 : OK（$(( $(stat -c %s "$f") / 1048576 )) MB）"
    return 0
  fi
  rm -f "$f.part"; say "  $1 : 下載失敗"; return 1
}

say "  【快速】模式用的模型："
get_model "ggml-tiny.bin" 60000000 || FAIL=1
get_model "ggml-tiny-q5_1.bin" 20000000

say "  【準確】模式用的模型（依記憶體決定）："
if [ "$RAM" -ge 5500 ]; then
  get_model "ggml-large-v3-turbo-q5_0.bin" 400000000 || get_model "ggml-small-q5_1.bin" 120000000
elif [ "$RAM" -ge 3500 ]; then
  get_model "ggml-small-q5_1.bin" 120000000
else
  get_model "ggml-base-q5_1.bin" 30000000
fi

say "  靜音偵測模型（準確模式用，可減少憑空冒出的句子）："
run curl -L -s -o "$MD/ggml-silero-v5.1.2.bin.part" \
  "https://huggingface.co/ggml-org/whisper-vad/resolve/main/ggml-silero-v5.1.2.bin"
if [ -s "$MD/ggml-silero-v5.1.2.bin.part" ]; then
  mv "$MD/ggml-silero-v5.1.2.bin.part" "$MD/ggml-silero-v5.1.2.bin"; say "  silero VAD : OK"
else
  rm -f "$MD/ggml-silero-v5.1.2.bin.part"; say "  silero VAD : 略過（程式會自動不使用）"
fi

# 舊版留下的設定檔會覆寫程式裡的固定值，是速度莫名變慢的來源
rm -f "$MD/args.conf" "$MD/model.conf" "$MD/lang.conf"

# ---------------------------------------------------------------------
say ""
say "===== [7/8] 安裝程式檔與啟動捷徑 ====="
mkdir -p "$DEST"
# 只複製執行需要的檔案。整個 repo 搬過去會把 .git、build/、文件一起帶上，
# 手機上沒必要，也讓 ~/ytscript 變得難以辨認。
for f in ytscript.py ui.html tokens.css manifest.json \
         icon-192.png icon-512.png icon-maskable.png; do
  [ -f "$APP/$f" ] && cp -f "$APP/$f" "$DEST/" 2>>"$LOG"
done

# 啟動腳本。termux-wake-lock 讓手機休眠時伺服器不會被系統殺掉。
cat > "$DEST/start.sh" <<'STARTER'
#!/data/data/com.termux/files/usr/bin/bash
termux-wake-lock 2>/dev/null
cd "$HOME/ytscript" || exit 1
python ytscript.py
termux-wake-unlock 2>/dev/null
STARTER
chmod +x "$DEST"/*.sh 2>/dev/null
say "  程式已安裝到 $DEST"

mkdir -p "$HOME/.shortcuts"
cat > "$HOME/.shortcuts/YouTube-Transcript.sh" <<'EOF'
#!/data/data/com.termux/files/usr/bin/bash
exec bash "$HOME/ytscript/start.sh"
EOF
chmod +x "$HOME/.shortcuts/YouTube-Transcript.sh"
say "  桌面捷徑腳本已建立（需搭配 Termux:Widget）"

# ---------------------------------------------------------------------
say ""
say "===== [8/8] 端對端驗證 ====="
ok() { say "  $(printf '%-16s' "$1") : $2"; }
command -v ffmpeg >/dev/null 2>&1 && ffmpeg -version >/dev/null 2>&1 \
  && ok "ffmpeg" "OK" || { ok "ffmpeg" "失敗"; FAIL=1; }
[ -x "$CLI" ] && ok "whisper-cli" "OK" || { ok "whisper-cli" "失敗"; FAIL=1; }
[ -s "$MD/ggml-tiny.bin" ] && ok "tiny 模型" "OK" || { ok "tiny 模型" "失敗"; FAIL=1; }
python -c "import yt_dlp" 2>/dev/null && ok "yt-dlp" "OK" || { ok "yt-dlp" "失敗"; FAIL=1; }
[ -f "$DEST/ytscript.py" ] && ok "程式檔" "OK" || { ok "程式檔" "失敗"; FAIL=1; }

# 真正跑一次：Python 產生音檔 -> ffmpeg 轉檔 -> whisper.cpp 聽寫
if [ -x "$CLI" ] && [ -s "$MD/ggml-tiny.bin" ] && ffmpeg -version >/dev/null 2>&1; then
  T="$HOME/.install-test"
  mkdir -p "$T"
  python - "$T/src.wav" <<'PYEOF' >>"$LOG" 2>&1
import sys, wave, math, struct
w = wave.open(sys.argv[1], 'wb'); w.setnchannels(2); w.setsampwidth(2); w.setframerate(44100)
buf = bytearray()
for i in range(44100 * 3):
    t = i / 44100
    v = int(11000 * (math.sin(2*math.pi*220*t) + 0.5*math.sin(2*math.pi*660*t)) / 1.5)
    buf += struct.pack('<hh', v, v)
w.writeframes(bytes(buf)); w.close()
PYEOF
  if run ffmpeg -y -loglevel error -i "$T/src.wav" -ar 16000 -ac 1 "$T/out.wav" \
     && run "$CLI" -m "$MD/ggml-tiny.bin" -f "$T/out.wav" -l zh -nt; then
    ok "端對端實測" "OK"
  else
    ok "端對端實測" "失敗"; FAIL=1
  fi
  rm -rf "$T"
else
  ok "端對端實測" "略過（前面有缺件）"
fi

# ---------------------------------------------------------------------
say ""
say "======================================================"
if [ "$FAIL" = "0" ]; then
  say "  安裝完成。"
  say ""
  say "  啟動：  bash ~/ytscript/start.sh"
  say "  然後瀏覽器開  127.0.0.1:8756"
  say ""
  say "  後續步驟請看 README.md 的「第三部分：桌面捷徑與 App 圖示」。"
else
  say "  有項目未通過（上面標示失敗的那幾行）。"
  say "  完整記錄在 $LOG"
  say "  README.md 最後一節「疑難排解」有對照表。"
fi
say "======================================================"
