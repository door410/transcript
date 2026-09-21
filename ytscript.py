# -*- coding: utf-8 -*-
"""
YouTube 逐字稿工具 — 專為「餵給 AI 分析」設計
=============================================

架構：本機網頁應用程式
  - 電腦：雙擊啟動，自動開啟瀏覽器
  - 手機：同一個 WiFi 下，用手機瀏覽器開啟顯示的網址即可

輸出格式針對 AI 理解最佳化：
  - 段落級時間戳（約 45 秒一段）—— 可驗證、不浪費 token
  - 完整影片後設資料（標題／頻道／日期／長度）
  - YouTube 章節（作者親手標註的結構，資訊密度最高）
  - 字幕品質標註（人工／自動），讓 AI 知道要不要容忍錯字
  - 內建分析提示詞

全部本機執行，無 API key、無帳號、無費用。
"""

import base64
import html as html_mod
import io
import json
import os
import re
import socket
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
import webbrowser
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

if sys.platform == "win32":
    try:
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")
    except Exception:
        pass

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_PORT = 8756

# 可直接取用的靜態檔（白名單，避免任意路徑讀取）
STATIC_FILES = {
    "tokens.css":        "text/css; charset=utf-8",
    "manifest.json":     "application/manifest+json; charset=utf-8",
    "icon-192.png":      "image/png",
    "icon-512.png":      "image/png",
    "icon-maskable.png": "image/png",
}

def load_asset(name):
    """讀取前端資源。先找磁碟上的檔案，沒有就退回內嵌版本。

    單檔版（由 build/make_single_file.py 產生）旁邊沒有這些檔案，資源是以
    EMBED_* 常數附在檔尾的。讓兩種情況共用同一條讀取路徑，就不必再像以前
    那樣維護兩份幾乎相同的 do_GET —— 那正是同一個 bug 得修兩次的原因。

    回傳 bytes；都找不到則回傳 None。
    """
    try:
        with open(os.path.join(BASE_DIR, name), "rb") as f:
            return f.read()
    except OSError:
        pass

    if name in ("ui.html", "tokens.css", "manifest.json"):
        key = {"ui.html": "EMBED_HTML", "tokens.css": "EMBED_CSS",
               "manifest.json": "EMBED_MANIFEST"}[name]
        text = globals().get(key)
        return text.encode("utf-8") if text is not None else None

    b64 = (globals().get("EMBED_ICONS") or {}).get(name)
    return base64.b64decode(b64) if b64 else None


# 在 Android 的 Termux 裡執行時，開啟瀏覽器的方式和桌面不同
IS_TERMUX = "com.termux" in os.environ.get("PREFIX", "") or os.path.isdir(
    "/data/data/com.termux")
DEFAULT_LANGS = ["zh-TW", "zh-Hant", "zh", "zh-Hans", "zh-CN", "en", "ja"]
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")

PROMPT_DEEP = """\
你是一位善於拆解知識型內容的學習夥伴。以下是一部 YouTube 影片的完整逐字稿。
請依照下列三個部分回答，全程使用繁體中文。

**最重要的規則：嚴格區分「作者說的」與「你的看法」。**
第一部分只能忠實還原影片內容，不得加入你的判斷或延伸；
第二、三部分才是你的觀點，請明確標示。
引用影片內容時一律附上時間戳（例如 `[12:34]`），方便我回原片核對。

---

### 第一部分：忠實還原（不得加入你的觀點）

1. **一句話總結** —— 如果只能用一句話說明這部影片，那會是什麼？

2. **內容結構還原** —— 依照作者**原本的講述順序**重建這部影片的架構，
   保留他的段落邏輯與鋪陳方式，**不要用你自己的分類重新組織**。
   每個環節附上時間戳與一到三句說明。

3. **核心論點與論證脈絡** —— 作者主張什麼？用什麼證據、案例、數據或類比支撐？
   他的論證是如何一步步推進的？

4. **關鍵概念** —— 出現的專有名詞或重要概念，各用一兩句白話解釋。

5. **精華段落** —— 3～5 個最值得我親自回去看的片段，
   附時間戳並說明「為什麼這段值得看」。

### 第二部分：你的解讀（這裡開始是你的觀點，請明確標示）

6. **你怎麼看** —— 這部影片的價值在哪？哪裡說得特別好？
   哪裡薄弱、跳躍或沒說清楚？

7. **作者的思考方式**（請特別著墨，這項最重要）——
   先撇開他講的結論，他「**如何思考**」這個問題？
   他怎麼拆解問題、用了哪些心智模型或框架、從什麼角度切入、
   為什麼選擇這個切入點？
   這套思考方式本身，往往比他的結論更值得我學習。

8. **盲點與反面觀點** —— 作者可能忽略了什麼？
   有沒有合理的反方立場？哪些說法需要進一步查證？

9. **定位** —— 這部影片在它所屬的領域中處於什麼位置？
   是入門介紹、進階探討，還是某個特定觀點的倡議？

### 第三部分：為我所用

10. **最有價值的三件事** —— 從這部影片我能帶走的三件最有價值的事，
    依價值高低排序，並說明「**為什麼是這三件**」。

11. **可遷移性** —— 這些觀念或思考方式，可以應用到哪些其他領域、
    或我日常工作與生活中的什麼情境？請給具體例子。

12. **自我檢測** —— 出 5 個問題讓我測試自己是否真的理解。
    **不要附上答案**，但附上可以找到答案的時間戳，讓我自己回去找。

13. **下一步** —— 一個我今天就能做、不超過 30 分鐘的具體行動。

---

**補充規則**
- 某一項若在這部影片中確實沒有對應內容，直接說「這部影片沒有涉及」，不要硬湊。
- 寧可深入講透少數幾點，也不要每點都淺淺帶過。
- 若逐字稿有明顯錯字或斷句錯誤，請依上下文合理推斷；
  若某處真的無法判讀，明確標註出來，不要自行編造。
"""

PROMPT_QUICK = """\
以下是一部 YouTube 影片的逐字稿。請用繁體中文做一份精簡的重點整理：

1. **一句話總結**
2. **五個核心重點** —— 依照作者原本的講述順序排列，每點附上時間戳
3. **最值得回看的片段** —— 3 個，附時間戳並說明原因
4. **最值得記住的一件事** —— 用一句話說
5. **一個行動** —— 我今天就能做的一件具體小事

引用時請附上時間戳（例如 `[12:34]`）。不要灌水，影片沒講到的就說沒有。
"""

PROMPTS = {"deep": PROMPT_DEEP, "quick": PROMPT_QUICK}
AI_PROMPT = PROMPT_DEEP  # 向後相容

CAPTION_NOTE = ("注意：以下逐字稿由 YouTube **自動語音辨識**產生，可能有錯字、"
                "同音字誤植或斷句錯誤。請依上下文合理推斷作者真正的意思，"
                "不要拘泥於字面用字。")


# ==========================================================================
# 基礎工具
# ==========================================================================

def extract_video_id(url_or_id):
    s = (url_or_id or "").strip()
    if not s:
        raise ValueError("請先貼上 YouTube 連結")
    if re.fullmatch(r"[A-Za-z0-9_-]{11}", s):
        return s
    for p in (r"youtu\.be/([A-Za-z0-9_-]{11})",
              r"[?&]v=([A-Za-z0-9_-]{11})",
              r"/shorts/([A-Za-z0-9_-]{11})",
              r"/live/([A-Za-z0-9_-]{11})",
              r"/embed/([A-Za-z0-9_-]{11})",
              r"/v/([A-Za-z0-9_-]{11})"):
        m = re.search(p, s)
        if m:
            return m.group(1)
    raise ValueError("這看起來不是 YouTube 連結，請確認網址：" + s[:100])


