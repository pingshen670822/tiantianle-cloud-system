import json
import pathlib
import ssl
import time
import urllib.request


ROOT = pathlib.Path(__file__).resolve().parent
REPORT_DIR = ROOT / "reports"
SITE_DIR = ROOT / "site"
REMOTE_URLS = [
    "https://pingshen670822.github.io/tiantianle-cloud-system/latest_analysis.json",
    "https://pingshen670822.github.io/tiantianle-cloud-system/reports/latest_analysis.json",
]


def fetch_json(url):
    full_url = url + ("&" if "?" in url else "?") + "sync=" + str(int(time.time()))
    request = urllib.request.Request(
        full_url,
        headers={
            "Cache-Control": "no-cache",
            "Pragma": "no-cache",
            "User-Agent": "tiantianle-local-cloud-sync",
        },
    )
    raw = urllib.request.urlopen(request, timeout=45, context=ssl._create_unverified_context()).read().decode()
    return json.loads(raw)


def payload_key(data):
    latest = data.get("latest_draw") or {}
    prediction = data.get("prediction") or {}
    return (
        str(latest.get("draw_date") or ""),
        tuple(int(n) for n in latest.get("numbers") or []),
        str(data.get("target_draw_date") or ""),
        tuple(int(n) for n in prediction.get("top9") or []),
        str(data.get("generated_at_taiwan") or ""),
    )


def choose_remote_payload():
    payloads = []
    errors = []
    for url in REMOTE_URLS:
        try:
            payloads.append(fetch_json(url))
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{url}: {exc}")
    if not payloads:
        raise RuntimeError("無法讀取雲端最新資料；" + "；".join(errors))
    payloads.sort(key=payload_key, reverse=True)
    return payloads[0]


def write_json_aliases(data):
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    SITE_DIR.mkdir(parents=True, exist_ok=True)
    (SITE_DIR / "reports").mkdir(parents=True, exist_ok=True)
    text = json.dumps(data, ensure_ascii=True, indent=2)
    targets = [
        REPORT_DIR / "latest_analysis.json",
        SITE_DIR / "latest_analysis.json",
        SITE_DIR / "reports" / "latest_analysis.json",
        SITE_DIR / "最新分析資料.json",
        SITE_DIR / "reports" / "最新分析資料.json",
    ]
    for path in targets:
        path.write_text(text, encoding="utf-8")


def main():
    remote = choose_remote_payload()
    write_json_aliases(remote)

    import tiantianle_ironlaw_report
    tiantianle_ironlaw_report.save_reports()

    import pages_build
    pages_build.main()

    import sanitize_public_outputs  # noqa: F401
    import system_stability_monitor
    system_stability_monitor.main()

    latest = remote.get("latest_draw") or {}
    super_single = remote.get("super_single_decision") or {}
    print(json.dumps({
        "status": "本機已回灌雲端最新資料",
        "generated_at_taiwan": remote.get("generated_at_taiwan"),
        "latest_draw": latest.get("draw_date"),
        "latest_numbers": latest.get("numbers"),
        "target_draw": remote.get("target_draw_date"),
        "target_taiwan_time": remote.get("prediction_draw_taiwan_time"),
        "super_single": super_single.get("numbers") or [super_single.get("number")],
        "top9": (remote.get("prediction") or {}).get("top9"),
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
