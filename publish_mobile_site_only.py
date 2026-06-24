import base64
import ctypes
import json
import os
import pathlib
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

BASE = pathlib.Path(__file__).resolve().parent
REPO = "pingshen670822/tiantianle-cloud-system"
CLIENT_ID = "178c6fc778ccc68e1d6a"
BLOCKED_NAME_PARTS = ("token", "secret", "credential", "password", "github_device_login")
BLOCKED_NAMES = {".env", ".env.local", ".env.production"}
FILE_ATTRIBUTE_HIDDEN = 0x2
INVALID_FILE_ATTRIBUTES = 0xFFFFFFFF


def request_json(url, data=None, method=None, headers=None, token=None, tolerate=()):
    body = None if data is None else json.dumps(data).encode()
    final_headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "tiantianle-mobile-site-publisher",
    }
    if headers:
        final_headers.update(headers)
    if token:
        final_headers["Authorization"] = "Bearer " + token
        final_headers["X-GitHub-Api-Version"] = "2022-11-28"
    req = urllib.request.Request(url, data=body, method=method, headers=final_headers)
    try:
        raw = urllib.request.urlopen(req, timeout=120, context=ssl._create_unverified_context()).read().decode()
        return json.loads(raw or "{}") if raw else {}
    except urllib.error.HTTPError as exc:
        text = exc.read().decode(errors="ignore")
        if exc.code in tolerate:
            return {"_status": exc.code, "body": text}
        raise RuntimeError(f"{method or 'GET'} {url} {exc.code} {text[:500]}")


def device_token():
    form = urllib.parse.urlencode(
        {"client_id": CLIENT_ID, "scope": "repo workflow read:org"}
    ).encode()
    req = urllib.request.Request(
        "https://github.com/login/device/code",
        data=form,
        headers={"Accept": "application/json", "User-Agent": "tiantianle-mobile-site-publisher"},
    )
    info = json.loads(
        urllib.request.urlopen(req, timeout=30, context=ssl._create_unverified_context()).read().decode()
    )
    print("")
    print("GitHub authorization required.")
    print("Open: " + info["verification_uri"])
    print("Code: " + info["user_code"])
    print("")
    print("Waiting up to 15 minutes after you enter the code...")
    sys.stdout.flush()
    deadline = time.time() + min(int(info.get("expires_in") or 899), 899)
    interval = int(info.get("interval") or 5)
    while time.time() < deadline:
        form = urllib.parse.urlencode(
            {
                "client_id": CLIENT_ID,
                "device_code": info["device_code"],
                "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
            }
        ).encode()
        req = urllib.request.Request(
            "https://github.com/login/oauth/access_token",
            data=form,
            headers={"Accept": "application/json", "User-Agent": "tiantianle-mobile-site-publisher"},
        )
        res = json.loads(
            urllib.request.urlopen(req, timeout=30, context=ssl._create_unverified_context()).read().decode()
        )
        if "access_token" in res:
            return res["access_token"]
        err = res.get("error", "")
        if err == "authorization_pending":
            time.sleep(interval)
            continue
        if err == "slow_down":
            interval += 5
            time.sleep(interval)
            continue
        raise RuntimeError("GitHub authorization failed: " + err)
    raise RuntimeError("GitHub authorization expired. Run this publisher again.")


def github_api(path, token, method="GET", data=None, tolerate=()):
    return request_json(
        "https://api.github.com/" + path.lstrip("/"),
        data=data,
        method=method,
        token=token,
        tolerate=tolerate,
    )


