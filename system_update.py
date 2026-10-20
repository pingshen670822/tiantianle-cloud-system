"""One update path for Windows and cloud; publish only after a current, consistent audit."""
import argparse
import hashlib
import importlib.util
import json
import os
import math
import sys
from datetime import datetime, timedelta
from pathlib import Path

ROOT=Path(__file__).resolve().parent

def runtime_defaults(mode=None):
    if mode: os.environ['TIANTIANLE_RUN_MODE']=mode
    os.environ.setdefault('TIANTIANLE_RUN_MODE','realtime')
    deep=os.environ['TIANTIANLE_RUN_MODE']=='deep'
    for family in ('CORE','INDUSTRIAL','FORMULA','UNLIKELY','ADVANCED'):
        os.environ.setdefault(f'TIANTIANLE_{family}_BACKTEST_ROUNDS','120' if deep else '30')
    for key,value in {'PACK_GOVERNANCE_ROUNDS':80 if deep else 30,'PRECISION_TOURNAMENT_ROUNDS':120 if deep else 30,
                      'GROUP_BACKTEST_SHORT':60 if deep else 30,'GROUP_BACKTEST_MID':120 if deep else 60,'GROUP_BACKTEST_LONG':240 if deep else 120}.items():
        os.environ.setdefault('TIANTIANLE_'+key,str(value))

def load_game():
    spec=importlib.util.spec_from_file_location('tiantianle_runtime',ROOT/'美國加州天天樂_20260618_第1版.py')
    module=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

