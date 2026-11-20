#!/data/data/com.termux/files/usr/bin/bash
# 建立手機上的名稱與捷徑（幾秒鐘，可重複執行）：
#   - 指令 transcript         ：在 Termux 輸入 transcript 就啟動
#   - Termux:Widget 捷徑 transcript
# install.sh 會呼叫它；更新時也會呼叫，讓名稱永遠跟著新版走。
START="$HOME/ytscript/start.sh"
BIN="${PREFIX:-/data/data/com.termux/files/usr}/bin/transcript"
printf '#!/data/data/com.termux/files/usr/bin/bash\nexec bash "%s"\n' "$START" > "$BIN"
chmod +x "$BIN"
mkdir -p "$HOME/.shortcuts"
rm -f "$HOME/.shortcuts/YouTube-Transcript.sh"      # 舊名稱
cp "$BIN" "$HOME/.shortcuts/transcript"
chmod +x "$HOME/.shortcuts/transcript"
echo "  已建立：指令 transcript、桌面小工具捷徑 transcript"