def normalize_target(url_or_id):
    """判斷輸入是 YouTube 還是其他平台，回傳 (平台, 正規化網址, YouTube影片ID或None)。

    YouTube 走專用快速通道（engine 1）；其他平台一律交給 yt-dlp，
    它支援上千個網站（Bilibili、Vimeo、X、TikTok、Twitch、Podcast…）。
    """
    s = (url_or_id or "").strip()
    if not s:
        raise ValueError("請先貼上影片連結")

    # 純 11 碼視為 YouTube 影片 ID
    if re.fullmatch(r"[A-Za-z0-9_-]{11}", s):
        return "youtube", f"https://www.youtube.com/watch?v={s}", s

    if not re.match(r"https?://", s, re.I):
        if re.match(r"[\w-]+(\.[\w-]+)+/", s):
            s = "https://" + s
        else:
            raise ValueError("這看起來不是有效的網址，請貼上完整連結：" + s[:100])

    host = urllib.parse.urlparse(s).netloc.lower()
    if "youtube.com" in host or "youtu.be" in host:
        return "youtube", s, extract_video_id(s)

    return "other", s, None


def fmt_ts(sec, force_hour=False):
    sec = max(0, int(float(sec)))
    h, m, s = sec // 3600, (sec % 3600) // 60, sec % 60
    if h or force_hour:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"


def fmt_duration(sec):
    if not sec:
        return "未知"
    sec = int(sec)
    h, m, s = sec // 3600, (sec % 3600) // 60, sec % 60
    if h:
        return f"{h} 小時 {m} 分"
    if m:
        return f"{m} 分 {s} 秒"
    return f"{s} 秒"


def is_cjk(text):
    sample = text[:500]
    if not sample:
        return False
    cjk = sum(1 for c in sample if "一" <= c <= "鿿")
    return cjk > len(sample) * 0.15


def est_tokens(text):
    """粗估 token 數：中日韓字元約 1 token，其餘約 4 字元 1 token。"""
    cjk = sum(1 for c in text if "一" <= c <= "鿿" or "぀" <= c <= "ヿ")
    other = len(text) - cjk
    return int(cjk + other / 4)


# ==========================================================================
# 逐字稿清理
# ==========================================================================

NOISE_PAT = re.compile(
    r"^\s*[\[\(（【]?\s*(音樂|音乐|掌聲|掌声|笑聲|笑声|無聲|背景音樂|"
    r"music|applause|laughter|silence|sound effect|foreign|blank_audio|"
    r"♪+|＃|#)\s*[\]\)）】]?\s*$", re.I)

FILLER_EN = re.compile(r"\b(um+|uh+|erm+|hmm+|mm+hmm)\b[,]?\s*", re.I)
FILLER_ZH = re.compile(r"(?<![一-鿿])(呃+|嗯+|欸+|唉+)(?![一-鿿])")


def clean_segments(segments, aggressive=True):
    """移除雜訊標記、連續重複行、口頭禪。保守處理，避免刪掉有意義的內容。"""
    out = []
    prev = None
    for seg in segments:
        t = (seg.get("text") or "").replace("\n", " ").strip()
        t = re.sub(r"\s+", " ", t)
        if not t:
            continue
        if NOISE_PAT.match(t) or re.fullmatch(r"[♪♫\s]+", t):
            continue
        if aggressive:
            t = FILLER_EN.sub("", t)
            t = FILLER_ZH.sub("", t)
            t = re.sub(r"\b(\w+)( \1\b)+", r"\1", t)      # the the the -> the
            t = re.sub(r"\s+", " ", t).strip()
            if not t:
                continue
        if prev is not None and t == prev:                 # 滾動字幕的重複行
            continue
        prev = t
        out.append({"text": t, "start": seg.get("start", 0.0),
                    "duration": seg.get("duration", 0.0)})
    return out


def build_paragraphs(segments, target_sec=45):
    """把破碎字幕合併成語意段落，每段記錄起始時間。

    以「約 45 秒一段」為目標，優先在句末標點處斷開；
    自動字幕沒有標點時則以長度上限強制斷段。
    """
    if not segments:
        return []
    cjk = is_cjk(" ".join(s["text"] for s in segments[:50]))
    sep = "" if cjk else " "
    hard_chars = 180 if cjk else 900
    enders = "。！？!?…」』】."

    paras, buf, start = [], "", None
    for seg in segments:
        t = seg["text"].strip()
        if not t:
            continue
        if start is None:
            start = seg["start"]
        buf = t if not buf else buf + sep + t
        elapsed = seg["start"] + (seg.get("duration") or 0) - start
        ended = buf and buf[-1] in enders
        if (elapsed >= target_sec and ended) or elapsed >= target_sec * 1.8 \
                or len(buf) >= hard_chars:
            paras.append({"start": start, "text": buf.strip()})
            buf, start = "", None
    if buf.strip():
        paras.append({"start": start or 0, "text": buf.strip()})
    return paras


# ==========================================================================
# 引擎 1：youtube-transcript-api（最快）
# ==========================================================================

def engine_transcript_api(video_id, langs, log):
    from youtube_transcript_api import YouTubeTranscriptApi

    api = YouTubeTranscriptApi()
    tlist = api.list(video_id)
    codes = [f"{t.language_code}{'(自動)' if t.is_generated else ''}" for t in tlist]
    log("找到字幕軌：" + "、".join(codes[:10]))

    transcript = None
    for finder in ("find_manually_created_transcript", "find_generated_transcript"):
        try:
            transcript = getattr(tlist, finder)(langs)
            break
        except Exception:
            continue

    if transcript is None:
        first = next(iter(tlist))
        if first.is_translatable:
            for target in ("zh-TW", "zh-Hant", "zh-Hans", "en"):
                try:
                    transcript = first.translate(target)
                    log(f"原始語言 {first.language_code}，已自動翻譯為 {target}")
                    break
                except Exception:
                    continue
        transcript = transcript or first

    fetched = transcript.fetch()
    segs = [{"text": sn.text, "start": sn.start, "duration": sn.duration} for sn in fetched]
    return segs, {"lang": transcript.language_code, "generated": transcript.is_generated}


# ==========================================================================
# 引擎 2：yt-dlp（備援 + 後設資料來源）
# ==========================================================================

def ytdlp_info(url):
    import yt_dlp
    opts = {"skip_download": True, "quiet": True, "no_warnings": True,
            "writesubtitles": True, "writeautomaticsub": True}
    with yt_dlp.YoutubeDL(opts) as ydl:
        return ydl.extract_info(url, download=False)


# 這幾條「軌」會出現在 yt-dlp 的 subtitles 欄位裡，但它們不是字幕：
#   danmaku   —— bilibili 彈幕。那是觀眾留言，和影片旁白無關，格式也是
#                彈幕專用的 <d p="...">，用字幕解析器讀出來永遠是空的。
#   live_chat —— YouTube 直播留言回放，同理。
# 沒排除它們的後果不只是解析失敗：has_caption_tracks 會把彈幕當成字幕，
# 於是「有字幕但抓不到」的防呆被誤觸發，連 AI 聽寫都一併略過，
# 等於每一部 bilibili 影片都直接死在這裡。
NON_CAPTION_TRACKS = ("danmaku", "live_chat")


def real_caption_tracks(tracks):
    """濾掉彈幕、直播留言這類掛在字幕欄位、但其實不是字幕的軌。"""
    return {k: v for k, v in (tracks or {}).items()
            if k.lower() not in NON_CAPTION_TRACKS}


def has_caption_tracks(info):
    """影片是否真的有字幕軌？None 代表無法判斷（連後設資料都沒拿到）。"""
    if not info:
        return None
    return bool(real_caption_tracks(info.get("subtitles"))
                or real_caption_tracks(info.get("automatic_captions")))


def fetch_with_retry(url, log, tries=3):
    """下載字幕內容。遇到 429 時退避重試，短暫限流多半撐得過去。"""
    last = None
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            return urllib.request.urlopen(req, timeout=30).read()
        except urllib.error.HTTPError as e:
            last = e
            if e.code in (429, 503) and i < tries - 1:
                wait = 3 * (i + 1)
                log(f"YouTube 暫時限流，{wait} 秒後重試（第 {i + 2}/{tries} 次）")
                time.sleep(wait)
                continue
            raise
        except Exception as e:
            last = e
            if i < tries - 1:
                time.sleep(2)
                continue
            raise
    raise last


