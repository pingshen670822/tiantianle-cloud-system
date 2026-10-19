# 天天樂鐵律專用版

## 2026-10-19 流程重寫

- 電腦更新：`天天樂一鍵啟動.bat`；正式程式為 `system_update.py`。
- 手機更新：`天天樂雲端一鍵上線.bat`；只要求 GitHub 執行同一套已驗證流程，不直接覆寫網站。
- 舊名稱僅為相容入口，已移除原本的分支強制覆寫、切換網站發布模式及失敗後假成功邏輯。
- 更新使用作業系統互斥鎖、SQLite 一致快照、隔離運算、驗證後置換及中斷復原日誌；運算失敗時保留上一份有效戰報。
- 開獎前後、每三小時檢查及13:00完整重算保留；重複密集排程已移除。救援只在主更新失敗時呼叫同一流程。
- 診斷：`logs/last_update.log`、`work/update_status.json`、`reports/repair_validation.json`。
- 回歸測試：`python -m unittest discover -s tests -v`；每次雲端發布前必須通過。

## 一鍵啟動

根目錄只保留一個啟動檔：

```text
天天樂一鍵啟動.bat
```

雙擊後會自動更新資料、重新運算預測、產生戰報，並開啟手機/電腦共用的一鍵入口：

```text
site/index.html
```

## 分頁保留

分頁保留，但不再做成一堆外層按鈕：

```text
site/prediction.html
site/review.html
site/prediction-history.html
```

- `prediction.html`：本日預測、高機率監控、95% 目標治理、獨支驗證。
- `review.html`：上期命中與未命中檢討、降權與修正。
- `prediction-history.html`：每期預測對比。

## 手機版

手機安裝入口仍保留：

```text
site/install.html
```

畫面只保留一個主要按鈕，不再顯示多個分散入口。

## 免電腦雲端手機版

真正免電腦版不是 `file:///C:/...` 本機檔案，而是 GitHub Pages 網址。

第一次請雙擊：

```text
天天樂雲端一鍵上線.bat
```

完成 GitHub 官方登入後，系統會建立 `tiantianle-cloud-system`、啟用 GitHub Pages 與 GitHub Actions，並產生：

```text
天天樂手機雲端網址.txt
```

手機安裝與每日查看都使用這個網址；電腦關機後仍可開啟，更新由 GitHub Actions 自動執行。
