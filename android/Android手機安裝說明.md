# 在 Android 手機上獨立運行（不需要開電腦）

裝好之後，手機桌面會有一個圖示，點一下就開，**完全不需要電腦**。
功能和電腦版一樣：三種分析模式、段落時間戳、下載 .md／.txt／.srt。

**唯一的差別在 AI 聽寫**（只有「沒有字幕的影片」才用得到）：
Android 裝不了電腦版用的 faster-whisper，所以手機改用 **whisper.cpp**。
它在 Termux 上沒有現成的執行檔，安裝腳本會**從原始碼編譯，約 5～15 分鐘**。
有字幕的影片完全不受影響。

**為什麼手機可以直接抓 YouTube？** YouTube 封鎖的是機房 IP（AWS／GCP／Azure），
手機的 4G／5G／WiFi 是住宅等級 IP，YouTube 不擋。

> 2026-09-24 改版：以前的做法是從 Google Drive 下載 `手機安裝包.zip`、再執行
> `/sdcard/Download/install.sh`。**那個流程已經停用**，請一律用下面的 git 方式。
> git 方式的好處是：之後更新只要一行 `git pull`。

---

## ⚠️ 第一件最重要的事

**Termux 必須從 F-Droid 安裝，絕對不要用 Google Play 的版本。**
Google Play 上的 Termux 是多年前的舊版，套件安裝會失敗。這是最多人卡住的地方。

---

## 步驟一：安裝兩個 App

1. 用手機瀏覽器開啟 **https://f-droid.org**，下載並安裝 F-Droid
   （Android 會問要不要允許「安裝未知來源的應用程式」，選允許）
2. 打開 F-Droid，搜尋並安裝：
   - **Termux** —— Linux 環境，程式實際跑在這裡
   - **Termux:Widget** —— 讓你可以在桌面放一個圖示
3. 把 Termux 打開一次，等它完成初始化

---

## 步驟二：下載程式並安裝

建議在 **WiFi、插著電**的狀態下做。打開 Termux，一次一行輸入：

```bash
pkg install -y git
```

```bash
git clone https://github.com/door410/transcript.git
```

```bash
bash transcript/android/install.sh
```

安裝腳本共 8 步，全部自動：

| 步驟 | 做什麼 | 時間 |
|---|---|---|
| [1/8] | 修復套件系統 | 幾秒 |
| [2/8] | 系統套件整包升級（避免 Termux 升級到一半的問題） | 幾分鐘 |
| [3/8] | 安裝 python、git、ffmpeg 等 | 幾分鐘 |
| [4/8] | 安裝 Python 套件（版本依 `requirements/core.txt`） | 1 分鐘 |
| [5/8] | **編譯 whisper.cpp**（固定版本 v1.9.4，只編譯程式會用到的 `whisper-cli`） | **5～15 分鐘，不要關 Termux** |
| [6/8] | 下載 AI 聽寫模型（快速用 `tiny-q5_1`；準確依記憶體，8 GB 手機為 `large-v3-turbo`） | 依網速 |
| [7/8] | 建立啟動器 `~/ytscript/start.sh` 與桌面捷徑 | 幾秒 |
| [8/8] | 端對端驗證 | 幾秒 |

最後看到「**安裝完成。**」就成功了。如果有項目顯示「失敗」：
- 完整記錄在 `~/install-log.txt`
- 有字幕的影片仍然可以用；只是沒字幕的影片不能 AI 聽寫
- 可以直接再跑一次 `bash transcript/android/install.sh`（做過的步驟會跳過）

---

## 步驟三：開啟必要權限（很重要）

Termux 從桌面小工具啟動時，需要「**顯示在其他應用程式上層**」權限，
否則點了圖示只會跳出紅色提示而不會啟動。

**設定 → 應用程式 → Termux → 顯示在其他應用程式上層 → 允許**
（部分機型叫「懸浮視窗」或「在其他應用程式上層顯示」）

另外建議：**設定 → 應用程式 → Termux → 電池 → 不最佳化／無限制**，
這樣長時間轉錄才不會被系統中斷。

---

## 步驟四：放桌面圖示

