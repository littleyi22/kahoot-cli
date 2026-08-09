# kahoot-cli 🎮

> 用 Python + Playwright 驅動真實 Chrome，讓 AI Agent 或腳本自動在 Kahoot! 建立互動遊戲並出題。

## ✨ 特色

- 🤖 **AI Agent 友善**：附帶標準 Skill 說明，可直接讓 AI Agent 呼叫此 CLI 完成 Kahoot 出題。
- 🖼️ **自動配圖**：支援 Kahoot! 內建的 Getty 媒體庫關鍵字搜尋，自動為每道題目插入合適圖片。
- 💎 **付費題型全支援**：多選、簡答填充、排列解謎、文字雲、票選活動，一個 JSON 設定搞定。
- 🔒 **零密碼外洩**：登入完全在您本機的真實 Chrome 中進行，session 僅存在本機，絕不上傳。
- 🏃 **背景靜默執行**：預設 Headless 背景出題，不干擾您的工作視窗。

---

## 📦 安裝 (Windows PowerShell)

```powershell
# 1. Clone 專案
git clone https://github.com/<your-username>/kahoot-cli.git
cd kahoot-cli

# 2. 一鍵安裝依賴
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\setup.ps1
```

---

## 🔑 第一次登入

```powershell
# 開啟專用 Chrome，手動登入您的 Kahoot! 帳號
python kahoot.py chrome-login

# 登入成功後，回到 PowerShell 擷取並儲存 Session
python kahoot.py grab-session

# 驗證登入狀態
python kahoot.py check
# 看到 [OK] 登入有效 即表示設定完成！
```

---

## 🚀 快速出題

```powershell
# 使用範例 JSON 建立一個遊戲（儲存為草稿）
python kahoot.py create --content examples/quiz_example.json

# 付費帳號使用進階題型
python kahoot.py create --content examples/premium_example.json --premium

# 建立完畢直接發布
python kahoot.py create --content examples/quiz_example.json --publish

# 有頭模式（可看見瀏覽器操作過程）
python kahoot.py create --content examples/quiz_example.json --no-headless
```

---

## 📋 指令速查

| 指令 | 說明 |
|---|---|
| `python kahoot.py doctor` | 診斷本機環境（Python / Playwright / Chrome / 登入狀態）|
| `python kahoot.py chrome-login` | 開啟專用 Chrome Profile（Port: 9334）供手動登入 |
| `python kahoot.py grab-session` | 從偵錯 Chrome 擷取 cookies 並儲存至 `~/.kahoot/state.json` |
| `python kahoot.py check` | 驗證本地 Session 是否仍有效 |
| `python kahoot.py create --content x.json` | 讀取 JSON 並自動建立遊戲（預設 Headless + 存為草稿）|
| `python kahoot.py create ... --publish` | 建立後直接發布 |
| `python kahoot.py create ... --premium` | 宣告付費帳號，解鎖進階題型 |
| `python kahoot.py create ... --no-headless` | 有頭模式，可看見操作畫面 |
| `python kahoot.py create ... --dry-run` | 只驗證 JSON 格式，不執行瀏覽器 |

---

## 📝 題目 JSON 格式說明

所有題目均以一個 JSON 檔案定義，範例在 `examples/` 資料夾中。

```json
{
  "title": "互動遊戲標題",
  "description": "活動的簡短說明（選填）",
  "questions": [
    {
      "question": "題幹（問題的完整文字）",
      "answers": ["選項 A", "選項 B", "選項 C", "選項 D"],
      "correct": 0,
      "type": "quiz",
      "image_search": "Getty 搜尋關鍵字（英文效果較佳）"
    }
  ]
}
```

### 題型一覽

| `type` 值 | 題型名稱 | 帳號需求 | `answers` 規則 | 需 `correct` |
|---|---|---|---|---|
| `quiz` | 多選測驗題 | ✅ 免費 | 2–4 個選項 | ✅ 必填（索引 0–3）|
| `true_false` | 是非題 | ✅ 免費 | `["是", "否"]` | ✅ 必填 |
| `type_answer` | 簡答 / 填充題 | 💎 付費 | 1 個以上的正確答案 | 通常填 `0` |
| `puzzle` | 排列解謎 | 💎 付費 | **恰好 4 個**，依正確排列順序填入 | ❌ 不需要 |
| `word_cloud` | 文字雲 | 💎 付費 | `[]`（空陣列） | ❌ 不需要 |
| `poll` | 票選活動 | 💎 付費 | 2–4 個投票選項 | ❌ 不需要 |

> 💡 `image_search` 和 `image`（本機路徑）為可選欄位，兩者擇一即可。

---

## 📂 範例檔案

| 檔案 | 說明 |
|---|---|
| [`examples/quiz_example.json`](examples/quiz_example.json) | 標準多選測驗題範例（台灣地理） |
| [`examples/riddles_example.json`](examples/riddles_example.json) | 猜燈謎簡答填充題範例（付費）|
| [`examples/premium_example.json`](examples/premium_example.json) | 排列解謎 + 文字雲 + 票選活動綜合範例（付費）|

---

## 🤖 AI Agent 對接指南

本專案附帶 [`SKILL.md`](SKILL.md)，可直接作為 Antigravity / Claude / GPT 等 AI Agent 的 Skill 設定。

### Skill 觸發關鍵字（示例）
- 「到 Kahoot 出題」
- 「幫我建立 Kahoot 遊戲」
- 「自動化出 Kahoot 題目」
- 「做 Kahoot 猜燈謎/填充/問答」

### Agent 出題 SOP

```
1. 生成符合 JSON 格式的題目並寫入 output/ 資料夾
2. 執行 python kahoot.py check 確認 Session 有效
3. 執行 python kahoot.py create --content output/xxx.json [--premium] [--publish]
4. 等待程式完成，回報發布結果
```

詳細規格請見 [`SKILL.md`](SKILL.md)。

---

## 🔒 安全聲明

- 本工具**絕對不會、也無法看到**您的帳號密碼。
- 登入完全在您本機的真實 Chrome 瀏覽器中進行。
- Session cookies 僅存於本機 `~/.kahoot/state.json`，已在 `.gitignore` 中排除，**請勿手動提交此檔案**。

---

## 🗂️ 技術棧

- **Python 3.10+**
- **Playwright** — 瀏覽器自動化，支援 CDP 接管與 Persistent Profile 雙模式
- **Google Chrome**（本機安裝）— 以真實瀏覽器指紋繞過 bot 偵測

---

## 📄 授權

MIT License
