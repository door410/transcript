# -*- coding: utf-8 -*-
"""自我檢查：改完程式後跑一次，確認原本的功能沒有壞。

給誰用：維護這個工具的人（不一定會寫程式）。每次改完程式、更新套件、
       git pull 之後都跑一次。全部 [通過] 才 commit。

用法（在專案資料夾裡執行）：
    python tools/selfcheck.py            第 1 級：離線檢查，約 5 秒，不連網
    python tools/selfcheck.py --online   第 2 級：再加一次真的抓 YouTube 字幕
    python tools/selfcheck.py --whisper  第 3 級：再加一次真的 AI 聽寫（會下載音訊與模型）

結果：
    最後一行是「全部通過」才算過。任何一行 [失敗] 都代表有東西壞了，
    把整段輸出貼給 AI 請它解釋即可。

這個檔只「讀」主程式，不會修改任何程式檔。
第 2 級會在逐字稿快取裡多存一筆測試影片（幾 KB，無害）。
"""
import io
import json
import os
import re
import sys
import threading
import time
import urllib.request

# 用 reconfigure 而不是另外包一層 TextIOWrapper：ytscript 匯入時會自己再包一次，
# 若這裡也包，舊的那層被回收時會把底下的輸出關掉，之後每個 print 都會報錯。
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
    except Exception:
        pass

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

# 一部 19 秒、有字幕、存在很多年的公開影片。用來做線上測試，流量極小。
TEST_VIDEO = "https://www.youtube.com/watch?v=jNQXAC9IVRw"

# 實測過的套件版本（安裝腳本從這裡讀）
REQ_FILES = ["requirements/core.txt", "requirements/whisper.txt", "requirements/gpu.txt"]

RESULTS = []


def check(name, fn):
    """跑一項檢查。fn 回傳字串＝附註；丟例外＝失敗。"""
    try:
        note = fn()
        RESULTS.append((True, name))
        print(f"  [通過] {name}" + (f" —— {note}" if note else ""))
    except Exception as e:
        RESULTS.append((False, name))
        print(f"  [失敗] {name}\n         原因：{type(e).__name__}: {e}")


def expect(cond, msg):
    if not cond:
        raise AssertionError(msg)


# ---------------------------------------------------------------------------
# 第 1 級：離線
# ---------------------------------------------------------------------------

def t_files_exist():
    need = ["ytscript.py", "ui.html", "tokens.css", "manifest.json",
            "icon-192.png", "icon-512.png", "icon-maskable.png", "icon.ico",
            "start.vbs", "make_shortcut.vbs", "安裝.bat", "疑難排解.bat",
            os.path.join("android", "install.sh")] + REQ_FILES
    missing = [f for f in need if not os.path.exists(os.path.join(ROOT, f))]
    expect(not missing, "缺少檔案：" + "、".join(missing))


def t_import():
    import ytscript  # noqa: F401  —— 語法錯誤會在這裡爆出來
    return "ytscript.py 可以被載入（沒有語法錯誤）"


def t_ascii_launchers():
    bad = []
    for name in ("start.vbs", "make_shortcut.vbs", "安裝.bat", "疑難排解.bat"):
        with open(os.path.join(ROOT, name), "rb") as f:
            raw = f.read()
        if any(b > 127 for b in raw):
            bad.append(f"{name} 含中文或其他非 ASCII 字元")
        if sys.platform == "win32" and b"\r\n" not in raw:
            bad.append(f"{name} 不是 CRLF 換行")
    # pip 在 Big5 系統上可能用 Big5 讀 requirements 檔，中文註解會讓安裝失敗
    for name in REQ_FILES:
        with open(os.path.join(ROOT, name), "rb") as f:
            if any(b > 127 for b in f.read()):
                bad.append(f"{name} 含中文或其他非 ASCII 字元")
    expect(not bad, "；".join(bad) + "（原因見 README「給未來的我」）")


def _read_reqs(name):
    """讀 requirements 檔，回傳 [(套件名, 版本條件字串)]。"""
    out = []
    with io.open(os.path.join(ROOT, name), encoding="ascii") as f:
        for line in f:
            line = line.split("#", 1)[0].strip()
            if line:
                m = re.match(r"([A-Za-z0-9_.\-]+)\s*(.*)", line)
                out.append((m.group(1), m.group(2).strip()))
    return out


def _satisfies(version, spec):
    try:
        from packaging.specifiers import SpecifierSet
    except ImportError:
        from pip._vendor.packaging.specifiers import SpecifierSet
    return (not spec) or SpecifierSet(spec).contains(version, prereleases=True)


