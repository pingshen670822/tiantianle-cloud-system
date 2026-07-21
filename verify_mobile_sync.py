import argparse
import json
import pathlib
import ssl
import time
import urllib.error
import urllib.request
from datetime import datetime
from zoneinfo import ZoneInfo


ROOT = pathlib.Path(__file__).resolve().parent
REPORT_DIR = ROOT / "reports"
SITE_DIR = ROOT / "site"
REMOTE_ANALYSIS_URL = "https://pingshen670822.github.io/tiantianle-cloud-system/latest_analysis.json"
TAIWAN = ZoneInfo("Asia/Taipei")


def read_json(path):
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def fetch_remote_json(url, retries, sleep_seconds):
    last_error = ""
    context = ssl._create_unverified_context()
    for attempt in range(1, retries + 1):
        try:
            full_url = url + ("&" if "?" in url else "?") + "verify=" + str(int(time.time()))
            req = urllib.request.Request(
                full_url,
                headers={
                    "Cache-Control": "no-cache",
                    "Pragma": "no-cache",
                    "User-Agent": "tiantianle-mobile-sync-verifier",
                },
            )
            raw = urllib.request.urlopen(req, timeout=45, context=context).read().decode()
            return json.loads(raw)
        except Exception as exc:  # noqa: BLE001
            last_error = str(exc)
            if attempt < retries:
                time.sleep(sleep_seconds)
    raise RuntimeError(last_error or "remote fetch failed")


def fetch_remote_until_synced(url, local_payload, retries, sleep_seconds):
    last_remote = {}
    last_mismatches = []
    last_error = ""
    for attempt in range(1, retries + 1):
        try:
            last_remote = core_payload(fetch_remote_json(url, 1, 0))
            last_mismatches = ["本機與雲端:" + field for field in compare(local_payload, last_remote)]
            if not last_mismatches:
                return last_remote, [], ""
        except Exception as exc:  # noqa: BLE001
            last_error = str(exc)
            last_mismatches = ["雲端讀取失敗"]
        if attempt < retries:
            time.sleep(sleep_seconds)
    return last_remote, last_mismatches, last_error


def core_payload(data):
    latest = data.get("latest_draw") or {}
    freshness = data.get("freshness") or {}
    prediction = data.get("prediction") or {}
    return {
        "generated_at_taiwan": data.get("generated_at_taiwan", ""),
        "latest_draw_date": latest.get("draw_date") or freshness.get("latest_draw_date") or "",
        "latest_numbers": [int(n) for n in latest.get("numbers") or []],
        "target_draw_date": data.get("target_draw_date") or "",
        "target_taiwan_time": freshness.get("target_taiwan_safe_update_time") or data.get("prediction_draw_taiwan_time") or "",
        "top9": [int(n) for n in (prediction.get("top9") or [item.get("number") for item in (data.get("candidates") or [])[:9]])],
        "top15": [int(n) for n in (prediction.get("top15") or [item.get("number") for item in (data.get("candidates") or [])[:15]])[:15]],
        "engine": data.get("industrial_engine_version") or ((data.get("industrial_engine") or {}).get("engine_version")) or "",
    }


def compare(left, right):
    fields = ["latest_draw_date", "latest_numbers", "target_draw_date", "target_taiwan_time", "top9", "top15", "engine"]
    return [field for field in fields if left.get(field) != right.get(field)]


def write_status(payload):
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    SITE_DIR.mkdir(parents=True, exist_ok=True)
    (SITE_DIR / "reports").mkdir(parents=True, exist_ok=True)
    json_text = json.dumps(payload, ensure_ascii=False, indent=2)
    for path in [
        REPORT_DIR / "mobile_sync_status.json",
        SITE_DIR / "mobile_sync_status.json",
        SITE_DIR / "reports" / "mobile_sync_status.json",
    ]:
        path.write_text(json_text, encoding="utf-8")
    lines = [
        "# 天天樂手機同步檢查",
        "",
        f"- 檢查時間：{payload['checked_at_taiwan']} 台灣時間",
        f"- 結論：{payload['status']}",
        f"- 本機最新開獎：{payload['local'].get('latest_draw_date')} / {' '.join(f'{n:02d}' for n in payload['local'].get('latest_numbers', []))}",
        f"- 手機最新開獎：{payload.get('remote', {}).get('latest_draw_date', payload['site'].get('latest_draw_date'))} / {' '.join(f'{n:02d}' for n in payload.get('remote', payload['site']).get('latest_numbers', []))}",
        f"- 下期台灣時間：{payload['local'].get('target_taiwan_time')}",
        f"- 不同步欄位：{', '.join(payload.get('mismatches') or []) or '無'}",
    ]
    markdown = "\n".join(lines) + "\n"
    for path in [
        REPORT_DIR / "mobile_sync_status.md",
        REPORT_DIR / "天天樂手機同步檢查.md",
        SITE_DIR / "mobile_sync_status.md",
        SITE_DIR / "天天樂手機同步檢查.md",
        SITE_DIR / "reports" / "mobile_sync_status.md",
        SITE_DIR / "reports" / "天天樂手機同步檢查.md",
    ]:
        path.write_text(markdown, encoding="utf-8")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--local-only", action="store_true")
    parser.add_argument("--remote", action="store_true")
    parser.add_argument("--retries", type=int, default=8)
    parser.add_argument("--sleep", type=int, default=8)
    args = parser.parse_args()

    local = core_payload(read_json(REPORT_DIR / "latest_analysis.json"))
    site = core_payload(read_json(SITE_DIR / "latest_analysis.json"))
    mismatches = ["本機與手機資料夾:" + field for field in compare(local, site)]
    remote_payload = {}
    remote_error = ""

    need_remote = args.remote or not args.local_only
    if need_remote:
        remote_payload, remote_mismatches, remote_error = fetch_remote_until_synced(
            REMOTE_ANALYSIS_URL,
            local,
            args.retries,
            args.sleep,
        )
        mismatches.extend(remote_mismatches)

    status = "同步" if not mismatches else "不同步"
    payload = {
        "checked_at_taiwan": datetime.now(TAIWAN).isoformat(timespec="seconds"),
        "status": status,
        "local": local,
        "site": site,
        "remote": remote_payload,
        "remote_url": REMOTE_ANALYSIS_URL,
        "remote_error": remote_error,
        "mismatches": mismatches,
    }
    write_status(payload)
    print(json.dumps({"status": status, "mismatches": mismatches}, ensure_ascii=False))
    if mismatches:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
