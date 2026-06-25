import csv
import html
import json
import math
import re
import shutil
import socket
import sqlite3
import ssl
import sys
import time
import urllib.request
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta
from itertools import combinations
from pathlib import Path
from zoneinfo import ZoneInfo

from aerospace_engine import compute_aerospace_assurance
from industrial_engine import compute_industrial_analysis
from tiantianle_core import compute_tiantianle_core_analysis

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
REPORT_DIR = BASE_DIR / "reports"
LOG_DIR = BASE_DIR / "logs"
BACKUP_DIR = BASE_DIR / "backups"
IMPORT_DIR = BASE_DIR / "history_import"
VALIDATION_DIR = BASE_DIR / "validation_sources"
CACHE_DIR = DATA_DIR / "latest_cache"
DB_PATH = DATA_DIR / "california_fantasy5.sqlite"
CSV_PATH = DATA_DIR / "california_fantasy5.csv"
ANALYSIS_JSON = REPORT_DIR / "latest_analysis.json"
BATTLE_MD = REPORT_DIR / "latest_battle_report.md"
BATTLE_HTML = REPORT_DIR / "latest_battle_report.html"
ENHANCED_BATTLE_HTML = REPORT_DIR / "tiantianle_ironlaw_battle_report.html"
DASHBOARD_HTML = REPORT_DIR / "dashboard.html"
FILE_CHECK_MD = REPORT_DIR / "file_integrity_report.md"
HISTORY_REPORT_MD = REPORT_DIR / "history_scraper_report.md"
NETWORK_REPORT_MD = REPORT_DIR / "network_diagnostic_report.md"
IMPORT_REPORT_MD = REPORT_DIR / "csv_import_report.md"
VALIDATION_REPORT_MD = REPORT_DIR / "source_validation_report.md"
HEALTH_REPORT_MD = REPORT_DIR / "system_health_report.md"
DATA_INTEGRITY_REPORT_MD = REPORT_DIR / "data_integrity_report.md"
NUMBER_MAX = 39
DRAW_SIZE = 5
WINDOWS = [5, 10, 20, 50, 100]
PACK_GOALS = {
    "strong_single": 1,
    "two_hit_one": 1,
    "three_hit_two": 2,
    "five_hit_two": 2,
    "nine_hit_three": 3,
    "precision_single": 1,
    "precision_two_hit_one": 1,
    "precision_three_hit_one": 1,
}
CALIFORNIA_TZ = ZoneInfo("America/Los_Angeles")
TAIWAN_TZ = ZoneInfo("Asia/Taipei")
FULL_HISTORY_START_YEAR = 1992
FULL_HISTORY_MIN_ROWS = 3000
ENGINE_VERSION = "tiantianle_ironlaw_industrial_v1"
OFFICIAL_LATEST_URL = "https://www.calottery.com/en/draw-games/fantasy-5"
LATEST_CONSENSUS_MIN_SOURCES = 2
HISTORY_SOURCES = [
    {"name": "Lotto8Latest", "url": "https://www.lotto-8.com/usa/listltoFT5.asp?indexpage=1&orderby=new"},
    {"name": "LottolyzerLatest", "url": "https://en.lottolyzer.com/history/united-states/fantasy-5-california/"},
    {"name": "LotteryNetLatest", "url": "https://www.lottery.net/california/fantasy-5/numbers"},
    {"name": "LotteryUSA", "url": "https://www.lotteryusa.com/california/fantasy-5/year/{year}"},
    {"name": "LotteryNet", "url": "https://www.lottery.net/california/fantasy-5/numbers/{year}"},
    {"name": "LotteryCorner", "url": "https://lotterycorner.com/ca/fantasy-5/{year}"},
    {"name": "LotteryPredictor", "url": "https://lotterypredictor.com/california/fantasy5/results?resultsdate={year}-01-01"},
]


SEED_DRAWS = [
    ("2026-04-01", [7, 12, 16, 20, 32]),
    ("2026-04-02", [7, 21, 25, 31, 37]),
    ("2026-04-03", [14, 15, 23, 30, 37]),
    ("2026-04-04", [1, 4, 9, 18, 32]),
    ("2026-04-05", [4, 13, 16, 19, 37]),
    ("2026-04-06", [4, 5, 20, 21, 39]),
    ("2026-04-07", [4, 8, 23, 28, 29]),
    ("2026-04-08", [6, 7, 8, 27, 32]),
    ("2026-04-09", [1, 5, 17, 23, 32]),
    ("2026-04-10", [11, 12, 28, 29, 31]),
    ("2026-04-11", [10, 16, 18, 27, 28]),
    ("2026-04-12", [14, 16, 20, 22, 38]),
    ("2026-04-13", [3, 13, 20, 29, 37]),
    ("2026-04-14", [2, 8, 23, 33, 34]),
    ("2026-04-15", [21, 28, 30, 32, 39]),
    ("2026-04-16", [8, 10, 21, 22, 38]),
    ("2026-04-17", [9, 10, 23, 24, 25]),
    ("2026-04-18", [1, 10, 13, 14, 31]),
    ("2026-04-19", [13, 16, 23, 33, 36]),
    ("2026-04-20", [7, 17, 36, 38, 39]),
    ("2026-04-21", [2, 11, 12, 35, 39]),
    ("2026-04-22", [9, 14, 19, 30, 33]),
    ("2026-04-23", [15, 17, 30, 34, 35]),
    ("2026-04-24", [3, 6, 18, 29, 34]),
    ("2026-04-25", [1, 5, 6, 20, 34]),
    ("2026-04-26", [9, 11, 18, 33, 37]),
    ("2026-04-27", [2, 4, 5, 10, 31]),
    ("2026-04-28", [14, 19, 33, 37, 38]),
    ("2026-04-29", [1, 5, 20, 21, 39]),
    ("2026-04-30", [10, 14, 21, 33, 39]),
    ("2026-05-01", [8, 19, 28, 35, 36]),
    ("2026-05-02", [11, 16, 18, 20, 23]),
    ("2026-05-03", [5, 10, 14, 16, 22]),
    ("2026-05-04", [9, 13, 17, 19, 31]),
    ("2026-05-05", [8, 13, 18, 32, 36]),
    ("2026-05-06", [2, 5, 13, 16, 36]),
    ("2026-05-07", [3, 8, 12, 26, 29]),
    ("2026-05-08", [5, 9, 12, 14, 15]),
    ("2026-05-09", [4, 11, 12, 28, 35]),
    ("2026-05-10", [9, 11, 17, 25, 29]),
    ("2026-05-11", [14, 17, 19, 29, 38]),
    ("2026-05-12", [8, 17, 25, 31, 33]),
    ("2026-05-13", [4, 19, 23, 24, 32]),
    ("2026-05-14", [1, 8, 31, 32, 38]),
    ("2026-05-15", [6, 10, 26, 29, 33]),
    ("2026-05-16", [10, 12, 21, 22, 30]),
    ("2026-05-17", [3, 12, 15, 29, 33]),
    ("2026-05-18", [11, 16, 30, 31, 33]),
    ("2026-05-19", [9, 13, 15, 18, 19]),
    ("2026-05-20", [2, 10, 16, 20, 39]),
    ("2026-05-21", [1, 6, 11, 34, 39]),
    ("2026-05-22", [6, 14, 16, 28, 36]),
    ("2026-05-23", [7, 26, 33, 35, 37]),
    ("2026-05-24", [2, 4, 11, 12, 24]),
    ("2026-05-25", [2, 14, 34, 35, 39]),
    ("2026-05-26", [2, 6, 19, 22, 27]),
    ("2026-05-27", [7, 15, 16, 22, 30]),
    ("2026-05-28", [2, 12, 20, 30, 34]),
    ("2026-05-29", [2, 5, 27, 35, 36]),
    ("2026-05-30", [1, 15, 21, 23, 24]),
    ("2026-05-31", [4, 9, 15, 20, 30]),
    ("2026-06-01", [6, 14, 23, 28, 37]),
    ("2026-06-02", [5, 11, 19, 25, 31]),
]


def setup_dirs():
    for path in [DATA_DIR, REPORT_DIR, LOG_DIR, BACKUP_DIR, IMPORT_DIR, VALIDATION_DIR, CACHE_DIR]:
        path.mkdir(parents=True, exist_ok=True)


def california_now():
    return datetime.now(CALIFORNIA_TZ)


def taiwan_now():
    return datetime.now(TAIWAN_TZ)


def iso_local(dt):
    return dt.isoformat(timespec="seconds")


def latest_allowed_draw_date():
    ca_now = california_now()
    if (ca_now.hour, ca_now.minute) >= (18, 50):
        return ca_now.date().isoformat()
    return (ca_now.date() - timedelta(days=1)).isoformat()


def draw_date_allowed(draw_date):
    return str(draw_date) <= latest_allowed_draw_date()


def draw_release_times(draw_date):
    ca_day = datetime.strptime(str(draw_date), "%Y-%m-%d").date()
    ca_release = datetime(ca_day.year, ca_day.month, ca_day.day, 18, 50, tzinfo=CALIFORNIA_TZ)
    tw_release = ca_release.astimezone(TAIWAN_TZ)
    return {
        "california_draw_date": ca_day.isoformat(),
        "california_draw_time": "18:30",
        "california_safe_update_time": ca_release.strftime("%Y-%m-%d %H:%M %Z"),
        "taiwan_safe_update_time": tw_release.strftime("%Y-%m-%d %H:%M"),
        "taiwan_safe_update_date": tw_release.date().isoformat(),
        "timezone_rule": "California draw 18:30; safe update 18:50 PT. Taiwan is 09:50 during daylight time and 10:50 during standard time.",
    }


def log(message):
    setup_dirs()
    text = f"{iso_local(taiwan_now())} {message}"
    print(text)
    with (LOG_DIR / "system.log").open("a", encoding="utf-8") as handle:
        handle.write(text + "\n")