def _pick_track(tracks, langs):
    tracks = real_caption_tracks(tracks)
    for want in langs:
        for code in tracks:
            if code.lower() == want.lower():
                return code, tracks[code]
    for want in langs:
        base = want.split("-")[0].lower()
        for code in tracks:
            if code.lower().startswith(base):
                return code, tracks[code]
    if tracks:
        code = next(iter(tracks))
        return code, tracks[code]
    return None, None


# SRT 與 WebVTT 的時間碼。時／百分秒都可能省略，所以都設成可選。
TIMECODE_RE = re.compile(
    r"(?:(\d{1,2}):)?(\d{1,2}):(\d{2})[.,](\d{1,3})\s*-->\s*"
    r"(?:(\d{1,2}):)?(\d{1,2}):(\d{2})[.,](\d{1,3})")


def _parse_json3(body):
    """YouTube 的 json3。"""
    segs = []
    for ev in json.loads(body).get("events", []):
        if not ev.get("segs"):
            continue
        text = "".join(sg.get("utf8", "") for sg in ev["segs"]).strip()
        if text:
            segs.append({"text": text,
                         "start": (ev.get("tStartMs") or 0) / 1000.0,
                         "duration": (ev.get("dDurationMs") or 0) / 1000.0})
    return segs


def _parse_srv1(body):
    """YouTube 的 srv1／ttml 系列：<text start=".." dur="..">內容</text>。"""
    segs = []
    for m in re.finditer(r'<text start="([\d.]+)"(?: dur="([\d.]+)")?>(.*?)</text>',
                         body, re.S):
        text = html_mod.unescape(re.sub(r"<[^>]+>", "", m.group(3))).strip()
        if text:
            segs.append({"text": text, "start": float(m.group(1)),
                         "duration": float(m.group(2) or 0)})
    return segs


def _parse_srt_vtt(body):
    """SRT／WebVTT。bilibili 的人工字幕就是 yt-dlp 轉出來的 SRT。"""
    segs = []
    for block in re.split(r"\n\s*\n", body.replace("\r\n", "\n").strip()):
        lines = block.split("\n")
        idx = next((i for i, ln in enumerate(lines) if TIMECODE_RE.search(ln)), None)
        if idx is None:
            continue
        g = TIMECODE_RE.search(lines[idx]).groups()

        def secs(h, m, s, ms):
            # 百分秒可能只有 1～2 位，補滿 3 位才不會把 .5 秒讀成 5 毫秒
            return int(h or 0) * 3600 + int(m) * 60 + int(s) + int(ms.ljust(3, "0")) / 1000.0

        start, end = secs(*g[:4]), secs(*g[4:])
        text = " ".join(ln.strip() for ln in lines[idx + 1:] if ln.strip())
        text = html_mod.unescape(re.sub(r"<[^>]+>", "", text)).strip()
        if text:
            segs.append({"text": text, "start": start,
                         "duration": max(0.0, end - start)})
    return segs


def engine_ytdlp(url, langs, log, info=None):
    info = info or ytdlp_info(url)
    manual = info.get("subtitles") or {}
    auto = info.get("automatic_captions") or {}

    code, track = _pick_track(manual, langs)
    generated = False
    if not track:
        code, track = _pick_track(auto, langs)
        generated = True
    if not track:
        raise RuntimeError("這部影片沒有任何字幕軌")

    log(f"yt-dlp 取得字幕軌 {code}{'（自動）' if generated else '（人工）'}")
    fmt = (next((f for f in track if f.get("ext") == "json3"), None)
           or next((f for f in track if f.get("ext") == "srv1"), None)
           or next((f for f in track if f.get("ext") in ("srt", "vtt")), None)
           or track[0])

    # bilibili 之類的站台是把字幕內容直接塞在 data 裡的，沒有可下載的 url。
    # 舊版寫死 fmt["url"]，碰到這種字幕會 KeyError。
    if fmt.get("data") is not None:
        body = fmt["data"]
        if isinstance(body, bytes):
            body = body.decode("utf-8", "replace")
    else:
        body = fetch_with_retry(fmt["url"], log).decode("utf-8", "replace")

    ext = (fmt.get("ext") or "").lower()
    if ext == "json3":
        segs = _parse_json3(body)
    elif ext in ("srt", "vtt"):
        segs = _parse_srt_vtt(body)
    else:
        # 格式不明就兩種都試一次，總比直接放棄好
        segs = _parse_srv1(body) or _parse_srt_vtt(body)

    if not segs:
        raise RuntimeError(f"抓到字幕軌 {code}（{ext or '未知格式'}）但解析不出內容")
    return segs, {"lang": code, "generated": generated}


# ==========================================================================
# 引擎 3：faster-whisper（影片完全沒字幕時）
# ==========================================================================

def estimate_audio_mb(info, low_data=True):
    """從後設資料估算音訊下載量（MB）。不連網，純計算。"""
    if not info:
        return None
    dur = float(info.get("duration") or 0)
    cands = []
    for f in (info.get("formats") or []):
        if f.get("vcodec") not in (None, "none"):
            continue
        if f.get("acodec") in (None, "none"):
            continue
        size = f.get("filesize") or f.get("filesize_approx")
        abr = f.get("abr") or 0
        if not size and abr and dur:
            size = abr * 1000 / 8 * dur
        if size:
            cands.append((abr or 999, size))
    if not cands:
        return None
    cands.sort()
    return (cands[0][1] if low_data else cands[-1][1]) / 1048576


def download_audio(url, log, low_data=True, info=None):
    """只下載音訊。省流量模式會挑位元率最低的音軌。

    Whisper 一律把音訊重新取樣成 16kHz 單聲道，所以高位元率音源
    對辨識準確度幾乎沒有幫助，卻會多耗好幾倍的行動數據。
    """
    import tempfile
    import yt_dlp

    est = estimate_audio_mb(info, low_data)
    if est:
        log(f"準備下載音訊，預估約 {est:.1f} MB"
            + ("（省流量模式）" if low_data else ""))

    tmpdir = tempfile.mkdtemp(prefix="audio_")
    opts = {"format": "bestaudio/best",
            "outtmpl": os.path.join(tmpdir, "a.%(ext)s"),
            "quiet": True, "no_warnings": True}
    if low_data:
        # '+abr' = 由小到大排序，等於挑最低位元率的音軌
        opts["format_sort"] = ["+abr", "+size"]

    with yt_dlp.YoutubeDL(opts) as ydl:
        got = ydl.extract_info(url, download=True)
        path = ydl.prepare_filename(got)

    size_mb = os.path.getsize(path) / 1048576 if os.path.exists(path) else 0
    log(f"音訊下載完成：實際用掉 {size_mb:.1f} MB 流量")
    return path, tmpdir, size_mb, got


# 本機實測的處理速度（實時倍率）。用來在開始 AI 聽寫前預估耗時，
# 讓使用者知道大概要等多久，而不是默默卡住。
RT_FACTOR = {"tiny": 17.0, "base": 11.0, "small": 4.2, "medium": 1.5}
RT_PHONE = {"tiny": 1.5, "base": 0.9, "small": 0.35, "medium": 0.15}


def eta_text(duration, model):
    """預估 AI 聽寫要多久，回傳人話。"""
    tbl = RT_PHONE if IS_TERMUX else RT_FACTOR
    ratio = tbl.get(model, 4.0)
    sec = (duration or 0) / ratio
    if not sec:
        return ""
    if sec < 90:
        return f"約 {int(sec)} 秒"
    return f"約 {int(sec // 60)} 分鐘"


# 各模型的下載大小（MB）。用來在首次下載時給出有意義的百分比與預估時間。
WHISPER_MODEL_MB = {"tiny": 75, "base": 142, "small": 466,
                    "medium": 1530, "large-v2": 3090, "large-v3": 3090}


def _hf_cache_dir():
    try:
        from huggingface_hub.constants import HF_HUB_CACHE
        return HF_HUB_CACHE
    except Exception:
        return os.path.join(os.path.expanduser("~"), ".cache", "huggingface", "hub")


def _model_cache_root(size):
    return os.path.join(_hf_cache_dir(), f"models--Systran--faster-whisper-{size}")


