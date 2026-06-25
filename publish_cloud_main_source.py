import base64
import json
import pathlib
import ssl
import time
import urllib.error
import urllib.request


BASE = pathlib.Path(__file__).resolve().parent
REPO = "pingshen670822/tiantianle-cloud-system"
TOKEN_FILE = BASE / "mobile_access_token.txt"
BLOCKED_DIRS = {".git", ".gh-cli", "__pycache__", "backups", "logs"}
BLOCKED_NAMES = {".env", ".env.local", ".env.production", ".gitconfig-gh"}
BLOCKED_PARTS = ("token", "secret", "credential", "password", "github_device_login")


def request_json(path, token, data=None, method="GET", tolerate=()):
    body = None if data is None else json.dumps(data).encode()
    req = urllib.request.Request(
        "https://api.github.com/" + path.lstrip("/"),
        data=body,
        method=method,
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": "Bearer " + token,
            "User-Agent": "tiantianle-main-source-publisher",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    try:
        raw = urllib.request.urlopen(req, timeout=120, context=ssl._create_unverified_context()).read().decode()
        return json.loads(raw or "{}") if raw else {}
    except urllib.error.HTTPError as exc:
        text = exc.read().decode(errors="ignore")
        if exc.code in tolerate:
            return {"_status": exc.code, "body": text}
        raise RuntimeError(f"{method} {path} {exc.code} {text[:500]}")


def allowed(path):
    rel_parts = path.relative_to(BASE).parts
    if any(part in BLOCKED_DIRS for part in rel_parts):
        return False
    lower_name = path.name.lower()
    if lower_name in BLOCKED_NAMES:
        return False
    if path.suffix.lower() == ".zip":
        return False
    if any(part in lower_name for part in BLOCKED_PARTS):
        return False
    return True


def source_files():
    files = []
    for path in BASE.rglob("*"):
        if not path.is_file() or not allowed(path):
            continue
        files.append((path.relative_to(BASE).as_posix(), path))
    return sorted(files)


def main():
    if not TOKEN_FILE.exists():
        raise RuntimeError("mobile_access_token.txt is required for API publishing")
    token = TOKEN_FILE.read_text(encoding="utf-8", errors="ignore").strip()
    if not token:
        raise RuntimeError("mobile_access_token.txt is empty")

    request_json(f"repos/{REPO}", token)
    ref = request_json(f"repos/{REPO}/git/ref/heads/main", token, tolerate=(404,))
    parent = None if ref.get("_status") == 404 else ref.get("object", {}).get("sha")
    entries = []
    for rel, path in source_files():
        blob = request_json(
            f"repos/{REPO}/git/blobs",
            token,
            method="POST",
            data={"content": base64.b64encode(path.read_bytes()).decode(), "encoding": "base64"},
        )
        entries.append({"path": rel, "mode": "100644", "type": "blob", "sha": blob["sha"]})
    tree = request_json(f"repos/{REPO}/git/trees", token, method="POST", data={"tree": entries})
    commit_data = {
        "message": "Update Tiantianle source, precision model, and instant refresh",
        "tree": tree["sha"],
        "committer": {
            "name": "tiantianle-cloud-bot",
            "email": "tiantianle-cloud-bot@users.noreply.github.com",
            "date": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        },
    }
    if parent:
        commit_data["parents"] = [parent]
    commit = request_json(f"repos/{REPO}/git/commits", token, method="POST", data=commit_data)
    if ref.get("_status") == 404:
        request_json(
            f"repos/{REPO}/git/refs",
            token,
            method="POST",
            data={"ref": "refs/heads/main", "sha": commit["sha"]},
        )
    else:
        request_json(
            f"repos/{REPO}/git/refs/heads/main",
            token,
            method="PATCH",
            data={"sha": commit["sha"], "force": True},
        )
    print(f"main source published: {commit['sha']}")
    print(f"files: {len(entries)}")


if __name__ == "__main__":
    main()
