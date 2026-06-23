# 網路診斷報告

- 產生時間：2026-06-16T12:31:21+08:00
- 狀態：blocked
- 異常來源：6

## 檢查結果
| 來源 | Host | DNS | TCP 443 | HTTPS | 錯誤 |
| --- | --- | --- | --- | --- | --- |
| Lotto8 | www.lotto-8.com | ok | failed | failed | tcp443: [WinError 10013] 嘗試存取通訊端被拒絕，因為存取權限不足。 |
| Lottolyzer | en.lottolyzer.com | ok | failed | failed | tcp443: [WinError 10013] 嘗試存取通訊端被拒絕，因為存取權限不足。 |
| LotteryUSA | www.lotteryusa.com | ok | failed | failed | tcp443: [WinError 10013] 嘗試存取通訊端被拒絕，因為存取權限不足。 |
| LotteryNet | www.lottery.net | ok | failed | failed | tcp443: [WinError 10013] 嘗試存取通訊端被拒絕，因為存取權限不足。 |
| LotteryCorner | lotterycorner.com | ok | failed | failed | tcp443: [WinError 10013] 嘗試存取通訊端被拒絕，因為存取權限不足。 |
| LotteryPredictor | lotterypredictor.com | ok | failed | failed | tcp443: [WinError 10013] 嘗試存取通訊端被拒絕，因為存取權限不足。 |

## 改善建議
- 若 DNS 失敗：檢查網路 DNS 或改用手機熱點測試。
- 若 TCP 443 失敗：Windows 防火牆或防毒軟體可能擋住 Python 連線。
- 若 HTTPS 失敗：可能是權限、代理伺服器或網站防爬限制。
- 線上抓不到時：將歷史 CSV 放入 history_import 資料夾，並重新執行主系統。