"""GitHub API client; CLI only requests the verified workflow."""
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
BASE=Path(__file__).resolve().parent
REPO='pingshen670822/tiantianle-cloud-system'
TOKEN_FILE=BASE/'mobile_access_token.txt'

def request_json(path,token,data=None,method='GET',tolerate=()):
    url='https://api.github.com/'+urllib.parse.quote(path.lstrip('/'),safe='/?=&%')
    body=None if data is None else json.dumps(data).encode('utf-8')
    request=urllib.request.Request(url,data=body,method=method,headers={
        'Accept':'application/vnd.github+json','Authorization':'Bearer '+token,
        'User-Agent':'tiantianle-verified-updater','X-GitHub-Api-Version':'2022-11-28'})
    attempts=3 if method=='GET' else 1
    for attempt in range(attempts):
        try:
            with urllib.request.urlopen(request,timeout=30) as response:
                raw=response.read().decode('utf-8')
            return json.loads(raw) if raw else {}
        except urllib.error.HTTPError as exc:
            if exc.code in tolerate: return {'_status':exc.code}
            if method=='GET' and exc.code>=500 and attempt+1<attempts:
                time.sleep(0.5*(attempt+1));continue
            raise RuntimeError(f'GitHub {method} failed: HTTP {exc.code}') from exc
        except (urllib.error.URLError,TimeoutError):
            if attempt+1==attempts: raise
            time.sleep(0.5*(attempt+1))

def main():
    from cloud_update_request import main as request_update
    request_update()

if __name__=='__main__': main()
