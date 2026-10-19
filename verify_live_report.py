import hashlib
import json
import math
import time
import urllib.request
from pathlib import Path

ROOT=Path(__file__).resolve().parent
BASE='https://pingshen670822.github.io/tiantianle-cloud-system/'

def equivalent(a,b):
    if isinstance(a,float) or isinstance(b,float):
        return isinstance(a,(int,float)) and isinstance(b,(int,float)) and math.isclose(a,b,rel_tol=1e-12,abs_tol=1e-12)
    if isinstance(a,dict) and isinstance(b,dict):
        return a.keys()==b.keys() and all(equivalent(a[k],b[k]) for k in a)
    if isinstance(a,list) and isinstance(b,list):
        return len(a)==len(b) and all(equivalent(x,y) for x,y in zip(a,b))
    return a==b

def verify_once():
    local=json.loads((ROOT/'reports/latest_analysis.json').read_text(encoding='utf-8-sig'))
    stamp=str(time.time_ns())
    remote=json.load(urllib.request.urlopen(BASE+'latest_analysis.json?v='+stamp,timeout=20))
    # Official and consensus sources can describe the same draw with different provenance.
    for key in ('draw_date','numbers'):
        if remote.get('latest_draw',{}).get(key)!=local.get('latest_draw',{}).get(key):
            raise RuntimeError('Live draw mismatch: '+key)
    for key in ('target_draw_date','ensemble50'):
        if not equivalent(remote.get(key),local.get(key)): raise RuntimeError('Live report mismatch: '+key)
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
