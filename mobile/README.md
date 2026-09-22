# 逐字稿工具 — 手機版（Android / Termux）

把 YouTube、Bilibili 等平台的影片轉成逐字稿，整份在手機本機執行。
有現成字幕就直接抓字幕（幾秒鐘）；沒有字幕就用 AI 聽寫（完全離線運算）。

這份說明是**給全新手機從零安裝**用的。照著做一遍，中間不需要自己判斷任何事情。

---

## 這套東西是什麼

執行起來之後，它在手機內部開了一個**本機網頁伺服器**，監聽 `8756` 這個埠。
你用瀏覽器連 `127.0.0.1:8756` 就是操作介面。

理解這一點很重要，因為它決定了使用方式：

- 主畫面上的「逐字稿」圖示是**瀏覽器書籤**，不是 app。它自己不會啟動任何東西。
- 主畫面上的終端機圖示（Termux:Widget 捷徑）才是真正**啟動程式**的那個。
- 所以順序永遠是：先啟動，再開畫面。

程式只在你啟動時執行，關掉就完全停止，不會常駐背景。

---

## 第一部分：安裝三個 App

**全部都要從 F-Droid 安裝，不要用 Google Play 的版本。**
Play 商店版的 Termux 已經停止更新，套件系統與 F-Droid 版不相容，裝了會出問題。

1. 用瀏覽器開 <https://f-droid.org>，下載並安裝 **F-Droid**
   （需要允許「安裝未知來源的應用程式」）
2. 打開 F-Droid，搜尋並安裝：
   - **Termux** — 終端機本體，必裝
   - **Termux:Widget** — 桌面啟動捷徑，強烈建議裝
3. 安裝完**先打開 Termux 一次**，讓它完成初始化

> 裝好之後建議關閉 Termux 的電池最佳化，否則系統可能在聽寫途中把它砍掉：
> 設定 → 應用程式 → Termux → 電池 → 不受限制

---

## 第二部分：在 Termux 裡安裝

### 步驟 1：給予儲存權限

```bash
termux-setup-storage
```

會跳出權限對話框，按「允許」。這一步讓 Termux 讀得到手機的「下載」資料夾。

### 步驟 2：取得安裝包

把這個 repo 的 `mobile` 資料夾下載到手機的「下載」資料夾。
從 GitHub 網頁按 `Code → Download ZIP` 最簡單。

然後解壓：

```bash
cd ~
unzip -o /sdcard/Download/transcript-main.zip
```

（檔名依你下載到的實際名稱調整。`ls /sdcard/Download/*.zip` 可以列出來看。）

如果 `unzip` 不存在：

```bash
pkg install -y unzip
```

### 步驟 3：執行安裝腳本

```bash
cd ~/transcript-main/mobile
bash install.sh
```

**這一步要 20～40 分鐘**，而且會下載約 700 MB～1.3 GB（模型檔）。
請用 WiFi、插著電、不要關掉 Termux。

腳本會依序做這些事，每一步都會回報成功或失敗：

| 步驟 | 內容 |
|---|---|
| 1 | 修復 dpkg 卡住的狀態 |
| 2 | 整包系統升級（解決 `libc++` 版本不同步導致 ffmpeg 無法啟動） |
| 3 | 安裝 python、git、cmake、clang、ffmpeg 等，並**實際執行 ffmpeg 確認能跑** |
| 4 | 安裝 yt-dlp、youtube-transcript-api、opencc |
| 5 | 下載並編譯 whisper.cpp，開啟 ARM 的 dotprod／fp16 加速指令 |
| 6 | 下載辨識模型（依手機記憶體決定大小） |
| 7 | 安裝程式檔到 `~/ytscript`，建立桌面捷徑腳本 |
| 8 | 端對端實測：產生音檔 → ffmpeg 轉檔 → whisper 聽寫 |

最後看到「安裝完成」就成功了。若有項目失敗，對照本文最後的「疑難排解」。

腳本可以重複執行，已完成的步驟會自動跳過。

### 步驟 4：第一次啟動