def _dir_bytes(path):
    total = 0
    for dirpath, _dirs, files in os.walk(path):
        for fn in files:
            try:
                total += os.path.getsize(os.path.join(dirpath, fn))
            except OSError:
                pass                    # 下載中的檔案隨時可能被改名，忽略即可
    return total


def whisper_model_cached(size):
    """模型是否已完整存在本機。不連網、也不把模型載進記憶體。"""
    snaps = os.path.join(_model_cache_root(size), "snapshots")
    if not os.path.isdir(snaps):
        return False
    for _dirpath, _dirs, files in os.walk(snaps):
        if "model.bin" in files:
            return True
    return False


def _report_model_download(size, log, stop):
    """模型下載期間每隔幾秒回報進度。

    沒有這段的話，首次使用會有好幾分鐘、慢速網路上甚至幾十分鐘完全沒有任何
    輸出。實測有人因此等了 25 分鐘，以為程式當掉 —— 而它其實只是在下載。
    百分比是用快取目錄的大小去估的，不完全精確，但足以看出它在動。
    """
    root = _model_cache_root(size)
    total_mb = WHISPER_MODEL_MB.get(size, 0)
    t0 = time.time()
    while not stop.wait(5):
        mb = _dir_bytes(root) / (1024 * 1024)
        if mb < 1:
            continue
        elapsed = time.time() - t0
        rate = mb / elapsed if elapsed > 0 else 0
        if total_mb:
            pct = min(99, int(mb / total_mb * 100))
            msg = f"下載 AI 模型 {size}… {pct}%（{mb:.0f}/{total_mb} MB"
            left = (total_mb - mb) / rate if rate > 0.05 else 0
            if 0 < left < 36000:
                msg += f"．約還要 {int(left // 60)} 分 {int(left % 60)} 秒"
            log(msg + "）")
        else:
            log(f"下載 AI 模型 {size}…（已取得 {mb:.0f} MB）")


def load_whisper_with_progress(size, log):
    """載入模型；若本機還沒有，下載期間持續回報進度。"""
    if whisper_model_cached(size):
        log(f"載入 AI 模型 {size}…")
        return load_whisper_model(size, log)

    mb = WHISPER_MODEL_MB.get(size)
    log(f"首次使用 {size} 模型，需要先下載"
        + (f"約 {mb} MB" if mb else "模型檔")
        + "（只有這一次，之後永久離線可用）")

    stop = threading.Event()
    watcher = threading.Thread(target=_report_model_download,
                               args=(size, log, stop), daemon=True)
    watcher.start()
    try:
        return load_whisper_model(size, log)
    finally:
        stop.set()


def enable_cuda_dlls():
    """Windows 上讓程式找得到 pip 安裝的 CUDA 函式庫。

    nvidia-cublas-cu12 / nvidia-cudnn-cu12 會把 DLL 放在 site-packages\\nvidia\\*\\bin，
    但那些目錄不在系統 DLL 搜尋路徑裡，不手動加入的話 CTranslate2 會找不到，
    結果就是明明裝了顯卡函式庫卻一直退回 CPU。
    """
    if sys.platform != "win32":
        return
    try:
        import nvidia
        base = os.path.dirname(nvidia.__file__)
        for sub in os.listdir(base):
            d = os.path.join(base, sub, "bin")
            if os.path.isdir(d):
                os.add_dll_directory(d)
    except Exception:
        pass


def _import_whisper_first():
    """一定要在碰 ctranslate2 之前先匯入 faster-whisper。順序不能反。

    Anaconda 環境裡有兩份 Intel OpenMP：ctranslate2 自帶一份，MKL 一份。
    實測（Anaconda Python 3.13 + ctranslate2 4.8.2）：
        import ctranslate2 → import faster_whisper → 建立模型   OMP: Error #15
        import faster_whisper → import ctranslate2 → 建立模型   正常
    而且那不是可以攔截的例外，是 OpenMP 直接 abort 整個行程，try/except
    完全接不到，使用者只會看到程式無聲無息地消失。

    這個順序陷阱很容易再次踩到：pick_device() 會被 default_model_size()
    在真正開始聽寫之前先呼叫，所以光靠 engine_whisper 自己先匯入是不夠的。
    """
    try:
        import faster_whisper  # noqa: F401
    except Exception:
        pass            # 沒裝就算了，反正沒有 faster-whisper 也不會用到 GPU


def _cuda_libs_present():
    """cublas 函式庫到底在不在。

    get_cuda_device_count() 只證明有顯卡驅動，不代表推論時載得到 cublas ——
    CTranslate2 是延遲載入的，缺函式庫會等到真正 encode() 時才炸。
    這件事不只影響能不能用 GPU：pick_device() 的結果還會決定模型大小
    （見 default_model_size），判斷錯就會挑了 small 卻跑在 CPU 上，
    正好是最慢的組合。

    這裡直接看檔案在不在，不用 ctypes 去載。載入成功與否還牽涉 DLL 搜尋
    路徑的細節（os.add_dll_directory 對 ctypes 的影響），查檔案單純得多，
    而且真的載不起來時還有 _force_cuda_load() 這道保險。
    """
    if sys.platform != "win32":
        return True                 # 其他平台交給 ctranslate2 自己判斷
    try:
        import nvidia
        base = os.path.dirname(nvidia.__file__)
        for sub in os.listdir(base):
            d = os.path.join(base, sub, "bin")
            if os.path.isdir(d) and any(f.lower().startswith("cublas64_")
                                        for f in os.listdir(d)):
                return True
    except Exception:
        pass
    for p in os.environ.get("PATH", "").split(os.pathsep):
        if p.strip() and os.path.exists(os.path.join(p, "cublas64_12.dll")):
            return True
    return False


def pick_device():
    """有 NVIDIA 顯卡就用 GPU，否則用 CPU。回傳 (device, compute_type)。

    計算型別的選擇有陷阱：Pascal 世代顯卡（GTX 10 系列）的 FP16 吞吐量
    被限制在 1/64，用 float16 反而比 CPU 還慢。但它們支援 DP4A 整數指令，
    所以一律用 int8，這在新舊顯卡上都是安全且快速的選擇。
    """
    try:
        _import_whisper_first()
        enable_cuda_dlls()
        import ctranslate2
        if ctranslate2.get_cuda_device_count() > 0 and _cuda_libs_present():
            return "cuda", "int8_float32"
    except Exception:
        pass
    return "cpu", "int8"


def _force_cuda_load(model):
    """對 1 秒無聲實際跑一次推論，強迫 CTranslate2 當場載入 CUDA 函式庫。

    CTranslate2 是延遲載入的：建構子完全不碰 cublas／cudnn，要到第一次
    encode() 才載。所以只把建構子包在 try 裡，錯誤根本抓不到 —— 它會等到
    後面真正 transcribe() 時才炸（RuntimeError: cublas64_12.dll not found），
    那時已經在 try 區塊外面，退回 CPU 的保護網形同虛設。
    """
    import numpy as np

    segs, _ = model.transcribe(np.zeros(16000, dtype=np.float32),
                               language="en", without_timestamps=True)
    next(iter(segs), None)      # transcribe 回傳產生器，要消費才會真的算


def load_whisper_model(size, log):
    """載入模型，GPU 失敗時自動退回 CPU（缺 CUDA 函式庫時很常見）。"""
    from faster_whisper import WhisperModel

    device, compute = pick_device()
    if device == "cuda":
        try:
            m = WhisperModel(size, device="cuda", compute_type=compute)
            _force_cuda_load(m)
            log(f"使用顯示卡加速（GPU．{compute}）")
            return m
        except Exception as e:
            log(f"顯示卡無法使用（{type(e).__name__}），改用 CPU")
    return WhisperModel(size, device="cpu", compute_type="int8")


def default_model_size():
    """自動挑模型，不讓使用者選。

    實測（18.7 分鐘影片，對照人工字幕）：
        tiny   75MB   1分05秒   與 small 分歧 5.6%
        base  142MB   1分42秒   與 small 分歧 4.9%
        small 466MB   4分27秒   基準
    base 比 tiny 只好 0.7 個百分點卻慢 1.5 倍，完全被支配，所以不使用。
    """
    if IS_TERMUX:
        return "tiny"                       # 手機 CPU 弱，只能用最小的
    if pick_device()[0] == "cuda":
        return "small"                      # 顯卡夠快，直接給最佳品質
    return "small" if (os.cpu_count() or 2) >= 4 else "tiny"