def t_package_versions():
    """已安裝的套件是不是 requirements/ 裡實測過的版本。
    core.txt 不符合 → 失敗（三台都靠它）。whisper／gpu 不符合 → 只提醒：
    安裝腳本在實測版本裝不起來時會退回最新版，那種情況能用就不必處理。"""
    from importlib.metadata import version, PackageNotFoundError
    import ytscript as y

    files = ["requirements/core.txt"]
    if not y.IS_TERMUX:
        try:
            import faster_whisper  # noqa: F401
            files.append("requirements/whisper.txt")
        except ImportError:
            pass
        try:
            version("nvidia-cublas-cu12")
            files.append("requirements/gpu.txt")
        except PackageNotFoundError:
            pass

    bad, differ = [], []
    for name in files:
        for pkg, spec in _read_reqs(name):
            try:
                v = version(pkg)
            except PackageNotFoundError:
                (bad if name.endswith("core.txt") else differ).append(f"{pkg} 未安裝")
                continue
            if not _satisfies(v, spec):
                (bad if name.endswith("core.txt") else differ).append(f"{pkg} {v}（要求 {spec}）")
    expect(not bad, "；".join(bad) + "。請執行：python -m pip install --upgrade -r requirements/core.txt")
    checked = "、".join(os.path.basename(n) for n in files)
    if differ:
        return f"檢查 {checked}；注意，與實測版本不同：" + "；".join(differ) + "（能用就不必處理）"
    return f"{checked} 都符合"


def t_video_id():
    import ytscript as y
    cases = {
        "https://www.youtube.com/watch?v=dQw4w9WgXcQ": "dQw4w9WgXcQ",
        "https://youtu.be/dQw4w9WgXcQ?si=abc": "dQw4w9WgXcQ",
        "https://www.youtube.com/shorts/dQw4w9WgXcQ": "dQw4w9WgXcQ",
        "https://m.youtube.com/watch?v=dQw4w9WgXcQ&t=30s": "dQw4w9WgXcQ",
        "dQw4w9WgXcQ": "dQw4w9WgXcQ",
    }
    for url, want in cases.items():
        kind, _u, vid = y.normalize_target(url)
        expect(kind == "youtube" and vid == want, f"{url} 解析成 {kind}/{vid}")
    kind, _u, vid = y.normalize_target("https://www.bilibili.com/video/BV1xx411c7mD")
    expect(kind == "other" and vid is None, "bilibili 連結應該交給 yt-dlp")
    try:
        y.normalize_target("")
        raise AssertionError("空白輸入應該要報錯")
    except ValueError:
        pass


def t_clean_and_paragraphs():
    import ytscript as y
    segs = [{"text": "[音樂]", "start": 0, "duration": 2},
            {"text": "嗯 大家好", "start": 2, "duration": 3},
            {"text": "大家好", "start": 5, "duration": 1},       # 與上一行清理後重複
            {"text": "今天講三件事。", "start": 6, "duration": 40},
            {"text": "第一件事。", "start": 50, "duration": 5}]
    cleaned = y.clean_segments(segs)
    texts = [s["text"] for s in cleaned]
    expect("[音樂]" not in texts, "雜訊標記沒被移除")
    expect(texts.count("大家好") == 1, f"重複行沒被合併：{texts}")
    paras = y.build_paragraphs(cleaned, 45)
    expect(len(paras) >= 1 and paras[0]["start"] == 2, f"段落合併結果不對：{paras}")


def t_parsers():
    import ytscript as y
    srt = "1\n00:00:01,000 --> 00:00:03,500\n你好\n\n2\n00:00:04,000 --> 00:00:06,000\n世界\n"
    s = y._parse_srt_vtt(srt)
    expect(len(s) == 2 and s[0]["text"] == "你好" and abs(s[0]["duration"] - 2.5) < 0.01,
           f"SRT 解析錯誤：{s}")
    j3 = json.dumps({"events": [{"tStartMs": 1000, "dDurationMs": 2000,
                                 "segs": [{"utf8": "hello"}]}]})
    s = y._parse_json3(j3)
    expect(s and s[0]["text"] == "hello" and s[0]["start"] == 1.0, f"json3 解析錯誤：{s}")
    s = y._parse_srv1('<text start="1.5" dur="2">A &amp; B</text>')
    expect(s and s[0]["text"] == "A & B", f"srv1 解析錯誤：{s}")


def _fake_result(mode):
    import ytscript as y
    meta = {"title": "測試影片", "channel": "測試頻道", "duration": 125,
            "upload_date": "2026-01-01", "url": "https://youtu.be/xxxxxxxxxxx",
            "chapters": [{"start": 0, "title": "開場"}, {"start": 60, "title": "正文"}]}
    segs = [{"text": f"這是第 {i} 句話。", "start": i * 5.0, "duration": 5.0}
            for i in range(25)]
    opts = {"prompt_mode": mode, "timestamps": "para", "target_sec": 45,
            "include_meta": True, "clean": True}
    return y.assemble(meta, segs, {"lang": "zh-TW", "generated": True}, opts,
                      log=lambda m: None)


