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
  - 影片簡介欄
  - 字幕品質標註（人工／自動），讓 AI 知道要不要容忍錯字
  - 內建分析提示詞

全部本機執行，無 API key、無帳號、無費用。
"""

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
    "sw.js":             "application/javascript; charset=utf-8",
    "manifest.json":     "application/manifest+json; charset=utf-8",
    "icon-192.png":      "image/png",
    "icon-512.png":      "image/png",
    "icon-maskable.png": "image/png",
}

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


# yt-dlp 會把下面這些「軌」放進 subtitles，但它們不是字幕：
#   danmaku / danmu  -> Bilibili 彈幕，是觀眾留言，不是逐字稿
#   live_chat / rechat -> 直播聊天室紀錄
# 舊版把它們當成字幕，於是判定「這部影片有字幕」而拒絕啟動 AI 聽寫，
# 導致 Bilibili 無字幕影片永遠產不出逐字稿。
PSEUDO_SUB_CODES = ("danmaku", "danmu", "live_chat", "rechat", "dm")


def real_tracks(tracks):
    """濾掉彈幕／聊天室這類假字幕軌，只留真正的字幕軌。"""
    out = {}
    for code, val in (tracks or {}).items():
        c = str(code).lower()
        if c in PSEUDO_SUB_CODES:
            continue
        if any(bad in c for bad in ("danmaku", "danmu", "live_chat", "rechat")):
            continue
        out[code] = val
    return out


class EmptyCaptionError(RuntimeError):
    """字幕軌存在但解析不出任何句子 —— 應該退回 AI 聽寫，而不是叫使用者等限流恢復。"""


def has_caption_tracks(info):
    """影片是否真的有「可用的」字幕軌？None 代表無法判斷。"""
    if not info:
        return None
    return bool(real_tracks(info.get("subtitles"))
                or real_tracks(info.get("automatic_captions")))


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
                log(f"伺服器暫時限流，{wait} 秒後重試（第 {i + 2}/{tries} 次）")
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


def _parse_caption(raw, ext):
    """把各平台的字幕格式解析成統一的段落清單。

    支援：YouTube json3、YouTube srv1/ttml（XML）、Bilibili CC（json 的
    body 陣列）、SRT、WebVTT。舊版只認得 json3 和 YouTube 的 XML，
    遇到其他平台的格式會解析出空結果。
    """
    body = raw.decode("utf-8", "replace") if isinstance(raw, bytes) else (raw or "")
    segs = []

    # --- YouTube json3 ---
    if ext == "json3" or '"events"' in body[:2000]:
        try:
            data = json.loads(body)
        except Exception:
            data = {}
        for ev in data.get("events", []):
            if not ev.get("segs"):
                continue
            text = "".join(sg.get("utf8", "") for sg in ev["segs"]).strip()
            if text:
                segs.append({"text": text,
                             "start": (ev.get("tStartMs") or 0) / 1000.0,
                             "duration": (ev.get("dDurationMs") or 0) / 1000.0})
        if segs:
            return segs

    # --- Bilibili CC 字幕：{"body":[{"from":1.2,"to":3.4,"content":"…"}]} ---
    if body.lstrip().startswith("{"):
        try:
            data = json.loads(body)
        except Exception:
            data = None
        rows = None
        if isinstance(data, dict):
            for key in ("body", "subtitles", "segments"):
                if isinstance(data.get(key), list):
                    rows = data[key]
                    break
        elif isinstance(data, list):
            rows = data
        for it in (rows or []):
            if not isinstance(it, dict):
                continue
            text = str(it.get("content") or it.get("text") or "").strip()
            if not text:
                continue
            st = float(it.get("from") or it.get("start") or 0)
            en = float(it.get("to") or it.get("end") or st)
            segs.append({"text": text, "start": st,
                         "duration": max(en - st, 0)})
        if segs:
            return segs

    # --- XML（YouTube srv1 / ttml）---
    for m in re.finditer(r'<text start="([\d.]+)"(?: dur="([\d.]+)")?>(.*?)</text>',
                         body, re.S):
        text = html_mod.unescape(re.sub(r"<[^>]+>", "", m.group(3))).strip()
        if text:
            segs.append({"text": text, "start": float(m.group(1)),
                         "duration": float(m.group(2) or 0)})
    if segs:
        return segs

    for m in re.finditer(r'<p[^>]*\bbegin="([^"]+)"[^>]*?(?:\bend="([^"]+)")?[^>]*>(.*?)</p>',
                         body, re.S):
        text = html_mod.unescape(re.sub(r"<[^>]+>", " ", m.group(3))).strip()
        if text:
            st = _ts_to_sec(m.group(1))
            en = _ts_to_sec(m.group(2)) if m.group(2) else st
            segs.append({"text": text, "start": st,
                         "duration": max(en - st, 0)})
    if segs:
        return segs

    # --- SRT / WebVTT ---
    pat = re.compile(r'(\d{1,2}:\d{2}:\d{2}[.,]\d{1,3}|\d{1,2}:\d{2}[.,]\d{1,3})'
                     r'\s*-->\s*'
                     r'(\d{1,2}:\d{2}:\d{2}[.,]\d{1,3}|\d{1,2}:\d{2}[.,]\d{1,3})')
    lines = body.splitlines()
    i = 0
    while i < len(lines):
        m = pat.search(lines[i])
        if not m:
            i += 1
            continue
        st, en = _ts_to_sec(m.group(1)), _ts_to_sec(m.group(2))
        i += 1
        buf = []
        while i < len(lines) and lines[i].strip() and not pat.search(lines[i]):
            buf.append(re.sub(r"<[^>]+>", "", lines[i]).strip())
            i += 1
        text = html_mod.unescape(" ".join(x for x in buf if x)).strip()
        if text and not text.isdigit():
            segs.append({"text": text, "start": st, "duration": max(en - st, 0)})
    return segs


def _ts_to_sec(ts):
    """把 00:01:02,500 / 00:01:02.500 / 01:02.5 轉成秒。"""
    if ts is None:
        return 0.0
    ts = str(ts).strip().replace(",", ".")
    if ts.endswith("s"):
        try:
            return float(ts[:-1])
        except Exception:
            return 0.0
    parts = ts.split(":")
    try:
        parts = [float(x) for x in parts]
    except Exception:
        return 0.0
    sec = 0.0
    for x in parts:
        sec = sec * 60 + x
    return sec


def engine_ytdlp(url, langs, log, info=None):
    info = info or ytdlp_info(url)
    raw_manual = info.get("subtitles") or {}
    raw_auto = info.get("automatic_captions") or {}
    manual = real_tracks(raw_manual)
    auto = real_tracks(raw_auto)

    dropped = [c for c in raw_manual if c not in manual]
    if dropped:
        log("略過非字幕軌（彈幕／聊天室）：" + "、".join(map(str, dropped[:5])))

    # 排出候選順序：偏好語言的人工字幕 -> 偏好語言的自動字幕 -> 其餘真字幕軌。
    # 舊版只挑一條，那條解析失敗就整個放棄；現在會往下試。
    candidates = []
    seen = set()

    def add(code, track, generated):
        if code and track and code not in seen:
            seen.add(code)
            candidates.append((code, track, generated))

    c, t = _pick_track(manual, langs)
    add(c, t, False)
    c, t = _pick_track(auto, langs)
    add(c, t, True)
    for src, gen in ((manual, False), (auto, True)):
        for c, t in src.items():
            add(c, t, gen)

    if not candidates:
        raise RuntimeError("這部影片沒有任何字幕軌")

    tried = []
    for code, track, generated in candidates[:4]:
        log(f"yt-dlp 取得字幕軌 {code}{'（自動）' if generated else '（人工）'}")
        fmt = (next((f for f in track if f.get("ext") == "json3"), None)
               or next((f for f in track
                        if (f.get("ext") or "").lower()
                        in ("srv1", "json", "vtt", "srt", "ttml", "srv3")), None)
               or track[0])
        raw = fetch_with_retry(fmt["url"], log)
        segs = _parse_caption(raw, (fmt.get("ext") or "").lower())
        if segs:
            return segs, {"lang": code, "generated": generated}
        tried.append(str(code))
        log(f"字幕軌 {code} 沒有可用內容，換下一條…")

    raise EmptyCaptionError(
        "字幕軌存在但解析不出任何句子（已試："
        + "、".join(tried) + "），改用 AI 聽寫")


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


def work_dir():
    """暫存資料夾。

    不使用系統 TMPDIR：Termux 的 TMPDIR 會在 app 啟動時被清空，
    而從主畫面捷徑啟動的背景工作階段有時拿到的是不存在或不可寫的路徑，
    結果就是下載階段丟出 [Errno 5] I/O error。放在自己的 cache 下最安全。
    """
    d = os.path.join(os.path.expanduser("~"), ".cache", "ytscript", "tmp")
    os.makedirs(d, exist_ok=True)
    return d


def download_audio(url, log, low_data=True, info=None):
    """只下載音訊，並且一定要下載成功。

    音軌格式的可用性因平台、影片、地區而異：某些位元率的音軌在手機上
    抓不下來。所以這裡準備多個方案由「品質最合適」到「一定抓得到」
    逐層退讓，而不是一個方案失敗就整個放棄。
    """
    import shutil as _sh
    import tempfile
    import yt_dlp

    est = estimate_audio_mb(info, low_data)
    if est:
        log(f"準備下載音訊，預估約 {est:.1f} MB"
            + ("（省流量模式）" if low_data else ""))

    tmpdir = tempfile.mkdtemp(prefix="audio_", dir=work_dir())
    try:
        free_mb = _sh.disk_usage(tmpdir).free / 1048576
    except Exception:
        free_mb = None
    if free_mb is not None and free_mb < 300:
        log(f"注意：可用儲存空間只剩 {free_mb:.0f} MB")

    base = {"outtmpl": os.path.join(tmpdir, "a.%(ext)s"),
            "quiet": True, "no_warnings": True, "noprogress": True,
            "retries": 5, "fragment_retries": 5,
            "concurrent_fragment_downloads": 1}

    plans = []
    if low_data:
        plans.append(dict(base, format="worstaudio/bestaudio/best",
                          format_sort=["+abr", "+size"]))
    else:
        # 品質模式：偏好 64kbps 以上，但不硬指定某個位元率，
        # 避免挑到一個抓不下來的音軌。
        plans.append(dict(base, format="bestaudio[abr>=64]/bestaudio/best",
                          format_sort=["+abr"]))
    plans.append(dict(base, format="bestaudio/best"))
    plans.append(dict(base, format="worstaudio/worst"))
    plans.append(dict(base, format="best"))

    def pick_file():
        """yt-dlp 經過後製後副檔名可能改變，直接找資料夾裡最大的檔案。"""
        best = None
        for name in os.listdir(tmpdir):
            f = os.path.join(tmpdir, name)
            if os.path.isfile(f) and os.path.getsize(f) > 10_000:
                if best is None or os.path.getsize(f) > os.path.getsize(best):
                    best = f
        return best

    errs = []
    for i, opts in enumerate(plans, 1):
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                got = ydl.extract_info(url, download=True)
            path = pick_file()
            if path:
                size_mb = os.path.getsize(path) / 1048576
                log(f"音訊下載完成：實際用掉 {size_mb:.1f} MB 流量")
                return path, tmpdir, size_mb, got
            errs.append(f"方案{i}：下載結束但找不到音訊檔")
        except Exception as e:
            errs.append(f"方案{i}：{type(e).__name__}: {str(e)[:200]}")
        if i < len(plans):
            log(f"音訊下載方案 {i} 不成功，換下一個音軌格式…")

    _sh.rmtree(tmpdir, ignore_errors=True)
    tail = f"（暫存位置可用空間 {free_mb:.0f} MB）" if free_mb is not None else ""
    raise RuntimeError("音訊下載失敗，五種音軌格式都試過了" + tail + "：\n"
                       + "\n".join(errs))


# 本機實測的處理速度（實時倍率）。用來在開始 AI 聽寫前預估耗時，
# 讓使用者知道大概要等多久，而不是默默卡住。
RT_FACTOR = {"tiny": 17.0, "base": 11.0, "small": 4.2, "medium": 1.5,
             "large-v3-turbo": 2.2}
RT_PHONE = {"tiny": 1.5, "base": 0.9, "small": 0.35, "medium": 0.15,
            "large-v3-turbo": 0.22}


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


def pick_device():
    """有 NVIDIA 顯卡就用 GPU，否則用 CPU。回傳 (device, compute_type)。

    計算型別的選擇有陷阱：Pascal 世代顯卡（GTX 10 系列）的 FP16 吞吐量
    被限制在 1/64，用 float16 反而比 CPU 還慢。但它們支援 DP4A 整數指令，
    所以一律用 int8，這在新舊顯卡上都是安全且快速的選擇。
    """
    try:
        enable_cuda_dlls()
        import ctranslate2
        if ctranslate2.get_cuda_device_count() > 0:
            return "cuda", "int8_float32"
    except Exception:
        pass
    return "cpu", "int8"


def load_whisper_model(size, log):
    """載入模型，GPU 失敗時自動退回 CPU（缺 CUDA 函式庫時很常見）。"""
    from faster_whisper import WhisperModel

    device, compute = pick_device()
    if device == "cuda":
        try:
            m = WhisperModel(size, device="cuda", compute_type=compute)
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
        # 舊版在這裡寫死 tiny，導致介面上的「準確」在手機上完全沒有作用，
        # 中文辨識錯字連篇。改成依實際記憶體挑跑得動的最佳模型；
        # 想要快就在介面選「快速」，那條路徑仍然直接指定 tiny。
        return quality_model_size()
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

    log(f"載入 AI 模型 {model_size}…（首次會下載模型，之後永久離線可用）")
    model = load_whisper_model(model_size, log)

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

# 段與段之間的降溫等待（秒）。設 0 關閉。
COOLDOWN_SEC = int(os.environ.get("YTSCRIPT_COOLDOWN_SEC", "15") or 0)
GGML_SIZES = {"tiny": 75, "base": 142, "small": 466, "medium": 1500,
              "large-v3": 3100, "large-v3-turbo": 1600,
              "tiny-q5_1": 31, "base-q5_1": 57, "small-q5_1": 190,
              "medium-q5_0": 539, "large-v3-turbo-q5_0": 574}
GGML_URL = "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-{}.bin"

# 量化版檔案小很多、ARM 上更快，品質損失遠小於「降一級模型」。
# 所以寧可用量化的大模型，也不要用未量化的小模型。
GGML_QUANT = {"tiny": "tiny-q5_1", "base": "base-q5_1", "small": "small-q5_1",
              "medium": "medium-q5_0", "large-v3-turbo": "large-v3-turbo-q5_0"}

# 品質由高到低。turbo 的解碼層只有 4 層（large-v3 是 32 層），
# 中文準確度接近 large-v3，速度卻和 medium 相當，是手機上的最佳選擇。
QUALITY_LADDER = ["large-v3-turbo", "medium", "small", "base", "tiny"]

# 各模型跑起來大概需要的可用記憶體（MB），以量化版估算
MODEL_RAM_MB = {"large-v3-turbo": 1600, "medium": 1500,
                "small": 800, "base": 400, "tiny": 300}


def total_ram_mb():
    """讀系統總記憶體。讀不到回 0（代表無法判斷）。"""
    try:
        with io.open("/proc/meminfo", encoding="utf-8") as f:
            for line in f:
                if line.startswith("MemTotal:"):
                    return int(line.split()[1]) // 1024
    except Exception:
        pass
    return 0


def quality_model_size():
    """「準確」模式用的模型：在跑得動的前提下取最準的那個。

    不讀任何設定檔。large-v3-turbo 的解碼層只有 4 層（large-v3 是 32 層），
    中文準確度接近 large-v3，是手機上實際跑得動的最高品質選擇。
    """
    ram = total_ram_mb()
    if ram >= 5500:
        return "large-v3-turbo"
    if ram >= 3500:
        return "small"
    if ram >= 2000:
        return "base"
    return "tiny"


def smaller_model(size):
    """記憶體不足時往下降一級。"""
    try:
        i = QUALITY_LADDER.index(size)
    except ValueError:
        return "tiny"
    return QUALITY_LADDER[i + 1] if i + 1 < len(QUALITY_LADDER) else None


def model_dir():
    d = os.path.join(os.path.expanduser("~"), ".cache", "whisper-cpp")
    os.makedirs(d, exist_ok=True)
    return d


VAD_MODEL_URL = ("https://huggingface.co/ggml-org/whisper-vad/"
                 "resolve/main/ggml-silero-v5.1.2.bin")

# 交給模型的開場提示。whisper 會延續提示的用字與標點風格，
# 這是讓輸出變成「繁體中文、有標點」最有效的一招，成本幾乎是零。
ZH_PROMPT = "以下是一段繁體中文的逐字稿，內容通順、用詞正確，並且標有標點符號。"


def primary_lang(langs=None, lang=None):
    """永遠回傳 zh。

    這裡刻意不做任何偵測、不讀設定檔、不看字幕偏好清單。理由：
    whisper-cli 的 -l 預設值是 en（不是 auto），任何「偵測失敗就退回預設」
    的寫法都會把中文影片辨識成英文 —— 而偵測是靠解析文字輸出，本來就不可靠。
    使用者的內容是中文，鎖定 zh 是確定性的正解，不需要選項。
    """
    return "zh"


def vad_model_path(log=None, download=True):
    """語音活動偵測模型。有它就能跳過靜音段 —— 同時提升品質與速度。

    靜音段是 whisper 產生幻覺文字（憑空冒出的句子）的主要來源。
    """
    path = os.path.join(model_dir(), "ggml-silero-v5.1.2.bin")
    if os.path.exists(path) and os.path.getsize(path) > 500_000:
        return path
    if not download:
        return None
    try:
        if log:
            log("下載語音偵測模型（約 2 MB，只需這一次）…")
        req = urllib.request.Request(VAD_MODEL_URL, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=120) as r, open(path + ".part", "wb") as f:
            f.write(r.read())
        os.replace(path + ".part", path)
        return path
    except Exception:
        try:
            os.remove(path + ".part")
        except Exception:
            pass
        return None


def to_traditional(segs, log=None):
    """簡體轉繁體（台灣用詞）。

    whisper 的中文輸出多半是簡體，對繁體使用者來說整篇都是「錯字」。
    有安裝 opencc 才轉換，沒有就原樣回傳，不影響其他功能。
    """
    try:
        from opencc import OpenCC
    except Exception:
        # 沒裝就自己裝一次。這是讓輸出變繁體的必要元件，
        # 不應該變成使用者要自己處理的步驟。
        try:
            import subprocess
            if log:
                log("安裝簡繁轉換元件（只需這一次）…")
            subprocess.run([sys.executable, "-m", "pip", "install", "--quiet",
                            "opencc-python-reimplemented"],
                           capture_output=True, timeout=600)
            from opencc import OpenCC
        except Exception:
            if log:
                log("簡繁轉換元件安裝失敗，輸出可能是簡體")
            return segs
    try:
        cc = OpenCC("s2twp")
    except Exception:
        try:
            cc = OpenCC("s2t")
        except Exception:
            return segs
    for seg in segs:
        try:
            seg["text"] = cc.convert(seg["text"])
        except Exception:
            pass
    return segs


def whisper_threads():
    """固定 4 條執行緒，與 whisper.cpp 自己的預設一致。

    這裡刻意不做「自動調校」也不讀設定檔：短音檔量不到熱降頻，量出來的
    「最佳執行緒數」放到長影片上常常是錯的，而一旦寫進設定檔就會默默
    拖慢每一次執行，還很難發現。固定值至少是可預期的。
    """
    try:
        n = os.cpu_count() or 4
    except Exception:
        n = 4
    return max(2, min(int(n), 4))


def find_whisper_cli():
    """找 whisper.cpp 的執行檔。

    優先找從原始碼建置出來的版本。（早期版本會先找 termux-stt 這個 pip
    套件，但那個 wheel 只有 0.1 MB、純 Python，裡面根本沒有執行檔。）
    """
    import shutil

    home = os.path.expanduser("~")
    for p in (os.path.join(home, "whisper.cpp", "build", "bin", "whisper-cli"),
              os.path.join(home, "whisper.cpp", "build", "bin", "main"),
              os.path.join(home, "whisper.cpp", "build", "bin", "whisper"),
              os.path.join(home, "whisper.cpp", "main")):
        if os.path.exists(p) and os.access(p, os.X_OK):
            return p

    for name in ("whisper-cli", "whisper-cpp", "whisper", "main"):
        p = shutil.which(name)
        if p:
            return p
    return None


def ensure_ggml_model(size, log):
    """確保模型檔存在，不在就從 Hugging Face 下載（僅第一次，之後永久離線可用）。"""
    # 已經有的任何一種版本都直接沿用，不重複下載。
    names = []
    q = GGML_QUANT.get(size)
    if q:
        names.append(f"ggml-{q}.bin")
    names += [f"ggml-{size}-q5_1.bin", f"ggml-{size}-q8_0.bin", f"ggml-{size}.bin"]
    for name in names:
        cand = os.path.join(model_dir(), name)
        if os.path.exists(cand) and os.path.getsize(cand) > 1_000_000:
            return cand

    size = q or size            # 沒有的話下載量化版
    path = os.path.join(model_dir(), f"ggml-{size}.bin")

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


_WHISPER_CAPS = None


def whisper_caps(exe):
    """一次問清楚這個 whisper-cli 支援哪些旗標。

    舊做法是「先用完整參數跑，失敗就拿掉一個再跑」—— 但一次聽寫可能
    要幾十分鐘，用一個長工作去試探旗標，等於把等待時間乘上好幾倍。
    改成啟動時讀一次 --help，只組裝真正支援的旗標。
    """
    import subprocess
    global _WHISPER_CAPS
    if _WHISPER_CAPS is not None:
        return _WHISPER_CAPS
    text = ""
    try:
        h = subprocess.run([exe, "--help"], capture_output=True, timeout=30)
        text = ((h.stdout or b"") + b"\n" + (h.stderr or b"")).decode("utf-8", "replace")
    except Exception:
        pass
    flags = ("--vad", "-vm", "-vt", "-vsd", "-vp", "--prompt", "-dl",
             "-bo", "-bs", "-et", "-mc", "-pp", "-np", "-nt", "-oj", "-of", "-t")
    _WHISPER_CAPS = {f: (f in text) for f in flags}
    if not text:                      # --help 都讀不到，就只用最基本的參數
        _WHISPER_CAPS = {f: False for f in flags}
    return _WHISPER_CAPS


def run_whisper(cmd, timeout_sec, log, label):
    """執行 whisper-cli，邊跑邊回報進度。

    舊版加了 -np（不印任何東西），畫面上只有一句「AI 聽寫中…」，
    使用者無法分辨是在跑還是卡死。現在解析進度百分比並回報預估剩餘時間。
    """
    import subprocess
    t0 = time.time()
    try:
        proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL,
                                stderr=subprocess.PIPE,
                                text=True, errors="replace", bufsize=1)
    except Exception as e:
        return 1, f"無法啟動 whisper-cli：{e}"

    killer = threading.Timer(timeout_sec, proc.kill)
    killer.daemon = True
    killer.start()

    pat = re.compile(r"progress\s*=\s*(\d+)\s*%")
    tail_lines = []
    last_report = 0.0
    try:
        for line in proc.stderr:
            line = line.rstrip()
            if line:
                tail_lines.append(line)
                if len(tail_lines) > 40:
                    tail_lines.pop(0)
            m = pat.search(line)
            if m and time.time() - last_report > 4:
                last_report = time.time()
                pct = max(1, min(99, int(m.group(1))))
                spent = time.time() - t0
                eta = spent / pct * (100 - pct)
                log(f"{label} {pct}%（已跑 {int(spent//60)} 分 {int(spent%60)} 秒，"
                    f"預計還要 {int(eta//60)} 分 {int(eta%60)} 秒）")
    except Exception:
        pass
    rc = proc.wait()
    killer.cancel()
    spent = int(time.time() - t0)
    if rc == 0:
        log(f"聽寫完成，花了 {spent//60} 分 {spent%60} 秒")
    return rc, "\n".join(tail_lines)


def engine_whispercpp(url, langs, log, model_size=None, low_data=True, info=None,
                      lang=None):
    import shutil
    import subprocess

    exe = find_whisper_cli()
    if not exe:
        raise RuntimeError(
            "找不到 whisper.cpp 執行檔。\n"
            "Termux 請建置一次：\n"
            "    pkg install -y git cmake clang\n"
            "    git clone --depth 1 https://github.com/ggml-org/whisper.cpp ~/whisper.cpp\n"
            "    cd ~/whisper.cpp && cmake -B build && cmake --build build -j4")

    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("需要 ffmpeg 才能轉換音訊。Termux：pkg install ffmpeg")

    # 光是檔案存在不代表能跑。Termux 上常見 libc++ 與 libplacebo 版本不同步，
    # ffmpeg 一啟動就被動態連結器擋下（CANNOT LINK EXECUTABLE）。先驗一次，
    # 否則錯誤會等到轉檔階段才以「沒有產生任何文字」的形式出現。
    try:
        probe = subprocess.run([ffmpeg, "-version"], capture_output=True, timeout=60)
        probe_ok = probe.returncode == 0
        probe_msg = (probe.stderr or probe.stdout or b"").decode("utf-8", "replace")
    except Exception as exc:
        probe_ok, probe_msg = False, str(exc)
    if not probe_ok:
        raise RuntimeError(
            "ffmpeg 有安裝但無法執行，所以沒辦法把音訊轉成聽寫用的格式。\n\n"
            "Termux 修法（通常是套件版本不同步）：\n"
            "    pkg update && pkg upgrade -y\n\n"
            "系統訊息：\n" + probe_msg.strip()[:400])

    model_size = model_size or default_model_size()
    state = {"model": ensure_ggml_model(model_size, log), "size": model_size}

    audio, tmpdir, size_mb, _got = download_audio(url, log, low_data, info)

    # 固定中文。不偵測、不讓 whisper 自己猜，因為 -l 的預設值是 en，
    # 任何猜錯或沒抓到的情況都會變成「中文影片輸出英文逐字稿」。
    hint = "zh"
    state["lang"] = hint
    total = float((_got or {}).get("duration") or (info or {}).get("duration") or 0)
    caps = whisper_caps(exe)

    def build_args():
        """依模型大小與實際支援的旗標組參數。

        關鍵：束搜索（-bs/-bo 5）會讓運算量變成好幾倍。小模型的存在意義
        就是快，硬套束搜索等於兩邊都拿不到 —— 所以只有中大型模型才開。
        """
        fast = state["size"] in ("tiny", "base")
        a = []
        if caps.get("-bs") and caps.get("-bo"):
            a += (["-bs", "1", "-bo", "1"] if fast else ["-bs", "5", "-bo", "5"])
        if not fast and caps.get("-et"):
            a += ["-et", "2.4"]
        if not fast and caps.get("-mc"):
            a += ["-mc", "64"]
        if caps.get("--prompt"):
            a += ["--prompt", ZH_PROMPT]
        # VAD 要先把整段音訊跑過一次語音偵測模型。準確模式值得（能壓掉
        # 靜音段的幻覺文字），但快速模式的重點就是快，多一趟前處理不划算。
        if not fast and caps.get("--vad") and caps.get("-vm"):
            vm = vad_model_path(log)
            if vm:
                a += ["--vad", "-vm", vm]
                if caps.get("-vt"):
                    a += ["-vt", "0.5"]
        if caps.get("-pp"):
            a += ["-pp"]
        return a, fast

    extra, fast = build_args()
    mode = "快速（貪婪解碼）" if fast else "準確（束搜索 5）"
    log(f"聽寫設定：模型 {state['size']}｜語言 {hint}｜{mode}"
        + ("｜跳過靜音" if "--vad" in extra else ""))
    if total:
        log(f"影片長度 {int(total//60)} 分 {int(total%60)} 秒，預估 {eta_text(total, state['size'])}")

    def transcribe_chunk(offset, idx, seconds):
        """轉成 16kHz WAV -> 聽寫 -> 立刻刪掉暫存檔，回傳帶偏移的段落。"""
        wav = os.path.join(tmpdir, f"c{idx}.wav")
        cmd = [ffmpeg, "-y", "-loglevel", "error"]
        if offset is not None:
            cmd += ["-ss", str(offset), "-t", str(CHUNK_SEC)]
        cmd += ["-i", audio, "-ar", "16000", "-ac", "1", "-c:a", "pcm_s16le", wav]
        conv = subprocess.run(cmd, capture_output=True, timeout=3600)
        if not os.path.exists(wav) or os.path.getsize(wav) < 2000:
            msg = (conv.stderr or b"").decode("utf-8", "replace")[:300]
            raise RuntimeError("音訊轉檔失敗（ffmpeg）：" + (msg or "產出的檔案是空的"))

        base_out = os.path.join(tmpdir, f"o{idx}")
        # -l 一定要送。whisper-cli 不給 -l 時預設是 en，中文影片會被當英文處理。
        cmd2 = [exe, "-m", state["model"], "-f", wav, "-oj", "-of", base_out,
                "-l", "zh"]
        if caps.get("-nt"):
            cmd2 += ["-nt"]
        cmd2 += ["-t", str(whisper_threads())] + extra

        # 逾時上限依音訊長度計算。固定 4 小時的話，真的卡死也要等到天亮。
        budget = max(900, int((seconds or 600) * 40))
        label = ("AI 聽寫中" if offset is None
                 else f"AI 聽寫中（第 {idx + 1} 段）")
        rc, err = run_whisper(cmd2, budget, log, label)

        jp = base_out + ".json"
        got_segs = []
        if os.path.exists(jp):
            try:
                with io.open(jp, encoding="utf-8") as f:
                    data = json.load(f)
            except Exception:
                data = {}
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
        if not got_segs and rc != 0:
            log(f"這一段沒有產出（結束碼 {rc}）")
            if err:
                log("whisper 訊息：" + err.splitlines()[-1][:160])
        return got_segs

    def run_all():
        out = []
        if total > CHUNK_SEC * 1.2:
            # 長影片分段：7 小時的影片一次轉檔會產生約 770 MB 暫存 WAV，
            # 手機很容易空間不足。分段後尖峰只有一段的大小（約 55 MB）。
            n = int(total // CHUNK_SEC) + 1
            log(f"影片較長（{total/3600:.1f} 小時），分成 {n} 段處理以節省暫存空間")
            for i in range(n):
                got = transcribe_chunk(i * CHUNK_SEC, i, CHUNK_SEC)
                if not got and i > 0:
                    break
                out += got
                # 段與段之間稍微停一下讓晶片降溫。持續滿載會觸發系統降頻，
                # 屆時整體反而更慢，所以這個等待通常不會讓總時間變長。
                if i + 1 < n and COOLDOWN_SEC > 0:
                    log(f"稍停 {COOLDOWN_SEC} 秒讓手機降溫…")
                    time.sleep(COOLDOWN_SEC)
        else:
            out = transcribe_chunk(None, 0, total or 600)
        return out

    try:
        segs = run_all()

        # 大模型在手機上跑不動時，whisper-cli 會直接被系統殺掉、什麼都不輸出。
        # 與其讓使用者一無所獲，不如自動降一級再試。
        while not segs:
            nxt = smaller_model(state["size"])
            if not nxt:
                break
            log(f"模型 {state['size']} 沒有產出（多半是記憶體不足），改用 {nxt} 重試…")
            state["size"] = nxt
            state["model"] = ensure_ggml_model(nxt, log)
            extra, fast = build_args()
            segs = run_all()
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)

    if not segs:
        raise RuntimeError("AI 聽寫沒有產生任何文字（音訊可能整段無聲，"
                           "或這台裝置的記憶體不足以執行任何模型）")

    segs = to_traditional(segs, log)      # 一律簡轉繁

    return segs, {"lang": "zh", "generated": True, "whisper": True,
                  "engine": f"whisper.cpp {state['size']}", "audio_mb": size_mb}


# ==========================================================================
# 簡介欄過濾
# ==========================================================================

# 這些網域出現在簡介裡，幾乎都是社群導流、贊助或周邊，與影片內容無關
JUNK_DOMAINS = (
    "twitter.com", "x.com", "instagram.com", "facebook.com", "fb.me", "fb.com",
    "threads.net", "tiktok.com", "discord.gg", "discord.com", "t.me", "line.me",
    "lin.ee", "weibo.com", "patreon.com", "ko-fi.com", "buymeacoffee",
    "paypal.me", "paypal.com", "linktr.ee", "beacons.ai", "bit.ly/sub",
    "opensea", "shopee", "amzn.to", "twitch.tv", "onlyfans",
    "youtube.com/channel", "youtube.com/c/", "youtube.com/user",
    "youtube.com/@", "youtu.be/@", "reurl.cc",
)

# 這些網域是真正的參考資料，即使該行有連結也要保留
GOOD_DOMAINS = (
    "arxiv.org", "doi.org", "wikipedia.org", "github.com", "scholar.google",
    "nature.com", "science.org", "pubmed", "ncbi.nlm.nih.gov", "ssrn.com",
    "jstor.org", "books.google", "goodreads.com", "nih.gov", "who.int",
    "ourworldindata.org", "statista.com",
)

# 樣板用語：導流、贊助、商務、音樂授權、製作人員
JUNK_KEYWORDS = (
    "訂閱", "订阅", "追蹤我", "关注我", "按讚", "点赞", "小鈴鐺", "小铃铛",
    "加入會員", "加入会员", "會員專屬", "会员专属", "贊助", "赞助", "抖內", "斗内",
    "打賞", "打赏", "斗內", "業配", "业配", "商務合作", "商务合作", "合作邀約",
    "洽詢", "洽询", "邀約", "邀约", "來信", "来信", "聯絡信箱", "联系邮箱",
    "粉絲專頁", "粉丝页", "粉絲團", "社群連結", "社群平台",
    "主頻道", "主频道", "副頻道", "副频道", "第二頻道", "第二频道",
    "背景音樂", "背景音乐", "音樂來源", "音乐来源", "音效來源", "音效来源",
    "配樂", "配乐", "剪輯師", "剪辑师", "後製", "后期制作", "字幕協力",
    "版權所有", "版权所有", "免責聲明", "免责声明", "折扣碼", "折扣码", "優惠碼",
    "subscribe", "follow me", "join this channel", "join our discord",
    "patreon", "merch", "sponsor", "affiliate", "use code", "promo code",
    "music by", "musicbed", "epidemic sound", "artlist", "soundstripe",
    "background music", "sound effects", "royalty free", "edited by",
    "produced by", "special thanks to our", "business inquiries",
    "photo by", "image by", "images by", "footage by", "thumbnail by",
    "translated by", "translation by", "voiceover by", "dubbed by",
    "звуковая дорожка", "攝影：", "攝影by", "圖片來源", "图片来源",
)

# 這些關鍵字通常是一個「區塊」的開頭，底下幾行都是同類資訊，要一併略過
BLOCK_HEADERS = (
    "背景音樂", "背景音乐", "音樂來源", "音乐来源", "音效來源", "音效来源",
    "配樂", "配乐", "剪輯師", "剪辑师", "後製", "后期制作", "字幕協力",
    "社群連結", "社群平台", "粉絲專頁", "粉丝页", "粉絲團",
    "music by", "background music", "sound effects", "edited by",
    "produced by", "musicbed", "epidemic sound", "artlist", "soundstripe",
)

URL_RE = re.compile(r"https?://\S+|www\.\S+", re.I)
CHAPTER_LINE_RE = re.compile(r"^\s*\(?\d{1,2}:\d{2}(:\d{2})?\)?\s*[-–—:：]?\s*\S")
HASHTAG_ONLY_RE = re.compile(r"^\s*(#[^\s#]+\s*)+$")
DECOR_ONLY_RE = re.compile(r"^[\s\W_]+$", re.U)


def filter_description(desc, drop_chapters=True):
    """只留下與影片內容真正相關的簡介文字。

    移除社群導流、贊助、音樂授權、製作人員等樣板；
    章節時間軸也移除（已另外用結構化方式呈現）。
    參考資料類連結（論文、維基、GitHub 等）則保留。
    """
    if not desc:
        return ""

    kept = []
    suppress = False        # 是否正處於一個樣板區塊內（例如「背景音樂：」底下的曲目清單）

    for raw in desc.splitlines():
        line = raw.rstrip()
        stripped = line.strip()

        if not stripped:
            suppress = False          # 空行結束一個區塊
            kept.append("")
            continue

        low = stripped.lower()
        valuable = any(g in low for g in GOOD_DOMAINS)

        if suppress and not valuable:
            continue
        suppress = False

        if DECOR_ONLY_RE.match(stripped) or HASHTAG_ONLY_RE.match(stripped):
            continue
        if drop_chapters and CHAPTER_LINE_RE.match(stripped):
            continue

        if not valuable:
            if any(d in low for d in JUNK_DOMAINS):
                continue
            hit = next((k for k in JUNK_KEYWORDS if k in low), None)
            if hit:
                # 若這行像是區塊標題（以冒號結尾，或本身就是製作資訊標題），
                # 連同底下的內容一併略過，直到遇見空行。
                if stripped.endswith((":", "：")) or hit in BLOCK_HEADERS:
                    suppress = True
                continue
            # 只有連結、沒有說明文字的行
            if URL_RE.search(stripped) and len(URL_RE.sub("", stripped).strip()) < 8:
                continue
            # 只是個帳號代稱
            if re.fullmatch(r"[@＠][\w.\-]+", stripped):
                continue

        kept.append(line)

    text = "\n".join(kept)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()

    # 剩下的太短就當作沒有有效內容
    return "" if len(text) < 40 else text


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
            "description": (info.get("description") or "").strip(),
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

        desc_mode = opts.get("desc_mode", "filter")
        if not opts.get("include_desc", True):      # 舊版選項相容
            desc_mode = "none"
        desc = (meta.get("description") or "").strip()
        if desc and desc_mode != "none":
            if desc_mode == "filter":
                desc = filter_description(desc)
            if desc:
                if len(desc) > 1500:
                    desc = desc[:1500].rstrip() + "…（簡介過長，已截斷）"
                head = "## 影片簡介欄" if desc_mode == "full" else "## 影片簡介（已濾除社群與贊助資訊）"
                L.append(head + "\n")
                L.append("> " + desc.replace("\n", "\n> "))
                L.append("")

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

    # 只有真的要用到影片資訊（標題/章節/簡介）時才抓那 202 KB。
    # 不需要時改用 1 KB 的 oEmbed，只有備援引擎啟動時才補抓。
    # 簡介欄是包在影片資訊區塊裡的，所以只要看 include_meta 就好
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

    # 關鍵防呆：分清楚「字幕存在但『暫時』抓不到」與「沒有可用字幕」。
    # 前者只要等限流恢復，後者該直接用 AI 聽寫。
    #
    # 舊版只要 metadata 裡有任何字幕軌就擋下 AI 聽寫，於是兩種情況都被
    # 誤判成「等一下再試」：Bilibili 的彈幕軌被當成字幕，抓下來是空的，
    # 使用者卻被告知「這部影片有字幕」而永遠拿不到逐字稿。
    # 現在只有在錯誤訊息真的顯示被限流／逾時的時候才擋。
    blob = "\n".join(errors)
    rate_limited = any(k in blob for k in (
        "429", "503", "Too Many Requests", "Service Unavailable",
        "timed out", "TimeoutError", "temporarily"))
    if not segments and has_caption_tracks(info) and rate_limited:
        # 只顯示真正的字幕語言。automatic_captions 裡有上百條
        # 「翻譯成某語言」的衍生軌（aa-zh、ab-zh…），列出來只會造成誤解。
        manual = list(real_tracks(info.get("subtitles")).keys())
        auto = [k for k in real_tracks(info.get("automatic_captions"))
                if "-" not in k or k.split("-")[0] in ("zh", "pt", "es", "en")]
        tracks = (manual or auto)[:6]
        site = "伺服器"
        try:
            site = urllib.parse.urlparse(url).netloc or site
        except Exception:
            pass
        raise RuntimeError(
            "這部影片其實有字幕（" + "、".join(map(str, tracks)) + " …），"
            "但現在下載不到。\n\n"
            f"原因幾乎都是 {site} 暫時限制了這台裝置的請求次數（HTTP 429），"
            "通常幾分鐘到一小時內會自動恢復。\n\n"
            "已自動略過 AI 聽寫 —— 這部影片有現成字幕，"
            "沒必要花幾十分鐘重新辨識。請稍後再試一次。\n\n"
            "技術細節：\n" + blob)

    if not segments and opts.get("allow_whisper", True):
        mdl0 = opts.get("whisper_model") or default_model_size()
        dur0 = float((info or {}).get("duration") or 0)
        mb0 = estimate_audio_mb(info, True)
        bits = ["這部影片沒有可用字幕，自動改用 AI 聽寫"]
        if dur0:
            bits.append(f"預計 {eta_text(dur0, mdl0)}")
        if mb0:
            bits.append(f"下載約 {mb0:.1f} MB")
        log("｜".join(bits) + "（全程在本機運算）")
        # Android 沒有 CTranslate2 預編譯套件，所以手機優先走 whisper.cpp
        order = ([engine_whispercpp, engine_whisper] if IS_TERMUX
                 else [engine_whisper, engine_whispercpp])
        mdl = opts.get("whisper_model")
        # 「快速」模式（指定 tiny）維持省流量；品質模式改用 ~96k 音源，
        # 極低位元率的編碼失真在大模型上會明顯反映成錯字。
        low = opts.get("low_data")
        if low is None:
            low = (mdl == "tiny")
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

    切換分析模式、時間戳、簡介過濾等選項時只會重跑這裡，完全不耗流量。
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

# 閒置多久自動關閉（分鐘）。預設 0 = 不自動關閉，由使用者自己在
# Android 通知列按 Exit 結束 —— 那個動作同時結束 Termux 工作階段，
# wake-lock 也一起放掉，比程式自作主張關閉更符合預期。
# 想要自動關閉就設環境變數，例如 YTSCRIPT_IDLE_MIN=20。
IDLE_MIN = int(os.environ.get("YTSCRIPT_IDLE_MIN", "0") or 0)
LAST_SEEN = time.time()


def touch():
    """有人在用。每次收到請求都更新。"""
    global LAST_SEEN
    LAST_SEEN = time.time()


def idle_watchdog():
    """沒人用就自己關掉，順便放掉 wake-lock。"""
    if IDLE_MIN <= 0:
        return
    limit = IDLE_MIN * 60
    while True:
        time.sleep(20)
        with JOBS_LOCK:
            busy = any(j.get("status") == "running" for j in JOBS.values())
        if busy:                       # 聽寫中絕對不能關
            touch()
            continue
        if time.time() - LAST_SEEN > limit:
            print(f"\n   閒置超過 {IDLE_MIN} 分鐘，自動關閉以節省電力。")
            print("   要再用時，點主畫面的啟動捷徑即可。\n")
            try:
                import subprocess
                subprocess.run(["termux-wake-unlock"], capture_output=True, timeout=10)
            except Exception:
                pass
            os._exit(0)
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
        touch()
        path = urllib.parse.urlparse(self.path).path
        if path in ("/", "/index.html"):
            try:
                with open(os.path.join(BASE_DIR, "ui.html"), "rb") as f:
                    return self._send(200, f.read(), "text/html; charset=utf-8")
            except FileNotFoundError:
                return self._send(500, "找不到 ui.html", "text/plain; charset=utf-8")

        # 給捷徑腳本與 Service Worker 用：確認這個埠上跑的是本程式
        if path in ("/health", "/api/health"):
            return self._send(200, json.dumps({"ok": True, "app": "ytscript"}))

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
            try:
                with open(os.path.join(BASE_DIR, name), "rb") as f:
                    return self._send(200, f.read(), STATIC_FILES[name])
            except FileNotFoundError:
                return self._send(404, b"", STATIC_FILES[name])

        if path == "/api/info":
            ip = lan_ip()
            return self._send(200, json.dumps({
                "port": PORT,
                "lan_url": f"http://{ip}:{PORT}" if ip else None,
            }))

        return self._send(404, json.dumps({"error": "not found"}))

    def do_POST(self):
        touch()
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


def instance_alive(port):
    """這個埠上跑的是不是本程式自己？"""
    try:
        req = urllib.request.Request(f"http://127.0.0.1:{port}/health")
        with urllib.request.urlopen(req, timeout=2) as r:
            return b'"ytscript"' in r.read(200)
    except Exception:
        return False


def port_free(port):
    with socket.socket() as s:
        return s.connect_ex(("127.0.0.1", port)) != 0


def free_port(start):
    """優先使用預設埠。

    舊版只要預設埠被占用就換下一個，但主畫面的捷徑固定指向 8756，
    一旦服務跑到 8757，圖示就永遠打不開 —— 而且看起來像是「沒反應」，
    完全無從判斷。現在只有在該埠被「別的程式」占用時才換。
    """
    if port_free(start):
        return start
    for p in range(start + 1, start + 30):
        if port_free(p):
            return p
    return start


def serve(open_browser=True):
    global SERVER, PORT

    # 已經有一份在跑就不要再開一份：直接把瀏覽器叫起來就好。
    # 否則第二份會退到 8757，而主畫面捷徑指的是 8756，變成打不開。
    if instance_alive(DEFAULT_PORT):
        print(f"\n   服務已經在執行中（埠 {DEFAULT_PORT}），直接開啟畫面。\n")
        if open_browser:
            open_url(f"http://localhost:{DEFAULT_PORT}")
        return

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
    print("   用完請在 Android 通知列按 Exit 結束（會一併放掉 wake-lock）。")
    if IDLE_MIN > 0:
        print(f"   閒置 {IDLE_MIN} 分鐘沒人使用也會自動關閉。")
    print()

    touch()
    threading.Thread(target=idle_watchdog, daemon=True).start()

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
