import argparse
import json
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parent
REPORTS = ROOT / "reports"
SITE = ROOT / "site"
TAIWAN = ZoneInfo("Asia/Taipei")


def load_json(path, default=None):
    if default is None:
        default = {}
    try:
        if not path.exists():
            return default
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception as exc:
        return {"_read_error": str(exc)}


def numbers_text(values):
    out = []
    for value in values or []:
        try:
            out.append(f"{int(value):02d}")
        except (TypeError, ValueError):
            continue
    return " ".join(out)


def snapshot():
    analysis = load_json(REPORTS / "latest_analysis.json")
    site_analysis = load_json(SITE / "latest_analysis.json")
    freshness = analysis.get("freshness") or {}
    latest = (analysis.get("latest_draw") or {}).get("draw_date") or freshness.get("latest_draw_date") or ""
    allowed = freshness.get("allowed_latest_draw_date") or latest
    target = analysis.get("target_draw_date") or freshness.get("target_draw_date") or ""
    site_latest = (site_analysis.get("latest_draw") or {}).get("draw_date") or (site_analysis.get("freshness") or {}).get("latest_draw_date") or ""
    site_target = site_analysis.get("target_draw_date") or (site_analysis.get("freshness") or {}).get("target_draw_date") or ""
    prediction = analysis.get("prediction") or {}
    strict_gate = analysis.get("strict_prediction_gate") or (analysis.get("industrial_engine") or {}).get("strict_prediction_gate") or {}
    return {
        "generated_at_taiwan": analysis.get("generated_at_taiwan") or "",
        "latest_draw_date": latest,
        "allowed_latest_draw_date": allowed,
        "target_draw_date": target,
        "target_taiwan_time": freshness.get("target_taiwan_safe_update_time") or analysis.get("prediction_draw_taiwan_time") or "",
        "latest_numbers": (analysis.get("latest_draw") or {}).get("numbers") or [],
        "top9": prediction.get("top9") or [],
        "strict_status": strict_gate.get("status") or "",
        "strict_no_padding": bool(strict_gate.get("no_padding")),
        "qualified_count": strict_gate.get("qualified_count") or len(strict_gate.get("qualified_numbers") or []),
        "site_latest_draw_date": site_latest,
        "site_target_draw_date": site_target,
        "is_stale": bool(latest and allowed and latest < allowed),
        "is_synced": bool(latest and target and site_latest == latest and site_target == target),
    }


def run_step(name, command, timeout, required=False):
    started = time.time()
    row = {
        "name": name,
        "command": " ".join(command),
        "ok": False,
        "seconds": 0,
        "returncode": None,
        "tail": "",
    }
    try:
        proc = subprocess.run(
            command,
            cwd=ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=timeout,
        )
        row["returncode"] = proc.returncode
        row["ok"] = proc.returncode == 0 or not required
        row["tail"] = "\n".join((proc.stdout or "").splitlines()[-20:])
    except subprocess.TimeoutExpired as exc:
        row["returncode"] = "timeout"
        row["ok"] = False
        row["tail"] = (exc.stdout or "")[-2000:] if isinstance(exc.stdout, str) else "timeout"
    except Exception as exc:
        row["returncode"] = "error"
        row["ok"] = False
        row["tail"] = str(exc)
    row["seconds"] = round(time.time() - started, 1)
    if required and not row["ok"]:
        row["required_failed"] = True
    return row


