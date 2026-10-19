import hashlib
import json
import time
import urllib.request
from pathlib import Path

ROOT=Path(__file__).resolve().parent
BASE='https://pingshen670822.github.io/tiantianle-cloud-system/'

def verify_once():
    local=json.loads((ROOT/'reports/latest_analysis.json').read_text(encoding='utf-8-sig'))
    stamp=str(time.time_ns())
    remote=json.load(urllib.request.urlopen(BASE+'latest_analysis.json?v='+stamp,timeout=20))
    for key in ('latest_draw','target_draw_date','ensemble50'):
        if remote.get(key)!=local.get(key): raise RuntimeError('Live report mismatch: '+key)
    html=urllib.request.urlopen(BASE+'?v='+stamp,timeout=20).read().decode('utf-8')
    for marker in ('ensemble50-required','top15-six-groups','full39-six-groups',local['target_draw_date']):
        if marker not in html: raise RuntimeError('Live report section missing: '+marker)
    print('Live report verified:',remote['latest_draw']['draw_date'],'->',remote['target_draw_date'],flush=True)

if __name__=='__main__':
    for attempt in range(1,19):
        try:
            verify_once()
            break
        except Exception as exc:
            print('Live check',attempt,str(exc),flush=True)
            if attempt==18: raise
            time.sleep(10)
