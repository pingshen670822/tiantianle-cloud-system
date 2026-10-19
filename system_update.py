"""One update path for Windows and cloud; publish only after a current, consistent audit."""
import argparse
import hashlib
import importlib.util
import json
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

ROOT=Path(__file__).resolve().parent

def runtime_defaults():
    os.environ.setdefault('TIANTIANLE_RUN_MODE','realtime')
    for family in ('CORE','INDUSTRIAL','FORMULA','UNLIKELY','ADVANCED'):
        os.environ.setdefault(f'TIANTIANLE_{family}_BACKTEST_ROUNDS','30')
    for key,value in {'PACK_GOVERNANCE_ROUNDS':30,'PRECISION_TOURNAMENT_ROUNDS':30,
                      'GROUP_BACKTEST_SHORT':30,'GROUP_BACKTEST_MID':60,'GROUP_BACKTEST_LONG':120}.items():
        os.environ.setdefault('TIANTIANLE_'+key,str(value))

def load_game():
    spec=importlib.util.spec_from_file_location('tiantianle_runtime',ROOT/'美國加州天天樂_20260618_第1版.py')
    module=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

def audit(game):
    a=json.loads((ROOT/'reports/latest_analysis.json').read_text(encoding='utf-8-sig'))
    site=json.loads((ROOT/'site/latest_analysis.json').read_text(encoding='utf-8-sig'))
    latest=a['latest_draw']['draw_date']; expected=game.latest_allowed_draw_date()
    problems=[]
    if latest!=expected: problems.append(f'開獎資料落後：{latest}，應達{expected}')
    if a['target_draw_date']!=game.next_date(latest): problems.append('適用日期錯誤')
    if not a.get('freshness',{}).get('latest_source_confirmed'): problems.append('最新資料來源未確認')
    e=a.get('ensemble50',{})
    if e.get('module_count')!=50 or e.get('verification',{}).get('modules_verified')!=50: problems.append('50組驗證未完成')
    if e.get('based_on_date')!=latest or e.get('target_draw_date')!=a['target_draw_date']: problems.append('模組使用過期資料')
    if e.get('verification',{}).get('walk_forward_samples')!=60: problems.append('60期回測未完成')
    if a!=site: problems.append('電腦與手機JSON不一致')
    for key in ('six_number_combinations','full39_six_combinations'):
        block=e.get(key,{})
        groups=block.get('groups',[])
        if len(groups)!=10 or len({tuple(g['numbers']) for g in groups})!=10: problems.append(key+': 組數或重複錯誤')
        for g in groups:
            if len(set(g['numbers']))!=6 or any(n<1 or n>39 for n in g['numbers']): problems.append(key+': 號碼格式錯誤')
            if g.get('backtest_samples')!=60: problems.append(key+': 回測缺漏')
        if key=='six_number_combinations' and any(not set(g['numbers'])<=set(e['ranking'][:15]) for g in groups): problems.append('前15名組合超出候選池')
        if key=='full39_six_combinations' and [g['score_units'] for g in groups]!=sorted((g['score_units'] for g in groups),reverse=True): problems.append('全39碼前十名排序錯誤')
    for rel in ('site/index.html','site/prediction.html','site/latest_battle_report.html'):
        text=(ROOT/rel).read_text(encoding='utf-8')
        for marker in ('ensemble50-required','top15-six-groups','full39-six-groups','終極獨隻','2中2','3中3','5中5','7中5','9中5','適用日期'):
            if marker not in text: problems.append(rel+': 缺少'+marker)
        if a['target_draw_date'] not in text: problems.append(rel+': 適用日期缺漏')
    result={'status':'passed' if not problems else 'failed','checked_at_taiwan':game.iso_local(game.taiwan_now()),
            'latest_draw_date':latest,'expected_latest_date':expected,'target_draw_date':a['target_draw_date'],
            'module_count':e.get('module_count'),'walk_forward_samples':60,'problems':problems,
            'analysis_sha256':hashlib.sha256((ROOT/'reports/latest_analysis.json').read_bytes()).hexdigest()}
    for rel in ('reports/repair_validation.json','site/repair_validation.json'):
        (ROOT/rel).write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    if problems: raise RuntimeError('; '.join(problems))
    print(json.dumps(result,ensure_ascii=False),flush=True)
    return result

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--validate-only',action='store_true')
    args=parser.parse_args()
    runtime_defaults(); game=load_game()
    if not args.validate_only:
        game.run()
        import pages_build
        pages_build.main()
    audit(game)

if __name__=='__main__':
    main()