```bash
bash ~/ytscript/start.sh
```

畫面會顯示網址，瀏覽器自己會打開。若沒有自動打開，手動開 `127.0.0.1:8756`。

---

## 第三部分：桌面捷徑與 App 圖示

做完這一步，日常使用就只要點兩下。

### 建立啟動捷徑（終端機圖示）

安裝腳本已經建立好 `~/.shortcuts/YouTube-Transcript.sh`。接著：

1. 回到手機主畫面
2. 長按桌面空白處 → 小工具 / Widgets
3. 找到 **Termux:Widget** → 選 **Termux shortcut**（單一捷徑）
4. 放到桌面上，選擇 `YouTube-Transcript.sh`

以後點這個圖示就會啟動服務。

### 建立操作介面圖示（PWA）

1. 先用上面的捷徑把服務啟動起來
2. 瀏覽器開 `127.0.0.1:8756`
3. 瀏覽器選單 → **加到主畫面**
4. 命名為「逐字稿」

第一次開啟時，頁面會安裝一個 Service Worker。裝好之後，服務沒在跑時點這個圖示，
會看到「服務啟動中」的等待畫面並自動輪詢，而不是瀏覽器的錯誤頁。

---

## 第四部分：日常使用

1. 點**終端機圖示**啟動服務
2. 點**逐字稿圖示**開啟介面（或等它自己打開）
3. 貼上影片連結，按「開始轉錄」
4. 用完在 Android 通知列按 **Exit** 結束

### 為什麼不能只點逐字稿圖示？

因為它只是書籤，網頁沒有權限啟動 Termux 程式，這是 Android 的限制。

### 為什麼點了啟動捷徑後畫面沒有自動跳出來？

Android 10 之後禁止背景程式開啟畫面。捷徑腳本是在背景執行的，
所以它叫瀏覽器的請求可能被系統攔下。這時直接點逐字稿圖示即可 ——
服務還沒好也沒關係，等待畫面會自己接上。

### 兩種辨識模式

| | 快速（預設） | 準確 |
|---|---|---|
| 模型 | tiny | 依記憶體，8GB 機型為 large-v3-turbo |
| 解碼 | 貪婪解碼 | 束搜索 5 |
| 靜音偵測 | 不使用 | 使用 |
| 3 分鐘影片 | 約 30～60 秒 | 約 8～15 分鐘 |
| 適合 | 日常抓重點 | 要仔細研讀的內容 |

語言固定中文、輸出固定繁體，沒有其他設定可調。

### 介面功能

- 連結輸入框右側的 **✕** 一鍵清空，方便貼下一個連結
- 逐字稿輸出框**可以直接編輯**，刪改內容後，複製與下載都會用你改過的版本
- 改壞了按「還原這一頁」回到原始輸出
- Markdown 與純文字兩個分頁各自獨立保存你的修改

### 重新調校（換手機或覺得變慢時）

```bash
bash ~/ytscript/setup-quality.sh
```

會檢查 ARM 加速指令有沒有開、補下載缺少的模型、清掉舊設定檔。

---

## 疑難排解

### 介面全黑看不到字

PWA 快取了舊的樣式檔。在頁面上**下拉重新整理**。

### ffmpeg 報 `CANNOT LINK EXECUTABLE ... libplacebo.so`

`libc++` 版本落後於其他套件。這是 Termux「升級到一半」的典型狀態：

```bash
pkg update && pkg upgrade -y
```

仍然失敗的話，換套件庫鏡像再升級一次：

```bash
termux-change-repo
```

### `dpkg: error processing package ffmpeg`

ffmpeg 的安裝後腳本失敗，會卡住之後所有安裝。執行檔本身沒問題：

```bash
printf '#!/data/data/com.termux/files/usr/bin/sh\nexit 0\n' > $PREFIX/var/lib/dpkg/info/ffmpeg.postinst
chmod +x $PREFIX/var/lib/dpkg/info/ffmpeg.postinst
dpkg --configure -a
```

### 點捷徑沒反應 / 圖示打不開

