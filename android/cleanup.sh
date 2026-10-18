#!/data/data/com.termux/files/usr/bin/bash
# =====================================================================
#  清掉舊版留下、這個版本（fast-only）用不到的檔案
#
#  用法：bash ~/transcript/android/cleanup.sh
#
#  只刪下面明確列出的東西，每一項都先確認存在、認得出是這個工具的檔案才刪；
#  可以重複執行。不會動到程式本身（~/transcript）、whisper.cpp 與 tiny 模型。
#  注意：會刪掉準確模式的模型。之後若改用 main 分支，重跑 install.sh 會重新下載。
# =====================================================================

MD="$HOME/.cache/whisper-cpp"
free_kb() { df -k "$HOME" 2>/dev/null | awk 'NR==2 {print $4}'; }
before=$(free_kb)
n=0
T='~'                                  # 放變數裡：直接寫 ~ 會被 bash 展開回完整路徑
gone() { echo "  已刪除：${1/#$HOME/$T}"; n=$((n + 1)); }

echo "清理舊版留下的多餘檔案…"

# 1. 用不到的 AI 模型：fast-only 只用 ggml-tiny-q5_1.bin
if [ -d "$MD" ]; then
  for f in "$MD"/*; do
    [ -f "$f" ] || continue
    [ "$(basename "$f")" = "ggml-tiny-q5_1.bin" ] && continue
    rm -f "$f" && gone "$f"
  done
fi

# 2. 舊手機版從 ZIP 解壓出來的資料夾。裡面有 mobile/install.sh 才是它，避免誤刪同名的其他東西
for d in "$HOME"/transcript-main*; do
  [ -d "$d" ] && [ -f "$d/mobile/install.sh" ] && rm -rf "$d" && gone "$d"
done

# 3. 「下載」資料夾裡的舊安裝包
for z in /sdcard/Download/transcript-main*.zip; do
  [ -f "$z" ] && rm -f "$z" && gone "$z"
done

# 4. 舊版程式副本留下的零碎檔案（新版的 install.sh 不認得它們，所以沒清）
for f in "$HOME/ytscript/sw.js" "$HOME/ytscript/setup-quality.sh" "$HOME/setup-log.txt"; do
  [ -f "$f" ] && rm -f "$f" && gone "$f"
done

# 5. 安裝過程的下載暫存。刪掉完全安全，只是日後重裝套件要重新下載
pip cache purge >/dev/null 2>&1 && echo "  已清空 pip 下載暫存"
apt-get clean >/dev/null 2>&1 && echo "  已清空套件下載暫存"

after=$(free_kb)
echo ""
if [ -n "$before" ] && [ -n "$after" ] && [ $(( (after - before) / 1024 )) -ge 1 ]; then
  echo "完成：刪除 $n 項，手機多出約 $(( (after - before) / 1024 )) MB 空間。"
else
  echo "完成：刪除 $n 項。"
fi
