from __future__ import annotations

import json
import argparse
import re
import ssl
import subprocess
import sys
import time
import urllib.request
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent
REPORTS = ROOT / "reports"
SITE = ROOT / "site"
TAIWAN = timezone(timedelta(hours=8))
REMOTE_BASE = "https://pingshen670822.github.io/tiantianle-cloud-system"

LOCAL_ANALYSIS_PATHS = [
    REPORTS / "latest_analysis.json",
    SITE / "latest_analysis.json",
    SITE / "data" / "latest_analysis.json",
    SITE / "reports" / "latest_analysis.json",
]

REPORT_HTML_PATHS = [
    REPORTS / "latest_battle_report.html",
    REPORTS / "tiantianle_ironlaw_battle_report.html",
    SITE / "reports" / "latest_battle_report.html",
    SITE / "reports" / "complete_report.html",
]

PY_COMPILE_FILES = [
    "offline_full_history_recalc.py",
    "prediction_final_lock_guard.py",
    "tenfold_validation_gate.py",
    "repair_no_empty_prediction.py",
    "super_single_pattern_miner.py",
    "ultimate_single_deep_validation.py",
    "cloud_self_repair.py",
    "pages_build.py",
    "publish_mobile_site_only.py",
    "publish_cloud_main_source.py",
    "system_gap_audit.py",
    "verify_mobile_sync.py",
    "system_stability_monitor.py",
    "tiantianle_ironlaw_report.py",
]


def safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def numbers(values: Any) -> list[int]:
    output: list[int] = []
    for value in values or []:
        number = safe_int(value)
        if 1 <= number <= 39 and number not in output:
            output.append(number)
    return output


def fmt_numbers(values: Any) -> str:
    return " ".join(f"{number:02d}" for number in numbers(values))


def read_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return {}


def fetch_json(path: str) -> dict[str, Any]:
    try:
        url = f"{REMOTE_BASE}/{path}?scan={int(time.time() * 1000)}"
        req = urllib.request.Request(
            url,
            headers={
                "Cache-Control": "no-cache",
                "Pragma": "no-cache",
                "User-Agent": "tiantianle-full-system-integrity-scan",
            },
        )
        raw = urllib.request.urlopen(req, timeout=60, context=ssl._create_unverified_context()).read()
        return json.loads(raw.decode("utf-8-sig"))
    except Exception as exc:
        return {"_error": str(exc)}


def core_payload(payload: dict[str, Any]) -> dict[str, Any]:
    latest = payload.get("latest_draw") or {}
    prediction = payload.get("prediction") or {}
    lock = payload.get("prediction_final_lock") or {}
    gate = payload.get("strict_prediction_gate") or {}
    super_single = payload.get("super_single_decision") or {}
    ultimate = payload.get("ultimate_super_single_engine") or {}
    candidates = payload.get("official_candidates") or payload.get("candidates") or []
    first_candidate = candidates[0] if candidates and isinstance(candidates[0], dict) else {}
    return {
        "generated_at_taiwan": payload.get("generated_at_taiwan") or "",
        "draw_count": safe_int(payload.get("draw_count")),
        "latest_draw_date": latest.get("draw_date") or "",
        "latest_numbers": numbers(latest.get("numbers") or []),
        "target_draw_date": payload.get("target_draw_date") or "",
        "target_taiwan_time": payload.get("prediction_draw_taiwan_time") or "",
        "top1": numbers(prediction.get("top1") or []),
        "top9": numbers(prediction.get("top9") or []),
        "top15": numbers(prediction.get("top15") or []),
        "lock_single": safe_int(lock.get("final_single")),
        "lock_top9": numbers(lock.get("final_top9") or []),
        "gate_numbers": numbers(gate.get("qualified_numbers") or []),
        "super_single": safe_int(super_single.get("number")),
        "ultimate_single": safe_int(ultimate.get("selected_number")),
        "first_candidate": safe_int(first_candidate.get("number")),
        "first_candidate_rank": safe_int(first_candidate.get("rank")),
        "first_candidate_locked": bool(first_candidate.get("final_lock_selected")),
    }


def equal_core(left: dict[str, Any], right: dict[str, Any]) -> list[str]:
    fields = [
        "generated_at_taiwan",
        "draw_count",
        "latest_draw_date",
        "latest_numbers",
        "target_draw_date",
        "target_taiwan_time",
        "top1",
        "top9",
        "top15",
        "lock_single",
        "gate_numbers",
        "super_single",
        "ultimate_single",
        "first_candidate",
    ]
    return [field for field in fields if left.get(field) != right.get(field)]


def fetch_remote_core_until_synced(
    path: str,
    base_core: dict[str, Any],
    retries: int = 12,
    sleep_seconds: int = 5,
) -> tuple[dict[str, Any], dict[str, Any], list[str]]:
    payload: dict[str, Any] = {}
    core: dict[str, Any] = {}
    diff: list[str] = []
    for attempt in range(1, retries + 1):
        payload = fetch_json(path)
        if payload.get("_error"):
            diff = ["_error"]
        else:
            core = core_payload(payload)
            diff = equal_core(base_core, core)
            if not diff:
                return payload, core, []
        if attempt < retries:
            time.sleep(sleep_seconds)
    return payload, core, diff