多半是埠跑掉了。確認服務在哪個埠：

```bash
curl -s 127.0.0.1:8756/health
```

有回應就代表正常。沒有的話先把殘留的程序清掉再啟動：

```bash
pkill -f ytscript.py
bash ~/ytscript/start.sh
```

### 聽寫很慢

先確認 ARM 加速指令有沒有編進去：

```bash
~/whisper.cpp/build/bin/whisper-cli -m ~/.cache/whisper-cpp/ggml-tiny.bin \
  -f ~/whisper.cpp/samples/jfk.wav -np -nt 2>&1 | grep system_info
```

看 `DOTPROD` 或 `MATMUL_INT8` 是不是 `1`。是 `0` 的話重跑 `setup-quality.sh`，
它會用正確的指令集重新編譯。開與不開的差距是好幾倍。

再來確認介面上選的是「快速」而不是「準確」—— 兩者運算量差約 15 倍。

### 手機很燙

AI 聽寫會讓 CPU 持續滿載，發熱無法完全避免。程式已經把執行緒限制在 4 條，
長影片的段與段之間也會停 15 秒降溫。想調整降溫時間：

```bash
YTSCRIPT_COOLDOWN_SEC=30 bash ~/ytscript/start.sh
```

日常用「快速」模式可以大幅減少發熱。

### 逐字稿是簡體

`opencc` 沒裝成功。程式會在第一次用到時自己重試，也可以手動裝：

```bash
pip install opencc-python-reimplemented
```

### bilibili 影片抓不到字幕就失敗

已修正。舊版把 bilibili 的**彈幕軌**誤認成字幕軌，因此判定「這部影片有字幕」
而拒絕啟動 AI 聽寫。現在彈幕、直播聊天室這類軌道會被排除。

### 音訊下載失敗

程式會依序試五種音軌格式。五種都失敗時，錯誤訊息會列出每一種各自的原因
和剩餘儲存空間。常見原因是空間不足或平台暫時限流。

---

## 檔案說明

```
mobile/
├── README.md            這份說明
├── install.sh           全新安裝腳本
└── app/
    ├── ytscript.py      主程式（伺服器、字幕引擎、AI 聽寫）
    ├── ui.html          操作介面
    ├── tokens.css       樣式
    ├── sw.js            Service Worker（服務未啟動時的等待畫面）
    ├── start.sh         啟動腳本
    ├── setup-quality.sh 重新調校用
    ├── manifest.json    PWA 設定
    └── icon-*.png       圖示
```

安裝後的位置：

| 內容 | 路徑 |
|---|---|
| 程式 | `~/ytscript/` |
| 聽寫引擎 | `~/whisper.cpp/` |
| 模型 | `~/.cache/whisper-cpp/` |
| 暫存 | `~/.cache/ytscript/tmp/` |
| 桌面捷徑 | `~/.shortcuts/YouTube-Transcript.sh` |
| 安裝記錄 | `~/install-log.txt` |

---

## 設計上的幾個決定

**只監聽本機還是整個網段？** 程式綁定 `0.0.0.0`，所以同一個 WiFi 下的其他
裝置也連得到。在家裡沒問題，常接公共 WiFi 的話要注意。

**為什麼手機用 whisper.cpp 而不是 faster-whisper？** Android 沒有 CTranslate2
的預編譯套件，faster-whisper 裝不起來。whisper.cpp 從原始碼編譯即可。

**為什麼模型用量化版？** 量化的品質損失，遠小於「降一級模型」的損失。
所以寧可用量化的大模型，也不要用未量化的小模型。

**為什麼語言寫死中文？** `whisper-cli` 的 `-l` 預設值是 `en` 而不是 auto，
任何「偵測失敗就用預設」的寫法都會把中文影片辨識成英文。寫死是確定性的做法。

**為什麼不做自動效能調校？** 短音檔量不到熱降頻，量出來的「最佳執行緒數」
放到長影片上常常是錯的，而且一旦寫進設定檔就會默默拖慢每一次執行。
固定值至少是可預期的。
