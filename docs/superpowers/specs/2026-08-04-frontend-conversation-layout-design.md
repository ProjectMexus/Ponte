# Ponte 前端對話區固定佈局設計

## 目標

當右側服務工作區因多次聊天、資料卡或操作按鈕變長時，左側對話入口仍要保持可見；使用者不應需要回到頁面頂部才能繼續輸入。桌面版提供左右兩個獨立可滾動區域，手機版維持自然的上下閱讀流程。

## 根因

目前 `.conversation-panel` 只有 `min-height: 720px`，而 `.workspace-panel` 的高度由內容決定。`.workspace-panel` 雖然使用 `position: sticky`，但左側沒有相同的 viewport-bound behavior。當工作區內容變長，頁面總高度由右側內容主導，左側 panel 滾出視窗後就無法直接使用。

## 方案

### 桌面版（寬度大於 900px）

- `.conversation-panel` 和 `.workspace-panel` 都使用接近 viewport 的固定高度。
- 兩個 panel 都以 `position: sticky` 固定於視窗頂部安全距離，讓使用者下滑時仍能看到對話和工作區。
- `.conversation-list` 設為 `min-height: 0` 並保留 `overflow-y: auto`，只讓聊天訊息在左側內容區滾動；快捷按鈕和輸入表單維持可見。
- `.workspace-panel` 設為 `overflow-y: auto`，讓大量服務資料和操作在右側內部滾動，不再把整個頁面無限拉長。
- panel 內部使用 `overflow: hidden` 或等效邊界，避免內部滾動區域造成 panel 外溢。

### 手機版（寬度不大於 900px）

- 取消 panel 的 sticky、固定高度和內部限制，恢復正常文件流。
- `.app-shell` 維持單欄排列，使用者可用整頁上下滾動依序閱讀對話和工作區。
- 保留目前的手機按鈕、日期欄位及標題響應式樣式。

## 變更範圍

- 修改 `frontend/styles.css` 的桌面 panel 尺寸、sticky 與 overflow 規則，以及 900px 斷點的復原規則。
- 修改 `tests/test_frontend_static.py`，加入佈局 contract 檢查，防止未來移除 viewport-bound 或 mobile reset。
- 不修改 HTML 結構、JavaScript 事件、對話資料保存、middleware API 或業務流程。

## 互動與錯誤行為

這是純 CSS 佈局調整。聊天訊息仍由現有 `interaction-view.js` 追加並捲動 `.conversation-list`；工作區資料仍由既有 renderer 更新。任何 middleware 錯誤、空資料或 action 狀態維持原本呈現方式。

## 驗證

1. 執行 `python3 -m unittest tests.test_frontend_static -v`，確認靜態資產與新增佈局 contract 通過。
2. 執行所有既有 Python 測試，確認前端 CSS 變更沒有影響 backend 或 stack runner。
3. 執行 `node --check` 檢查所有前端 JavaScript 模組。
4. 用本地前端頁面做桌面與手機斷點 smoke check：桌面多次追加長訊息及工作區資料時，左右 panel 各自滾動且左側輸入區可持續使用；手機版仍可由上至下完整滾動。

## 完成條件

- 桌面視窗向下滾動後，左側對話 panel 仍在可見區域。
- 多筆工作區資料不再把右側 panel 無限延伸到整個頁面。
- 聊天列表能在左側內容區獨立滾動，且輸入表單保持可用。
- 900px 以下的單欄頁面不被固定高度或 sticky 破壞。
- 所有驗證命令通過。