def html_section(text: str, start_marker: str, end_marker: str) -> str:
    start = text.find(start_marker)
    if start < 0:
        return ""
    end = text.find(end_marker, start + len(start_marker))
    if end < 0:
        end = len(text)
    return text[start:end]


def report_numbers_from_section(section: str) -> list[int]:
    found = []
    for match in re.finditer(r"class=['\"]num['\"][^>]*>\s*(\d{1,2})\s*<|<td[^>]*>\s*(\d{2})\s*</td>", section):
        value = match.group(1) or match.group(2)
        number = safe_int(value)
        if 1 <= number <= 39 and number not in found:
            found.append(number)
    return found


def add_issue(issues: list[dict[str, str]], level: str, area: str, message: str, fix: str = "") -> None:
    issues.append({"level": level, "area": area, "message": message, "fix": fix})


def run_py_compile(issues: list[dict[str, str]]) -> None:
    files = [str(ROOT / name) for name in PY_COMPILE_FILES if (ROOT / name).exists()]
    if not files:
        add_issue(issues, "critical", "程式語法", "找不到可檢查的主程式檔案")
        return
    result = subprocess.run([sys.executable, "-m", "py_compile", *files], cwd=ROOT, capture_output=True, text=True)
    if result.returncode != 0:
        add_issue(issues, "critical", "程式語法", result.stderr.strip() or result.stdout.strip(), "修正語法錯誤")


def workflow_guard_scan(issues: list[dict[str, str]]) -> None:
    required = [
        ROOT / ".github" / "workflows" / "tiantianle-cloud-auto-update.yml",
        ROOT / ".github" / "workflows" / "tiantianle-cloud-self-heal.yml",
    ]
    for path in required:
        if not path.exists():
            add_issue(issues, "critical", "雲端排程", f"缺少工作流：{path.name}")
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        if "prediction_final_lock_guard.py" not in text:
            add_issue(issues, "critical", "雲端排程", f"{path.name} 未接定版鎖守門", "所有會改預測的步驟後都要跑定版鎖")
        if "tenfold_validation_gate.py" not in text:
            add_issue(issues, "critical", "雲端排程", f"{path.name} 未接十重驗證守門", "所有發布前必須跑十重驗證")


