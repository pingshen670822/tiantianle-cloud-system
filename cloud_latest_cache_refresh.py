import json
import ssl
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parent
CACHE_DIR = ROOT / "data" / "latest_cache"
REPORTS_DIR = ROOT / "reports"
TAIWAN_TZ = ZoneInfo("Asia/Taipei")
CALIFORNIA_TZ = ZoneInfo("America/Los_Angeles")


def current_year():
    return datetime.now(CALIFORNIA_TZ).year


def cache_sources():
    year = current_year()
    return [
        ("calottery_official.html", "https://www.calottery.com/en/draw-games/fantasy-5"),
        ("lotto8_latest.html", "https://www.lotto-8.com/usa/listltoFT5.asp?indexpage=1&orderby=new"),
        ("lottolyzer_latest.html", "https://en.lottolyzer.com/history/united-states/fantasy-5-california/"),
        ("lotteryusa_latest.html", "https://www.lotteryusa.com/california/fantasy-5/"),
        ("lotteryusa_year.html", f"https://www.lotteryusa.com/california/fantasy-5/year/{year}"),
        ("lotterynet_latest.html", "https://www.lottery.net/california/fantasy-5/numbers"),
        ("lotterynet_year.html", f"https://www.lottery.net/california/fantasy-5/numbers/{year}"),
    ]


def download(url, timeout=45):
    stamp = int(time.time() * 1000)
    separator = "&" if "?" in url else "?"
    request = urllib.request.Request(
        f"{url}{separator}tiantianle_nocache={stamp}",
        headers={
            "User-Agent": "Mozilla/5.0 TiantianleCloudSelfRepair/20260929",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9,zh-TW;q=0.8",
            "Cache-Control": "no-cache",
            "Pragma": "no-cache",
        },
    )
    with urllib.request.urlopen(request, timeout=timeout, context=ssl._create_unverified_context()) as response:
        return response.read()


def main():
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    results = []
    ok_count = 0
    for name, url in cache_sources():
        status = {"file": name, "url": url, "ok": False, "bytes": 0, "error": ""}
        last_error = None
        for attempt in range(1, 4):
            try:
                raw = download(url)
                if len(raw) < 500:
                    raise RuntimeError("download too small")
                tmp = CACHE_DIR / f"{name}.tmp"
                tmp.write_bytes(raw)
                tmp.replace(CACHE_DIR / name)
                status.update({"ok": True, "bytes": len(raw), "attempt": attempt})
                ok_count += 1
                break
            except Exception as exc:
                last_error = exc
                time.sleep(2 * attempt)
        if not status["ok"]:
            status["error"] = str(last_error or "unknown")
        results.append(status)

    report = {
        "checked_at_taiwan": datetime.now(TAIWAN_TZ).isoformat(timespec="seconds"),
        "status": "ok" if ok_count >= 2 else "warning",
        "successful_sources": ok_count,
        "total_sources": len(results),
        "results": results,
    }
    (REPORTS_DIR / "cloud_latest_cache_refresh.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    lines = [
        "# 天天樂雲端最新來源快取自救",
        "",
        f"- 檢查時間：{datetime.now(TAIWAN_TZ):%Y-%m-%d %H:%M:%S} 台灣時間",
        f"- 狀態：{report['status']}",
        f"- 成功來源：{ok_count}/{len(results)}",
        "",
        "| 來源檔 | 結果 | 大小 | 錯誤 |",
        "| --- | --- | ---: | --- |",
    ]
    for item in results:
        lines.append(
            f"| {item['file']} | {'成功' if item['ok'] else '失敗'} | {item['bytes']} | {item['error'] or '-'} |"
        )
    (REPORTS_DIR / "cloud_latest_cache_refresh.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps({"status": report["status"], "successful_sources": ok_count}, ensure_ascii=False))
    return 0 if ok_count >= 2 else 1


if __name__ == "__main__":
    raise SystemExit(main())