def engine_whisper(url, langs, log, model_size=None, low_data=True, info=None,
                   lang=None):
    try:
        import faster_whisper  # noqa: F401
    except ImportError:
        raise RuntimeError(
            "這部影片沒有任何字幕，需要用 AI 聽寫，但還沒安裝聽寫元件。\n"
            "請執行一次（免費、之後永久可用）：\n"
            "    pip install faster-whisper")

    model_size = model_size or default_model_size()
    audio, tmpdir, size_mb, got = download_audio(url, log, low_data, info)
    total = float((got or {}).get("duration") or (info or {}).get("duration") or 0)

    model = load_whisper_with_progress(model_size, log)

    # 語言交給 Whisper 自動偵測（lang=None）。
    # 先前的寫法是從語言偏好清單取第一個，而預設清單第一個永遠是 zh，
    # 等於把英文影片硬指定成中文辨識，產出完全錯誤的結果。
    log("AI 聽寫中…（完全在本機運算，不會上傳任何資料）"
        + ("" if lang else "｜語言自動偵測"))
    segments, winfo = model.transcribe(
        audio, beam_size=5, vad_filter=True, language=lang,
        condition_on_previous_text=False)

    segs = []
    t0 = time.time()
    for s in segments:
        t = (s.text or "").strip()
        if t:
            segs.append({"text": t, "start": s.start, "duration": s.end - s.start})
        if total and len(segs) % 12 == 0 and segs:
            pct = min(99, int(s.end / total * 100))
            spent = time.time() - t0
            eta = spent / max(s.end, 1) * max(total - s.end, 0)
            log(f"AI 聽寫中… {pct}%（預計還要 {int(eta // 60)} 分 {int(eta % 60)} 秒）")

    import shutil
    shutil.rmtree(tmpdir, ignore_errors=True)
    return segs, {"lang": winfo.language, "generated": True, "whisper": True,
                  "engine": f"faster-whisper {model_size}", "audio_mb": size_mb}


# ==========================================================================
# 引擎 3B：whisper.cpp（手機用；Android 沒有 CTranslate2 預編譯套件）
# ==========================================================================

CHUNK_SEC = 1800          # 長影片每 30 分鐘一段處理，避免暫存 WAV 過大
GGML_SIZES = {"tiny": 75, "base": 142, "small": 466, "medium": 1500, "large-v3": 3100}
GGML_URL = "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-{}.bin"


def model_dir():
    d = os.path.join(os.path.expanduser("~"), ".cache", "whisper-cpp")
    os.makedirs(d, exist_ok=True)
    return d


def find_whisper_cli():
    """找 whisper.cpp 的執行檔（Android 上由 termux-stt 提供預編譯版）。"""
    import shutil

    try:                                    # termux-stt 內附 ARM64 預編譯執行檔
        import termux_stt
        for name in ("whisper-cli", "main"):
            p = os.path.join(os.path.dirname(termux_stt.__file__), "bin", name)
            if os.path.exists(p):
                return p
    except Exception:
        pass

    for name in ("whisper-cli", "whisper-cpp", "whisper", "main"):
        p = shutil.which(name)
        if p:
            return p

    home = os.path.expanduser("~")
    for p in (os.path.join(home, "whisper.cpp", "build", "bin", "whisper-cli"),
              os.path.join(home, "whisper.cpp", "build", "bin", "main"),
              os.path.join(home, "whisper.cpp", "main")):
        if os.path.exists(p):
            return p
    return None


def ensure_ggml_model(size, log):
    """確保模型檔存在，不在就從 Hugging Face 下載（僅第一次，之後永久離線可用）。"""
    path = os.path.join(model_dir(), f"ggml-{size}.bin")
    if os.path.exists(path) and os.path.getsize(path) > 1_000_000:
        return path

    mb = GGML_SIZES.get(size, 0)
    log(f"首次使用，正在下載 AI 聽寫模型 {size}（約 {mb} MB，只需這一次）…")
    tmp = path + ".part"
    req = urllib.request.Request(GGML_URL.format(size), headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=120) as r, open(tmp, "wb") as f:
        total = int(r.headers.get("Content-Length") or 0)
        done = 0
        last = 0.0
        while True:
            chunk = r.read(1 << 20)
            if not chunk:
                break
            f.write(chunk)
            done += len(chunk)
            if total and time.time() - last > 2:
                last = time.time()
                log(f"下載模型中… {done * 100 // total}%（{done // 1048576}/{total // 1048576} MB）")
    os.replace(tmp, path)
    log("模型下載完成，之後不需再下載")
    return path