def audit(game):
    def invalid_constant(value):raise ValueError('Invalid JSON numeric constant: '+value)
    a=json.loads((ROOT/'reports/latest_analysis.json').read_text(encoding='utf-8-sig'),parse_constant=invalid_constant)
    site=json.loads((ROOT/'site/latest_analysis.json').read_text(encoding='utf-8-sig'),parse_constant=invalid_constant)
    latest=a['latest_draw']['draw_date']; expected=game.latest_allowed_draw_date()
    problems=[]
    if latest!=expected: problems.append(f'開獎資料落後：{latest}，應達{expected}')
    if a['target_draw_date']!=game.next_date(latest): problems.append('適用日期錯誤')
    if not a.get('freshness',{}).get('latest_source_confirmed'): problems.append('最新資料來源未確認')
    if not game.source_is_confirmed(a['latest_draw'].get('source','')):problems.append('來源標記與確認狀態不符')
    actual=a['latest_draw'].get('numbers',[])
    if len(actual)!=5 or len(set(actual))!=5 or any(type(n) is not int or not 1<=n<=39 for n in actual):problems.append('實際開獎號碼無效')
    e=a.get('ensemble50',{})
    if e.get('module_count')!=1000 or e.get('verification',{}).get('modules_verified')!=1000: problems.append('1000組驗證未完成')
    modules=e.get('modules',[])
    if len(modules)!=1000 or len({m.get('id') for m in modules})!=1000:problems.append('1000組模組內容缺漏或重複')
    from module1000 import configurations,configuration_signature,SCHEMA_VERSION,FAMILIES
    try:
        if e.get('version')!=SCHEMA_VERSION or e.get('family_count')!=len(FAMILIES):problems.append('1000組算法版本或家族數錯誤')
        if [configuration_signature(m) for m in modules]!=[configuration_signature(m) for m in configurations()]:problems.append('1000組配置與登錄定義不一致')
        if [m['id'] for m in modules]!=[m['id'] for m in configurations()]:problems.append('1000組登錄識別碼不一致')
        for m in modules:
            validation=m.get('validation',{});scores={int(k):v for k,v in m.get('scores',{}).items()}
            if sorted(scores)!=list(range(1,40)) or any(not math.isfinite(v) for v in scores.values()) or sorted(scores,key=lambda n:(-scores[n],n))!=m['ranking']:
                problems.append('模組數值或排名不一致');break
            if validation.get('samples')!=60 or type(validation.get('single_hits')) is not int or not 0<=validation['single_hits']<=60 or not 0<=validation.get('top5_avg_hits',-1)<=validation.get('top9_avg_hits',-1)<=5 or len(validation.get('replay_sha256',''))!=64:
                problems.append('模組回測明細缺漏或無效');break
        report=e.get('algorithm_report',{})
        if report.get('method_count')!=19 or report.get('random_control_count')!=1 or report.get('fusion_configuration_count')!=950:
            problems.append('算法與參數實驗計數不一致')
        representatives=report.get('representatives',[])
        if len(representatives)!=20 or len(report.get('pairwise_diversity',[]))!=190:problems.append('算法差異證據缺漏')
        registered={m['id']:m for m in modules}
        for representative in representatives:
            original=registered.get(representative.get('id'))
            if original is None or any(representative.get(key)!=original.get(key) for key in ('family','window','parameters','ranking','scores','validation')):problems.append('算法代表與實算模組不一致');break
            trace=representative.get('trace',[])
            if len(trace)!=60 or len(representative['validation'].get('blocks',[]))!=3:problems.append('算法逐期及分段回測缺漏');break
            if any(t['target_date']!=record['target_date'] or t['actual']!=record['actual_numbers'] or t['top5_hits']!=len(set(t['top5'])&set(t['actual'])) for t,record in zip(trace,e.get('backtest_manifest',[]))):problems.append('算法逐期回測記錄不一致');break
            if sum(t['top1'] in t['actual'] for t in trace)!=representative['validation']['single_hits']:problems.append('算法獨隻回測記錄不一致');break
        proof=e.get('verification',{});manifest=e.get('backtest_manifest',[])
        if proof.get('replay_rounds')!=2 or proof.get('replay_periods_verified')!=60 or proof.get('module_forecasts')!=60000 or proof.get('unique_configurations')!=1000:problems.append('1000組雙輪回測驗證未完成')
        if proof.get('unique_current_rankings')!=len({tuple(m['ranking']) for m in modules}):problems.append('不同排名實際數量不一致')
        if len(manifest)!=60 or manifest[-1]['target_date']!=latest or any(r['module_count']!=1000 or r['training_last_date']>=r['target_date'] or len(r['forecast_sha256'])!=64 or len(r['input_sha256'])!=64 for r in manifest):problems.append('逐期回測日期或排名指紋缺漏')
    except (KeyError,TypeError,ValueError,IndexError):
        problems.append('1000組配置或回測結構無效')
    if any(sorted(m.get('ranking',[]))!=list(range(1,40)) or any(type(n) is not int for n in m.get('ranking',[])) for m in modules):problems.append('模組排名缺碼或重複')
    if sorted(e.get('ranking',[]))!=list(range(1,40)):problems.append('總排名格式錯誤')
    from ensemble50 import number_percentages
    try:
        calculated_percentages=number_percentages(modules)
        if e.get('number_percentages')!=calculated_percentages:problems.append('單號百分比與1000組排名不一致或缺漏')
        if [r['number'] for r in calculated_percentages['numbers']]!=e.get('ranking'):problems.append('單號百分比排序與融合排名不一致')
    except (ValueError,KeyError,TypeError):
        problems.append('單號百分比來源排名無效')
    sizes={'終極獨隻':1,'2中2':2,'3中3':3,'5中5':5,'7中5':7,'9中5':9}
    required={p.get('name'):p for p in e.get('packs',[])}
    for label,size in sizes.items():
        numbers=required.get(label,{}).get('numbers',[])
        if len(numbers)!=size or len(set(numbers))!=size or any(type(n) is not int or not 1<=n<=39 for n in numbers):problems.append('必備牌型缺漏或格式錯誤：'+label)
    if e.get('based_on_date')!=latest or e.get('target_draw_date')!=a['target_draw_date']: problems.append('模組使用過期資料')
    if e.get('verification',{}).get('walk_forward_samples')!=60: problems.append('60期回測未完成')
    if a!=site: problems.append('電腦與手機JSON不一致')
    for key in ('six_number_combinations','full39_six_combinations'):
        block=e.get(key,{})
        groups=block.get('groups',[])
        if len(groups)!=10 or len({tuple(g['numbers']) for g in groups})!=10: problems.append(key+': 組數或重複錯誤')
        for g in groups:
            if len(g['numbers'])!=6 or len(set(g['numbers']))!=6 or any(type(n) is not int or n<1 or n>39 for n in g['numbers']): problems.append(key+': 號碼格式錯誤')
            if g.get('backtest_samples')!=60: problems.append(key+': 回測缺漏')
            if not math.isfinite(float(g.get('model_score',float('nan')))):problems.append(key+': 評分無效')
            counts=g.get('backtest_hits_at_least',{})
            values=[counts.get(str(t),-1) for t in (5,4,3,2)]
            if any(type(v) is not int for v in values) or not 0<=values[0]<=values[1]<=values[2]<=values[3]<=60:problems.append(key+': 回測命中統計無效')
        if key=='six_number_combinations' and any(not set(g['numbers'])<=set(e['ranking'][:15]) for g in groups): problems.append('前15名組合超出候選池')
        if key=='full39_six_combinations' and [g['score_units'] for g in groups]!=sorted((g['score_units'] for g in groups),reverse=True): problems.append('全39碼前十名排序錯誤')
        if key=='full39_six_combinations' and (block.get('exhaustive_verification',{}).get('all_top10_exact_match') is not True or block.get('exhaustive_verification',{}).get('combinations_scored')!=3262623):problems.append('全39碼獨立完整枚舉驗證未完成')
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
    parser.add_argument('--worker',action='store_true',help=argparse.SUPPRESS)
    parser.add_argument('--mode',choices=('realtime','deep'))
    parser.add_argument('--all',action='store_true',help=argparse.SUPPRESS)
    args=parser.parse_args()
    mode='deep' if args.all else (args.mode or os.environ.get('TIANTIANLE_RUN_MODE','realtime'))
    runtime_defaults(mode)
    if args.validate_only:
        from update_transaction import UpdateLock,recover
        with UpdateLock(ROOT/'work/update.lock'):
            recover(ROOT)
            audit(load_game())
    elif args.worker:
        if os.environ.get('TIANTIANLE_STAGE_ROOT')!=str(ROOT.resolve()) or ROOT.parent.name!='work' or not ROOT.name.startswith('stage-'):
            raise RuntimeError('Worker may run only inside an isolated update workspace')
        game=load_game()
        game.run()
        import pages_build
        pages_build.main()
        audit(game)
    else:
        from update_transaction import isolated_update
        isolated_update(ROOT,mode)

if __name__=='__main__':
    main()