def t_output_shape():
    """ui.html 會讀這些欄位。少任何一個，畫面就會壞。"""
    r = _fake_result("deep")
    for k in ("meta", "sub_meta", "markdown", "plaintext", "srt", "parts", "stats"):
        expect(k in r, f"結果少了 {k}")
    for k in ("tokens", "paragraphs", "chapters", "audio_mb"):
        expect(k in r["stats"], f"stats 少了 {k}")
    md = r["markdown"]
    expect("## 給 AI 的分析指示" in md, "深度模式應該附上分析指示")
    expect("## 逐字稿" in md and "`[00:00]`" in md, "逐字稿或時間戳不見了")
    expect("## 影片章節" in md, "章節不見了")
    expect("-->" in r["srt"], "SRT 格式不對")
    return f"約 {r['stats']['tokens']} tokens、{r['stats']['paragraphs']} 段"


def t_every_mode():
    import ytscript as y
    for mode in list(y.PROMPTS) + ["none"]:
        md = _fake_result(mode)["markdown"]
        has = "## 給 AI 的分析指示" in md
        expect(has == (mode != "none"), f"模式 {mode} 的分析指示出現與否不對")
    return "模式：" + "、".join(list(y.PROMPTS) + ["none"])


def t_ui_matches_backend():
    """介面上的按鈕和後端要對得上。新增分析模式時最容易漏改的地方。"""
    import re
    import ytscript as y
    with io.open(os.path.join(ROOT, "ui.html"), encoding="utf-8") as f:
        html = f.read()
    seg = re.search(r'id="segPrompt".*?</div>', html, re.S)
    expect(seg, "ui.html 找不到 segPrompt（分析模式按鈕區）")
    ui_modes = re.findall(r'data-v="([^"]+)"', seg.group(0))
    back = set(y.PROMPTS) | {"none"}
    expect(set(ui_modes) == back,
           f"介面按鈕 {sorted(ui_modes)} 與後端 PROMPTS {sorted(back)} 不一致")
    hints = re.search(r"const PROMPT_HINTS = \{(.*?)\};", html, re.S)
    expect(hints, "ui.html 找不到 PROMPT_HINTS")
    for m in ui_modes:
        expect(re.search(r"\b" + re.escape(m) + r"\s*:", hints.group(1)),
               f"PROMPT_HINTS 少了 {m} 的說明文字")
    for el in ("url", "go", "btnCopy", "btnMd", "btnTxt", "btnSrt", "out", "status", "err"):
        expect(f'id="{el}"' in html, f"ui.html 少了 id=\"{el}\" 的元素（JavaScript 會找不到它）")


def t_local_server():
    """真的啟動本機伺服器，確認網頁與 API 活著。不開瀏覽器。"""
    import ytscript as y
    y.DEFAULT_PORT = 8790
    th = threading.Thread(target=y.serve, kwargs={"open_browser": False}, daemon=True)
    old = sys.stdout
    sys.stdout = io.StringIO()          # 把啟動橫幅吞掉，免得輸出變亂
    try:
        th.start()
        for _ in range(50):
            if y.SERVER is not None:
                break
            time.sleep(0.1)
    finally:
        sys.stdout = old
    expect(y.SERVER is not None, "伺服器沒有啟動起來")
    base = f"http://127.0.0.1:{y.PORT}"
    try:
        page = urllib.request.urlopen(base + "/", timeout=10).read().decode("utf-8")
        expect("開始轉錄" in page, "首頁內容不對")
        css = urllib.request.urlopen(base + "/tokens.css", timeout=10)
        expect(css.status == 200, "tokens.css 讀不到")
        ping = json.loads(urllib.request.urlopen(base + "/api/ping", timeout=10).read())
        expect(ping.get("ok"), "/api/ping 回應不對")
        req = urllib.request.Request(base + "/api/start", data=b'{"url":""}',
                                     headers={"Content-Type": "application/json"})
        try:
            urllib.request.urlopen(req, timeout=10)
            raise AssertionError("空白網址應該回 400")
        except urllib.error.HTTPError as e:
            expect(e.code == 400, f"空白網址應該回 400，實際 {e.code}")
    finally:
        y.SERVER.shutdown()
    return f"連接埠 {y.PORT}"


