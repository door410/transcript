#!/data/data/com.termux/files/usr/bin/bash
# 一次性準備：開啟 ARM 加速指令、下載兩個模式要用的模型、裝簡繁轉換。
# 這支腳本不寫任何設定檔 —— 兩個模式的參數都固定在程式裡。
# 刻意不使用 set -e / set -u

WH="$HOME/whisper.cpp"
CLI="$WH/build/bin/whisper-cli"
MD="$HOME/.cache/whisper-cpp"
SAMPLE="$WH/samples/jfk.wav"
LOG="$HOME/setup-log.txt"
HF="https://huggingface.co/ggerganov/whisper.cpp/resolve/main"

: > "$LOG"; mkdir -p "$MD"
say() { echo "$@" | tee -a "$LOG"; }
run() { "$@" >>"$LOG" 2>&1; }
NPROC=$(nproc 2>/dev/null || echo 4)
RAM=$(awk '/MemTotal/{printf "%d", $2/1024}' /proc/meminfo 2>/dev/null || echo 0)

say "======================================================"
say "  一次性準備  $(date '+%H:%M')"
say "  CPU ${NPROC} 核｜記憶體 ${RAM} MB"
say "======================================================"
[ -x "$CLI" ] || { say "找不到 whisper-cli。"; exit 1; }

# 清掉舊版留下的設定檔。它們會覆寫程式裡的固定值，是速度莫名變慢的來源。
rm -f "$MD/args.conf" "$MD/model.conf" "$MD/lang.conf"

# ---------------- 1. ARM 加速指令 ----------------
say ""
say "===== [1/3] ARM 加速指令 ====="
if [ ! -s "$SAMPLE" ]; then
  mkdir -p "$WH/samples"
  run curl -L -s -o "$SAMPLE" \
    "https://raw.githubusercontent.com/ggml-org/whisper.cpp/master/samples/jfk.wav"
fi
SI=$("$CLI" -m "$MD/ggml-tiny.bin" -f "$SAMPLE" -np -nt 2>&1 | grep -i system_info | head -1)
say "  $SI"
if echo "$SI" | grep -qiE "DOTPROD *= *1|MATMUL_INT8 *= *1"; then
  say "  已開啟，不需重建"
else
  say "  缺少 dotprod／i8mm —— 這是最大的效能損失，重新建置（5～15 分鐘）"
  cp "$CLI" "$CLI.slow.bak" 2>/dev/null
  ( cd "$WH" && rm -rf build && cmake -B build -DCMAKE_BUILD_TYPE=Release \
      -DGGML_NATIVE=ON \
      -DCMAKE_C_FLAGS="-O3 -march=armv8.2-a+dotprod+fp16" \
      -DCMAKE_CXX_FLAGS="-O3 -march=armv8.2-a+dotprod+fp16" ) >>"$LOG" 2>&1
  ( cd "$WH" && cmake --build build -j"$NPROC" --config Release ) >>"$LOG" 2>&1
  if [ ! -x "$CLI" ]; then
    say "  指定指令集失敗，改用保守設定重建"
    ( cd "$WH" && rm -rf build && cmake -B build -DCMAKE_BUILD_TYPE=Release -DGGML_NATIVE=ON ) >>"$LOG" 2>&1
    ( cd "$WH" && cmake --build build -j"$NPROC" --config Release ) >>"$LOG" 2>&1
  fi
  if [ -x "$CLI" ]; then
    ln -sf "$CLI" "$PREFIX/bin/whisper-cli" 2>/dev/null
    say "  重建完成"
  else
    [ -f "$CLI.slow.bak" ] && cp "$CLI.slow.bak" "$CLI" && say "  重建失敗，已還原舊執行檔"
  fi
fi

# ---------------- 2. 模型 ----------------
say ""
say "===== [2/3] 下載模型 ====="
get_model() {
  local f="$MD/$1"
  [ -s "$f" ] && [ "$(stat -c %s "$f")" -gt "$2" ] && { say "  $1 : 已有"; return 0; }
  say "  下載 $1 …"
  run curl -L --retry 3 -C - -o "$f.part" "$HF/$1"
  if [ -s "$f.part" ] && [ "$(stat -c %s "$f.part")" -gt "$2" ]; then
    mv "$f.part" "$f"; say "  $1 : OK（$(( $(stat -c %s "$f") / 1048576 )) MB）"; return 0
  fi
  rm -f "$f.part"; say "  $1 : 下載失敗"; return 1
}

say "  快速模式用的模型："
get_model "ggml-tiny-q5_1.bin" 20000000

say "  準確模式用的模型（依記憶體決定）："
if [ "$RAM" -ge 5500 ]; then
  get_model "ggml-large-v3-turbo-q5_0.bin" 400000000 || get_model "ggml-small-q5_1.bin" 120000000
elif [ "$RAM" -ge 3500 ]; then
  get_model "ggml-small-q5_1.bin" 120000000
else
  get_model "ggml-base-q5_1.bin" 30000000
fi

say "  靜音偵測模型（準確模式用）："
run curl -L -s -o "$MD/ggml-silero-v5.1.2.bin.part" \
  "https://huggingface.co/ggml-org/whisper-vad/resolve/main/ggml-silero-v5.1.2.bin"
if [ -s "$MD/ggml-silero-v5.1.2.bin.part" ]; then
  mv "$MD/ggml-silero-v5.1.2.bin.part" "$MD/ggml-silero-v5.1.2.bin"; say "  silero VAD : OK"
else
  rm -f "$MD/ggml-silero-v5.1.2.bin.part"; say "  silero VAD : 略過（程式會自動不使用）"
fi

# ---------------- 3. 簡繁轉換 ----------------
say ""
say "===== [3/3] 簡體轉繁體 ====="
if python -c "import opencc" >/dev/null 2>&1; then
  say "  opencc : 已安裝"
else
  run pip install opencc-python-reimplemented
  python -c "import opencc" >/dev/null 2>&1 && say "  opencc : 安裝成功" || say "  opencc : 安裝失敗（程式會在第一次使用時自己再試一次）"
fi

say ""
say "======================================================"
say "  準備完成。介面上兩個模式："
say ""
say "    快速（預設）→ tiny ＋ 貪婪解碼，不做靜音偵測"
say "    準確        → 依記憶體選最大模型 ＋ 束搜索 5 ＋ 靜音偵測"
say ""
say "  語言固定中文，輸出固定繁體。沒有其他設定。"
say ""
say "  3 秒後啟動服務。瀏覽器開 127.0.0.1:8756"
say "  進去後【下拉重新整理】一次，讓介面更新。"
say "======================================================"
sleep 3
exec bash "$HOME/ytscript/start.sh"