def engine_whispercpp(url, langs, log, model_size=None, low_data=True, info=None,
                      lang=None):
    import shutil
    import subprocess

    exe = find_whisper_cli()
    if not exe:
        raise RuntimeError(
            "找不到 whisper.cpp 執行檔。\n"
            "Android 請在 Termux 執行：pkg install ffmpeg && pip install termux-stt")

    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("需要 ffmpeg 才能轉換音訊。Android：pkg install ffmpeg")

    model_size = model_size or default_model_size()
    model = ensure_ggml_model(model_size, log)

    audio, tmpdir, size_mb, _got = download_audio(url, log, low_data, info)

    # 同 engine_whisper：語言預設自動偵測，不從偏好清單硬猜
    hint = lang or "auto"
    total = float((_got or {}).get("duration") or (info or {}).get("duration") or 0)

    def transcribe_chunk(src, offset, idx):
        """轉成 16kHz WAV -> 聽寫 -> 立刻刪掉暫存檔，回傳帶偏移的段落。"""
        wav = os.path.join(tmpdir, f"c{idx}.wav")
        cmd = [ffmpeg, "-y"]
        if offset is not None:
            cmd += ["-ss", str(offset), "-t", str(CHUNK_SEC)]
        cmd += ["-i", src, "-ar", "16000", "-ac", "1", "-c:a", "pcm_s16le", wav]
        subprocess.run(cmd, capture_output=True, timeout=3600)
        if not os.path.exists(wav) or os.path.getsize(wav) < 2000:
            return []

        base_out = os.path.join(tmpdir, f"o{idx}")
        subprocess.run([exe, "-m", model, "-f", wav, "-l", hint,
                        "-oj", "-of", base_out, "-np", "-nt"],
                       capture_output=True, timeout=14400)
        jp = base_out + ".json"
        got_segs = []
        if os.path.exists(jp):
            with open(jp, encoding="utf-8") as f:
                data = json.load(f)
            for item in data.get("transcription", []):
                txt = (item.get("text") or "").strip()
                if not txt:
                    continue
                off = item.get("offsets") or {}
                st = (off.get("from") or 0) / 1000.0 + (offset or 0)
                en = (off.get("to") or 0) / 1000.0 + (offset or 0)
                got_segs.append({"text": txt, "start": st,
                                 "duration": max(en - st, 0)})
        for f_ in (wav, jp):                    # 立刻回收空間
            try:
                os.remove(f_)
            except Exception:
                pass
        return got_segs

    segs = []
    if total > CHUNK_SEC * 1.2:
        # 長影片分段處理：7 小時的影片若一次轉檔會產生約 770 MB 的暫存 WAV，
        # 手機很容易空間不足。分段後尖峰只有一段的大小（約 55 MB）。
        n = int(total // CHUNK_SEC) + 1
        log(f"影片較長（{total/3600:.1f} 小時），分成 {n} 段處理以節省暫存空間")
        for i in range(n):
            log(f"AI 聽寫中… 第 {i+1}/{n} 段")
            got = transcribe_chunk(audio, i * CHUNK_SEC, i)
            if not got and i > 0:
                break
            segs += got
    else:
        log("AI 聽寫中…（完全離線運算）")
        segs = transcribe_chunk(audio, None, 0)

    shutil.rmtree(tmpdir, ignore_errors=True)
    if not segs:
        raise RuntimeError("AI 聽寫沒有產生任何文字（音訊可能是無聲的，"
                           "或模型太大導致記憶體不足）")
    return segs, {"lang": hint, "generated": True, "whisper": True,
                  "engine": f"whisper.cpp {model_size}", "audio_mb": size_mb}


# ==========================================================================
# 後設資料
# ==========================================================================

def oembed_meta(video_id):
    """超輕量備援：不需任何套件，瞬間取得標題與頻道。"""
    url = ("https://www.youtube.com/oembed?url=https://www.youtube.com/watch?v="
           + video_id + "&format=json")
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    d = json.loads(urllib.request.urlopen(req, timeout=15).read().decode("utf-8"))
    return {"title": d.get("title"), "channel": d.get("author_name"),
            "channel_url": d.get("author_url")}


def collect_meta(url, info=None, video_id=None):
    meta = {"video_id": video_id, "url": url}
    if info:
        meta["url"] = info.get("webpage_url") or url
        site = info.get("extractor_key") or info.get("extractor") or ""
        if site and site.lower() not in ("youtube", "generic"):
            meta["platform"] = site
        upload = info.get("upload_date") or ""
        if len(upload) == 8:
            upload = f"{upload[:4]}-{upload[4:6]}-{upload[6:]}"
        meta.update({
            "title": info.get("title"),
            "channel": info.get("uploader") or info.get("channel"),
            "channel_url": info.get("uploader_url") or info.get("channel_url"),
            "duration": info.get("duration"),
            "upload_date": upload,
            "view_count": info.get("view_count"),
            "chapters": [{"start": c.get("start_time") or 0, "title": c.get("title") or ""}
                         for c in (info.get("chapters") or [])],
        })
    if not meta.get("title") and video_id:      # oEmbed 只適用 YouTube
        try:
            meta.update({k: v for k, v in oembed_meta(video_id).items() if v})
        except Exception:
            pass
    return meta


# ==========================================================================
# Markdown 產生（AI 最佳化格式）
# ==========================================================================

def build_markdown(meta, paras, sub_meta, opts):
    ts_mode = opts.get("timestamps", "para")
    L = []

    mode = opts.get("prompt_mode", "deep")
    if not opts.get("include_prompt", True):   # 舊版選項相容
        mode = "none"
    if mode in PROMPTS:
        L.append("## 給 AI 的分析指示\n")
        L.append(PROMPTS[mode])
        if sub_meta.get("generated"):
            L.append("\n" + CAPTION_NOTE)
        L.append("\n---\n")

    title = meta.get("title") or "YouTube 影片逐字稿"
    L.append(f"# {title}\n")

    if opts.get("include_meta", True):
        L.append("## 影片資訊\n")
        rows = []
        if meta.get("platform"):
            rows.append(("平台", meta["platform"]))
        if meta.get("channel"):
            rows.append(("頻道", meta["channel"]))
        if meta.get("upload_date"):
            rows.append(("發布日期", meta["upload_date"]))
        if meta.get("duration"):
            rows.append(("影片長度", fmt_duration(meta["duration"])))
        src = ("YouTube 自動字幕（語音辨識）" if sub_meta.get("generated")
               else "人工上傳字幕")
        if sub_meta.get("whisper"):
            src = "本機 AI 聽寫（Whisper）"
        rows.append(("字幕來源", f"{src}．語言 {sub_meta.get('lang', '未知')}"))
        rows.append(("影片網址", meta.get("url", "")))
        L.append("| 項目 | 內容 |")
        L.append("|---|---|")
        for k, v in rows:
            L.append(f"| {k} | {v} |")
        L.append("")

        if meta.get("chapters"):
            L.append("## 影片章節（作者標註）\n")
            for c in meta["chapters"]:
                L.append(f"- `[{fmt_ts(c['start'])}]` {c['title']}")
            L.append("")

        # 簡介欄已移除。YouTube 簡介幾乎都是聯盟行銷連結、邀請碼、交易所
        # 推薦與 SEO 關鍵字堆砌，靠黑名單永遠追不上新的變形，留著只會把
        # 業配文餵給 AI。真正有價值的結構資訊是上面的「影片章節」，
        # 那是另外抽的，不受影響。需要原始簡介時請自行到影片頁面取得。

    L.append("## 逐字稿\n")
    long_video = (meta.get("duration") or 0) >= 3600
    for p in paras:
        if ts_mode == "none":
            L.append(p["text"] + "\n")
        else:
            L.append(f"**`[{fmt_ts(p['start'], long_video)}]`** {p['text']}\n")

    return "\n".join(L).strip() + "\n"


def build_plaintext(meta, paras, sub_meta, opts):
    ts_mode = opts.get("timestamps", "para")
    L = []
    if opts.get("include_meta", True):
        L.append(meta.get("title") or "YouTube 影片逐字稿")
        if meta.get("channel"):
            L.append("頻道：" + meta["channel"])
        if meta.get("duration"):
            L.append("長度：" + fmt_duration(meta["duration"]))
        L.append("網址：" + meta.get("url", ""))
        L.append("=" * 50)
        L.append("")
    long_video = (meta.get("duration") or 0) >= 3600
    for p in paras:
        if ts_mode == "none":
            L.append(p["text"])
        else:
            L.append(f"[{fmt_ts(p['start'], long_video)}] {p['text']}")
        L.append("")
    return "\n".join(L).strip() + "\n"


def build_srt(segments):
    def t(sec):
        sec = max(0.0, float(sec))
        h, m = int(sec // 3600), int((sec % 3600) // 60)
        return ("%02d:%02d:%06.3f" % (h, m, sec % 60)).replace(".", ",")
    out, n = [], 0
    for s in segments:
        txt = s["text"].strip()
        if not txt:
            continue
        n += 1
        end = s["start"] + (s.get("duration") or 2.0)
        out += [str(n), f"{t(s['start'])} --> {t(end)}", txt, ""]
    return "\n".join(out)


# ==========================================================================
# 主流程
# ==========================================================================

def transcribe(url_or_id, opts=None, log=print):
    opts = opts or {}
    langs = opts.get("langs") or DEFAULT_LANGS
    kind, url, vid = normalize_target(url_or_id)

    # --- 快取：同一部影片再處理一次時完全不耗流量 ---
    cached = None if opts.get("no_cache") else cache_load(url)
    if cached:
        log("這部影片處理過了，直接用本機快取（不耗任何流量）")
        return assemble(cached["meta"], cached["segments"],
                        cached["sub_meta"], opts, log)

    # 只有真的要用到影片資訊（標題／章節）時才抓那 202 KB。
    # 不需要時改用 1 KB 的 oEmbed，只有備援引擎啟動時才補抓。
    need_info = kind != "youtube" or opts.get("include_meta", True)

    pool = ThreadPoolExecutor(max_workers=2)
    info_future = pool.submit(lambda: _safe(ytdlp_info, url)) if need_info else None

    segments, sub_meta, errors = None, None, []

    if kind == "youtube":
        log("正在取得字幕…")
        try:
            segments, sub_meta = engine_transcript_api(vid, langs, log)
        except Exception as e:
            errors.append(f"引擎1 {type(e).__name__}: {str(e)[:150]}")
            log("主要管道未成功，切換備援…")
    else:
        log("非 YouTube 連結，交給 yt-dlp 處理…")

    info = info_future.result() if info_future else None
    if info is None and not segments:
        info = _safe(ytdlp_info, url)      # 備援引擎需要它，這時才補抓

    if not segments:
        try:
            segments, sub_meta = engine_ytdlp(url, langs, log, info=info)
        except Exception as e:
            errors.append(f"引擎2 {type(e).__name__}: {str(e)[:150]}")
            log("這部影片沒有現成字幕…")

    # 關鍵防呆：分清楚「這部影片沒有字幕」與「字幕存在但暫時抓不到」。
    # 兩者的正確處置完全相反 —— 前者該用 AI 聽寫，後者只要等一下重試。
    # 若因為被限流就跑去聽寫，使用者會白白等上數十分鐘的運算。
    if not segments and has_caption_tracks(info):
        # 只顯示真正的字幕語言。automatic_captions 裡有上百條
        # 「翻譯成某語言」的衍生軌（aa-zh、ab-zh…），列出來只會造成誤解。
        manual = list((info.get("subtitles") or {}).keys())
        auto = [k for k in (info.get("automatic_captions") or {})
                if "-" not in k or k.split("-")[0] in ("zh", "pt", "es", "en")]
        tracks = (manual or auto)[:6]
        raise RuntimeError(
            "這部影片其實有字幕（" + "、".join(tracks) + " …），"
            "但現在下載不到。\n\n"
            "原因幾乎都是 YouTube 暫時限制了這台電腦的請求次數（HTTP 429），"
            "通常幾分鐘到一小時內會自動恢復。\n\n"
            "已自動略過 AI 聽寫 —— 這部影片有現成字幕，"
            "沒必要花幾十分鐘重新辨識。請稍後再試一次。\n\n"
            "技術細節：\n" + "\n".join(errors))

    if not segments and opts.get("allow_whisper", True):
        mdl0 = opts.get("whisper_model") or default_model_size()
        dur0 = float((info or {}).get("duration") or 0)
        mb0 = estimate_audio_mb(info, True)
        bits = ["這部影片沒有字幕，自動改用 AI 聽寫"]
        if dur0:
            bits.append(f"預計 {eta_text(dur0, mdl0)}")
        if mb0:
            bits.append(f"下載約 {mb0:.1f} MB")
        log("｜".join(bits) + "（全程在本機運算）")
        # Android 沒有 CTranslate2 預編譯套件，所以手機優先走 whisper.cpp
        order = ([engine_whispercpp, engine_whisper] if IS_TERMUX
                 else [engine_whisper, engine_whispercpp])
        mdl = opts.get("whisper_model")
        low = opts.get("low_data", True)   # 實測證實無品質影響，一律啟用
        for fn in order:
            try:
                segments, sub_meta = fn(url, langs, log, model_size=mdl,
                                        low_data=low, info=info,
                                        lang=opts.get("whisper_lang") or None)
                if segments:
                    break
            except Exception as e:
                errors.append(f"{fn.__name__} {type(e).__name__}: {str(e)[:250]}")

    pool.shutdown(wait=False)

    if not segments:
        if not opts.get("allow_whisper", True):
            errors.append("（「沒字幕時用 AI 聽寫」目前是關閉的，開啟後可處理無字幕影片）")
        raise RuntimeError("無法取得這部影片的逐字稿。\n\n" + "\n".join(errors))

    meta = collect_meta(url, info, vid)
    cache_save(url, meta, segments, sub_meta)

    log(f"取得 {len(segments)} 段原始字幕，整理中…")
    return assemble(meta, segments, sub_meta, opts, log)


# 分份的兩個門檻分開設定：
#   SPLIT_ABOVE  低於這個大小就完全不切 —— 一小時的影片約 1.8 萬 tokens，
#                AI 一次讀完毫無問題，切開反而是多餘的干擾
#   PART_TOKENS  真的需要切時，每一份的目標大小
SPLIT_ABOVE = 30000
PART_TOKENS = 18000


def split_parts(meta, paras, sub_meta, opts, log=print):
    """長影片切成多份，每份都能獨立貼給 AI。

    七小時的課程影片逐字稿可達九萬 tokens，雖然塞得進 AI 的上限，
    但超長輸入會讓分析品質明顯下降。切成數份各自分析，效果好得多。
    優先沿著作者標註的章節切，沒有章節才按長度切。
    """
    if not paras:
        return []

    total = est_tokens("".join(p["text"] for p in paras))
    if total <= SPLIT_ABOVE:
        return []

    chapters = meta.get("chapters") or []
    groups, cur, cur_tok = [], [], 0

    if chapters and len(chapters) >= 2:
        # 依章節邊界切，累積到接近目標大小才斷開
        bounds = [c["start"] for c in chapters[1:]] + [float("inf")]
        bi = 0
        for p in paras:
            while bi < len(bounds) - 1 and p["start"] >= bounds[bi]:
                bi += 1
                if cur_tok >= PART_TOKENS * 0.8:
                    groups.append(cur)
                    cur, cur_tok = [], 0
            cur.append(p)
            cur_tok += est_tokens(p["text"])
            if cur_tok >= PART_TOKENS * 1.4:
                groups.append(cur)
                cur, cur_tok = [], 0
    else:
        for p in paras:
            cur.append(p)
            cur_tok += est_tokens(p["text"])
            if cur_tok >= PART_TOKENS:
                groups.append(cur)
                cur, cur_tok = [], 0
    if cur:
        groups.append(cur)

    n = len(groups)
    long_video = (meta.get("duration") or 0) >= 3600
    title = meta.get("title") or "影片逐字稿"
    parts = []
    for i, g in enumerate(groups, 1):
        a = fmt_ts(g[0]["start"], long_video)
        b = fmt_ts(g[-1]["start"] + 60, long_video)
        L = []
        if opts.get("prompt_mode", "deep") in PROMPTS:
            L.append("## 給 AI 的分析指示\n")
            L.append(PROMPTS[opts.get("prompt_mode", "deep")])
            if sub_meta.get("generated"):
                L.append("\n" + CAPTION_NOTE)
            L.append(f"\n**這是整部影片的第 {i} 份（共 {n} 份），涵蓋 {a}～{b}。**\n"
                     "請只針對這一份的內容分析，不要臆測其他份的內容。\n")
            L.append("\n---\n")
        L.append(f"# {title}")
        L.append(f"\n> 第 {i} / {n} 份．時間範圍 {a}～{b}"
                 + (f"．頻道 {meta['channel']}" if meta.get("channel") else ""))
        L.append(f"\n> 影片網址：{meta.get('url', '')}\n")
        if i == 1 and meta.get("chapters"):
            L.append("## 影片章節（整部）\n")
            for c in meta["chapters"]:
                L.append(f"- `[{fmt_ts(c['start'], long_video)}]` {c['title']}")
            L.append("")
        L.append("## 逐字稿\n")
        for p in g:
            if opts.get("timestamps", "para") == "none":
                L.append(p["text"] + "\n")
            else:
                L.append(f"**`[{fmt_ts(p['start'], long_video)}]`** {p['text']}\n")
        md = "\n".join(L).strip() + "\n"
        parts.append({"index": i, "total": n, "range": f"{a}～{b}",
                      "markdown": md, "tokens": est_tokens(md)})

    log(f"影片較長（約 {total:,} tokens），已切成 {n} 份，每份可單獨貼給 AI")
    return parts


def assemble(meta, segments, sub_meta, opts, log=print):
    """把原始字幕整理成各種輸出格式。純本機運算，不連網。

    切換分析模式、時間戳等選項時只會重跑這裡，完全不耗流量。
    """
    cleaned = clean_segments(segments, aggressive=opts.get("clean", True))
    paras = build_paragraphs(cleaned, target_sec=int(opts.get("target_sec", 45)))

    markdown = build_markdown(meta, paras, sub_meta, opts)
    plaintext = build_plaintext(meta, paras, sub_meta, opts)
    parts = split_parts(meta, paras, sub_meta, opts, log)

    log(f"完成：{len(paras)} 個段落")
    return {
        "meta": meta, "sub_meta": sub_meta,
        "paragraphs": paras,
        "markdown": markdown,
        "plaintext": plaintext,
        "srt": build_srt(cleaned),
        "parts": parts,
        "stats": {
            "segments": len(segments),
            "paragraphs": len(paras),
            "chars": sum(len(p["text"]) for p in paras),
            "tokens": est_tokens(markdown),
            "chapters": len(meta.get("chapters") or []),
            "audio_mb": round(sub_meta.get("audio_mb", 0), 1),
            "parts": len(parts),
        },
    }


# ---- 本機快取：同一部影片重複處理時完全不耗流量 ----------------------

def cache_dir():
    d = os.path.join(os.path.expanduser("~"), ".cache", "yt-transcript")
    os.makedirs(d, exist_ok=True)
    return d


def _cache_file(url):
    import hashlib
    key = hashlib.sha256(url.encode("utf-8")).hexdigest()[:20]
    return os.path.join(cache_dir(), key + ".json")


def cache_load(url):
    p = _cache_file(url)
    if not os.path.exists(p):
        return None
    try:
        with open(p, encoding="utf-8") as f:
            d = json.load(f)
        if d.get("segments") and d.get("meta"):
            return d
    except Exception:
        pass
    return None


def cache_save(url, meta, segments, sub_meta):
    try:
        with open(_cache_file(url), "w", encoding="utf-8") as f:
            json.dump({"url": url, "meta": meta, "segments": segments,
                       "sub_meta": sub_meta, "saved": time.time()},
                      f, ensure_ascii=False)
    except Exception:
        pass


def _safe(fn, *a):
    try:
        return fn(*a)
    except Exception:
        return None


# ==========================================================================
# 本機網頁伺服器
# ==========================================================================

JOBS = {}
JOBS_LOCK = threading.Lock()
SERVER = None
PORT = None


def _dialog(title, msg, error=False):
    """用 pythonw 執行時沒有主控台，訊息要用小視窗顯示。"""
    try:
        import tkinter as tk
        from tkinter import messagebox
        root = tk.Tk()
        root.withdraw()
        (messagebox.showerror if error else messagebox.showinfo)(title, msg)
        root.destroy()
    except Exception:
        print(msg)


def ensure_deps():
    """首次啟動自動安裝必要套件，用小視窗顯示進度（無主控台也看得到）。"""
    try:
        import youtube_transcript_api, yt_dlp  # noqa: F401
        return True
    except ImportError:
        pass

    import subprocess
    win = None
    try:
        import tkinter as tk
        win = tk.Tk()
        win.title("YouTube 逐字稿工具")
        win.geometry("400x130")
        win.resizable(False, False)
        win.eval("tk::PlaceWindow . center")
        tk.Label(win, text="首次啟動，正在安裝必要元件…",
                 font=("Microsoft JhengHei UI", 12)).pack(pady=(32, 8))
        tk.Label(win, text="約需 30 秒，完成後會自動開啟", fg="#666",
                 font=("Microsoft JhengHei UI", 9)).pack()
        win.update()
    except Exception:
        win = None

    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        subprocess.run([sys.executable, "-m", "pip", "install", "--upgrade",
                        "youtube-transcript-api", "yt-dlp"],
                       creationflags=flags, capture_output=True, timeout=600)
    except Exception:
        pass

    if win:
        try:
            win.destroy()
        except Exception:
            pass

    try:
        import youtube_transcript_api, yt_dlp  # noqa: F401
        return True
    except ImportError:
        _dialog("無法安裝必要元件",
                "自動安裝失敗，請開啟命令提示字元手動執行：\n\n"
                "pip install youtube-transcript-api yt-dlp", error=True)
        return False


def _run_job(job_id, url, opts):
    def log(msg):
        with JOBS_LOCK:
            j = JOBS.get(job_id)
            if j:
                j["log"].append(str(msg))
    try:
        result = transcribe(url, opts, log=log)
        with JOBS_LOCK:
            JOBS[job_id].update(status="done", result=result)
    except Exception as e:
        with JOBS_LOCK:
            JOBS[job_id].update(status="error", error=str(e))


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):
        pass

    def _send(self, code, body, ctype="application/json; charset=utf-8"):
        if isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionAbortedError):
            pass

    def do_GET(self):
        path = urllib.parse.urlparse(self.path).path
        if path in ("/", "/index.html"):
            body = load_asset("ui.html")
            if body is None:
                return self._send(500, "找不到 ui.html", "text/plain; charset=utf-8")
            return self._send(200, body, "text/html; charset=utf-8")

        if path == "/api/status":
            qs = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            jid = (qs.get("id") or [""])[0]
            with JOBS_LOCK:
                job = JOBS.get(jid)
                if not job:
                    return self._send(404, json.dumps({"error": "查無此工作"}))
                payload = {"status": job["status"], "log": job["log"][-12:]}
                if job["status"] == "done":
                    payload["result"] = job["result"]
                elif job["status"] == "error":
                    payload["error"] = job["error"]
            return self._send(200, json.dumps(payload, ensure_ascii=False))

        # 靜態檔（樣式、PWA manifest 與圖示）。白名單，不開放任意路徑。
        if path.lstrip("/") in STATIC_FILES:
            name = path.lstrip("/")
            body = load_asset(name)
            if body is None:
                return self._send(404, b"", STATIC_FILES[name])
            return self._send(200, body, STATIC_FILES[name])

        if path == "/api/info":
            ip = lan_ip()
            return self._send(200, json.dumps({
                "port": PORT,
                "lan_url": f"http://{ip}:{PORT}" if ip else None,
            }))

        return self._send(404, json.dumps({"error": "not found"}))

    def do_POST(self):
        path = urllib.parse.urlparse(self.path).path

        if path == "/api/quit":
            self._send(200, json.dumps({"ok": True}))
            threading.Timer(0.3, lambda: SERVER and SERVER.shutdown()).start()
            return

        if path != "/api/start":
            return self._send(404, json.dumps({"error": "not found"}))
        try:
            n = int(self.headers.get("Content-Length") or 0)
            data = json.loads(self.rfile.read(n).decode("utf-8") or "{}")
        except Exception as e:
            return self._send(400, json.dumps({"error": f"請求格式錯誤：{e}"}))

        url = (data.get("url") or "").strip()
        if not url:
            return self._send(400, json.dumps({"error": "請提供 YouTube 連結"},
                                              ensure_ascii=False))
        opts = data.get("options") or {}
        jid = uuid.uuid4().hex[:12]
        with JOBS_LOCK:
            JOBS[jid] = {"status": "running", "log": [], "result": None,
                         "error": None, "t": time.time()}
            for k in [k for k, v in JOBS.items() if time.time() - v["t"] > 3600]:
                JOBS.pop(k, None)
        threading.Thread(target=_run_job, args=(jid, url, opts), daemon=True).start()
        return self._send(200, json.dumps({"id": jid}))