1. 長按手機桌面空白處 → **小工具** → 找到 **Termux:Widget**
2. 拖到桌面 → 選 **YouTube-Transcript**
3. 點一下 → Termux 會啟動程式，瀏覽器自動打開 `127.0.0.1:8756`

### 做成全螢幕 App（推薦）

瀏覽器打開工具後，點右上角 **⋮** → **加入主畫面**（或「安裝應用程式」）。
主畫面會多一個「逐字稿」圖示，點下去就是全螢幕、沒有網址列。

> 主畫面圖示只是「打開介面」，真正跑程式的是 Termux。
> 所以順序是：**先點 Termux 小工具啟動 → 之後用主畫面圖示操作**。

---

## 日常使用

1. 點桌面的 Termux 小工具 → 瀏覽器自動打開
2. 從 YouTube App 複製影片連結，貼上 → 開始轉錄
3. 按「複製全部給 AI」→ 切到 ChatGPT／Claude App → 貼上送出

**結束：** 關掉瀏覽器分頁，5 分鐘後程式會自動結束。
要馬上結束：拉下通知列，在 Termux 的通知上按 **Exit**。

沒有打開 Termux 小工具、直接在 Termux 裡啟動也可以：

```bash
bash ~/ytscript/start.sh
```

---

## 更新程式

```bash
cd ~/transcript && git pull
```

然後重新啟動（通知列 Termux 按 Exit → 再點桌面小工具）。**就這樣。**

手機直接執行 `~/transcript` 裡的程式，`git pull` 下來的就是新版，不需要再複製任何檔案。
（`~/ytscript/` 裡只有啟動器 `start.sh`。）

**只有下面這些情況，才需要再跑一次安裝腳本：**
- `git pull` 的訊息裡出現 `android/install.sh` 或 `requirements/` 有變動
- 自我檢查叫你重跑
- Termux 出現奇怪的錯誤（例如 `CANNOT LINK EXECUTABLE`）

```bash
bash ~/transcript/android/install.sh
```

> **從舊版升級的人（2026-09-24 以前安裝的）：** 以前的安裝方式是把程式複製到 `~/ytscript/`。
> 請 `git pull` 之後**重跑一次** `bash ~/transcript/android/install.sh`，它會自動換成新方式並清掉舊副本。
> 之後就只需要 `git pull`。

### 確認一切正常

```bash
python ~/transcript/tools/selfcheck.py
```

最後一行是「全部通過」就沒問題。其中「手機啟動器指向這個資料夾」這一項，
會告訴你是不是還在用舊的安裝方式。

---

## 常見問題

**`pkg install` 失敗、一直出現錯誤**
九成是裝到了 Google Play 版的 Termux。移除後改從 F-Droid 安裝。

**點桌面圖示沒反應**
- Termux:Widget 沒裝，或步驟二沒跑完（`~/.shortcuts/` 裡沒有檔案）
- 沒開「顯示在其他應用程式上層」權限（步驟三）

**跑到一半手機休眠就斷掉**
啟動器已經自動加了 `termux-wake-lock`。還是會斷的話，
到「設定 → 應用程式 → Termux → 電池」改成「不最佳化／無限制」。

**突然抓不到字幕**

```bash
cd ~/transcript && pip install --upgrade -r requirements/core.txt
```

**沒字幕的影片失敗：「找不到 whisper.cpp 執行檔」或「需要 ffmpeg」**

```bash
bash ~/transcript/android/install.sh
```

更多狀況見 `docs/維護手冊/07_除錯.md` 的「情境 E：手機版突然錯誤」。

---

## 佔多少空間？

| 項目 | 大小 |
|---|---|
| Python、ffmpeg 與套件 | 約 250 MB |
| whisper.cpp 原始碼與編譯結果 | 約 500 MB 以內 |
| AI 模型 | 快速 31 MB；準確：記憶體 5.5 GB 以上約 574 MB、3.5 GB 以上約 181 MB |
| 逐字稿快取 | 最多約 2.7 MB |
| 程式本身 | 幾百 KB |

影片音訊是邊用邊刪的，不會累積。
