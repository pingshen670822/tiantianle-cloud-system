# 天天樂系統

## 操作入口

- 電腦更新：雙擊 `天天樂一鍵啟動.bat`，完成驗證後開啟 `site/index.html`。
- 手機雲端更新：雙擊 `天天樂雲端一鍵上線.bat`，送出 GitHub 更新要求；完成前保留上一份有效戰報。
- 手機網址：https://pingshen670822.github.io/tiantianle-cloud-system/
- `RUN_TIANTIANLE_NOW.bat`、兩個 `PUBLISH_*.bat` 及舊 Python 名稱僅為相容入口，沒有各自的更新或發布實作。

## 唯一更新流程

`system_update.py` → 作業系統互斥鎖 → SQLite 一致快照 → 隔離運算 → 驗證 → 可復原的正式資料置換。

正式資料、戰報與手機網站在驗證前不會被新運算覆寫。置換中斷時，復原日誌會在下一次啟動恢復一致狀態；保留一份上一版備份。

`cloud_update_request.py` 只送出同一套雲端流程的執行要求。已移除直接覆寫 gh-pages、切換 Pages 模式、失敗後仍宣告成功，以及多套修復程式互相改寫資料的舊實作。

## 保留的戰報規格

- 適用日期、終極獨隻、2中2、3中3、5中5、7中5、9中5。
- 50組模組與60期逐期回測。
- 前15名六碼10組，以及1–39全號碼六碼最高分10組。
- 模型評分、命中紀錄及信心狀態分開標示；模型評分不等於中獎機率。

## 自動更新

保留夏令與冬令開獎後更新、每三小時檢查、台灣13:00完整重算及21:45安全更新；已移除重複密集觸發。

主流程失敗時，救援工作呼叫同一套流程，不再執行另一套修改器。雲端依序執行測試、隔離重算、驗證、正式部署與網站同步核對。

## 診斷與驗證

- 執行狀態：`work/update_status.json`。
- 最近一次更新紀錄：`logs/last_update.log`。
- 發布前驗證：`reports/repair_validation.json`。
- 上一版備份：`work/rollback-*`。
- 測試：`python -m unittest discover -s tests -v`。
- 只驗證：`python system_update.py --validate-only`。
- 完整重算：`python system_update.py --mode deep`。

外部開獎來源或託管服務暫時無法使用時，更新可能失敗；此時應查看紀錄並重試，不能將過期資料標為新一期，或將未通過驗證的輸出發布。
