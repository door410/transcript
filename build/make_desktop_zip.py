# -*- coding: utf-8 -*-
"""打包一份可以直接丟到另一台 Windows 電腦的 zip。

用途：不想在筆電上裝 Git 時使用。解壓縮後執行「安裝.bat」即可。

代價要講清楚：這份 zip 是「某個時間點的快照」，之後主專案每更新一次就得
重新打包、重新傳一次。用 git clone 的話更新只是一行 git pull。

用法：
    python build/make_desktop_zip.py
產出：
    dist/YouTube逐字稿工具_電腦版.zip
"""
import io
import os
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DIST = os.path.join(ROOT, "dist")

# 電腦版執行所需的完整檔案集
FILES = [
    "ytscript.py",
    "ui.html",
    "tokens.css",
    "manifest.json",
    "icon.ico",
    "icon-192.png",
    "icon-512.png",
    "icon-maskable.png",
    "start.vbs",
    "make_shortcut.vbs",
    "安裝.bat",
    "疑難排解.bat",
    "README.md",
    "安裝指南.md",
]

READ_ME_FIRST = """\
YouTube 逐字稿工具 — 電腦版
================================

安裝步驟
--------
1. 把這個資料夾整個解壓縮到你想放的位置
   （建議 C:\\Users\\你的帳號\\yt-transcript，不要放在 Google Drive 裡）
2. 先確認有裝 Python：https://www.python.org/downloads/
   安裝時務必勾選「Add Python to PATH」
3. 雙擊「安裝.bat」
4. 裝好後，雙擊桌面上新出現的捷徑即可使用

沒有 NVIDIA 顯卡也完全能用，安裝程式會自動跳過 CUDA，省下 2 GB。

更新
----
這個 zip 是打包當下的版本。之後要更新有兩個方式：

  A. 重新跟我要一份新的 zip，解壓縮覆蓋（簡單，但每次都要重傳）
  B. 改用 git（一次設定，之後更新只要一行）：
       git clone https://github.com/door410/transcript.git

  長期來說 B 省事很多。

詳細說明見「安裝指南.md」與「README.md」。
"""


def main():
    os.makedirs(DIST, exist_ok=True)
    out = os.path.join(DIST, "YouTube逐字稿工具_電腦版.zip")
    missing = [f for f in FILES if not os.path.exists(os.path.join(ROOT, f))]
    if missing:
        raise SystemExit("缺少檔案：" + "、".join(missing))

    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for name in FILES:
            z.write(os.path.join(ROOT, name), "yt-transcript/" + name)
        # .bat 與 .vbs 必須是 CRLF，zipfile 不會動內容，這裡直接檢查而非轉換
        for name in FILES:
            if name.endswith((".bat", ".vbs")):
                with open(os.path.join(ROOT, name), "rb") as f:
                    raw = f.read()
                if b"\r\n" not in raw:
                    raise SystemExit(f"{name} 不是 CRLF 行尾，Windows 上會出錯")
                if any(b > 127 for b in raw):
                    raise SystemExit(f"{name} 含非 ASCII 位元組，Big5 環境下會壞掉")
        z.writestr("yt-transcript/先讀我.txt",
                   READ_ME_FIRST.replace("\n", "\r\n").encode("utf-8-sig"))

    print("  產生 %s（%.0f KB）" % (os.path.relpath(out, ROOT),
                                    os.path.getsize(out) / 1024))


if __name__ == "__main__":
    main()
