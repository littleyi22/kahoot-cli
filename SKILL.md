---
name: kahoot_quiz_creator
description: 當使用者要求「到 Kahoot 出題」、「建立 Kahoot 遊戲」、「自動化出 Kahoot 題目」、「做 Kahoot 猜燈謎/問答」或提及關鍵字「Kahoot」時觸發。此 Skill 指引 AI 使用本地 Chrome Profile 配合 H 槽的 Kahoot CLI 腳本 (kahoot.py) 自動填寫題幹、搜尋配圖並儲存發布。
---

# Kahoot! CLI 自動化出題與互動遊戲建置指南 (Kahoot Quiz Creator Skill)

本 Skill 用於指引 AI 讀取使用者的題目內容（或自行生成題目），並呼叫本機自動化出題腳本 `kahoot.py` 登入使用者的帳號，自動將題目送上 Kahoot! 平台並發布。

## 🛠️ CLI 運作環境與指令定位

* **CLI 腳本路徑**：`H:/我的雲端硬碟/粉專/008 數位專案與互動程式/1150809 Kahoot CLI/kahoot.py`
* **Python 解釋器**：`C:/Python314/python.exe`（或直接使用本機預設的 `python`）
* **CDP 真實登入瀏覽器啟動指令**（用於登入過期時）：
  ```powershell
  python kahoot.py chrome-login
  ```
* **自動出題主指令**：
  ```powershell
  python kahoot.py create --content [JSON檔案路徑] [--premium] [--publish]
  ```
  * `--premium`：當包含進階/付費題型（簡答填充、排列解謎、文字雲、票選活動）時必須加上。
  * `--publish`：建立完畢直接發布，若不加則預設儲存為草稿 (Draft)。

---

## 📋 題目 JSON 配置格式與題型規範

當使用者提供大綱或要求出題時，AI 應先在 `output/` 資料夾下產生符合以下結構的 JSON 實體檔案，再呼叫 CLI 執行出題：

```json
{
  "title": "互動遊戲標題",
  "description": "活動的簡短說明",
  "questions": [
    {
      "question": "題目題幹描述 (例如：猜燈謎...打一日常用品)",
      "answers": ["選項A", "選項B", "選項C", "選項D"],
      "correct": 0,
      "type": "quiz",
      "image_search": "Getty圖片搜尋關鍵字 (如: apple)"
    }
  ]
}
```

### 支援的五大題型 (`type` 欄位)
1. **多選測驗題 (`"type": "quiz"`)**： *(免費題型)*
   * `answers`：必須提供 2 至 4 個選項。
   * `correct`：正確答案的索引值（0-3）。
2. **是非題 (`"type": "true_false"`)**： *(免費題型，預設使用 quiz 的 True/False 代替)*
   * 亦屬於免費題型。
3. **簡答/填充題 (`"type": "type_answer"`)**： *(付費高級題型，需加 `--premium`)*
   * `answers`：提供 1 個或多個可接受的正確謎底。
   * `correct`：通常為 0。
4. **排列解謎 (`"type": "puzzle"`)**： *(付費高級題型，需加 `--premium`)*
   * `answers`：**必須提供 4 個選項**，且填寫順序必須是**「正確的排序順序」**。
5. **文字雲 (`"type": "word_cloud"`)**： *(付費高級題型，需加 `--premium`)*
   * `answers`：填寫空陣列 `[]`（玩家自行作答，無預設選項）。
6. **票選活動 (`"type": "poll"`)**： *(付費高級題型，需加 `--premium`)*
   * `answers`：提供最多 4 個投票選項。無須 `correct` 勾選。

---

## 🚀 AI 出題自動化流程執行步驟

### 步驟 1：產出題目 JSON 實體檔
* 將題目整理成上述 JSON 格式，並一律直接寫入並建立實體檔案，存放在工作區 of output 資料夾中（例如 `output/kahoot_riddles.json`）。
* **重要**：絕對不可只在對話框輸出程式碼區塊讓使用者自行複製。

### 步驟 2：執行 Session 效能檢查
* 執行 `python kahoot.py check` 確保本機 Session 依然有效。
* 若顯示 `[失效] 登入 Session 已過期`：
  - 提示使用者執行 `python kahoot.py chrome-login` 重啟瀏覽器，並手動完成登入後，在對話框回覆「我登入好了」，再由 AI 執行 `python kahoot.py grab-session` 儲存憑證。

### 步驟 3：呼叫 CLI 執行出題
* 依據題型判定是否為付費帳號（若含進階題型，加 `--premium` 旗標），並執行 create 指令。
* 程式會自動接管 Chrome，並以 **「有頭模式」**（若加 `--no-headless` / 互動）或背景執行，自動配置標題、出題、搜尋合適圖片，並後置清理預設 dummy 第一題，最後完成發布或存為草稿。