def scan(include_remote: bool = True) -> dict[str, Any]:
    issues: list[dict[str, str]] = []
    run_py_compile(issues)
    workflow_guard_scan(issues)

    local_payloads = {path.relative_to(ROOT).as_posix(): read_json(path) for path in LOCAL_ANALYSIS_PATHS}
    local_core = {name: core_payload(payload) for name, payload in local_payloads.items()}
    base_name = "reports/latest_analysis.json"
    base_core = local_core.get(base_name) or {}
    if not base_core:
        add_issue(issues, "critical", "主資料", "reports/latest_analysis.json 讀取失敗")

    for name, core in local_core.items():
        if not core:
            add_issue(issues, "critical", "本機同步", f"{name} 讀取失敗")
            continue
        diff = equal_core(base_core, core)
        if diff:
            add_issue(issues, "critical", "本機同步", f"{name} 與主資料不同步：{', '.join(diff)}", "重新跑定版鎖與戰報重建")

    lock_single = base_core.get("lock_single")
    if lock_single:
        expected = [lock_single]
        checks = {
            "top1": base_core.get("top1"),
            "super_single": [base_core.get("super_single")],
            "ultimate_single": [base_core.get("ultimate_single")],
            "first_candidate": [base_core.get("first_candidate")],
        }
        for field, value in checks.items():
            if numbers(value) != expected:
                add_issue(issues, "critical", "定版鎖", f"{field} 未同步定版獨隻 {lock_single}，目前 {fmt_numbers(value)}", "套用 prediction_final_lock_guard.py")
    else:
        add_issue(issues, "critical", "定版鎖", "缺少定版獨隻")

    base_payload = local_payloads.get(base_name) or {}
    tenfold = base_payload.get("tenfold_validation_gate") or {}
    tenfold_passed = safe_int(tenfold.get("passed_count"))
    tenfold_minimum = safe_int(tenfold.get("minimum_required"), 10)
    if tenfold.get("status") != "通過" or tenfold_passed < tenfold_minimum:
        add_issue(
            issues,
            "critical",
            "十重驗證",
            f"十重驗證未通過或不足：{tenfold_passed}/{tenfold.get('total_count', 0)}，最低 {tenfold_minimum}",
            "先跑 tenfold_validation_gate.py，再重建戰報",
        )
    pack_pool = numbers(tenfold.get("verified_pack_pool") or [])
    prediction = base_payload.get("prediction") or {}
    if pack_pool:
        expected_groups = {
            "top2": pack_pool[:2],
            "top3": pack_pool[:3],
            "top5": pack_pool[:5],
            "top9": pack_pool[:9],
            "top15": pack_pool[:9],
        }
        for field, expected_group in expected_groups.items():
            actual = numbers(prediction.get(field) or [])
            if actual != expected_group:
                add_issue(
                    issues,
                    "critical",
                    "包牌同步",
                    f"{field} 顯示 {fmt_numbers(actual)}，十重驗證池為 {fmt_numbers(expected_group)}",
                    "重新執行 tenfold_validation_gate.py",
                )

    expected_top9 = base_core.get("top9") or []
    for path in REPORT_HTML_PATHS:
        if not path.exists():
            add_issue(issues, "critical", "戰報檔案", f"缺少戰報：{path.relative_to(ROOT)}")
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        for required_text in [
            str(base_core.get("latest_draw_date") or ""),
            str(base_core.get("target_draw_date") or ""),
            f"{lock_single:02d}" if lock_single else "",
        ]:
            if required_text and required_text not in text:
                add_issue(issues, "critical", "戰報內容", f"{path.relative_to(ROOT)} 缺少必要文字：{required_text}")
        candidate_section = html_section(text, "下期研究候選前9名", "生成號碼逐號驗算")
        verify_section = html_section(text, "生成號碼逐號驗算", "強牌組精算")
        candidate_numbers = report_numbers_from_section(candidate_section)
        verify_numbers = report_numbers_from_section(verify_section)
        if expected_top9 and candidate_numbers and candidate_numbers[: len(expected_top9)] != expected_top9:
            add_issue(issues, "critical", "戰報候選表", f"{path.relative_to(ROOT)} 前9表格顯示 {fmt_numbers(candidate_numbers)}，主資料為 {fmt_numbers(expected_top9)}", "報表生成必須使用 prediction.top9")
        if expected_top9 and verify_numbers and verify_numbers[: len(expected_top9)] != expected_top9:
            add_issue(issues, "critical", "逐號驗算表", f"{path.relative_to(ROOT)} 逐號驗算顯示 {fmt_numbers(verify_numbers)}，主資料為 {fmt_numbers(expected_top9)}", "逐號驗算必須使用定版後候選")

    remote_core = {}
    if include_remote:
        remote_payloads: dict[str, dict[str, Any]] = {}
        remote_diffs: dict[str, list[str]] = {}
        for name in [
            "latest_analysis.json",
            "data/latest_analysis.json",
            "reports/latest_analysis.json",
        ]:
            payload, core, diff = fetch_remote_core_until_synced(name, base_core)
            remote_payloads[name] = payload
            remote_diffs[name] = diff
            if core:
                remote_core[name] = core
        for name, payload in remote_payloads.items():
            if payload.get("_error"):
                add_issue(issues, "warning", "雲端讀取", f"{name} 讀取失敗：{payload.get('_error')}", "稍後重試或檢查 Pages 部署")
                continue
            diff = remote_diffs.get(name) or []
            if diff:
                add_issue(issues, "critical", "雲端同步", f"{name} 與本機不同步：{', '.join(diff)}", "重新發布手機雲端版")

    status = "通過" if not [item for item in issues if item["level"] == "critical"] else "需修復"
    payload = {
        "checked_at_taiwan": datetime.now(TAIWAN).isoformat(timespec="seconds"),
        "status": status,
        "critical_count": len([item for item in issues if item["level"] == "critical"]),
        "warning_count": len([item for item in issues if item["level"] == "warning"]),
        "local": base_core,
        "remote": remote_core,
        "issues": issues,
    }
    REPORTS.mkdir(parents=True, exist_ok=True)
    (SITE / "reports").mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, ensure_ascii=False, indent=2)
    for path in [
        REPORTS / "full_system_integrity_scan.json",
        SITE / "full_system_integrity_scan.json",
        SITE / "reports" / "full_system_integrity_scan.json",
    ]:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    md_lines = [
        "# 天天樂全系統掃描",
        "",
        f"- 檢查時間：{payload['checked_at_taiwan']} 台灣時間",
        f"- 結論：{status}",
        f"- 嚴重問題：{payload['critical_count']}",
        f"- 警告：{payload['warning_count']}",
        f"- 最新開獎：{base_core.get('latest_draw_date')} / {fmt_numbers(base_core.get('latest_numbers'))}",
        f"- 預測目標：{base_core.get('target_draw_date')} / {base_core.get('target_taiwan_time')}",
        f"- 定版獨隻：{base_core.get('lock_single')}",
        "",
        "## 問題清單",
    ]
    if issues:
        md_lines.extend(f"- [{item['level']}] {item['area']}：{item['message']}；處理：{item.get('fix') or '已記錄'}" for item in issues)
    else:
        md_lines.append("- 無")
    markdown = "\n".join(md_lines) + "\n"
    for path in [
        REPORTS / "full_system_integrity_scan.md",
        SITE / "full_system_integrity_scan.md",
        SITE / "reports" / "full_system_integrity_scan.md",
    ]:
        path.write_text(markdown, encoding="utf-8")
    return payload


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--local-only", action="store_true")
    args = parser.parse_args()
    result = scan(include_remote=not args.local_only)
    print(json.dumps({"status": result["status"], "critical": result["critical_count"], "warning": result["warning_count"]}, ensure_ascii=False))
    raise SystemExit(2 if result["critical_count"] else 0)