def open_url(url):
    """開啟瀏覽器。Termux 沒有標準的 webbrowser 支援，改用 Android 的方式。"""
    if IS_TERMUX:
        import subprocess
        for cmd in (["termux-open-url", url],
                    ["am", "start", "-a", "android.intent.action.VIEW", "-d", url]):
            try:
                subprocess.run(cmd, check=True, capture_output=True, timeout=15)
                return
            except Exception:
                continue
        print(f"\n   請用手機瀏覽器開啟：{url}\n")
        return
    try:
        webbrowser.open(url)
    except Exception:
        pass


def lan_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return None


def free_port(start):
    for p in range(start, start + 30):
        with socket.socket() as s:
            if s.connect_ex(("127.0.0.1", p)) != 0:
                return p
    return start


def serve(open_browser=True):
    global SERVER, PORT

    if not ensure_deps():
        return

    PORT = port = free_port(DEFAULT_PORT)
    try:
        SERVER = srv = ThreadingHTTPServer(("0.0.0.0", port), Handler)
    except OSError as e:
        _dialog("無法啟動", f"連接埠 {port} 無法使用：{e}", error=True)
        return
    ip = lan_ip()

    print()
    print("  ┌─────────────────────────────────────────────┐")
    print("  │   YouTube 逐字稿工具  已啟動                │")
    print("  └─────────────────────────────────────────────┘")
    print()
    print(f"   電腦上使用：  http://localhost:{port}")
    if ip:
        print(f"   手機上使用：  http://{ip}:{port}")
        print("                （手機需連到同一個 WiFi）")
    print()
    print("   關閉這個視窗就會結束程式。")
    print()

    if open_browser:
        threading.Timer(0.8, lambda: open_url(f"http://localhost:{port}")).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\n   已結束。")


# ==========================================================================
# 進入點
# ==========================================================================

if __name__ == "__main__":
    args = sys.argv[1:]
    if args and not args[0].startswith("-"):
        r = transcribe(args[0], {"clean": True}, log=lambda m: print("  " + m, file=sys.stderr))
        if "--txt" in args:
            print(r["plaintext"])
        elif "--srt" in args:
            print(r["srt"])
        else:
            print(r["markdown"])
    else:
        serve(open_browser="--no-browser" not in args)