def init_db(conn):
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS draws (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            draw_date TEXT NOT NULL UNIQUE,
            n1 INTEGER NOT NULL,
            n2 INTEGER NOT NULL,
            n3 INTEGER NOT NULL,
            n4 INTEGER NOT NULL,
            n5 INTEGER NOT NULL,
            source TEXT,
            created_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS predictions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            based_on_date TEXT NOT NULL UNIQUE,
            target_date TEXT,
            candidates_json TEXT NOT NULL,
            strong_packs_json TEXT NOT NULL,
            created_at TEXT NOT NULL,
            settled_at TEXT,
            actual_date TEXT,
            actual_numbers_json TEXT,
            top5_hits INTEGER,
            top10_hits INTEGER,
            top15_hits INTEGER,
            strong_pack_hits_json TEXT,
            status TEXT NOT NULL DEFAULT 'pending'
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS prediction_snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            based_on_date TEXT NOT NULL,
            target_date TEXT,
            candidates_json TEXT NOT NULL,
            strong_packs_json TEXT NOT NULL,
            created_at TEXT NOT NULL,
            snapshot_reason TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS update_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            started_at TEXT NOT NULL,
            finished_at TEXT,
            status TEXT NOT NULL,
            message TEXT
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS history_year_status (
            year INTEGER PRIMARY KEY,
            status TEXT NOT NULL,
            source TEXT,
            draw_count INTEGER NOT NULL DEFAULT 0,
            inserted_count INTEGER NOT NULL DEFAULT 0,
            attempts INTEGER NOT NULL DEFAULT 0,
            last_error TEXT,
            updated_at TEXT NOT NULL
        )
        """
    )
    conn.commit()


def backup_db():
    if not DB_PATH.exists():
        return
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    target = BACKUP_DIR / f"california_fantasy5_{taiwan_now().strftime('%Y%m%d_%H%M%S')}.sqlite"
    shutil.copy2(DB_PATH, target)
    for old in sorted(BACKUP_DIR.glob("california_fantasy5_*.sqlite"), key=lambda p: p.stat().st_mtime, reverse=True)[1:]:
        old.unlink()


def valid_numbers(numbers):
    return len(numbers) == 5 and len(set(numbers)) == 5 and all(1 <= n <= NUMBER_MAX for n in numbers)


def source_priority(source):
    text = str(source or "").lower()
    if "calottery" in text or "official:" in text:
        return 120
    if "consensus_latest" in text:
        return 108
    if "manual_verified" in text:
        return 96
    if "lotteryusa" in text:
        return 90
    if "auto_csv_import" in text and "user_selected" in text:
        return 85
    if "lottolyzer" in text or "lotto8" in text:
        return 75
    if "lottery.net" in text or "lotterynet_year" in text:
        return 65
    if "lotterynet_latest" in text:
        return 35
    if "cached_latest" in text:
        return 45
    return 50


def source_is_confirmed(source):
    text = str(source or "").lower()
    return any(
        marker in text
        for marker in (
            "calottery",
            "official:",
            "consensus_latest",
            "manual_verified",
            "auto_csv_import:user_selected",
            "auto_csv_import:00_user_selected",
        )
    )


def upsert_draw(conn, draw_date, numbers, source):
    numbers = sorted(int(n) for n in numbers)
    if not draw_date_allowed(draw_date):
        return False
    if not valid_numbers(numbers):
        return False
    existing = conn.execute(
        "SELECT n1,n2,n3,n4,n5,source FROM draws WHERE draw_date=?",
        (draw_date,),
    ).fetchone()
    if existing:
        existing_numbers = tuple(int(x) for x in existing[:5])
        new_numbers = tuple(numbers)
        old_source = existing[5] or ""
        if existing_numbers == new_numbers:
            if source_priority(source) > source_priority(old_source):
                conn.execute(
                    "UPDATE draws SET source=?,created_at=? WHERE draw_date=?",
                    (source, iso_local(taiwan_now()), draw_date),
                )
                return True
            return False
        if source_priority(source) > source_priority(old_source):
            conn.execute(
                """
                UPDATE draws
                SET n1=?,n2=?,n3=?,n4=?,n5=?,source=?,created_at=?
                WHERE draw_date=?
                """,
                (*numbers, source, iso_local(taiwan_now()), draw_date),
            )
            return True
        raise ValueError(
            f"draw_conflict:{draw_date}: existing={existing_numbers} source={old_source} "
            f"new={new_numbers} source={source}"
        )
    conn.execute(
        """
        INSERT OR IGNORE INTO draws(draw_date,n1,n2,n3,n4,n5,source,created_at)
        VALUES(?,?,?,?,?,?,?,?)
        """,
        (draw_date, *numbers, source, iso_local(taiwan_now())),
    )
    return conn.total_changes > 0


def seed_draws(conn):
    return 0


def parse_csv_date(value):
    value = str(value or "").strip()
    for fmt in ["%Y-%m-%d", "%m/%d/%Y", "%B %d, %Y", "%b %d, %Y", "%Y/%m/%d"]:
        try:
            return datetime.strptime(value, fmt).date().isoformat()
        except ValueError:
            pass
    return value if re.match(r"^\d{4}-\d{2}-\d{2}$", value) else ""


def parse_csv_numbers(row):
    values = []
    lower_row = {str(k).strip().lower(): str(v).strip() for k, v in row.items()}
    for key in ["n1", "n2", "n3", "n4", "n5"]:
        if lower_row.get(key):
            values.append(int(lower_row[key]))
    if valid_numbers(values):
        return values
    joined = " ".join(str(value) for value in row.values())
    candidates = [int(x) for x in re.findall(r"\b(?:0?[1-9]|[12]\d|3[0-9])\b", joined)]
    return candidates[-5:] if valid_numbers(candidates[-5:]) else []


def auto_import_csv_files(conn):
    setup_dirs()
    imported = []
    for path in sorted(IMPORT_DIR.glob("*.csv")):
        count = 0
        skipped = 0
        try:
            with path.open("r", encoding="utf-8-sig", newline="") as handle:
                reader = csv.DictReader(handle)
                for row in reader:
                    date_keys = ["draw_date", "date", "draw date", "winning date"]
                    lower_row = {str(k).strip().lower(): str(v).strip() for k, v in row.items()}
                    draw_date = ""
                    for key in date_keys:
                        if lower_row.get(key):
                            draw_date = parse_csv_date(lower_row[key])
                            break
                    numbers = parse_csv_numbers(row)
                    if draw_date and valid_numbers(numbers):
                        before = conn.total_changes
                        upsert_draw(conn, draw_date, numbers, f"auto_csv_import:{path.name}")
                        count += 1 if conn.total_changes > before else 0
                    else:
                        skipped += 1
            imported.append({"file": path.name, "inserted": count, "skipped": skipped, "status": "success"})
        except Exception as exc:
            imported.append({"file": path.name, "inserted": count, "skipped": skipped, "status": "failed", "error": str(exc)})
    lines = [
        "# \u6b77\u53f2 CSV \u5099\u63f4\u532f\u5165\u5831\u544a",
        "",
        f"- \u7522\u751f\u6642\u9593\uff1a{iso_local(taiwan_now())}",
        f"- \u6383\u63cf\u8cc7\u6599\u593e\uff1a{IMPORT_DIR}",
        f"- \u6a94\u6848\u6578\uff1a{len(imported)}",
        "",
        "| \u6a94\u6848 | \u72c0\u614b | \u65b0\u589e | \u8df3\u904e | \u932f\u8aa4 |",
        "| --- | --- | ---: | ---: | --- |",
    ]
    for item in imported:
        lines.append(f"| {item['file']} | {item['status']} | {item['inserted']} | {item['skipped']} | {item.get('error', '-')} |")
    if not imported:
        lines.append("| - | waiting | 0 | 0 | - |")
    IMPORT_REPORT_MD.write_text("\n".join(lines), encoding="utf-8")
    conn.commit()
    return imported


def load_validation_csv(path):
    rows = {}
    skipped = 0
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            lower_row = {str(k).strip().lower(): str(v).strip() for k, v in row.items()}
            draw_date = ""
            for key in ["draw_date", "date", "draw date", "winning date"]:
                if lower_row.get(key):
                    draw_date = parse_csv_date(lower_row[key])
                    break
            numbers = parse_csv_numbers(row)
            if draw_date and valid_numbers(numbers):
                rows[draw_date] = tuple(sorted(numbers))
            else:
                skipped += 1
    return rows, skipped


def validate_sources(conn):
    setup_dirs()
    db_rows = {
        row[0]: tuple(row[1:6])
        for row in conn.execute("SELECT draw_date,n1,n2,n3,n4,n5 FROM draws ORDER BY draw_date").fetchall()
    }
    files = sorted(VALIDATION_DIR.glob("*.csv"))
    source_rows = {}
    file_results = []
    total_records = 0
    total_missing = 0
    total_conflicts = 0
    for path in files:
        try:
            rows, skipped = load_validation_csv(path)
            matches = 0
            missing = []
            conflicts = []
            for draw_date, numbers in rows.items():
                if draw_date not in db_rows:
                    missing.append(draw_date)
                elif db_rows[draw_date] != numbers:
                    conflicts.append({"date": draw_date, "source": numbers, "database": db_rows[draw_date]})
                else:
                    matches += 1
            total_records += len(rows)
            total_missing += len(missing)
            total_conflicts += len(conflicts)
            source_rows[path.name] = rows
            file_results.append({
                "file": path.name,
                "records": len(rows),
                "skipped": skipped,
                "matches": matches,
                "missing": len(missing),
                "conflicts": len(conflicts),
                "sample_missing": missing[:5],
                "sample_conflicts": conflicts[:5],
                "status": "success",
            })
        except Exception as exc:
            file_results.append({"file": path.name, "records": 0, "skipped": 0, "matches": 0, "missing": 0, "conflicts": 1, "sample_missing": [], "sample_conflicts": [{"error": str(exc)}], "status": "failed"})
            total_conflicts += 1

    by_date = defaultdict(list)
    for source_name, rows in source_rows.items():
        for draw_date, numbers in rows.items():
            by_date[draw_date].append((source_name, numbers))
    cross_checked = 0
    consensus = 0
    cross_conflicts = []
    for draw_date, values in sorted(by_date.items()):
        if len(values) < 2:
            continue
        cross_checked += 1
        unique = {numbers for _, numbers in values}
        if len(unique) == 1:
            consensus += 1
        else:
            cross_conflicts.append({"date": draw_date, "values": values})
    status = "verified" if files and total_conflicts == 0 and not cross_conflicts else ("waiting" if not files else "warning")
    confidence = "\u9ad8" if status == "verified" and consensus else ("\u4e2d" if status == "verified" else "\u9700\u4fee\u6b63")
    lines = [
        "# \u96d9\u4f86\u6e90\u4ea4\u53c9\u9a57\u8b49\u5831\u544a",
        "",
        f"- \u7522\u751f\u6642\u9593\uff1a{iso_local(taiwan_now())}",
        f"- \u4e3b\u8cc7\u6599\u5eab\u7b46\u6578\uff1a{len(db_rows)}",
        f"- \u9a57\u8b49\u6a94\u6578\uff1a{len(files)}",
        f"- \u5916\u90e8\u8cc7\u6599\u7b46\u6578\uff1a{total_records}",
        f"- \u4e3b\u5eab\u7f3a\u6f0f\uff1a{total_missing}",
        f"- \u4e3b\u5eab\u885d\u7a81\uff1a{total_conflicts}",
        f"- \u4f86\u6e90\u9593\u91cd\u758a\u6bd4\u5c0d\uff1a{cross_checked}",
        f"- \u4f86\u6e90\u9593\u4e00\u81f4\uff1a{consensus}",
        f"- \u4f86\u6e90\u9593\u885d\u7a81\uff1a{len(cross_conflicts)}",
        f"- \u8a55\u7d1a\uff1a{confidence}",
        "",
        "## \u6a94\u6848\u6bd4\u5c0d",
        "| \u6a94\u6848 | \u72c0\u614b | \u7b46\u6578 | \u5339\u914d | \u4e3b\u5eab\u7f3a\u6f0f | \u4e3b\u5eab\u885d\u7a81 | \u8df3\u904e |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for item in file_results:
        lines.append(f"| {item['file']} | {item['status']} | {item['records']} | {item['matches']} | {item['missing']} | {item['conflicts']} | {item['skipped']} |")
    if not file_results:
        lines.append("| - | waiting | 0 | 0 | 0 | 0 | 0 |")
    lines.extend(["", "## \u885d\u7a81\u6a23\u672c"])
    sample_lines = []
    for item in file_results:
        for conflict in item.get("sample_conflicts", []):
            sample_lines.append(f"- {item['file']} / {conflict}")
    for conflict in cross_conflicts[:10]:
        sample_lines.append(f"- cross_source / {conflict}")
    lines.extend(sample_lines or ["- \u7121"])
    VALIDATION_REPORT_MD.write_text("\n".join(lines), encoding="utf-8")
    return {
        "status": status,
        "confidence": confidence,
        "files": len(files),
        "records": total_records,
        "db_missing": total_missing,
        "db_conflicts": total_conflicts,
        "cross_checked": cross_checked,
        "cross_consensus": consensus,
        "cross_conflicts": len(cross_conflicts),
    }


def http_text(url, retries=1, timeout=6):
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) ca-fantasy5-history-builder/2.0",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9,zh-TW;q=0.8",
            "Cache-Control": "no-cache",
            "Pragma": "no-cache",
        },
    )
    context = ssl._create_unverified_context()
    last_error = None
    for attempt in range(1, retries + 1):
        try:
            with urllib.request.urlopen(request, timeout=timeout, context=context) as response:
                return response.read().decode("utf-8", errors="ignore")
        except Exception as exc:
            last_error = exc
            time.sleep(0.4 * attempt)
    raise last_error


def month_number(value):
    month_map = {
        "january": 1, "jan": 1, "february": 2, "feb": 2, "march": 3, "mar": 3,
        "april": 4, "apr": 4, "may": 5, "june": 6, "jun": 6, "july": 7, "jul": 7,
        "august": 8, "aug": 8, "september": 9, "sep": 9, "sept": 9, "october": 10,
        "oct": 10, "november": 11, "nov": 11, "december": 12, "dec": 12,
    }
    return month_map[value.lower()]


def unique_year_draws(draws):
    clean = {}
    for draw_date, numbers in draws:
        if valid_numbers(numbers):
            clean[draw_date] = sorted(int(n) for n in numbers)
    return sorted(clean.items())


def first_five_numbers(text):
    values = [int(x) for x in re.findall(r"\b(?:0?[1-9]|[12]\d|3[0-9])\b", text)]
    return values[:5]


def parse_year_page(text, year):
    decoded = html.unescape(re.sub(r"<[^>]+>", " ", text))
    decoded = re.sub(r"\s+", " ", decoded)
    month_names = "January|February|March|April|May|June|July|August|September|October|November|December|Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec"
    ordinal = r"(?:st|nd|rd|th)?"
    weekday_pattern = re.compile(
        rf"(Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday),?\s+({month_names})\s+(\d{{1,2}}){ordinal},?\s+({year})(.*?)(?=Est\. jackpot|Prize Payout|Past Result Date|Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday|$)",
        re.IGNORECASE,
    )
    result = []
    lotto8_pattern = re.compile(
        r"(?P<day>\d{2})/(?P<month>\d{2})\s+(?P<yy>\d{2})\([A-Z]{3}\)\s+"
        r"(?P<nums>\d{1,2}\s*,\s*\d{1,2}\s*,\s*\d{1,2}\s*,\s*\d{1,2}\s*,\s*\d{1,2})",
        re.IGNORECASE,
    )
    for match in lotto8_pattern.finditer(decoded):
        yy = int(match.group("yy"))
        full_year = 2000 + yy if yy <= 80 else 1900 + yy
        if full_year != year:
            continue
        draw_date = date(full_year, int(match.group("month")), int(match.group("day"))).isoformat()
        numbers = first_five_numbers(match.group("nums"))
        if valid_numbers(numbers):
            result.append((draw_date, numbers))
    for match in weekday_pattern.finditer(decoded):
        month = month_number(match.group(2))
        draw_date = date(int(match.group(4)), month, int(match.group(3))).isoformat()
        numbers = first_five_numbers(match.group(5))
        if valid_numbers(numbers):
            result.append((draw_date, numbers))

    named_date = re.compile(rf"\b({month_names})\s+(\d{{1,2}}){ordinal},?\s+({year})(.*?)(?=({month_names})\s+\d{{1,2}}{ordinal},?\s+{year}|\d{{4}}-\d{{2}}-\d{{2}}|$)", re.IGNORECASE)
    for match in named_date.finditer(decoded):
        month = month_number(match.group(1))
        draw_date = date(int(match.group(3)), month, int(match.group(2))).isoformat()
        numbers = first_five_numbers(match.group(4))
        if valid_numbers(numbers):
            result.append((draw_date, numbers))

    iso_date = re.compile(rf"\b({year}-\d{{2}}-\d{{2}})\b(.*?)(?=\d{{4}}-\d{{2}}-\d{{2}}|$)", re.IGNORECASE)
    for match in iso_date.finditer(decoded):
        draw_date = match.group(1)
        numbers = first_five_numbers(match.group(2))
        if valid_numbers(numbers):
            result.append((draw_date, numbers))
    return unique_year_draws(result)


def parse_official_calottery_latest(text):
    decoded = html.unescape(re.sub(r"<[^>]+>", " ", text or ""))
    decoded = re.sub(r"\s+", " ", decoded)
    pattern = re.compile(
        r"Winning Numbers:\s*(?:[A-Z]{3}/)?(?P<month>[A-Z]{3,9})\s+"
        r"(?P<day>\d{1,2}),?\s+(?P<year>\d{4})(?P<body>.*?)(?:This Could Be|Detailed Draw Results|LAST DRAW DETAILS|Past Winning Numbers|$)",
        re.IGNORECASE,
    )
    match = pattern.search(decoded)
    if not match:
        return []
    draw_year = int(match.group("year"))
    try:
        draw_date = date(draw_year, month_number(match.group("month")), int(match.group("day"))).isoformat()
    except Exception:
        return []
    numbers = first_five_numbers(match.group("body"))
    if not valid_numbers(numbers):
        return []
    return [(draw_date, numbers)]


def short_source_name(value):
    text = str(value or "").lower()
    if "calottery" in text:
        return "calottery"
    if "lotto-8" in text or "lotto8" in text:
        return "lotto8"
    if "lottolyzer" in text:
        return "lottolyzer"
    if "lotteryusa" in text:
        return "lotteryusa"
    if "lottery.net" in text or "lotterynet" in text:
        return "lotterynet"
    if "lotterycorner" in text:
        return "lotterycorner"
    if "lotterypredictor" in text:
        return "lotterypredictor"
    return re.sub(r"[^a-z0-9_]+", "_", str(value or "source").lower()).strip("_")[:40] or "source"


def apply_consensus_draws(conn, source_draws, channel, min_sources=LATEST_CONSENSUS_MIN_SOURCES):
    grouped = defaultdict(list)
    files = []
    skipped_future = []
    for source_name, draws in source_draws:
        clean_name = short_source_name(source_name)
        files.append({"source": clean_name, "draws_found": len(draws), "latest": draws[-1][0] if draws else ""})
        for draw_date, numbers in draws:
            numbers = tuple(sorted(int(n) for n in numbers))
            if not draw_date_allowed(draw_date):
                skipped_future.append({"draw_date": draw_date, "numbers": list(numbers), "source": clean_name})
                continue
            if not valid_numbers(numbers):
                continue
            grouped[(draw_date, numbers)].append(clean_name)

    by_date = defaultdict(list)
    for (draw_date, numbers), sources in grouped.items():
        by_date[draw_date].append({"numbers": list(numbers), "sources": sorted(set(sources))})

    conflicts = [
        {"draw_date": draw_date, "versions": versions}
        for draw_date, versions in sorted(by_date.items())
        if len(versions) > 1
    ]
    conflict_dates = {item["draw_date"] for item in conflicts}
    skipped_single = []
    skipped_conflict = []
    accepted = []
    applied = 0
    for (draw_date, numbers), sources in sorted(grouped.items()):
        unique_sources = sorted(set(sources))
        if draw_date in conflict_dates:
            skipped_conflict.append({"draw_date": draw_date, "numbers": list(numbers), "sources": unique_sources})
            continue
        if len(unique_sources) < min_sources:
            skipped_single.append({"draw_date": draw_date, "numbers": list(numbers), "sources": unique_sources})
            continue
        source_label = "consensus_latest:{}:{}".format(channel, "+".join(unique_sources[:5]))
        before = conn.total_changes
        upsert_draw(conn, draw_date, numbers, source_label)
        changed = conn.total_changes > before
        applied += 1 if changed else 0
        accepted.append(
            {
                "draw_date": draw_date,
                "numbers": list(numbers),
                "sources": unique_sources,
                "changed": changed,
            }
        )
    conn.commit()
    return {
        "added": applied,
        "accepted": accepted[-12:],
        "accepted_count": len(accepted),
        "files": files,
        "skipped_single_source": skipped_single[-12:],
        "skipped_single_source_count": len(skipped_single),
        "skipped_future": skipped_future[-12:],
        "skipped_future_count": len(skipped_future),
        "skipped_conflict": skipped_conflict[-12:],
        "skipped_conflict_count": len(skipped_conflict),
        "conflicts": conflicts[-12:],
        "conflict_count": len(conflicts),
    }


def fetch_official_latest(conn):
    result = {"status": "not_checked", "added": 0, "draws": [], "errors": []}
    try:
        draws = parse_official_calottery_latest(http_text(OFFICIAL_LATEST_URL, retries=1, timeout=8))
        result["draws"] = [{"draw_date": item[0], "numbers": item[1]} for item in draws]
        if not draws:
            result["status"] = "empty"
            result["errors"].append("official_page_empty_or_unparsed")
            return result
        added = 0
        for draw_date, numbers in draws:
            if not draw_date_allowed(draw_date):
                result["errors"].append(f"official_future_date_skipped:{draw_date}")
                continue
            before = conn.total_changes
            upsert_draw(conn, draw_date, numbers, "official:calottery")
            added += 1 if conn.total_changes > before else 0
        conn.commit()
        result["added"] = added
        result["status"] = "ok"
    except Exception as exc:
        result["status"] = "blocked"
        result["errors"].append(str(exc)[:300])
    return result


def update_history_year_status(conn, year, status, source, draw_count, inserted_count, attempts, last_error):
    conn.execute(
        """
        INSERT INTO history_year_status(year,status,source,draw_count,inserted_count,attempts,last_error,updated_at)
        VALUES(?,?,?,?,?,?,?,?)
        ON CONFLICT(year) DO UPDATE SET
            status=excluded.status,
            source=excluded.source,
            draw_count=excluded.draw_count,
            inserted_count=excluded.inserted_count,
            attempts=history_year_status.attempts + excluded.attempts,
            last_error=excluded.last_error,
            updated_at=excluded.updated_at
        """,
        (year, status, source, draw_count, inserted_count, attempts, (last_error or "")[:500], iso_local(taiwan_now())),
    )


def count_year_draws(conn, year):
    prefix = f"{year}-"
    return conn.execute("SELECT COUNT(*) FROM draws WHERE draw_date LIKE ?", (prefix + "%",)).fetchone()[0]


def fetch_history_year(conn, year):
    errors = []
    attempts = 0
    for source in HISTORY_SOURCES:
        attempts += 1
        url = source["url"].format(year=year)
        try:
            year_draws = parse_year_page(http_text(url), year)
            if not year_draws:
                errors.append(f"{source['name']}: empty")
                continue
            inserted = 0
            for draw_date, numbers in year_draws:
                before = conn.total_changes
                upsert_draw(conn, draw_date, numbers, url)
                inserted += 1 if conn.total_changes > before else 0
            update_history_year_status(conn, year, "success", source["name"], count_year_draws(conn, year), inserted, attempts, "")
            conn.commit()
            return inserted, []
        except Exception as exc:
            errors.append(f"{source['name']}: {exc}")
            time.sleep(0.2)
    update_history_year_status(conn, year, "failed", "", count_year_draws(conn, year), 0, attempts, " | ".join(errors))
    conn.commit()
    return 0, errors


def history_network_preflight(year):
    errors = []
    for source in HISTORY_SOURCES:
        url = source["url"].format(year=year)
        try:
            text = http_text(url)
            if len(text) > 500:
                return True, []
            errors.append(f"{source['name']}: short_response")
        except Exception as exc:
            errors.append(f"{source['name']}: {exc}")
    return False, errors


def run_network_diagnostics():
    setup_dirs()
    checks = []
    domains = [
        ("Lotto8", "www.lotto-8.com"),
        ("Lottolyzer", "en.lottolyzer.com"),
        ("LotteryUSA", "www.lotteryusa.com"),
        ("LotteryNet", "www.lottery.net"),
        ("LotteryCorner", "lotterycorner.com"),
        ("LotteryPredictor", "lotterypredictor.com"),
    ]
    for name, host in domains:
        item = {"name": name, "host": host, "dns": "failed", "tcp443": "failed", "https": "failed", "error": ""}
        try:
            socket.getaddrinfo(host, 443)
            item["dns"] = "ok"
        except Exception as exc:
            item["error"] = f"dns: {exc}"
            checks.append(item)
            continue
        try:
            with socket.create_connection((host, 443), timeout=5):
                item["tcp443"] = "ok"
        except Exception as exc:
            item["error"] = f"tcp443: {exc}"
            checks.append(item)
            continue
        try:
            url = next((source["url"].format(year=california_now().year) for source in HISTORY_SOURCES if host in source["url"]), f"https://{host}/")
            text = http_text(url)
            item["https"] = "ok" if len(text) > 500 else "short_response"
        except Exception as exc:
            item["error"] = f"https: {exc}"
        checks.append(item)
    blocked = [item for item in checks if item["dns"] != "ok" or item["tcp443"] != "ok" or item["https"] != "ok"]
    lines = [
        "# \u7db2\u8def\u8a3a\u65b7\u5831\u544a",
        "",
        f"- \u7522\u751f\u6642\u9593\uff1a{iso_local(taiwan_now())}",
        f"- \u72c0\u614b\uff1a{'ok' if not blocked else 'blocked'}",
        f"- \u7570\u5e38\u4f86\u6e90\uff1a{len(blocked)}",
        "",
        "## \u6aa2\u67e5\u7d50\u679c",
        "| \u4f86\u6e90 | Host | DNS | TCP 443 | HTTPS | \u932f\u8aa4 |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for item in checks:
        lines.append(f"| {item['name']} | {item['host']} | {item['dns']} | {item['tcp443']} | {item['https']} | {item['error'] or '-'} |")
    lines.extend([
        "",
        "## \u6539\u5584\u5efa\u8b70",
        "- \u82e5 DNS \u5931\u6557\uff1a\u6aa2\u67e5\u7db2\u8def DNS \u6216\u6539\u7528\u624b\u6a5f\u71b1\u9ede\u6e2c\u8a66\u3002",
        "- \u82e5 TCP 443 \u5931\u6557\uff1aWindows \u9632\u706b\u7246\u6216\u9632\u6bd2\u8edf\u9ad4\u53ef\u80fd\u64cb\u4f4f Python \u9023\u7dda\u3002",
        "- \u82e5 HTTPS \u5931\u6557\uff1a\u53ef\u80fd\u662f\u6b0a\u9650\u3001\u4ee3\u7406\u4f3a\u670d\u5668\u6216\u7db2\u7ad9\u9632\u722c\u9650\u5236\u3002",
        "- \u7dda\u4e0a\u6293\u4e0d\u5230\u6642\uff1a\u5c07\u6b77\u53f2 CSV \u653e\u5165 history_import \u8cc7\u6599\u593e\uff0c\u4e26\u91cd\u65b0\u57f7\u884c\u4e3b\u7cfb\u7d71\u3002",
    ])
    NETWORK_REPORT_MD.write_text("\n".join(lines), encoding="utf-8")
    return {"status": "ok" if not blocked else "blocked", "blocked_count": len(blocked), "checks": checks}


def fetch_history(conn, full=False):
    current_year = california_now().year
    start_year = FULL_HISTORY_START_YEAR if full else max(FULL_HISTORY_START_YEAR, current_year - 2)
    added = 0
    errors = []
    online_ok, preflight_errors = history_network_preflight(current_year)
    if not online_ok:
        error_text = "network_preflight_failed: " + " | ".join(preflight_errors)
        for year in range(start_year, current_year + 1):
            update_history_year_status(conn, year, "network_blocked", "", count_year_draws(conn, year), 0, len(HISTORY_SOURCES), error_text)
        conn.commit()
        return 0, [error_text[:500]]
    for year in range(start_year, current_year + 1):
        inserted, year_errors = fetch_history_year(conn, year)
        added += inserted
        errors.extend(f"{year} {item}" for item in year_errors)
    conn.commit()
    return added, errors[-12:]


def fetch_latest_results(conn):
    current_year = california_now().year
    urls = [
        "https://www.lotto-8.com/usa/listltoFT5.asp?indexpage=1&orderby=new",
        "https://en.lottolyzer.com/history/united-states/fantasy-5-california/",
        "https://www.lotteryusa.com/california/fantasy-5/",
        "https://www.lottery.net/california/fantasy-5/numbers",
        f"https://www.lottery.net/california/fantasy-5/numbers/{current_year}",
        f"https://www.lotteryusa.com/california/fantasy-5/year/{current_year}",
    ]
    official = fetch_official_latest(conn)
    errors = []
    source_draws = []
    for url in urls:
        try:
            draws = parse_year_page(http_text(url, retries=1, timeout=4), current_year)
            if not draws:
                errors.append(f"{url}: empty")
                continue
            source_draws.append((url, draws))
        except Exception as exc:
            errors.append(f"{url}: {exc}")
    consensus = apply_consensus_draws(conn, source_draws, "network")
    errors.extend(consensus.get("conflicts", []))
    errors.extend(official.get("errors", []))
    conn.commit()
    return {
        "added": int(official.get("added", 0)) + int(consensus.get("added", 0)),
        "checked": len(urls) + 1,
        "official": official,
        "consensus": consensus,
        "errors": errors[-6:],
    }


def import_cached_latest_pages(conn):
    setup_dirs()
    current_year = california_now().year
    source_draws = []
    files = []
    errors = []
    official_cache = {"status": "not_checked", "added": 0, "draws": [], "errors": []}
    for path in sorted(CACHE_DIR.glob("*.html")):
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
            if "calottery" in path.name.lower():
                draws = parse_official_calottery_latest(text)
                official_cache["draws"] = [{"draw_date": item[0], "numbers": item[1]} for item in draws]
                official_cache["status"] = "ok" if draws else "empty"
                inserted = 0
                for draw_date, numbers in draws:
                    before = conn.total_changes
                    upsert_draw(conn, draw_date, numbers, "official:calottery_cache")
                    inserted += 1 if conn.total_changes > before else 0
                official_cache["added"] += inserted
                files.append({"file": path.name, "draws_found": len(draws), "latest": draws[-1][0] if draws else "", "official": True})
                continue
            draws = parse_year_page(text, current_year)
            source_draws.append((path.name, draws))
            files.append({"file": path.name, "draws_found": len(draws), "latest": draws[-1][0] if draws else ""})
        except Exception as exc:
            errors.append(f"{path.name}: {exc}")
    consensus = apply_consensus_draws(conn, source_draws, "cache")
    consensus["added"] += official_cache.get("added", 0)
    consensus["official_cache"] = official_cache
    conn.commit()
    consensus["files"] = files
    consensus["errors"] = errors
    return consensus


def history_scraper_summary(conn):
    rows = conn.execute("SELECT year,status,source,draw_count,inserted_count,attempts,last_error,updated_at FROM history_year_status ORDER BY year").fetchall()
    total = conn.execute("SELECT COUNT(*),MIN(draw_date),MAX(draw_date) FROM draws").fetchone()
    failed = [row for row in rows if row[1] != "success"]
    complete_years = [row for row in rows if row[1] == "success"]
    return {
        "total_rows": total[0] or 0,
        "first_date": total[1],
        "latest_date": total[2],
        "tracked_years": len(rows),
        "successful_years": len(complete_years),
        "failed_years": len(failed),
        "failed_year_list": [row[0] for row in failed],
        "rows": rows,
    }


def render_history_scraper_report(conn):
    summary = history_scraper_summary(conn)
    title = "\u5168\u6b77\u53f2\u8cc7\u6599\u5eab\u6293\u53d6\u5668\u5831\u544a"
    lines = [
        f"# {title}",
        "",
        f"- \u7522\u751f\u6642\u9593\uff1a{iso_local(taiwan_now())}",
        f"- \u7e3d\u7b46\u6578\uff1a{summary['total_rows']}",
        f"- \u8cc7\u6599\u7bc4\u570d\uff1a{summary['first_date']} ~ {summary['latest_date']}",
        f"- \u8ffd\u8e64\u5e74\u4efd\uff1a{summary['tracked_years']}",
        f"- \u6210\u529f\u5e74\u4efd\uff1a{summary['successful_years']}",
        f"- \u5931\u6557\u5e74\u4efd\uff1a{summary['failed_years']}",
        "",
        "## \u9010\u5e74\u72c0\u614b",
        "| \u5e74\u4efd | \u72c0\u614b | \u4f86\u6e90 | \u7b46\u6578 | \u65b0\u589e | \u5617\u8a66 | \u6700\u5f8c\u932f\u8aa4 |",
        "| ---: | --- | --- | ---: | ---: | ---: | --- |",
    ]
    for row in summary["rows"]:
        lines.append(f"| {row[0]} | {row[1]} | {row[2] or '-'} | {row[3]} | {row[4]} | {row[5]} | {(row[6] or '-')[:120]} |")
    if not summary["rows"]:
        lines.append("| - | waiting | - | 0 | 0 | 0 | - |")
    HISTORY_REPORT_MD.write_text("\n".join(lines), encoding="utf-8")
    return summary


def fetch_draws(conn):
    rows = conn.execute("SELECT draw_date,n1,n2,n3,n4,n5,source FROM draws ORDER BY draw_date").fetchall()
    return [
        {"period": index, "draw_date": row[0], "numbers": list(row[1:6]), "source": row[6] or ""}
        for index, row in enumerate(rows, start=1)
    ]


def export_csv(conn):
    rows = conn.execute("SELECT draw_date,n1,n2,n3,n4,n5,source FROM draws ORDER BY draw_date").fetchall()
    with CSV_PATH.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["draw_date", "n1", "n2", "n3", "n4", "n5", "source"])
        writer.writerows(rows)


def frequency(draws):
    counter = Counter()
    for draw in draws:
        counter.update(draw["numbers"])
    return counter


def omission(draws):
    last = {n: None for n in range(1, NUMBER_MAX + 1)}
    for idx, draw in enumerate(draws):
        for n in draw["numbers"]:
            last[n] = idx
    last_idx = len(draws) - 1
    return {n: (last_idx - last[n] if last[n] is not None else len(draws)) for n in range(1, NUMBER_MAX + 1)}


def normalize(values):
    low = min(values.values())
    high = max(values.values())
    if high == low:
        return {k: 0 for k in values}
    return {k: (v - low) / (high - low) for k, v in values.items()}


def tail(number):
    return number % 10


def date_numbers(draw_date):
    dt = datetime.strptime(draw_date, "%Y-%m-%d").date() + timedelta(days=1)
    raw = [dt.year, dt.month, dt.day, int(f"{dt.month}{dt.day:02d}"), dt.month + dt.day, sum(int(ch) for ch in dt.strftime("%Y%m%d"))]
    return {((abs(x) - 1) % NUMBER_MAX) + 1 for x in raw}


def data_freshness(latest_draw_date):
    latest = datetime.strptime(latest_draw_date, "%Y-%m-%d").date()
    ca_now = california_now()
    ca_today = ca_now.date()
    allowed_latest = datetime.strptime(latest_allowed_draw_date(), "%Y-%m-%d").date()
    age_days = (allowed_latest - latest).days
    target = latest + timedelta(days=1)
    latest_release = draw_release_times(latest.isoformat())
    target_release = draw_release_times(target.isoformat())
    draw_result_due = (ca_now.hour, ca_now.minute) >= (18, 50)
    if age_days < 0:
        status = "future_data_error"
    elif age_days == 0:
        status = "ok"
    elif age_days == 1 and not draw_result_due:
        status = "ok_before_draw"
    elif age_days == 1 and draw_result_due:
        status = "late_after_draw"
    else:
        status = "stale"
    return {
        "california_today": ca_today.isoformat(),
        "california_time": ca_now.strftime("%H:%M:%S"),
        "allowed_latest_draw_date": allowed_latest.isoformat(),
        "age_days": age_days,
        "status": status,
        "latest_draw_date": latest.isoformat(),
        "latest_taiwan_safe_update_time": latest_release["taiwan_safe_update_time"],
        "latest_taiwan_safe_update_date": latest_release["taiwan_safe_update_date"],
        "target_draw_date": target.isoformat(),
        "target_taiwan_safe_update_time": target_release["taiwan_safe_update_time"],
        "target_taiwan_safe_update_date": target_release["taiwan_safe_update_date"],
        "timezone_rule": target_release["timezone_rule"],
        "official_prediction_allowed": status in {"ok", "ok_before_draw"},
    }


def pair_score(draws):
    latest = set(draws[-1]["numbers"])
    pairs = Counter()
    for draw in draws[-160:]:
        for pair in combinations(sorted(draw["numbers"]), 2):
            pairs[pair] += 1
    return normalize({n: sum(pairs.get(tuple(sorted((n, a))), 0) for a in latest) for n in range(1, NUMBER_MAX + 1)})


def score_numbers(draws):
    omissions = omission(draws)
    pair = pair_score(draws)
    date_set = date_numbers(draws[-1]["draw_date"])
    scores = defaultdict(float)
    reasons = defaultdict(list)
    for window, weight in [(5, 0.08), (10, 0.11), (20, 0.16), (50, 0.19), (100, 0.14)]:
        subset = draws[-window:] if len(draws) >= window else draws
        freq = frequency(subset)
        norm = normalize({n: freq.get(n, 0) for n in range(1, NUMBER_MAX + 1)})
        for n, value in norm.items():
            scores[n] += value * weight
            if value > 0.75:
                reasons[n].append(f"freq_{window}")
    gap_norm = normalize({n: math.log1p(omissions[n]) for n in range(1, NUMBER_MAX + 1)})
    tail_count = Counter(tail(n) for draw in draws[-60:] for n in draw["numbers"])
    tail_norm = normalize({n: tail_count.get(tail(n), 0) for n in range(1, NUMBER_MAX + 1)})
    latest = set(draws[-1]["numbers"])
    for n in range(1, NUMBER_MAX + 1):
        scores[n] += gap_norm[n] * 0.16
        scores[n] += pair[n] * 0.14
        scores[n] += tail_norm[n] * 0.08
        scores[n] += (0.08 if n in date_set else 0)
        scores[n] += (0.03 if any(abs(n - x) == 1 for x in latest) else 0)
        if gap_norm[n] > 0.72:
            reasons[n].append("\u907a\u6f0f\u88dc\u511f")
        if pair[n] > 0.72:
            reasons[n].append("\u62d6\u724c\u5171\u73fe")
        if tail_norm[n] > 0.72:
            reasons[n].append("\u5c3e\u6578\u724c")
        if n in date_set:
            reasons[n].append("\u65e5\u671f\u724c")
    ranked = sorted(range(1, NUMBER_MAX + 1), key=lambda n: (scores[n], -n), reverse=True)
    high = max(scores.values())
    low = min(scores.values())
    candidates = []
    for n in ranked:
        confidence = 50 if high == low else 50 + (scores[n] - low) / (high - low) * 49
        candidates.append({
            "number": n,
            "score": round(scores[n], 6),
            "confidence_index": round(confidence, 1),
            "omission": omissions[n],
            "reasons": reasons[n] or ["\u7d9c\u5408\u6a21\u578b"],
        })
    return candidates


def theoretical_probability(k, need):
    from math import comb
    total = comb(NUMBER_MAX, DRAW_SIZE)
    hit = sum(comb(k, i) * comb(NUMBER_MAX - k, DRAW_SIZE - i) for i in range(need, min(k, DRAW_SIZE) + 1))
    prob = hit / total
    return {"probability": round(prob, 6), "odds_1_in": round(1 / prob, 2) if prob else None}


def build_packs(candidates):
    nums = [x["number"] for x in candidates]
    return {
        "strong_single": {"name": "\u7368\u652f\u7cbe\u6e961\u4e2d1", "hit_goal": 1, "hit_goal_max": 1, "numbers": nums[:1], "theoretical_probability": theoretical_probability(1, 1)},
        "two_hit_one": {"name": "\u6700\u5f372\u4e2d1~2", "hit_goal": 1, "hit_goal_max": 2, "numbers": nums[:2], "theoretical_probability": theoretical_probability(2, 1)},
        "three_hit_two": {"name": "\u6700\u5f373\u4e2d2~3", "hit_goal": 2, "hit_goal_max": 3, "numbers": nums[:3], "theoretical_probability": theoretical_probability(3, 2)},
        "five_hit_two": {"name": "\u7a69\u5b9a5\u4e2d2~3", "hit_goal": 2, "hit_goal_max": 3, "numbers": nums[:5], "theoretical_probability": theoretical_probability(5, 2)},
        "nine_hit_three": {"name": "\u6700\u5f379\u4e2d3~5", "hit_goal": 3, "hit_goal_max": 5, "numbers": nums[:9], "theoretical_probability": theoretical_probability(9, 3)},
    }


def backtest(draws, rounds=180):
    if len(draws) < 20:
        return {"rounds": 0}
    start = max(10, len(draws) - rounds - 1)
    total = top5 = top10 = top15 = 0
    for idx in range(start, len(draws) - 1):
        train = draws[: idx + 1]
        actual = set(draws[idx + 1]["numbers"])
        ranked = [x["number"] for x in score_numbers(train)]
        top5 += len(set(ranked[:5]) & actual)
        top10 += len(set(ranked[:10]) & actual)
        top15 += len(set(ranked[:15]) & actual)
        total += 1
    return {
        "rounds": total,
        "top5_avg_hits": round(top5 / total, 3) if total else 0,
        "top10_avg_hits": round(top10 / total, 3) if total else 0,
        "top15_avg_hits": round(top15 / total, 3) if total else 0,
        "random_top10_expectation": round(DRAW_SIZE * 10 / NUMBER_MAX, 3),
        "random_top15_expectation": round(DRAW_SIZE * 15 / NUMBER_MAX, 3),
    }


def next_date(draw_date):
    return (datetime.strptime(draw_date, "%Y-%m-%d").date() + timedelta(days=1)).isoformat()


def store_prediction(conn, analysis):
    latest = analysis["latest_draw"]
    target_date = analysis["target_draw_date"]
    official_allowed = analysis.get("official_release_allowed", False)
    candidates_json = json.dumps(analysis["candidates"], ensure_ascii=False)
    strong_packs_json = json.dumps(analysis["strong_packs"], ensure_ascii=False)
    snapshot_reason = "official_pending_prediction" if official_allowed else "watch_only_pending_prediction"
    row = conn.execute("SELECT id,status,target_date FROM predictions WHERE based_on_date=?", (latest["draw_date"],)).fetchone()
    if row and row[1] == "settled":
        conn.execute(
            "INSERT INTO prediction_snapshots(based_on_date,target_date,candidates_json,strong_packs_json,created_at,snapshot_reason) VALUES(?,?,?,?,?,?)",
            (latest["draw_date"], target_date, candidates_json, strong_packs_json, iso_local(taiwan_now()), "rerun_recomputed_after_settlement"),
        )
        conn.commit()
        return "recomputed_snapshot_settled_period"
    if row:
        conn.execute(
            """
            UPDATE predictions
            SET target_date=?, candidates_json=?, strong_packs_json=?, created_at=?, status='pending'
            WHERE id=?
            """,
            (target_date, candidates_json, strong_packs_json, iso_local(taiwan_now()), row[0]),
        )
        status = "recomputed_updated_pending" if official_allowed else "recomputed_updated_watch_only_pending"
    else:
        conn.execute(
            "INSERT INTO predictions(based_on_date,target_date,candidates_json,strong_packs_json,created_at,status) VALUES(?,?,?,?,?,'pending')",
            (latest["draw_date"], target_date, candidates_json, strong_packs_json, iso_local(taiwan_now())),
        )
        status = "recomputed_inserted" if official_allowed else "recomputed_inserted_watch_only_pending"
    conn.execute(
        "INSERT INTO prediction_snapshots(based_on_date,target_date,candidates_json,strong_packs_json,created_at,snapshot_reason) VALUES(?,?,?,?,?,?)",
        (latest["draw_date"], target_date, candidates_json, strong_packs_json, iso_local(taiwan_now()), snapshot_reason),
    )
    conn.commit()
    return status


def backfill_predictions_from_snapshots(conn):
    rows = conn.execute(
        """
        SELECT id,based_on_date,target_date,candidates_json,strong_packs_json,created_at
        FROM prediction_snapshots
        WHERE target_date IS NOT NULL
        ORDER BY target_date,id
        """
    ).fetchall()
    latest_by_target = {}
    for row in rows:
        latest_by_target[row[2]] = row
    inserted = 0
    settled = 0
    skipped = 0
    for row in latest_by_target.values():
        _, based_on_date, target_date, candidates_json, strong_packs_json, created_at = row
        existing = conn.execute(
            "SELECT id,status FROM predictions WHERE based_on_date=? AND target_date=?",
            (based_on_date, target_date),
        ).fetchone()
        if existing:
            skipped += 1
            continue
        actual = conn.execute(
            "SELECT draw_date,n1,n2,n3,n4,n5 FROM draws WHERE draw_date=?",
            (target_date,),
        ).fetchone()
        if not actual:
            conn.execute(
                "INSERT INTO predictions(based_on_date,target_date,candidates_json,strong_packs_json,created_at,status) VALUES(?,?,?,?,?,'pending')",
                (based_on_date, target_date, candidates_json, strong_packs_json, created_at),
            )
            inserted += 1
            continue
        actual_numbers = set(actual[1:6])
        candidates = json.loads(candidates_json or "[]")
        ranked = [item.get("number") for item in candidates if isinstance(item, dict)]
        packs = json.loads(strong_packs_json or "{}")
        pack_hits = {}
        for key, pack in packs.items():
            numbers = pack.get("numbers", [])
            hits = len(set(numbers) & actual_numbers)
            goal = PACK_GOALS.get(key, int(pack.get("hit_goal", 1) or 1))
            pack_hits[key] = {
                "hits": hits,
                "hit_goal": goal,
                "passed": hits >= goal,
                "numbers": numbers,
                "missed_numbers": sorted(set(numbers) - actual_numbers),
            }
        conn.execute(
            """
            INSERT INTO predictions(
                based_on_date,target_date,candidates_json,strong_packs_json,created_at,
                settled_at,actual_date,actual_numbers_json,top5_hits,top10_hits,top15_hits,
                strong_pack_hits_json,status
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?, 'settled')
            """,
            (
                based_on_date,
                target_date,
                candidates_json,
                strong_packs_json,
                created_at,
                iso_local(taiwan_now()),
                actual[0],
                json.dumps(sorted(actual_numbers), ensure_ascii=False),
                len(set(ranked[:5]) & actual_numbers),
                len(set(ranked[:10]) & actual_numbers),
                len(set(ranked[:15]) & actual_numbers),
                json.dumps(pack_hits, ensure_ascii=False),
            ),
        )
        inserted += 1
        settled += 1
    conn.commit()
    return {"inserted": inserted, "settled": settled, "skipped": skipped}


def settle_predictions(conn):
    rows = conn.execute(
        """
        SELECT id,based_on_date,candidates_json,strong_packs_json,status,actual_date,actual_numbers_json
        FROM predictions
        WHERE status IN ('pending','settled')
        """
    ).fetchall()
    settled = 0
    for row in rows:
        actual = conn.execute("SELECT draw_date,n1,n2,n3,n4,n5 FROM draws WHERE draw_date > ? ORDER BY draw_date LIMIT 1", (row[1],)).fetchone()
        if not actual:
            continue
        actual_numbers = set(actual[1:6])
        actual_numbers_json = json.dumps(sorted(actual_numbers), ensure_ascii=False)
        if row[4] == "settled" and row[5] == actual[0] and (row[6] or "") == actual_numbers_json:
            continue
        candidates = json.loads(row[2])
        ranked = [x["number"] for x in candidates]
        packs = json.loads(row[3])
        pack_hits = {}
        for key, pack in packs.items():
            numbers = pack.get("numbers", [])
            hits = len(set(numbers) & actual_numbers)
            goal = PACK_GOALS.get(key, 1)
            pack_hits[key] = {
                "hits": hits,
                "hit_goal": goal,
                "passed": hits >= goal,
                "numbers": numbers,
                "missed_numbers": sorted(set(numbers) - actual_numbers),
            }
        conn.execute(
            """
            UPDATE predictions
            SET settled_at=?, actual_date=?, actual_numbers_json=?, top5_hits=?, top10_hits=?,
                top15_hits=?, strong_pack_hits_json=?, status='settled'
            WHERE id=?
            """,
            (
                iso_local(taiwan_now()),
                actual[0],
                actual_numbers_json,
                len(set(ranked[:5]) & actual_numbers),
                len(set(ranked[:10]) & actual_numbers),
                len(set(ranked[:15]) & actual_numbers),
                json.dumps(pack_hits, ensure_ascii=False),
                row[0],
            ),
        )
        settled += 1
    conn.commit()
    return settled


def _settled_prediction_from_row(row):
    candidates = json.loads(row[4] or "[]")
    actual_numbers = json.loads(row[3] or "[]")
    candidate_numbers = [item.get("number") for item in candidates if isinstance(item, dict)]
    actual_set = set(actual_numbers)
    candidate_review = []
    for idx, item in enumerate(candidates[:15], 1):
        if not isinstance(item, dict):
            continue
        number = item.get("number")
        candidate_review.append(
            {
                "rank": idx,
                "number": number,
                "hit": number in actual_set,
                "score": item.get("score"),
                "reasons": item.get("reasons", []),
            }
        )
    return {
        "based_on_date": row[0],
        "target_date": row[1],
        "actual_date": row[2],
        "actual_period": row[2],
        "actual_numbers": actual_numbers,
        "candidate_numbers": candidate_numbers,
        "candidate_review": candidate_review,
        "strong_pack_hits": json.loads(row[5] or "{}"),
        "top5_hits": row[6] or 0,
        "top10_hits": row[7] or 0,
        "top15_hits": row[8] or 0,
    }


def monthly_prediction_review(conn):
    latest = conn.execute("SELECT MAX(draw_date) FROM draws").fetchone()[0]
    if not latest:
        return {"has_review": False, "month": "", "sample_size": 0}
    month = latest[:7]
    rows = conn.execute(
        """
        SELECT based_on_date,target_date,actual_date,actual_numbers_json,candidates_json,
               strong_pack_hits_json,top5_hits,top10_hits,top15_hits
        FROM predictions
        WHERE status='settled' AND actual_date LIKE ?
        ORDER BY actual_date
        """,
        (month + "%",),
    ).fetchall()
    if not rows:
        return {"has_review": False, "month": month, "sample_size": 0}

    settled_items = [_settled_prediction_from_row(row) for row in rows]
    sample_size = len(settled_items)
    top5_values = [item["top5_hits"] for item in settled_items]
    top10_values = [item["top10_hits"] for item in settled_items]
    top15_values = [item["top15_hits"] for item in settled_items]
    actual_missed_top10 = Counter()
    late_hit_numbers = Counter()
    failed_counts = Counter()
    hit_counts = Counter()
    reason_hits = Counter()
    reason_misses = Counter()
    pack_stats = defaultdict(lambda: {"rounds": 0, "passes": 0, "hits": 0, "zero_hits": 0})
    top10_distribution = Counter(top10_values)

    for settled in settled_items:
        actual_set = set(settled["actual_numbers"])
        top10 = set(settled["candidate_numbers"][:10])
        top15_tail = set(settled["candidate_numbers"][10:15])
        for number in actual_set - top10:
            actual_missed_top10[number] += 1
        for number in actual_set & top15_tail:
            late_hit_numbers[number] += 1
        for number in settled["candidate_numbers"][:15]:
            if not isinstance(number, int):
                continue
            if number in actual_set:
                hit_counts[number] += 1
            else:
                failed_counts[number] += 1
        for candidate in settled["candidate_review"]:
            counter = reason_hits if candidate["hit"] else reason_misses
            counter.update(candidate.get("reasons") or [])
        for key, pack in (settled.get("strong_pack_hits") or {}).items():
            normalized_key = "legacy_three_hit_one" if key == "three_hit_one" else key
            stat = pack_stats[normalized_key]
            hits = int(pack.get("hits", 0) or 0)
            stat["rounds"] += 1
            stat["passes"] += 1 if pack.get("passed") else 0
            stat["hits"] += hits
            stat["zero_hits"] += 1 if hits == 0 else 0

    avg_top5 = round(sum(top5_values) / sample_size, 3)
    avg_top10 = round(sum(top10_values) / sample_size, 3)
    avg_top15 = round(sum(top15_values) / sample_size, 3)
    pack_summary = {}
    for key, stat in pack_stats.items():
        rounds = stat["rounds"] or 1
        pack_summary[key] = {
            "rounds": stat["rounds"],
            "passes": stat["passes"],
            "pass_rate": round(stat["passes"] / rounds, 3),
            "avg_hits": round(stat["hits"] / rounds, 3),
            "zero_hit_rate": round(stat["zero_hits"] / rounds, 3),
            "status": "usable_watch" if stat["passes"] / rounds >= 0.45 else "strict_downshift",
        }

    monthly_failed_numbers = [
        number for number, count in failed_counts.most_common()
        if count >= 3 and hit_counts.get(number, 0) == 0
    ][:12]
    weak_reasons = [
        reason for reason, miss in reason_misses.most_common(10)
        if miss >= max(2, reason_hits.get(reason, 0) * 2)
    ][:6]
    best_plan = {
        "mode": "monthly_precision_guard",
        "summary": "use Top10 as observation pool; strong packs require monthly and walk-forward pass before official release",
        "actions": [
            "strong_single_official_disabled_until_monthly_rate_reaches_20_percent",
            "three_hit_two_official_disabled_until_real_three_hit_two_samples_pass",
            "five_hit_two_and_nine_hit_three_watch_only_until_monthly_and_360_walk_forward_pass",
            "two_hit_one_kept_as_relative_observation_not_official_high_probability",
            "monthly_failed_numbers_soft_penalty_and_late_hit_recovery_promoted",
        ],
        "primary_watch_layer": "Top10",
        "relative_stable_pack": "two_hit_one" if pack_summary.get("two_hit_one", {}).get("pass_rate", 0) >= 0.45 else "none",
        "no_official_high_probability": True,
    }
    return {
        "has_review": True,
        "month": month,
        "sample_size": sample_size,
        "date_range": [settled_items[0]["actual_date"], settled_items[-1]["actual_date"]],
        "avg_top5_hits": avg_top5,
        "avg_top10_hits": avg_top10,
        "avg_top15_hits": avg_top15,
        "top10_distribution": dict(sorted(top10_distribution.items())),
        "pack_summary": pack_summary,
        "monthly_failed_numbers": monthly_failed_numbers,
        "monthly_late_hit_numbers": [{"number": n, "count": c} for n, c in late_hit_numbers.most_common(12)],
        "monthly_missed_actual_numbers": [{"number": n, "count": c} for n, c in actual_missed_top10.most_common(12)],
        "weak_reasons": weak_reasons,
        "best_rolling_plan": best_plan,
    }


def failure_review(conn):
    rows = conn.execute(
        """
        SELECT based_on_date,target_date,actual_date,actual_numbers_json,candidates_json,
               strong_pack_hits_json,top5_hits,top10_hits,top15_hits
        FROM predictions
        WHERE status='settled'
        ORDER BY actual_date DESC
        LIMIT 5
        """
    ).fetchall()
    seen_based_on = {row[0] for row in rows}
    snapshot_rows = conn.execute(
        """
        SELECT based_on_date,target_date,candidates_json,strong_packs_json
        FROM prediction_snapshots
        ORDER BY id DESC
        LIMIT 80
        """
    ).fetchall()
    for snap in snapshot_rows:
        based_on_date = snap[0]
        if based_on_date in seen_based_on:
            continue
        actual = conn.execute(
            "SELECT draw_date,n1,n2,n3,n4,n5 FROM draws WHERE draw_date > ? ORDER BY draw_date LIMIT 1",
            (based_on_date,),
        ).fetchone()
        if not actual:
            continue
        candidates = json.loads(snap[2] or "[]")
        ranked = [item.get("number") for item in candidates if isinstance(item, dict)]
        actual_numbers = set(actual[1:6])
        packs = json.loads(snap[3] or "{}")
        pack_hits = {}
        for key, pack in packs.items():
            numbers = pack.get("numbers", []) if isinstance(pack, dict) else []
            hits = len(set(numbers) & actual_numbers)
            goal = PACK_GOALS.get(key, 1)
            pack_hits[key] = {
                "hits": hits,
                "hit_goal": goal,
                "passed": hits >= goal,
                "numbers": numbers,
                "missed_numbers": sorted(set(numbers) - actual_numbers),
            }
        rows.append(
            (
                based_on_date,
                snap[1],
                actual[0],
                json.dumps(sorted(actual_numbers), ensure_ascii=False),
                snap[2],
                json.dumps(pack_hits, ensure_ascii=False),
                len(set(ranked[:5]) & actual_numbers),
                len(set(ranked[:10]) & actual_numbers),
                len(set(ranked[:15]) & actual_numbers),
            )
        )
        seen_based_on.add(based_on_date)
        if len(rows) >= 8:
            break
    rows = sorted(rows, key=lambda row: row[2] or "", reverse=True)[:5]
    if not rows:
        return {"has_review": False, "severity": "none", "actions": []}

    settled_items = [_settled_prediction_from_row(row) for row in rows]
    sample_size = len(settled_items)
    top5_values = [item["top5_hits"] for item in settled_items]
    top10_values = [item["top10_hits"] for item in settled_items]
    top15_values = [item["top15_hits"] for item in settled_items]
    failed_counts = Counter()
    hit_counts = Counter()
    previous_counts = Counter()
    reason_hits = Counter()
    reason_misses = Counter()
    pack_fail_counts = Counter()

    for settled in settled_items:
        actual_set = set(settled["actual_numbers"])
        previous_counts.update(n for n in settled["candidate_numbers"][:15] if isinstance(n, int))
        hit_counts.update(n for n in settled["candidate_numbers"][:15] if n in actual_set)
        failed_counts.update(n for n in settled["candidate_numbers"][:15] if isinstance(n, int) and n not in actual_set)
        for candidate in settled["candidate_review"]:
            reason_counter = reason_hits if candidate["hit"] else reason_misses
            reason_counter.update(candidate.get("reasons") or [])
        for key, pack in (settled.get("strong_pack_hits") or {}).items():
            if isinstance(pack, dict) and not pack.get("passed"):
                pack_fail_counts[key] += 1
                failed_counts.update(n for n in pack.get("missed_numbers", []) if isinstance(n, int))

    avg_top5 = round(sum(top5_values) / sample_size, 3)
    avg_top10 = round(sum(top10_values) / sample_size, 3)
    avg_top15 = round(sum(top15_values) / sample_size, 3)
    zero_top10_count = sum(1 for value in top10_values if value == 0)
    weak_top10_count = sum(1 for value in top10_values if value <= 1)
    severity = "normal"
    if avg_top10 < 1.2 or zero_top10_count >= 2:
        severity = "critical"
    elif avg_top10 < 2.0 or weak_top10_count >= 2:
        severity = "warning"

    rolling_failed_numbers = [
        number for number, count in failed_counts.most_common()
        if count >= 2 and hit_counts.get(number, 0) == 0
    ][:12]
    rolling_penalty_map = {
        str(number): count for number, count in failed_counts.items()
        if count >= 2 and hit_counts.get(number, 0) == 0
    }
    rolling_previous_numbers = [number for number, _ in previous_counts.most_common(20)]
    weak_reasons = [
        reason for reason, _ in reason_misses.most_common(6)
        if reason_hits.get(reason, 0) == 0 or reason_misses[reason] >= reason_hits.get(reason, 0) * 2
    ]

    monthly_review = monthly_prediction_review(conn)
    actions = [
        u"\u6700\u8fd15\u671f\u5df2\u7d0d\u5165\u6efe\u52d5\u6aa2\u8a0e\uff0cTop10\u5e73\u5747\u547d\u4e2d\u70ba"
        f" {avg_top10}",
        u"\u91cd\u8907\u9810\u6e2c\u4f46\u672a\u547d\u4e2d\u865f\u78bc\u5df2\u81ea\u52d5\u964d\u6b0a\uff1a"
        + fmt_numbers(rolling_failed_numbers[:8]),
    ]
    if monthly_review.get("has_review"):
        actions.append(
            u"\u672c\u6708\u7e3d\u6aa2\u8a0e\u5df2\u7d0d\u5165\uff1aTop10\u5e73\u5747 "
            + str(monthly_review.get("avg_top10_hits"))
            + u"\uff0c\u5f37\u7368\u82075\u4e2d2\u672a\u904e\u5be6\u6230\u9580\u6abb\uff0c\u6539\u4ee5\u89c0\u5bdf\u6c60\u8207\u6708\u5ea6\u964d\u6b0a\u904b\u884c"
        )
    if pack_fail_counts:
        actions.append(
            u"\u5931\u6e96\u5f37\u724c\u7d44\u5408\u5df2\u964d\u4f4e\u6b0a\u91cd\uff1a"
            + ", ".join(f"{key}:{count}" for key, count in pack_fail_counts.most_common(4))
        )
    if weak_reasons:
        actions.append(
            u"\u672a\u547d\u4e2d\u4f86\u6e90\u5df2\u5206\u6d41\u4fee\u6b63\uff1a"
            + " / ".join(weak_reasons[:4])
        )
    if severity in {"critical", "warning"}:
        actions.append(
            u"\u6a21\u578b\u5df2\u964d\u4f4e\u77ed\u671f\u71b1\u865f\u8207\u9023\u838a\u6b0a\u91cd\uff0c\u6539\u63d0\u9ad8\u907a\u6f0f\u3001\u5171\u73fe\u3001\u4e2d\u671f\u7a69\u5b9a\u6b0a\u91cd"
        )

    return {
        "has_review": True,
        "severity": severity,
        "actions": actions,
        "last_settled": settled_items[0],
        "recent_settled": settled_items,
        "monthly_review": monthly_review,
        "rolling_summary": {
            "sample_size": sample_size,
            "avg_top5_hits": avg_top5,
            "avg_top10_hits": avg_top10,
            "avg_top15_hits": avg_top15,
            "zero_top10_count": zero_top10_count,
            "weak_top10_count": weak_top10_count,
            "failed_number_counts": dict(failed_counts.most_common(15)),
            "hit_number_counts": dict(hit_counts.most_common(15)),
            "missed_reason_counts": dict(reason_misses.most_common(12)),
            "hit_reason_counts": dict(reason_hits.most_common(12)),
            "pack_fail_counts": dict(pack_fail_counts.most_common()),
        },
        "rolling_failed_numbers": rolling_failed_numbers,
        "rolling_penalty_map": rolling_penalty_map,
        "rolling_previous_numbers": rolling_previous_numbers,
        "rolling_weak_reasons": weak_reasons,
    }


def analyze(draws, review=None):
    industrial = compute_industrial_analysis(draws, review)
    tiantianle_core = compute_tiantianle_core_analysis(draws, review, industrial=industrial)
    industrial["primary_tiantianle_core"] = {
        "engine_version": tiantianle_core["engine_version"],
        "model_family": tiantianle_core["model_family"],
        "component_names": tiantianle_core["component_names"],
        "weights": tiantianle_core["weights"],
        "two_stage_status": tiantianle_core["two_stage_group_model"].get("status"),
    }
    aerospace = compute_aerospace_assurance(draws, industrial)
    if aerospace["release_assurance"]["status"] == "blocked":
        industrial.setdefault("release_gate", {})["status"] = "aerospace_blocked"
    elif aerospace["release_assurance"]["status"] == "watch_only":
        industrial.setdefault("release_gate", {})["aerospace_status"] = "watch_only"
    candidates = tiantianle_core["candidates"]
    freshness = data_freshness(draws[-1]["draw_date"])
    latest_source = draws[-1].get("source", "")
    latest_source_confirmed = source_is_confirmed(latest_source)
    freshness["latest_source"] = latest_source
    freshness["latest_source_confirmed"] = latest_source_confirmed
    freshness["source_confirmation_status"] = "confirmed" if latest_source_confirmed else "blocked_unconfirmed_latest_source"
    if not latest_source_confirmed:
        freshness["official_prediction_allowed"] = False
    official_release_allowed = (
        freshness.get("official_prediction_allowed", False)
        and industrial.get("release_gate", {}).get("status") == "official"
        and aerospace.get("release_assurance", {}).get("status") == "verified"
    )
    history_status = "complete" if len(draws) >= FULL_HISTORY_MIN_ROWS else ("partial" if len(draws) >= 180 else "seed_only")
    completeness = {
        "status": history_status,
        "required_minimum": FULL_HISTORY_MIN_ROWS,
        "current_count": len(draws),
        "message": "\u6b77\u53f2\u8cc7\u6599\u5df2\u5b8c\u6574\u63a5\u5165\u5929\u5929\u6a02\u5168\u6b77\u53f2\u5eab" if history_status == "complete" else "\u6b77\u53f2\u8cc7\u6599\u6b63\u5728\u589e\u88dc\uff0c\u672c\u6b21\u4ecd\u6703\u4f7f\u7528\u73fe\u6709\u5eab\u9032\u884c\u5b8c\u6574\u6f14\u7b97",
    }
    return {
        "engine_version": ENGINE_VERSION,
        "generated_at_taiwan": iso_local(taiwan_now()),
        "generated_at_california": iso_local(california_now()),
        "game": "\u5929\u5929\u6a02",
        "latest_draw": draws[-1],
        "target_draw_date": next_date(draws[-1]["draw_date"]),
        "freshness": freshness,
        "official_release_allowed": official_release_allowed,
        "draw_count": len(draws),
        "history_completeness": completeness,
        "failure_review": review or {"has_review": False, "severity": "none"},
        "industrial_engine": industrial,
        "primary_tiantianle_core": tiantianle_core,
        "aerospace_assurance": aerospace,
        "candidates": candidates,
        "official_candidates": candidates,
        "strong_packs": tiantianle_core["strong_prediction_packs"],
        "precision_micro_models": tiantianle_core.get("precision_micro_models", industrial.get("precision_micro_models", {})),
        "suggested_sets": tiantianle_core["suggested_sets"],
        "two_stage_group_model": tiantianle_core["two_stage_group_model"],
        "relationships": tiantianle_core["relationships"],
        "backtest": tiantianle_core["backtest"],
        "windows": [{"window": w, "hot": frequency(draws[-w:]).most_common(10)} for w in WINDOWS if len(draws) >= w],
    }


def data_integrity_audit(conn, cached_latest=None, latest_fetch=None, validation=None):
    rows = conn.execute("SELECT draw_date,n1,n2,n3,n4,n5,source FROM draws ORDER BY draw_date").fetchall()
    dates = [row[0] for row in rows]
    invalid_rows = []
    for row in rows:
        numbers = [int(row[i]) for i in range(1, 6)]
        if not valid_numbers(numbers):
            invalid_rows.append({"draw_date": row[0], "numbers": numbers, "source": row[6] or ""})
    duplicate_dates = [draw_date for draw_date, count in Counter(dates).items() if count > 1]
    future_rows = [row for row in rows if str(row[0]) > latest_allowed_draw_date()]
    latest = rows[-1] if rows else None
    latest_source = latest[6] if latest else ""
    latest_confirmed = bool(latest and source_is_confirmed(latest_source))
    recent_unconfirmed = [
        {"draw_date": row[0], "numbers": [int(row[i]) for i in range(1, 6)], "source": row[6] or ""}
        for row in rows[-14:]
        if not source_is_confirmed(row[6] or "")
    ]
    cache_single = int((cached_latest or {}).get("skipped_single_source_count", 0))
    cache_future = int((cached_latest or {}).get("skipped_future_count", 0))
    cache_conflict = int((cached_latest or {}).get("skipped_conflict_count", 0))
    network_consensus = (latest_fetch or {}).get("consensus", {})
    network_single = int(network_consensus.get("skipped_single_source_count", 0)) if isinstance(network_consensus, dict) else 0
    network_future = int(network_consensus.get("skipped_future_count", 0)) if isinstance(network_consensus, dict) else 0
    network_conflict = int(network_consensus.get("skipped_conflict_count", 0)) if isinstance(network_consensus, dict) else 0
    official = (latest_fetch or {}).get("official", {}) if isinstance(latest_fetch, dict) else {}
    status = "ok"
    warnings = []
    if invalid_rows:
        status = "error"
        warnings.append("invalid_number_rows")
    if duplicate_dates:
        status = "error"
        warnings.append("duplicate_draw_dates")
    if future_rows:
        status = "error"
        warnings.append("future_draw_rows_in_database")
    if latest and not latest_confirmed:
        status = "warning" if status == "ok" else status
        warnings.append("latest_draw_source_not_confirmed")
    if recent_unconfirmed:
        warnings.append("recent_rows_with_unconfirmed_source")
    audit = {
        "generated_at": iso_local(taiwan_now()),
        "status": status,
        "warnings": warnings,
        "row_count": len(rows),
        "first_draw_date": dates[0] if dates else "",
        "latest_draw_date": latest[0] if latest else "",
        "latest_numbers": [int(latest[i]) for i in range(1, 6)] if latest else [],
        "latest_source": latest_source or "",
        "latest_source_confirmed": latest_confirmed,
        "allowed_latest_draw_date": latest_allowed_draw_date(),
        "official_source_status": official.get("status", "not_checked") if isinstance(official, dict) else "not_checked",
        "official_source_errors": official.get("errors", []) if isinstance(official, dict) else [],
        "invalid_rows": invalid_rows[:20],
        "duplicate_dates": duplicate_dates[:20],
        "future_rows": [
            {"draw_date": row[0], "numbers": [int(row[i]) for i in range(1, 6)], "source": row[6] or ""}
            for row in future_rows[:20]
        ],
        "recent_unconfirmed": recent_unconfirmed,
        "quarantined_single_source_count": cache_single + network_single,
        "quarantined_future_count": cache_future + network_future,
        "quarantined_conflict_count": cache_conflict + network_conflict,
        "cached_latest": cached_latest or {},
        "latest_fetch": latest_fetch or {},
        "validation_status": (validation or {}).get("status", "not_run"),
        "validation_conflicts": int((validation or {}).get("db_conflicts", 0)) + int((validation or {}).get("cross_conflicts", 0)),
    }
    lines = [
        "# \u8cc7\u6599\u5b8c\u6574\u6027\u7a3d\u6838",
        "",
        f"- \u7522\u751f\u6642\u9593\uff1a{audit['generated_at']}",
        f"- \u72c0\u614b\uff1a{audit['status']}",
        f"- \u7e3d\u7b46\u6578\uff1a{audit['row_count']}",
        f"- \u8cc7\u6599\u7bc4\u570d\uff1a{audit['first_draw_date']} ~ {audit['latest_draw_date']}",
        f"- \u5141\u8a31\u6700\u65b0\u52a0\u5dde\u958b\u734e\u65e5\uff1a{audit['allowed_latest_draw_date']}",
        f"- \u6700\u65b0\u865f\u78bc\uff1a{fmt_numbers(audit['latest_numbers']) if audit['latest_numbers'] else '-'}",
        f"- \u6700\u65b0\u4f86\u6e90\uff1a{audit['latest_source'] or '-'}",
        f"- \u4f86\u6e90\u78ba\u8a8d\uff1a{audit['latest_source_confirmed']}",
        f"- \u5b98\u65b9\u4f86\u6e90\u72c0\u614b\uff1a{audit['official_source_status']}",
        f"- \u55ae\u4e00\u4f86\u6e90\u9694\u96e2\uff1a{audit['quarantined_single_source_count']}",
        f"- \u672a\u4f86\u65e5\u671f\u9694\u96e2\uff1a{audit['quarantined_future_count']}",
        f"- \u885d\u7a81\u8cc7\u6599\u9694\u96e2\uff1a{audit['quarantined_conflict_count']}",
        f"- \u9a57\u8b49\u885d\u7a81\uff1a{audit['validation_conflicts']}",
        "",
        "## \u8b66\u544a",
    ]
    lines.extend([f"- {item}" for item in warnings] or ["- \u7121"])
    lines.extend(["", "## \u8fd1\u671f\u672a\u78ba\u8a8d\u4f86\u6e90"])
    if recent_unconfirmed:
        for item in recent_unconfirmed:
            lines.append(f"- {item['draw_date']} {fmt_numbers(item['numbers'])} / {item['source']}")
    else:
        lines.append("- \u7121")
    lines.extend(["", "## \u975e\u6cd5\u6216\u672a\u4f86\u8cc7\u6599"])
    if invalid_rows or future_rows:
        for item in invalid_rows[:10]:
            lines.append(f"- invalid {item['draw_date']} {fmt_numbers(item['numbers'])} / {item['source']}")
        for item in audit["future_rows"][:10]:
            lines.append(f"- future {item['draw_date']} {fmt_numbers(item['numbers'])} / {item['source']}")
    else:
        lines.append("- \u7121")
    DATA_INTEGRITY_REPORT_MD.write_text("\n".join(lines), encoding="utf-8")
    return audit


def prediction_health(conn, analysis, network_diag=None, latest_fetch=None, cached_latest=None, data_audit=None):
    ca_today = analysis["freshness"]["california_today"]
    data_audit = data_audit or {}
    latest_source_confirmed = bool(data_audit.get("latest_source_confirmed", analysis["freshness"].get("latest_source_confirmed", False)))
    pending_rows = conn.execute(
        "SELECT based_on_date,target_date,created_at FROM predictions WHERE status='pending' ORDER BY target_date"
    ).fetchall()
    stale_pending = [row for row in pending_rows if (row[1] or "") < ca_today]
    current = conn.execute(
        "SELECT based_on_date,target_date,created_at,status FROM predictions WHERE target_date=? ORDER BY id DESC LIMIT 1",
        (analysis["target_draw_date"],),
    ).fetchone()
    network_status = (network_diag or {}).get("status", "unknown")
    latest_fetch_errors = len((latest_fetch or {}).get("errors", []))
    cached_added = (cached_latest or {}).get("added", 0)
    latest_added = (latest_fetch or {}).get("added", 0)
    update_channel_ok = (
        network_status == "ok"
        or (
            network_status == "skipped_fast_update"
            and analysis["freshness"]["status"] in {"ok", "ok_before_draw"}
            and analysis["latest_draw"]["draw_date"] == analysis["freshness"].get("allowed_latest_draw_date")
        )
        or (
            analysis["freshness"]["status"] in {"ok", "ok_before_draw"}
            and (latest_added > 0 or cached_added > 0)
        )
        or (
            analysis["freshness"]["status"] in {"ok", "ok_before_draw"}
            and latest_source_confirmed
        )
    )
    release_gate_status = analysis.get("industrial_engine", {}).get("release_gate", {}).get("status", "")
    prediction_records = conn.execute("SELECT COUNT(*) FROM predictions").fetchone()[0]
    settled_prediction_records = conn.execute("SELECT COUNT(*) FROM predictions WHERE status='settled'").fetchone()[0]
    snapshot_records = conn.execute("SELECT COUNT(*) FROM prediction_snapshots").fetchone()[0]
    completeness_items = [
        ("full_history_database", analysis.get("draw_count", 0) >= FULL_HISTORY_MIN_ROWS, 18),
        ("latest_draw_freshness", analysis["freshness"]["status"] in {"ok", "ok_before_draw", "fresh"}, 14),
        ("taiwan_time_rule", bool(analysis["freshness"].get("target_taiwan_safe_update_time")), 8),
        ("prediction_record_tracking", bool(current) and prediction_records > 0, 16),
        ("settlement_engine", settled_prediction_records > 0 or prediction_records <= 1, 12),
        ("snapshot_audit_trail", snapshot_records > 0, 8),
        ("mobile_cloud_pages", (BASE_DIR / "site" / "index.html").exists() and (BASE_DIR / "site" / "prediction.html").exists() and (BASE_DIR / "site" / "review.html").exists(), 10),
        ("automatic_update_channel", update_channel_ok, 10),
        ("report_generation", ANALYSIS_JSON.exists() and ENHANCED_BATTLE_HTML.exists(), 4),
    ]
    completeness_score = sum(weight for _, passed, weight in completeness_items if passed)
    completeness_score = min(100, completeness_score)
    health = {
        "engine_version": ENGINE_VERSION,
        "generated_at": iso_local(taiwan_now()),
        "latest_draw_date": analysis["latest_draw"]["draw_date"],
        "target_draw_date": analysis["target_draw_date"],
        "freshness": analysis["freshness"],
        "pending_predictions": len(pending_rows),
        "stale_pending_predictions": len(stale_pending),
        "current_target_prediction": {
            "based_on_date": current[0],
            "target_date": current[1],
            "created_at": current[2],
            "status": current[3],
        } if current else None,
        "network_status": network_status,
        "update_channel_ok": update_channel_ok,
        "data_integrity_status": data_audit.get("status", "not_run"),
        "latest_draw_source": data_audit.get("latest_source", analysis["freshness"].get("latest_source", "")),
        "latest_source_confirmed": latest_source_confirmed,
        "quarantined_single_source_count": data_audit.get("quarantined_single_source_count", 0),
        "quarantined_future_count": data_audit.get("quarantined_future_count", 0),
        "quarantined_conflict_count": data_audit.get("quarantined_conflict_count", 0),
        "latest_fetch_added": latest_added,
        "latest_fetch_errors": latest_fetch_errors,
        "cached_latest_added": cached_added,
        "release_gate_status": release_gate_status,
        "prediction_records": prediction_records,
        "settled_prediction_records": settled_prediction_records,
        "snapshot_records": snapshot_records,
        "system_completeness_percent": completeness_score,
        "system_completeness_items": [
            {"item": item, "passed": passed, "weight": weight}
            for item, passed, weight in completeness_items
        ],
    }
    status = "ok"
    warnings = []
    if not analysis.get("official_release_allowed"):
        if release_gate_status == "verified_research_complete":
            warnings.append("official_release_gate_not_promoted_but_research_complete")
        else:
            warnings.append("official_release_gate_watch_only")
    if stale_pending:
        status = "warning"
        warnings.append("pending_predictions_older_than_california_today")
    if not current and analysis.get("official_release_allowed"):
        status = "warning"
        warnings.append("current_target_prediction_not_stored_yet")
    if not update_channel_ok:
        status = "warning"
        warnings.append("automatic_network_update_channel_blocked")
    if data_audit.get("status") == "error":
        status = "warning"
        warnings.append("data_integrity_error_review_required")
    elif data_audit.get("status") == "warning":
        status = "warning"
        warnings.append("data_integrity_warning_review_required")
    if not latest_source_confirmed:
        status = "warning"
        warnings.append("latest_source_not_confirmed")
    health["status"] = status
    health["warnings"] = warnings
    lines = [
        "# \u7cfb\u7d71\u5065\u5eb7\u6aa2\u67e5",
        "",
        f"- \u5f15\u64ce\u7248\u672c\uff1a{health['engine_version']}",
        f"- \u7522\u751f\u6642\u9593\uff1a{health['generated_at']}",
        f"- \u72c0\u614b\uff1a{health['status']}",
        f"- \u6700\u65b0\u958b\u734e\u65e5\uff1a{health['latest_draw_date']}",
        f"- \u9810\u6e2c\u76ee\u6a19\u65e5\uff1a{health['target_draw_date']}",
        f"- \u8cc7\u6599\u65b0\u9bae\u5ea6\uff1a{analysis['freshness']['status']}",
        f"- \u8cc7\u6599\u65b0\u9bae\u5ea6\u5141\u8a31\uff1a{analysis['freshness'].get('official_prediction_allowed')}",
        f"- \u6700\u7d42\u6b63\u5f0f\u767c\u5e03\u5141\u8a31\uff1a{analysis.get('official_release_allowed')}",
        f"- \u5f85\u7d50\u7b97\u9810\u6e2c\uff1a{health['pending_predictions']}",
        f"- \u904e\u671f\u5f85\u7d50\u7b97\u9810\u6e2c\uff1a{health['stale_pending_predictions']}",
        f"- \u6b63\u5f0f\u9810\u6e2c\u7d00\u9304\uff1a{health['prediction_records']}",
        f"- \u5df2\u7d50\u7b97\u9810\u6e2c\u7d00\u9304\uff1a{health['settled_prediction_records']}",
        f"- \u9810\u6e2c\u5feb\u7167\u7d00\u9304\uff1a{health['snapshot_records']}",
        f"- \u81ea\u52d5\u7db2\u8def\u66f4\u65b0\uff1a{health['network_status']}",
        f"- \u66f4\u65b0\u901a\u9053\u53ef\u7528\uff1a{health['update_channel_ok']}",
        f"- \u8cc7\u6599\u5b8c\u6574\u6027\uff1a{health['data_integrity_status']}",
        f"- \u6700\u65b0\u8cc7\u6599\u4f86\u6e90\uff1a{health['latest_draw_source'] or '-'}",
        f"- \u6700\u65b0\u4f86\u6e90\u78ba\u8a8d\uff1a{health['latest_source_confirmed']}",
        f"- \u55ae\u4e00\u4f86\u6e90\u9694\u96e2\uff1a{health['quarantined_single_source_count']}",
        f"- \u672a\u4f86\u65e5\u671f\u9694\u96e2\uff1a{health['quarantined_future_count']}",
        f"- \u885d\u7a81\u8cc7\u6599\u9694\u96e2\uff1a{health['quarantined_conflict_count']}",
        f"- \u767c\u5e03\u95dc\u5361\uff1a{health['release_gate_status']}",
        f"- \u4e3b\u7cfb\u7d71\u5b8c\u6574\u5ea6\uff1a{health['system_completeness_percent']}%",
        f"- \u672c\u6b21\u7dda\u4e0a\u65b0\u589e\uff1a{health['latest_fetch_added']}",
        f"- \u672c\u6b21\u5feb\u53d6\u65b0\u589e\uff1a{health['cached_latest_added']}",
        "",
        "## \u8b66\u544a",
    ]
    lines.extend([f"- {item}" for item in warnings] or ["- \u7121"])
    lines.extend(["", "## \u4e3b\u7cfb\u7d71\u5b8c\u6574\u5ea6\u9805\u76ee"])
    for item in health["system_completeness_items"]:
        mark = "\u901a\u904e" if item["passed"] else "\u672a\u901a\u904e"
        lines.append(f"- {item['item']}：{mark} / {item['weight']}")
    lines.extend([
        "",
        "## \u7cbe\u6e96\u5ea6\u72c0\u614b",
        "- \u767c\u5e03\u95dc\u5361\u6703\u5206\u70ba official\u3001verified_research_complete\u3001watch_only\uff1bofficial \u624d\u662f\u6b63\u5f0f\u9ad8\u4fe1\u5fc3\u767c\u5e03\u3002",
        "- verified_research_complete \u4ee3\u8868\u8cc7\u6599\u3001\u6210\u719f\u5ea6\u3001\u4e3b\u76ee\u6a19\u7814\u7a76\u6b63\u908a\u969b\u90fd\u5df2\u5b8c\u6210\uff0c\u4f46\u4ecd\u4e0d\u4fdd\u8b49\u958b\u51fa\u3002",
    ])
    HEALTH_REPORT_MD.write_text("\n".join(lines), encoding="utf-8")
    return health


def latest_settled(conn):
    row = conn.execute(
        "SELECT based_on_date,actual_date,actual_numbers_json,candidates_json,strong_packs_json,top5_hits,top10_hits,top15_hits FROM predictions WHERE status='settled' ORDER BY actual_date DESC LIMIT 1"
    ).fetchone()
    if not row:
        return {}
    return {
        "based_on_date": row[0],
        "actual_date": row[1],
        "actual_numbers": json.loads(row[2] or "[]"),
        "candidates": json.loads(row[3] or "[]"),
        "strong_packs": json.loads(row[4] or "{}"),
        "top5_hits": row[5],
        "top10_hits": row[6],
        "top15_hits": row[7],
    }


def red_circle(number):
    return f'<span style="display:inline-flex;align-items:center;justify-content:center;width:30px;height:30px;border:2px solid #dc2626;border-radius:50%;color:#dc2626;font-weight:800;margin:0 2px;">{number:02d}</span>'


def hit_analysis(settled):
    if not settled:
        return []
    actual = set(settled["actual_numbers"])
    rank = {item["number"]: idx + 1 for idx, item in enumerate(settled["candidates"])}
    reasons = {item["number"]: item.get("reasons", []) for item in settled["candidates"]}
    rows = []
    for n in sorted(actual):
        sources = []
        if n in rank:
            if rank[n] <= 5:
                sources.append("Top5")
            if rank[n] <= 10:
                sources.append("Top10")
            if rank[n] <= 15:
                sources.append("Top15")
            sources.extend(reasons.get(n, []))
        for key, pack in settled["strong_packs"].items():
            if n in pack.get("numbers", []):
                sources.append(pack.get("name", key))
        rows.append({"number": n, "hit": bool(sources), "rank": rank.get(n), "sources": sources or ["\u672a\u9032\u5165\u6b63\u5f0f\u4e3b\u9078"]})
    return rows


def render_reports(conn, analysis):
    settled = latest_settled(conn)
    hit_rows = hit_analysis(settled)
    lines = [
        "# \u5929\u5929\u6a02\u9810\u6e2c\u6230\u5831",
        "",
        f"- \u53f0\u7063\u7522\u751f\u6642\u9593\uff1a{analysis['generated_at_taiwan']}",
        f"- \u5f15\u64ce\u7248\u672c\uff1a{analysis.get('engine_version', '-')}",
        f"- \u5de5\u696d\u5f15\u64ce\uff1a{analysis.get('industrial_engine', {}).get('engine_version', '-')}",
        f"- \u767c\u5e03\u95dc\u5361\uff1a{analysis.get('industrial_engine', {}).get('release_gate', {}).get('status', '-')}",
        f"- \u822a\u592a\u4fdd\u8b49\uff1a{analysis.get('aerospace_assurance', {}).get('release_assurance', {}).get('status', '-')}",
        f"- \u7576\u5730\u7522\u751f\u6642\u9593\uff1a{analysis['generated_at_california']}",
        f"- \u7576\u5730\u65e5\u671f\uff1a{analysis['freshness']['california_today']}",
        f"- \u7576\u5730\u6642\u9593\uff1a{analysis['freshness'].get('california_time', '-')}",
        f"- \u6700\u65b0\u958b\u734e\u53f0\u7063\u53ef\u66f4\u65b0\u6642\u9593\uff1a{analysis['freshness'].get('latest_taiwan_safe_update_time', '-')} / {fmt_numbers(analysis['latest_draw']['numbers'])}",
        f"- \u6700\u65b0\u958b\u734e\u4f86\u6e90\uff1a{analysis['freshness'].get('latest_source', '-') or '-'}",
        f"- \u6700\u65b0\u4f86\u6e90\u78ba\u8a8d\uff1a{analysis['freshness'].get('latest_source_confirmed')}",
        f"- \u9810\u6e2c\u958b\u734e\u53f0\u7063\u6642\u9593\uff1a{analysis['freshness'].get('target_taiwan_safe_update_time', '-')}",
        f"- \u8cc7\u6599\u72c0\u614b\uff1a{analysis['freshness']['status']} / \u843d\u5f8c {analysis['freshness']['age_days']} \u5929",
        f"- \u8cc7\u6599\u65b0\u9bae\u5ea6\u5141\u8a31\uff1a{analysis['freshness'].get('official_prediction_allowed')}",
        f"- \u6700\u7d42\u6b63\u5f0f\u767c\u5e03\u5141\u8a31\uff1a{analysis.get('official_release_allowed')}",
        f"- \u8cc7\u6599\u7b46\u6578\uff1a{analysis['draw_count']}",
        f"- \u6b77\u53f2\u5b8c\u6574\u5ea6\uff1a{analysis['history_completeness']['status']} / {analysis['history_completeness']['current_count']} \u7b46",
        f"- \u56de\u6e2c Top10\uff1a{analysis['backtest'].get('top10_avg_hits')}",
        "",
        "## \u5f37\u724c\u7d44",
    ]
    for pack in analysis["strong_packs"].values():
        prob = pack["theoretical_probability"]
        lines.append(f"- {pack['name']}\uff1a{fmt_numbers(pack['numbers'])} / \u7406\u8ad6\u6a5f\u7387 {prob['probability']} / 1\u4e2d{prob['odds_1_in']}")
    if settled:
        lines.extend([
            "",
            "## \u4e0a\u671f\u6b63\u5f0f\u9810\u6e2c\u547d\u4e2d\u89e3\u6790",
            f"- \u9810\u6e2c\u4f9d\u64da\uff1a{settled['based_on_date']}",
            f"- \u5be6\u969b\u958b\u51fa\uff1a{settled['actual_date']}",
            f"- Top5 / Top10 / Top15\uff1a{settled['top5_hits']} / {settled['top10_hits']} / {settled['top15_hits']}",
            "| \u865f\u78bc | \u547d\u4e2d | \u6392\u540d | \u4f86\u6e90\u95dc\u806f |",
            "| ---: | --- | ---: | --- |",
        ])
        for row in hit_rows:
            n = red_circle(row["number"]) if row["hit"] else f"{row['number']:02d}"
            lines.append(f"| {n} | {'\u662f' if row['hit'] else '\u5426'} | {row['rank'] or '-'} | {'\u3001'.join(row['sources'])} |")
    lines.extend(["", "## \u5019\u9078 Top 15", "| \u6392\u540d | \u865f\u78bc | \u6307\u6578 | \u907a\u6f0f | \u7406\u7531 |", "| ---: | ---: | ---: | ---: | --- |"])
    for idx, item in enumerate(analysis["candidates"][:15], 1):
        lines.append(f"| {idx} | {item['number']:02d} | {item['confidence_index']} | {item['omission']} | {'\u3001'.join(item['reasons'])} |")
    md = "\n".join(lines)
    BATTLE_MD.write_text(md, encoding="utf-8")
    html_report = build_enhanced_battle_html(analysis, settled, hit_rows, md)
    BATTLE_HTML.write_text(html_report, encoding="utf-8")
    DASHBOARD_HTML.write_text(html_report, encoding="utf-8")
    ENHANCED_BATTLE_HTML.write_text(html_report, encoding="utf-8")


def chip(number, hot=False):
    color = "#b91c1c" if hot else "#111827"
    bg = "#fff1f2" if hot else "#f8fafc"
    return f'<span class="ball" style="border-color:{color};color:{color};background:{bg}">{int(number):02d}</span>'


def balls(numbers, hot_set=None):
    hot_set = set(hot_set or [])
    return "".join(chip(number, int(number) in hot_set) for number in numbers)


def release_badge(analysis):
    status = analysis.get("industrial_engine", {}).get("release_gate", {}).get("status")
    allowed = analysis.get("official_release_allowed")
    if allowed or status == "official":
        text = "\u6b63\u5f0f\u767c\u5e03"
        cls = "ok"
    elif status == "verified_research_complete":
        text = "\u5be6\u6230\u7814\u7a76\u5b8c\u6574\u7248"
        cls = "ok"
    else:
        text = "\u89c0\u5bdf\u724c"
        cls = "warn"
    return f'<span class="badge {cls}">{text}</span>'


def build_enhanced_battle_html(analysis, settled, hit_rows, markdown_text):
    latest = analysis["latest_draw"]
    industrial = analysis.get("industrial_engine", {})
    release = industrial.get("release_gate", {})
    aerospace = analysis.get("aerospace_assurance", {}).get("release_assurance", {})
    top10 = [item["number"] for item in analysis["candidates"][:10]]
    top15_rows = []
    for index, item in enumerate(analysis["candidates"][:15], 1):
        top15_rows.append(
            "<tr>"
            f"<td>{index}</td><td>{chip(item['number'], index <= 10)}</td>"
            f"<td>{item.get('confidence_index', '')}</td><td>{item.get('omission', '')}</td>"
            f"<td>{html.escape('\u3001'.join(item.get('reasons', [])))}</td>"
            "</tr>"
        )
    pack_cards = []
    for pack in analysis.get("strong_packs", {}).values():
        prob = pack.get("theoretical_probability", {})
        pack_cards.append(
            '<div class="mini">'
            f"<b>{html.escape(pack.get('name', ''))}</b>"
            f'<div class="balls">{balls(pack.get("numbers", []))}</div>'
            f"<small>\u76ee\u6a19 {pack.get('hit_goal', '-')} \u4e2d\uff0c\u7406\u8ad6\u6a5f\u7387 {prob.get('probability', '-')} / 1\u4e2d{prob.get('odds_1_in', '-')}</small>"
            "</div>"
        )
    hit_table = ""
    if settled:
        rows = []
        for row in hit_rows:
            rows.append(
                "<tr>"
                f"<td>{chip(row['number'], row['hit'])}</td>"
                f"<td>{'\u662f' if row['hit'] else '\u5426'}</td>"
                f"<td>{row['rank'] or '-'}</td>"
                f"<td>{html.escape('\u3001'.join(row['sources']))}</td>"
                "</tr>"
            )
        hit_table = (
            '<section><div class="section-title">\u4e0a\u671f\u547d\u4e2d\u6aa2\u8a0e</div>'
            f'<p>\u9810\u6e2c\u4f9d\u64da\uff1a{settled["based_on_date"]} / \u5be6\u969b\u958b\u51fa\uff1a{settled["actual_date"]} {balls(settled["actual_numbers"], settled["actual_numbers"])}</p>'
            f'<p>Top5 / Top10 / Top15\uff1a<b>{settled["top5_hits"]}</b> / <b>{settled["top10_hits"]}</b> / <b>{settled["top15_hits"]}</b></p>'
            '<table><thead><tr><th>\u865f\u78bc</th><th>\u547d\u4e2d</th><th>\u6392\u540d</th><th>\u4f86\u6e90</th></tr></thead><tbody>'
            + "".join(rows)
            + "</tbody></table></section>"
        )
    warnings = []
    if not analysis.get("official_release_allowed"):
        if release.get("status") == "verified_research_complete":
            warnings.append("\u5df2\u9054\u5be6\u6230\u7814\u7a76\u5b8c\u6574\u7248\uff0c\u4f46\u672a\u9054\u6b63\u5f0f\u9ad8\u4fe1\u5fc3\u4fdd\u8b49\u9580\u6abb\u3002")
        else:
            warnings.append("\u5de5\u696d\u767c\u5e03\u95dc\u5361\u672a\u901a\u904e\uff0c\u672c\u671f\u50c5\u5217\u89c0\u5bdf\u724c\u3002")
    if analysis.get("freshness", {}).get("status") not in {"ok", "ok_before_draw"}:
        warnings.append("\u8cc7\u6599\u65b0\u9bae\u5ea6\u4e0d\u8db3\uff0c\u4e0d\u7522\u751f\u65b0\u6b63\u5f0f\u9810\u6e2c\u3002")
    warning_html = "".join(f"<li>{item}</li>" for item in warnings) or "<li>\u7121</li>"
    return f"""<!doctype html>
<html lang="zh-Hant"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>\u5929\u5929\u6a02\u9435\u5f8b\u6230\u5831</title>
<style>
body{{margin:0;font-family:"Microsoft JhengHei",Arial,sans-serif;background:#eef2f7;color:#111827}}
header{{background:#111827;color:white;padding:18px 16px}} main{{max-width:1180px;margin:auto;padding:14px}}
.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:12px}} section,.card,.mini{{background:white;border:1px solid #d7dee8;border-radius:8px;padding:14px;margin:12px 0}}
.card b{{display:block;font-size:13px;color:#64748b;margin-bottom:6px}} .value{{font-size:22px;font-weight:800}} .section-title{{font-size:20px;font-weight:800;margin-bottom:10px}}
.ball{{display:inline-flex;align-items:center;justify-content:center;width:34px;height:34px;border:2px solid;border-radius:50%;font-weight:800;margin:3px}}
.badge{{display:inline-block;padding:6px 10px;border-radius:999px;font-weight:800}} .badge.ok{{background:#dcfce7;color:#166534}} .badge.warn{{background:#fef3c7;color:#92400e}}
table{{width:100%;border-collapse:collapse;background:white}} th,td{{border-bottom:1px solid #e5e7eb;padding:9px;text-align:left;vertical-align:top}} th{{background:#f8fafc}}
.warnbox{{border-left:5px solid #f59e0b;background:#fffbeb}} pre{{white-space:pre-wrap;overflow:auto;background:#0f172a;color:#e5e7eb;padding:12px;border-radius:8px}}
</style></head><body>
<header><h1>\u5929\u5929\u6a02\u9435\u5f8b\u5f37\u5316\u6230\u5831</h1><div>{release_badge(analysis)} \u7522\u751f\uff1a{html.escape(analysis["generated_at_taiwan"])}</div></header>
<main>
<div class="grid">
<div class="card"><b>\u6700\u65b0\u958b\u734e\u53f0\u7063\u53ef\u66f4\u65b0\u6642\u9593</b><div class="value">{html.escape(analysis["freshness"].get("latest_taiwan_safe_update_time", "-"))}</div><div>{balls(latest["numbers"], latest["numbers"])}</div><div>{html.escape(analysis["freshness"].get("latest_source", "-") or "-")}</div></div>
<div class="card"><b>\u9810\u6e2c\u958b\u734e\u53f0\u7063\u6642\u9593</b><div class="value">{html.escape(analysis["freshness"].get("target_taiwan_safe_update_time", "-"))}</div><div>\u5c0d\u61c9\u52a0\u5dde\u958b\u734e\u65e5 {html.escape(analysis["target_draw_date"])}</div></div>
<div class="card"><b>\u8cc7\u6599\u7b46\u6578</b><div class="value">{analysis["draw_count"]}</div><div>{analysis["history_completeness"]["status"]}</div></div>
<div class="card"><b>\u767c\u5e03\u95dc\u5361</b><div class="value">{html.escape(release.get("status", "-"))}</div><div>\u822a\u592a\uff1a{html.escape(aerospace.get("status", "-"))}</div></div>
</div>
<section class="warnbox"><div class="section-title">\u98a8\u96aa\u8207\u767c\u5e03\u8aaa\u660e</div><ul>{warning_html}</ul></section>
<section><div class="section-title">\u6700\u65b0 Top10</div><div class="balls">{balls(top10)}</div></section>
<section><div class="section-title">\u5f37\u724c\u7d44</div><div class="grid">{''.join(pack_cards)}</div></section>
{hit_table}
<section><div class="section-title">\u5019\u9078 Top15</div><table><thead><tr><th>#</th><th>\u865f\u78bc</th><th>\u6307\u6578</th><th>\u907a\u6f0f</th><th>\u7406\u7531</th></tr></thead><tbody>{''.join(top15_rows)}</tbody></table></section>
<section><div class="section-title">\u5de5\u696d\u5f15\u64ce\u8207\u56de\u6e2c</div>
<p>\u5f15\u64ce\uff1a{html.escape(industrial.get("engine_version", "-"))}</p>
<p>Top10 \u56de\u6e2c\uff1a{analysis.get("backtest", {}).get("top10_avg_hits", "-")} / \u96a8\u6a5f\u671f\u671b\uff1a{analysis.get("backtest", {}).get("random_top10_expectation", "-")}</p>
<p>\u767c\u5e03\u95dc\u5361 edge\uff1a{release.get("actual_backtest_edge", "-")} / recent\uff1a{html.escape(str(release.get("recent_edges", "-")))}</p>
</section>
<section><div class="section-title">\u5929\u5929\u6a02\u6587\u5b57\u7248\u6230\u5831</div><pre>{html.escape(markdown_text)}</pre></section>
</main></body></html>"""


def fmt_numbers(numbers):
    return " ".join(f"{int(n):02d}" for n in numbers)


def file_check():
    bad = []
    notes = []
    checked = 0
    for path in BASE_DIR.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in {".py", ".ps1", ".bat", ".md", ".json", ".html", ".csv", ".txt"}:
            continue
        checked += 1
        try:
            text = path.read_text(encoding="utf-8")
        except Exception as exc:
            bad.append(f"{path.name}: {exc}")
            continue
        if path.suffix.lower() in {".py", ".ps1", ".bat"} and any("\u4e00" <= ch <= "\u9fff" for ch in text):
            notes.append(f"{path.name}: cjk_report_text_allowed")
    lines = ["# \u6a94\u6848\u8b80\u53d6\u6aa2\u67e5", "", f"- \u6aa2\u67e5\uff1a{checked}", f"- \u7570\u5e38\uff1a{len(bad)}", f"- \u5099\u8a3b\uff1a{len(notes)}"]
    lines.extend(bad)
    if notes:
        lines.extend(["", "## \u5099\u8a3b"])
        lines.extend(notes)
    FILE_CHECK_MD.write_text("\n".join(lines), encoding="utf-8")
    return not bad


def run(full=False):
    setup_dirs()
    backup_db()
    with sqlite3.connect(DB_PATH) as conn:
        init_db(conn)
        conn.execute("DELETE FROM draws WHERE draw_date > ?", (latest_allowed_draw_date(),))
        run_id = conn.execute("INSERT INTO update_runs(started_at,status) VALUES(?,?)", (iso_local(taiwan_now()), "running")).lastrowid
        conn.commit()
        seed_added = seed_draws(conn)
        csv_imported = auto_import_csv_files(conn)
        cached_latest = import_cached_latest_pages(conn)
        existing_count = conn.execute("SELECT COUNT(*) FROM draws").fetchone()[0]
        if full or existing_count < FULL_HISTORY_MIN_ROWS:
            network_diag = run_network_diagnostics()
        else:
            network_diag = {"status": "skipped_fast_update", "blocked_count": 0, "checks": []}
        latest_fetch = fetch_latest_results(conn)
        refreshed_count = conn.execute("SELECT COUNT(*) FROM draws").fetchone()[0]
        if full or refreshed_count < FULL_HISTORY_MIN_ROWS:
            fetched, errors = fetch_history(conn, full=full)
        else:
            fetched, errors = 0, []
        snapshot_backfill = backfill_predictions_from_snapshots(conn)
        settled_count = settle_predictions(conn)
        export_csv(conn)
        validation = validate_sources(conn)
        data_audit = data_integrity_audit(conn, cached_latest, latest_fetch, validation)
        draws = fetch_draws(conn)
        if not draws:
            raise RuntimeError("no draw data")
        analysis = analyze(draws, failure_review(conn))
        ANALYSIS_JSON.write_text(json.dumps(analysis, ensure_ascii=True, indent=2), encoding="utf-8")
        status = store_prediction(conn, analysis)
        health = prediction_health(conn, analysis, network_diag, latest_fetch, cached_latest, data_audit)
        render_reports(conn, analysis)
        try:
            import tiantianle_ironlaw_report

            tiantianle_ironlaw_report.save_reports()
        except Exception as exc:
            log(f"ironlaw_report_failed {exc}")
        scraper_summary = render_history_scraper_report(conn)
        ok = file_check()
        history_status = analysis["history_completeness"]["status"]
        run_status = "success" if ok and not errors and history_status == "complete" and health["status"] == "ok" else "warning"
        message = json.dumps({"seed_added": seed_added, "csv_imported": csv_imported, "cached_latest": cached_latest, "latest_fetch": latest_fetch, "fetched": fetched, "snapshot_backfill": snapshot_backfill, "settled_count": settled_count, "prediction": status, "errors": errors, "file_check": ok, "health": health, "history_status": history_status, "network": network_diag, "validation": validation, "data_audit": data_audit, "scraper": scraper_summary}, ensure_ascii=False)
        conn.execute("UPDATE update_runs SET finished_at=?,status=?,message=? WHERE id=?", (iso_local(taiwan_now()), run_status, message[:1000], run_id))
        conn.commit()
    log(f"done latest={draws[-1]['draw_date']} top10={fmt_numbers([x['number'] for x in analysis['candidates'][:10]])}")
    return analysis


def main():
    if "--validate-only" in sys.argv:
        setup_dirs()
        with sqlite3.connect(DB_PATH) as conn:
            init_db(conn)
            result = validate_sources(conn)
        print("\u4ea4\u53c9\u9a57\u8b49\u5b8c\u6210\uff1a", VALIDATION_REPORT_MD)
        print("\u8a55\u7d1a\uff1a", result["confidence"], "\u885d\u7a81\uff1a", result["db_conflicts"] + result["cross_conflicts"])
        return
    if "--network-only" in sys.argv:
        diag = run_network_diagnostics()
        print("\u7db2\u8def\u8a3a\u65b7\u5b8c\u6210\uff1a", NETWORK_REPORT_MD)
        print("\u72c0\u614b\uff1a", diag["status"], "\u7570\u5e38\u4f86\u6e90\uff1a", diag["blocked_count"])
        return
    if "--history-only" in sys.argv:
        setup_dirs()
        backup_db()
        with sqlite3.connect(DB_PATH) as conn:
            init_db(conn)
            seed_added = seed_draws(conn)
            csv_imported = auto_import_csv_files(conn)
            network_diag = run_network_diagnostics()
            fetched, errors = fetch_history(conn, full=True)
            export_csv(conn)
            summary = render_history_scraper_report(conn)
        print("\u5168\u6b77\u53f2\u6293\u53d6\u5b8c\u6210\uff1a", HISTORY_REPORT_MD)
        print("\u7a2e\u5b50\u65b0\u589e\uff1a", seed_added, "\u5099\u63f4CSV\u6a94\u6578\uff1a", len(csv_imported), "\u7dda\u4e0a\u65b0\u589e\uff1a", fetched, "\u7e3d\u7b46\u6578\uff1a", summary["total_rows"])
        print("\u7db2\u8def\u8a3a\u65b7\uff1a", network_diag["status"], NETWORK_REPORT_MD)
        if errors:
            print("\u6293\u53d6\u8b66\u544a\uff1a", " | ".join(errors[-3:]))
        return
    analysis = run(full="--all" in sys.argv)
    print("\u5831\u544a\uff1a", BATTLE_HTML)
    print("\u5019\u9078 Top10\uff1a", fmt_numbers([x["number"] for x in analysis["candidates"][:10]]))


if __name__ == "__main__":
    main()