def write_text_even_if_hidden(path, text, encoding="utf-8"):
    path = pathlib.Path(path)
    if os.name == "nt" and path.exists():
        attrs = ctypes.windll.kernel32.GetFileAttributesW(str(path))
        if attrs != INVALID_FILE_ATTRIBUTES and attrs & FILE_ATTRIBUTE_HIDDEN:
            ctypes.windll.kernel32.SetFileAttributesW(str(path), attrs & ~FILE_ATTRIBUTE_HIDDEN)
            try:
                path.write_text(text, encoding=encoding)
            finally:
                new_attrs = ctypes.windll.kernel32.GetFileAttributesW(str(path))
                if new_attrs != INVALID_FILE_ATTRIBUTES:
                    ctypes.windll.kernel32.SetFileAttributesW(str(path), new_attrs | FILE_ATTRIBUTE_HIDDEN)
            return
    path.write_text(text, encoding=encoding)


def approved_files():
    files = []
    for root_name in ("site", "data", "reports"):
        root = BASE / root_name
        if not root.exists():
            continue
        for path in root.rglob("*"):
            if not path.is_file():
                continue
            if "__pycache__" in path.parts or path.suffix.lower() == ".pyc":
                continue
            lowered = path.name.lower()
            if lowered in BLOCKED_NAMES or any(part in lowered for part in BLOCKED_NAME_PARTS):
                continue
            rel = path.relative_to(root).as_posix()
            if root_name != "site":
                rel = (pathlib.Path(root_name) / rel).as_posix()
            files.append((rel, path))
    return files


def publish(token):
    github_api(f"repos/{REPO}", token)
    ref = github_api(f"repos/{REPO}/git/ref/heads/gh-pages", token, tolerate=(404,))
    parent = None if ref.get("_status") == 404 else ref.get("object", {}).get("sha")
    entries = []
    files = approved_files()
    if not files:
        raise RuntimeError("No site/data/reports files found.")
    for rel, path in files:
        blob = github_api(
            f"repos/{REPO}/git/blobs",
            token,
            method="POST",
            data={"content": base64.b64encode(path.read_bytes()).decode(), "encoding": "base64"},
        )
        entries.append({"path": rel, "mode": "100644", "type": "blob", "sha": blob["sha"]})
    blob = github_api(
        f"repos/{REPO}/git/blobs",
        token,
        method="POST",
        data={"content": "", "encoding": "utf-8"},
    )
    entries.append({"path": ".nojekyll", "mode": "100644", "type": "blob", "sha": blob["sha"]})
    tree = github_api(f"repos/{REPO}/git/trees", token, method="POST", data={"tree": entries})
    commit_data = {
        "message": "Fix Tiantianle mobile site homepage and data",
        "tree": tree["sha"],
    }
    if parent:
        commit_data["parents"] = [parent]
    commit = github_api(f"repos/{REPO}/git/commits", token, method="POST", data=commit_data)
    if ref.get("_status") == 404:
        github_api(
            f"repos/{REPO}/git/refs",
            token,
            method="POST",
            data={"ref": "refs/heads/gh-pages", "sha": commit["sha"]},
        )
    else:
        github_api(
            f"repos/{REPO}/git/refs/heads/gh-pages",
            token,
            method="PATCH",
            data={"sha": commit["sha"], "force": True},
        )
    github_api(
        f"repos/{REPO}/pages",
        token,
        method="POST",
        data={"source": {"branch": "gh-pages", "path": "/"}},
        tolerate=(409,),
    )
    github_api(
        f"repos/{REPO}/pages",
        token,
        method="PUT",
        data={"source": {"branch": "gh-pages", "path": "/"}},
        tolerate=(404, 409),
    )
    return commit["sha"], len(files)


def main():
    token_path = BASE / "mobile_access_token.txt"
    if token_path.exists():
        token = token_path.read_text(encoding="utf-8", errors="ignore").strip()
    else:
        token = device_token()
        token_path.write_text(token, encoding="utf-8")
    sha, count = publish(token)
    url = "https://pingshen670822.github.io/tiantianle-cloud-system/"
    write_text_even_if_hidden(BASE / "tiantianle-mobile-cloud-url.txt", url + "\n", encoding="ascii")
    print("")
    print(f"已發布 {count} 個手機雲端檔案。")
    print("雲端版本: " + sha)
    print("手機網址: " + url)


if __name__ == "__main__":
    main()