def write_status(payload):
    REPORTS.mkdir(parents=True, exist_ok=True)
    SITE.mkdir(parents=True, exist_ok=True)
    (SITE / "reports").mkdir(parents=True, exist_ok=True)
    json_text = json.dumps(payload, ensure_ascii=False, indent=2)
    for path in [
        REPORTS / "cloud_self_repair_status.json",
        SITE / "cloud_self_repair_status.json",
        SITE / "reports" / "cloud_self_repair_status.json",
    ]:
        path.write_text(json_text, encoding="utf-8")

    after = payload.get("after") or {}
    lines = [
        "# 天天樂雲端自我修復狀態",
        "",
        f"- 檢查時間：{payload['checked_at_taiwan']} 台灣時間",
        f"- 狀態：{payload['status']}",
        f"- 最新開獎：{after.get('latest_draw_date') or '-'} / {numbers_text(after.get('latest_numbers')) or '-'}",
        f"- 允許最新開獎：{after.get('allowed_latest_draw_date') or '-'}",
        f"- 下期預測：{after.get('target_draw_date') or '-'} / 台灣時間 {after.get('target_taiwan_time') or '-'}",
        f"- 嚴格門：{after.get('strict_status') or '-'} / 合格 {after.get('qualified_count', 0)} 顆 / 不足不補 {after.get('strict_no_padding')}",
        f"- 手機同步：{'同步' if after.get('is_synced') else '未同步'}",
        "",
        "## 修復步驟",
        "| 步驟 | 結果 | 秒數 | 說明 |",
        "| --- | --- | ---: | --- |",
    ]
    for step in payload.get("steps") or []:
        detail = (step.get("tail") or "").replace("|", "｜").replace("\n", " / ")
        if len(detail) > 220:
            detail = detail[-220:]
        lines.append(f"| {step['name']} | {'通過' if step.get('ok') else '失敗'} | {step.get('seconds', 0)} | {detail or '-'} |")
    if payload.get("issues"):
        lines.extend(["", "## 仍需處理"])
        lines.extend(f"- {item}" for item in payload["issues"])
    else:
        lines.extend(["", "## 結論", "- 雲端自我修復流程已完成，允許發布與手機同步。"])
    markdown = "\n".join(lines) + "\n"
    for path in [
        REPORTS / "cloud_self_repair_status.md",
        REPORTS / "天天樂雲端自我修復狀態.md",
        SITE / "cloud_self_repair_status.md",
        SITE / "天天樂雲端自我修復狀態.md",
        SITE / "reports" / "cloud_self_repair_status.md",
        SITE / "reports" / "天天樂雲端自我修復狀態.md",
    ]:
        path.write_text(markdown, encoding="utf-8")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--retries", type=int, default=2)
    parser.add_argument("--remote", action="store_true")
    args = parser.parse_args()

    before = snapshot()
    steps = []
    required_failed = False
    for attempt in range(1, max(1, args.retries) + 1):
        steps.append(run_step(f"來源快取自救 {attempt}", [sys.executable, "cloud_latest_cache_refresh.py"], 240, required=False))
        steps.append(run_step(f"全歷史重算 {attempt}", [sys.executable, "offline_full_history_recalc.py"], 900, required=True))
        steps.append(run_step(f"戰報重建 {attempt}", [sys.executable, "pages_build.py"], 240, required=False))
        steps.append(run_step(f"公開檔清理 {attempt}", [sys.executable, "sanitize_public_outputs.py"], 120, required=False))
        steps.append(run_step(f"缺口檢測 {attempt}", [sys.executable, "system_gap_audit.py", "--local-only"], 240, required=True))
        steps.append(run_step(f"手機本機同步 {attempt}", [sys.executable, "verify_mobile_sync.py", "--local-only"], 180, required=True))
        steps.append(run_step(f"穩定度監測 {attempt}", [sys.executable, "system_stability_monitor.py"], 180, required=False))
        after_try = snapshot()
        if not after_try["is_stale"] and after_try["is_synced"]:
            break
        time.sleep(10)

    if args.remote:
        steps.append(run_step("手機雲端遠端同步", [sys.executable, "verify_mobile_sync.py", "--remote", "--retries", "6", "--sleep", "10"], 180, required=False))

    after = snapshot()
    issues = []
    if after["is_stale"]:
        issues.append(f"最新開獎仍落後：目前 {after['latest_draw_date']}，應到 {after['allowed_latest_draw_date']}")
    if not after["is_synced"]:
        issues.append(f"手機資料不同步：本機 {after['latest_draw_date']} / {after['target_draw_date']}，手機 {after['site_latest_draw_date']} / {after['site_target_draw_date']}")
    for step in steps:
        if step.get("required_failed"):
            required_failed = True
            issues.append(f"{step['name']} 失敗")

    status = "已修復" if not issues else "需再次自救"
    payload = {
        "checked_at_taiwan": datetime.now(TAIWAN).isoformat(timespec="seconds"),
        "status": status,
        "before": before,
        "after": after,
        "steps": steps,
        "issues": issues,
    }
    write_status(payload)
    print(json.dumps({"status": status, "issues": len(issues), "latest": after.get("latest_draw_date"), "target": after.get("target_draw_date")}, ensure_ascii=False))
    return 2 if (issues or required_failed) else 0


if __name__ == "__main__":
    raise SystemExit(main())
