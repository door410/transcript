# -*- coding: utf-8 -*-
"""把整個工具打包成一個 .py 檔，以及一份手機用的 zip。

為什麼需要這個：
    Android 的 Termux 上搬一堆檔案很麻煩，單一檔案最好傳。
    但先前的單檔版是「手動複製一份 ytscript.py 再貼上內嵌資源」維護的，
    結果就是同一個 bug 要修兩次 —— 而且真的漏過。
    改成從本體產生之後，本體修好，單檔版就自動跟上。

用法：
    python build/make_single_file.py
產出（都在 dist/，已被 .gitignore 排除，不進版控）：
    dist/逐字稿工具_單檔版.py
    dist/手機安裝包.zip
"""
import base64
import io
import os
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DIST = os.path.join(ROOT, "dist")

ICONS = ("icon-192.png", "icon-512.png", "icon-maskable.png")
# 手機安裝包要帶的檔案（Termux 上跑得起來的最小集合）
ZIP_FILES = ("ytscript.py", "ui.html", "tokens.css", "manifest.json") + ICONS


def read_text(name):
    with io.open(os.path.join(ROOT, name), encoding="utf-8") as f:
        return f.read()


def read_bytes(name):
    with open(os.path.join(ROOT, name), "rb") as f:
        return f.read()


def build_single_file():
    src = read_text("ytscript.py")

    embeds = [
        "\n# " + "=" * 74,
        "# 以下由 build/make_single_file.py 自動產生 —— 不要手動編輯。",
        "# 要改介面或樣式請改本體的 ui.html / tokens.css，再重新產生這個檔。",
        "# " + "=" * 74 + "\n",
        "EMBED_HTML = %r\n" % read_text("ui.html"),
        "EMBED_CSS = %r\n" % read_text("tokens.css"),
        "EMBED_MANIFEST = %r\n" % read_text("manifest.json"),
        "EMBED_ICONS = {",
    ]
    for name in ICONS:
        embeds.append("    %r: %r," % (name, base64.b64encode(read_bytes(name)).decode()))
    embeds.append("}\n")

    out = src + "\n" + "\n".join(embeds)
    os.makedirs(DIST, exist_ok=True)
    path = os.path.join(DIST, "逐字稿工具_單檔版.py")
    with io.open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(out)
    return path


def build_zip():
    os.makedirs(DIST, exist_ok=True)
    path = os.path.join(DIST, "手機安裝包.zip")
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        for name in ZIP_FILES:
            z.write(os.path.join(ROOT, name), name)
        # install.sh 放在和 ytscript.py 同一層；它會自己判斷這種版面。
        # 套件版本也要一起帶，否則手機會裝到未經測試的版本。
        z.write(os.path.join(ROOT, "android", "install.sh"), "install.sh")
        z.write(os.path.join(ROOT, "requirements", "core.txt"), "requirements/core.txt")
    return path


if __name__ == "__main__":
    for p in (build_single_file(), build_zip()):
        print("  產生 %s（%.0f KB）" % (os.path.relpath(p, ROOT),
                                        os.path.getsize(p) / 1024))
