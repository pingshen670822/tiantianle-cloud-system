import argparse
import json
import subprocess
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parent
REPORTS = ROOT / "reports"
SITE = ROOT / "site"
TAIWAN = ZoneInfo("Asia/Taipei")
CALIFORNIA = ZoneInfo("America/Los_Angeles")


def safe_int(value, default=0):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def expected_latest_draw_date():
    ca_now = datetime.now(CALIFORNIA)
    if (ca_now.hour, ca_now.minute) >= (19, 0):
        return ca_now.date().isoformat()
    return (ca_now.date() - timedelta(days=1)).isoformat()


def later_date(*values):
    cleaned = [str(value) for value in values if value]
    return max(cleaned) if cleaned else ""


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
    site_data_analysis = load_json(SITE / "data" / "latest_analysis.json")
    freshness = analysis.get("freshness") or {}
    site_freshness = site_analysis.get("freshness") or {}
    site_data_freshness = site_data_analysis.get("freshness") or {}
    latest = (analysis.get("latest_draw") or {}).get("draw_date") or freshness.get("latest_draw_date") or ""
    expected_latest = expected_latest_draw_date()
    allowed = later_date(freshness.get("allowed_latest_draw_date"), expected_latest, latest)
    target = analysis.get("target_draw_date") or freshness.get("target_draw_date") or ""
    site_latest = (site_analysis.get("latest_draw") or {}).get("draw_date") or (site_analysis.get("freshness") or {}).get("latest_draw_date") or ""
    site_target = site_analysis.get("target_draw_date") or (site_analysis.get("freshness") or {}).get("target_draw_date") or ""
    site_data_latest = (site_data_analysis.get("latest_draw") or {}).get("draw_date") or site_data_freshness.get("latest_draw_date") or ""
    site_data_target = site_data_analysis.get("target_draw_date") or site_data_freshness.get("target_draw_date") or ""
    prediction = analysis.get("prediction") or {}
    site_prediction = site_analysis.get("prediction") or {}
    site_data_prediction = site_data_analysis.get("prediction") or {}
    ultimate = analysis.get("ultimate_super_single_engine") or {}
    site_ultimate = site_analysis.get("ultimate_super_single_engine") or {}
    site_data_ultimate = site_data_analysis.get("ultimate_super_single_engine") or {}
    strong_packs = analysis.get("strong_packs") or {}
    site_strong_packs = site_analysis.get("strong_packs") or {}
    site_data_strong_packs = site_data_analysis.get("strong_packs") or {}
    strong_single = strong_packs.get("strong_single") or strong_packs.get("single") or {}
    site_strong_single = site_strong_packs.get("strong_single") or site_strong_packs.get("single") or {}
    site_data_strong_single = site_data_strong_packs.get("strong_single") or site_data_strong_packs.get("single") or {}
    strict_gate = analysis.get("strict_prediction_gate") or (analysis.get("industrial_engine") or {}).get("strict_prediction_gate") or {}
    local_core = {
        "generated_at_taiwan": analysis.get("generated_at_taiwan") or "",
        "draw_count": int(analysis.get("draw_count") or 0),
        "latest_draw_date": latest,
        "target_draw_date": target,
        "target_taiwan_time": freshness.get("target_taiwan_safe_update_time") or analysis.get("prediction_draw_taiwan_time") or "",
        "top1": [int(n) for n in (prediction.get("top1") or [])[:1]],
        "top9": [int(n) for n in (prediction.get("top9") or [])],
        "top15": [int(n) for n in (prediction.get("top15") or [])],
        "ultimate_single": safe_int(ultimate.get("selected_number")),
        "ultimate_model": ultimate.get("selected_model") or "",
        "strong_single_numbers": [int(n) for n in (strong_single.get("numbers") or [])],
    }
    site_core = {
        "generated_at_taiwan": site_analysis.get("generated_at_taiwan") or "",
        "draw_count": int(site_analysis.get("draw_count") or 0),
        "latest_draw_date": site_latest,
        "target_draw_date": site_target,
        "target_taiwan_time": site_freshness.get("target_taiwan_safe_update_time") or site_analysis.get("prediction_draw_taiwan_time") or "",
        "top1": [int(n) for n in (site_prediction.get("top1") or [])[:1]],
        "top9": [int(n) for n in (site_prediction.get("top9") or [])],
        "top15": [int(n) for n in (site_prediction.get("top15") or [])],
        "ultimate_single": safe_int(site_ultimate.get("selected_number")),
        "ultimate_model": site_ultimate.get("selected_model") or "",
        "strong_single_numbers": [int(n) for n in (site_strong_single.get("numbers") or [])],
    }
    site_data_core = {
        "generated_at_taiwan": site_data_analysis.get("generated_at_taiwan") or "",
        "draw_count": int(site_data_analysis.get("draw_count") or 0),
        "latest_draw_date": site_data_latest,
        "target_draw_date": site_data_target,
        "target_taiwan_time": site_data_freshness.get("target_taiwan_safe_update_time") or site_data_analysis.get("prediction_draw_taiwan_time") or "",
        "top1": [int(n) for n in (site_data_prediction.get("top1") or [])[:1]],
        "top9": [int(n) for n in (site_data_prediction.get("top9") or [])],
        "top15": [int(n) for n in (site_data_prediction.get("top15") or [])],
        "ultimate_single": safe_int(site_data_ultimate.get("selected_number")),
        "ultimate_model": site_data_ultimate.get("selected_model") or "",
        "strong_single_numbers": [int(n) for n in (site_data_strong_single.get("numbers") or [])],
    }
    sync_fields = [
        "generated_at_taiwan",
        "draw_count",
        "latest_draw_date",
        "target_draw_date",
        "target_taiwan_time",
        "top1",
        "top9",
        "top15",
        "ultimate_single",
        "ultimate_model",
        "strong_single_numbers",
    ]
    sync_mismatches = [field for field in sync_fields if local_core.get(field) != site_core.get(field)]
    sync_mismatches.extend(f"data:{field}" for field in sync_fields if local_core.get(field) != site_data_core.get(field))
    return {
        "generated_at_taiwan": local_core["generated_at_taiwan"],
        "draw_count": local_core["draw_count"],
        "latest_draw_date": latest,
        "expected_latest_draw_date": expected_latest,
        "allowed_latest_draw_date": allowed,
        "target_draw_date": target,
        "target_taiwan_time": local_core["target_taiwan_time"],
        "latest_numbers": (analysis.get("latest_draw") or {}).get("numbers") or [],
        "top1": local_core["top1"],
        "top9": local_core["top9"],
        "top15": local_core["top15"],
        "ultimate_single": local_core["ultimate_single"],
        "ultimate_model": local_core["ultimate_model"],
        "strong_single_numbers": local_core["strong_single_numbers"],
        "strict_status": strict_gate.get("status") or "",
        "strict_no_padding": bool(strict_gate.get("no_padding")),
        "qualified_count": strict_gate.get("qualified_count") or len(strict_gate.get("qualified_numbers") or []),
        "site_latest_draw_date": site_latest,
        "site_target_draw_date": site_target,
        "site_data_latest_draw_date": site_data_latest,
        "site_data_target_draw_date": site_data_target,
        "site_generated_at_taiwan": site_core["generated_at_taiwan"],
        "site_top1": site_core["top1"],
        "site_top9": site_core["top9"],
        "site_ultimate_single": site_core["ultimate_single"],
        "site_strong_single_numbers": site_core["strong_single_numbers"],
        "site_data_generated_at_taiwan": site_data_core["generated_at_taiwan"],
        "site_data_top1": site_data_core["top1"],
        "site_data_top9": site_data_core["top9"],
        "site_data_ultimate_single": site_data_core["ultimate_single"],
        "site_data_strong_single_numbers": site_data_core["strong_single_numbers"],
        "sync_mismatches": sync_mismatches,
        "has_unique_super_single": bool(
            len(local_core["top1"]) == 1
            and local_core["top1"][0] > 0
            and local_core["ultimate_single"] == local_core["top1"][0]
        ),
        "is_stale": bool(latest and allowed and latest < allowed),
        "is_synced": bool(latest and target and not sync_mismatches),
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
        f"- 應更新到期別：{after.get('expected_latest_draw_date') or '-'}",
        f"- 允許最新開獎：{after.get('allowed_latest_draw_date') or '-'}",
        f"- 下期預測：{after.get('target_draw_date') or '-'} / 台灣時間 {after.get('target_taiwan_time') or '-'}",
        f"- 最強獨隻：{numbers_text(after.get('top1')) or '-'} / {'完整' if after.get('has_unique_super_single') else '缺失'}",
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
        steps.append(run_step(f"前九防空修復 {attempt}", [sys.executable, "repair_no_empty_prediction.py"], 180, required=True))
        steps.append(run_step(f"終極獨隻驗證 {attempt}", [sys.executable, "ultimate_single_deep_validation.py"], 180, required=False))
        steps.append(run_step(f"戰報重建 {attempt}", [sys.executable, "pages_build.py"], 240, required=True))
        steps.append(run_step(f"公開檔清理 {attempt}", [sys.executable, "sanitize_public_outputs.py"], 120, required=True))
        steps.append(run_step(f"缺口檢測 {attempt}", [sys.executable, "system_gap_audit.py", "--fail-on-publish-blocking", "--local-only"], 240, required=True))
        steps.append(run_step(f"手機本機同步 {attempt}", [sys.executable, "verify_mobile_sync.py", "--local-only"], 180, required=True))
        steps.append(run_step(f"穩定度監測 {attempt}", [sys.executable, "system_stability_monitor.py"], 180, required=True))
        after_try = snapshot()
        if not after_try["is_stale"] and after_try["is_synced"] and after_try.get("has_unique_super_single"):
            break
        time.sleep(60 if after_try["is_stale"] else 10)

    if args.remote:
        steps.append(run_step("手機雲端遠端同步", [sys.executable, "verify_mobile_sync.py", "--remote", "--retries", "12", "--sleep", "10"], 240, required=True))

    after = snapshot()
    issues = []
    if after["is_stale"]:
        issues.append(f"最新開獎仍落後：目前 {after['latest_draw_date']}，應到 {after['allowed_latest_draw_date']}")
    if not after["is_synced"]:
        mismatch_text = "、".join(after.get("sync_mismatches") or ["未知欄位"])
        issues.append(f"手機資料不同步：本機 {after['latest_draw_date']} / {after['target_draw_date']}，手機 {after['site_latest_draw_date']} / {after['site_target_draw_date']}；欄位 {mismatch_text}")
    if not after.get("has_unique_super_single"):
        issues.append("最強獨隻缺失或與超級獨隻引擎不一致")
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