def t_device_report():
    """只報告，不判定對錯：這台機器會用哪一條路。"""
    import shutil
    import ytscript as y
    bits = []
    if y.IS_TERMUX:
        bits.append("平台：Android／Termux（手機版路徑）")
        bits.append("whisper.cpp：" + (y.find_whisper_cli() or "找不到！沒字幕的影片會失敗"))
        bits.append("ffmpeg：" + (shutil.which("ffmpeg") or "找不到！"))
    else:
        dev, comp = y.pick_device()
        bits.append(f"運算裝置：{dev.upper()}（{comp}）")
        try:
            import faster_whisper  # noqa: F401
            bits.append("faster-whisper：已安裝")
        except ImportError:
            bits.append("faster-whisper：未安裝（沒字幕的影片會失敗）")
    bits.append(f"「準確」模式會用的模型：{y.default_model_size()}")
    return "；".join(bits)


def t_phone_launcher():
    """手機專用：~/ytscript/start.sh 要直接執行這個 repo 裡的程式。
    舊版 install.sh 是把程式「複製」到 ~/ytscript 執行，git pull 之後手機
    仍在跑舊副本。還是舊安裝方式的話，要重跑一次 install.sh 換成新方式。"""
    import ytscript as y
    if not y.IS_TERMUX:
        return "不是手機，略過"
    run_dir = os.path.join(os.path.expanduser("~"), "ytscript")
    fix = "。請執行一次：bash ~/transcript/android/install.sh"
    expect(not os.path.exists(os.path.join(run_dir, "ytscript.py")),
           "還是舊的安裝方式（~/ytscript 裡有程式副本，git pull 不會更新它）" + fix)
    start = os.path.join(run_dir, "start.sh")
    expect(os.path.exists(start), "找不到啟動器 ~/ytscript/start.sh" + fix)
    with io.open(start, encoding="utf-8") as f:
        body = f.read()
    expect(f'cd "{ROOT}"' in body,
           "啟動器沒有指向這個資料夾（" + ROOT + "）" + fix)
    return "啟動器直接執行 " + ROOT + " 的程式，git pull 後重新啟動即是新版"


# ---------------------------------------------------------------------------
# 第 2、3 級：連網
# ---------------------------------------------------------------------------

def t_online_captions():
    import ytscript as y
    r = y.transcribe(TEST_VIDEO, {"no_cache": True, "prompt_mode": "none"},
                     log=lambda m: None)
    expect(r["stats"]["segments"] > 0, "抓到 0 段字幕")
    return f"標題「{r['meta'].get('title')}」，{r['stats']['segments']} 段"


def t_online_whisper():
    import ytscript as y
    fn = y.engine_whispercpp if y.IS_TERMUX else y.engine_whisper
    logs = []
    segs, sm = fn(TEST_VIDEO, y.DEFAULT_LANGS, logs.append, model_size="tiny")
    expect(segs, "AI 聽寫沒有產生文字")
    gpu = [m for m in logs if "顯示卡" in m]
    return f"{sm.get('engine')}，{len(segs)} 段" + (f"；{gpu[-1]}" if gpu else "")


def main():
    args = sys.argv[1:]
    print(f"\n自我檢查　專案位置：{ROOT}\nPython {sys.version.split()[0]}\n")
    print("第 1 級：離線檢查")
    for name, fn in [
        ("必要檔案都在", t_files_exist),
        ("主程式可以載入", t_import),
        (".bat／.vbs 維持純 ASCII", t_ascii_launchers),
        ("網址解析", t_video_id),
        ("字幕清理與段落合併", t_clean_and_paragraphs),
        ("三種字幕格式解析", t_parsers),
        ("輸出結構（介面需要的欄位）", t_output_shape),
        ("每一種分析模式", t_every_mode),
        ("介面按鈕與後端一致", t_ui_matches_backend),
        ("本機伺服器與 API", t_local_server),
        ("這台機器的硬體路徑", t_device_report),
        ("套件是實測過的版本", t_package_versions),
        ("手機啟動器指向這個資料夾", t_phone_launcher),
    ]:
        check(name, fn)

    if "--online" in args or "--whisper" in args:
        print("\n第 2 級：連網抓字幕")
        check("真的抓一部 YouTube 影片的字幕", t_online_captions)
    if "--whisper" in args:
        print("\n第 3 級：AI 聽寫（第一次會下載模型，可能要幾分鐘）")
        check("真的跑一次 AI 聽寫（tiny 模型）", t_online_whisper)

    bad = [n for ok, n in RESULTS if not ok]
    print()
    if bad:
        print(f"有 {len(bad)} 項失敗：" + "、".join(bad))
        print("→ 先不要 commit。把上面整段輸出貼給 AI，請它解釋原因。")
        sys.exit(1)
    print(f"全部通過（{len(RESULTS)} 項）")


if __name__ == "__main__":
    main()
