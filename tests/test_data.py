"""Build a current real-data fixture in memory when upgrading an older deployment."""
import copy
import csv
import json
from functools import lru_cache
from pathlib import Path
from module1000 import SCHEMA_VERSION

ROOT=Path(__file__).resolve().parents[1]

@lru_cache(maxsize=1)
def _current():
    a=json.loads((ROOT/'reports/latest_analysis.json').read_text(encoding='utf-8-sig'))
    if a['ensemble50'].get('version')!=SCHEMA_VERSION:
        from ensemble50 import compute
        with (ROOT/'fantasy5_full_history.csv').open(encoding='utf-8-sig') as handle:
            draws=[{'draw_date':r['draw_date'],'numbers':[int(r['n'+str(i)]) for i in range(1,6)]} for r in csv.DictReader(handle)]
        a['ensemble50']=compute(draws)
    return a

def current_analysis():
    return copy.deepcopy(_current())
