#!/data/data/com.termux/files/usr/bin/bash
# 啟動逐字稿服務。重複點捷徑不會開出第二份，只會把畫面叫起來。
PORT=8756
URL="http://127.0.0.1:$PORT"

open_ui() {
  termux-open-url "$URL" 2>/dev/null || \
  am start -a android.intent.action.VIEW -d "$URL" >/dev/null 2>&1
}

# 已經在跑就直接開畫面，不再啟動第二份（第二份會退到 8757，
# 而主畫面捷徑指的是 8756，結果就是「點了沒反應」）
if curl -s --max-time 2 "$URL/health" 2>/dev/null | grep -q ytscript; then
  open_ui
  exit 0
fi

termux-wake-lock 2>/dev/null
cd "$HOME/ytscript" || exit 1
python ytscript.py
termux-wake-unlock 2>/dev/null
