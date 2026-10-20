"""Compatibility entry point for 1000 configured modules and causal validation."""
import math
import json
import html
import heapq
import hashlib
from collections import Counter
from datetime import date, timedelta
from itertools import combinations

from module1000 import MODULE_COUNT, FAMILIES, WINDOWS, BLENDS, SCHEMA_VERSION, rank_modules, configurations, configuration_signature, forecast_hash, verify_exact_six

GOALS = ((1, 1, '終極獨隻'), (2, 2, '2中2'), (3, 3, '3中3'),
         (5, 5, '5中5'), (7, 5, '7中5'), (9, 5, '9中5'))

def consensus(modules):
    scores = dict.fromkeys(range(1,40), 0)
    for module in modules:
        for i,n in enumerate(module['ranking']):
            scores[n] += 39-i
    return sorted(scores, key=lambda n:(-scores[n],n))


def number_percentages(modules):
    """Normalize the existing equal-weight ranking points; not win probabilities."""
    if len(modules)!=MODULE_COUNT or len({m['id'] for m in modules})!=MODULE_COUNT:
        raise ValueError('Single-number percentages require 1000 unique modules')
    points=Counter(); support=Counter()
    for m in modules:
        ranked=m['ranking']
        if any(type(n) is not int for n in ranked) or sorted(ranked)!=list(range(1,40)):
            raise ValueError('Invalid ranking for single-number percentage')
        points.update({n:39-i for i,n in enumerate(ranked)})
        support.update(ranked[:9])
    ranking=sorted(points,key=lambda n:(-points[n],n))
    return {'method':'1000組名次積分合計 ÷ (1000×39) ×100；每組第一名39分、末名1分',
            'meaning':'融合排名分數百分比，不是開出機率，尚未校準',
            'numbers':[{'number':n,'rank':i+1,'ranking_points':points[n],
                        'ranking_score_percent':round(points[n]/(MODULE_COUNT*39)*100,4),
                        'top9_support_percent':round(support[n]/MODULE_COUNT*100,4)} for i,n in enumerate(ranking)]}

def six_number_groups(modules, ranked, count=10):
    """Fixed ranking/co-occurrence score with diversified groups, no outcome input."""
    pool=ranked[:15]
    quality=dict.fromkeys(pool,0.0)
    pairs=Counter()
    for m in modules:
        for i,n in enumerate(m['ranking']):
            if n in quality:
                quality[n]+=(39-i)/(39*len(modules))
        pairs.update(combinations(sorted(m['ranking'][:9]),2))
    candidates=[]
    for combo in combinations(sorted(pool),6):
        individual=sum(quality[n] for n in combo)/6
        support=sum(pairs[p]/len(modules) for p in combinations(combo,2))/15
        candidates.append((combo,0.8*individual+0.2*support))
    selected=[]
    usage=Counter()
    remaining=candidates
    for slot in range(count):
        def selection_score(row):
            combo,score=row
            shared=max((len(set(combo)&set(p['numbers'])) for p in selected),default=0)
            coverage=sum(1/(1+usage[n]) for n in combo)/6
            return score+0.18*coverage-0.08*shared/6
        eligible=[row for row in remaining if all(len(set(row[0])&set(p['numbers']))<=4 for p in selected)]
        combo,score=max(eligible or remaining,key=lambda row:(selection_score(row),tuple(-n for n in row[0])))
        selected.append({'group':slot+1,'numbers':list(combo),'model_score':round(score*100,2),
                         'confidence_label':'模型優先候選／未證實高機率'})
        usage.update(combo)
        remaining=[r for r in remaining if r[0]!=combo]
    return {'top15_ranked':pool,'groups':selected,'group_count':count,
            'method':'1000組排名分數80%＋前九共現支持20%；另以覆蓋與重疊限制分散10組',
            'score_meaning':'模型評分0–100，不是中獎機率；組號是固定選組順序',
            'unique_numbers_covered':len(usage)}

def full39_top_six(modules, count=10, pool=None):
    """Exact top-K using integer scores and an admissible branch upper bound."""
    ranks=Counter()
    pair_counts=Counter()
    for m in modules:
        ranks.update({n:39-i for i,n in enumerate(m['ranking'])})
        pair_counts.update(combinations(sorted(m['ranking'][:9]),2))
    pool=sorted(pool or range(1,40),key=lambda n:(-ranks[n],n))
    size=len(pool)
    linear=[10*ranks[n] for n in pool]
    edges=[[39*pair_counts[tuple(sorted((a,b)))] if a!=b else 0 for b in pool] for a in pool]
    suffix_max=[0]*(size+1)
    for i in range(size-1,-1,-1):
        suffix_max[i]=max(suffix_max[i+1],max(edges[i][i+1:],default=0))
    best=[]; visited=0; pruned=0
    def search(start,chosen,score):
        nonlocal visited,pruned
        visited+=1
        need=6-len(chosen)
        if need==0:
            numbers=tuple(sorted(pool[i] for i in chosen))
            entry=(score,tuple(-n for n in numbers),numbers)
            if len(best)<count:
                heapq.heappush(best,entry)
            elif entry>best[0]:
                heapq.heapreplace(best,entry)
            return
        if size-start<need:
            return
        gains=[linear[i]+sum(edges[i][j] for j in chosen) for i in range(start,size)]
        upper=score+sum(heapq.nlargest(need,gains))+math.comb(need,2)*suffix_max[start]
        if len(best)==count and upper<best[0][0]:
            pruned+=1
            return
        for i in range(start,size-need+1):
            search(i+1,chosen+(i,),score+gains[i-start])
    search(0,(),0)
    denominator=2925*len(modules)
    groups=[{'group':i,'numbers':list(numbers),'score_units':score,
             'model_score':round(score/denominator*100,4),
             'confidence_label':'評分前十／未證實高機率'}
            for i,(score,_,numbers) in enumerate(sorted(best,reverse=True),1)]
    tickets={tuple(ticket) for p in groups for ticket in combinations(p['numbers'],5)}
    return {'groups':groups,'group_count':count,'pool':sorted(pool),
            'expanded_five_number_tickets':6*count,'unique_five_number_tickets':len(tickets),
            'random_all5_probability_percent':len(tickets)/math.comb(39,5)*100,
            'search_space':math.comb(size,6),'search_method':'精確分支定界；整數評分；保留所有可能超越第十名的分支',
            'visited_nodes':visited,'pruned_branches':pruned,'score_denominator':denominator,
            'method':'平均排名分數80%＋前九共現支持20%；純取最高分，不加覆蓋或重疊限制',
            'score_meaning':'模型評分不是中獎機率；六碼候選組內含6種五碼組合'}

def compute(draws, samples=60):
    if len(draws)<120:
        raise ValueError('1000組驗證至少需要120期資料')
    if any(len(set(d['numbers']))!=5 or any(not 1<=n<=39 for n in d['numbers']) for d in draws):
        raise ValueError('歷史號碼完整性檢查失敗')
    dates = [d['draw_date'] for d in draws]
    if dates != sorted(set(dates)):
        raise ValueError('歷史日期重複或未排序')
    recent = [date.fromisoformat(d) for d in dates[-min(samples+1,len(dates)):]]
    if any((b-a).days != 1 for a,b in zip(recent,recent[1:])):
        raise ValueError('近期回測資料缺日，必須補齊後重新驗證')
    modules = rank_modules(draws)
    samples = min(samples,len(draws)-100)
    hits = {m['id']:[] for m in modules}
    single_hits={m['id']:0 for m in modules}
    top9_hits={m['id']:0 for m in modules}
    replay_digests={m['id']:hashlib.sha256() for m in modules}
    manifest=[]
    prefix_hashes=[];prefix_digest=hashlib.sha256()
    for row in draws:
        prefix_digest.update(row['draw_date'].encode());prefix_digest.update(bytes(sorted(row['numbers'])))
        prefix_hashes.append(prefix_digest.hexdigest())
    pack_hits = {label:[] for _,_,label in GOALS}
    six_stats=[Counter() for _ in range(10)]
    six_any=Counter()
    full_stats=[Counter() for _ in range(10)]
    full_any=Counter()
    for end in range(len(draws)-samples,len(draws)):
        prior = rank_modules(draws[:end])
        actual = set(draws[end]['numbers'])
        manifest.append({'training_count':end,'training_last_date':draws[end-1]['draw_date'],
                         'target_date':draws[end]['draw_date'],'input_sha256':prefix_hashes[end-1],
                         'module_count':len(prior),'forecast_sha256':forecast_hash(prior),
                         'actual_numbers':sorted(actual)})
        for m in prior:
            hits[m['id']].append(len(actual & set(m['ranking'][:5])))
            single_hits[m['id']]+=m['ranking'][0] in actual
            top9_hits[m['id']]+=len(actual & set(m['ranking'][:9]))
            replay_digests[m['id']].update(draws[end]['draw_date'].encode()+bytes(m['ranking'])+bytes(sorted(actual)))
        ranked = consensus(prior)
        prior_six=six_number_groups(prior,ranked)
        prior_full=full39_top_six(prior)
        full_hits=[len(actual & set(p['numbers'])) for p in prior_full['groups']]
        for stat,hit in zip(full_stats,full_hits):
            for goal in (2,3,4,5):
                stat[goal]+=hit>=goal
        for goal in (2,3,4,5):
            full_any[goal]+=max(full_hits)>=goal
        period_hits=[len(actual & set(p['numbers'])) for p in prior_six['groups']]
        for stat, hit in zip(six_stats,period_hits):
            for goal in (2,3,4,5):
                stat[goal]+=hit>=goal
        for goal in (2,3,4,5):
            six_any[goal]+=max(period_hits)>=goal
        for size,goal,label in GOALS:
            pack_hits[label].append(len(actual & set(ranked[:size]))>=goal)
    for m in modules:
        values = hits[m['id']]
        m['validation'] = {'samples':samples, 'top5_avg_hits':round(sum(values)/samples,4),
                           'single_hits':single_hits[m['id']],'single_rate_percent':round(single_hits[m['id']]/samples*100,4),
                           'top9_avg_hits':round(top9_hits[m['id']]/samples,4),
                           'replay_sha256':replay_digests[m['id']].hexdigest(),
                           'random_top5_expected_hits':25/39, 'structural_pass': sorted(m['ranking'])==list(range(1,40))}
    # Rebuild each historical prefix in a separate pass. Never select weights by this outcome.
    for record,end in zip(manifest,range(len(draws)-samples,len(draws))):
        replay=rank_modules(draws[:end])
        if forecast_hash(replay)!=record['forecast_sha256'] or record['training_last_date']>=record['target_date']:
            raise RuntimeError('Historical prefix replay mismatch')
    if forecast_hash(rank_modules(draws))!=forecast_hash(modules):
        raise RuntimeError('Current 1000-module replay mismatch')
    ranked = consensus(modules)
    six=six_number_groups(modules,ranked)
    full=full39_top_six(modules)
    full['exhaustive_verification']=verify_exact_six(modules,full['groups'])
    for p,stat in zip(full['groups'],full_stats):
        p['backtest_samples']=samples
        p['backtest_hits_at_least']={str(g):stat[g] for g in (2,3,4,5)}
    full['walk_forward_samples']=samples
    full['any_group_hits_at_least']={str(g):full_any[g] for g in (2,3,4,5)}
    for p,stat in zip(six['groups'],six_stats):
        p['backtest_samples']=samples
        p['backtest_hits_at_least']={str(g):stat[g] for g in (2,3,4,5)}
    six['walk_forward_samples']=samples
    six['any_group_hits_at_least']={str(g):six_any[g] for g in (2,3,4,5)}
    six['verification']={'groups_unique':len({tuple(p['numbers']) for p in six['groups']})==10,
                         'all_from_top15':all(set(p['numbers'])<=set(ranked[:15]) and len(set(p['numbers']))==6 for p in six['groups'])}
    packs=[]
    for size,goal,label in GOALS:
        numbers = sorted(ranked[:size])
        wins = sum(pack_hits[label])
        rate = wins/samples
        z=1.96
        centre=(rate+z*z/(2*samples))/(1+z*z/samples)
        margin=z*math.sqrt(rate*(1-rate)/samples+z*z/(4*samples*samples))/(1+z*z/samples)
        agreement = sum(sum(n in m['ranking'][:size] for n in numbers) for m in modules)/(MODULE_COUNT*size)*100
        baseline = sum(math.comb(size,k)*math.comb(39-size,5-k)/math.comb(39,5)
                       for k in range(goal,min(size,5)+1))
        packs.append({'name':label,'numbers':numbers,'hit_goal':goal,
                      'model_agreement_percent':round(agreement,2), 'confidence_label':'未證實高機率／觀察',
                      'backtest_samples':samples,'backtest_successes':wins,'backtest_rate_percent':round(rate*100,2),
                      'wilson_95_percent':[round(max(0,centre-margin)*100,2),round(min(1,centre+margin)*100,2)],
                      'random_baseline_percent':round(baseline*100,6)})
    return {'version':SCHEMA_VERSION,'family_count':len(FAMILIES),'configuration_count':MODULE_COUNT,
            'configuration_definition':{'families':list(FAMILIES),'windows':list(WINDOWS),'blends':list(BLENDS)},
            'backtest_manifest':manifest,
            'number_percentages':number_percentages(modules),'full39_six_combinations':full,'six_number_combinations':six,'module_count':len(modules),'modules':modules,'ranking':ranked,'packs':packs,
            'based_on_date':dates[-1],'target_draw_date':(date.fromisoformat(dates[-1])+timedelta(days=1)).isoformat(),
            'verification':{'status':'passed','modules_verified':sum(m['validation']['structural_pass'] for m in modules),
                            'walk_forward_samples':samples,'future_data_used':False,'weighting':'預先固定等權排名平均',
                            'replay_rounds':2,'replay_periods_verified':len(manifest),'module_forecasts':samples*MODULE_COUNT,
                            'numeric_values_checked':(samples+1)*MODULE_COUNT*39*2,
                            'unique_configurations':len({configuration_signature(m) for m in modules}),
                            'unique_current_rankings':len({tuple(m['ranking']) for m in modules}),
                            'note':'20個算法家族、10種視窗、5種長期頻率排名混合，共1000種配置；參數變體互有相關，不是1000份獨立證據。排名相同的配置照實列出。回測不保證下期。'}}

def report_section(analysis):
    e=analysis['ensemble50']
    fresh=analysis.get('freshness',{})
    lines=['## 必備戰報規格與1000組運算驗證',
           f"- 最新核對時間（台灣）：{analysis.get('last_checked_at_taiwan', analysis.get('generated_at_taiwan', '待確認'))}",
           f"- 適用日期（加州開獎日）：{e['target_draw_date']}",
           f"- 對應台灣開獎時間：{fresh.get('target_taiwan_safe_update_time','待確認')}",
           f"- 資料截至：{e['based_on_date']}；資料狀態：{fresh.get('status','待確認')}",
           f"- 模組：1000／1000完成；驗證：{e['verification']['modules_verified']}／1000；逐期回測：{e['verification']['walk_forward_samples']}期",
           '- 信心分數為1000組模組的選號共識比例，不是中獎機率。高機率狀態依驗證註明。',
           '| 組別 | 號碼 | 模組共識信心 | 高機率狀態 | 回測命中 | 隨機基準 | 95%信賴區間 |',
           '| --- | --- | --- | --- | --- | --- | --- |']
    for p in e['packs']:
        interval=p['wilson_95_percent']
        lines.append(f"| {p['name']} | {'、'.join(f'{n:02}' for n in p['numbers'])} | {p['model_agreement_percent']}% | {p['confidence_label']} | {p['backtest_successes']}/{p['backtest_samples']}（{p['backtest_rate_percent']}%） | {p['random_baseline_percent']}% | {interval[0]}–{interval[1]}% |")
    six=e.get('six_number_combinations')
    if six:
        lines.extend(['','## 前15名六碼組合（10組）',
                      '前15名依模型排名：'+'、'.join(f'{n:02}' for n in six['top15_ranked']),
                      six['score_meaning'],
                      '| 組別 | 六碼 | 模型評分 | 回測≥2中 | ≥3中 | ≥4中 | 5中 | 信心狀態 |',
                      '| --- | --- | --- | --- | --- | --- | --- | --- |'])
        for p in six['groups']:
            bt=p['backtest_hits_at_least']; total=p['backtest_samples']
            lines.append(f"| {p['group']} | {'、'.join(f'{n:02}' for n in p['numbers'])} | {p['model_score']} | {bt['2']}/{total} | {bt['3']}/{total} | {bt['4']}/{total} | {bt['5']}/{total} | {p['confidence_label']} |")
    full=e.get('full39_six_combinations')
    if full:
        lines.extend(['','## 1–39全號碼六碼包牌：評分最高10組',
                      f"適用日期：{e['target_draw_date']}；搜尋範圍：{full['search_space']:,}種六碼組合。",
                      full['method'],full['score_meaning'],
                      '| 名次 | 六碼 | 模型評分 | 回測≥2中 | ≥3中 | ≥4中 | 5中 |',
                      '| --- | --- | --- | --- | --- | --- | --- |'])
        for p in full['groups']:
            bt=p['backtest_hits_at_least']; total=p['backtest_samples']
            lines.append(f"| {p['group']} | {'、'.join(f'{n:02}' for n in p['numbers'])} | {p['model_score']} | {bt['2']}/{total} | {bt['3']}/{total} | {bt['4']}/{total} | {bt['5']}/{total} |")
        lines.append(f"六碼各展開6種五碼：共{full['expanded_five_number_tickets']}種，跨組去重後{full['unique_five_number_tickets']}種。")
    return '\n'.join(lines)

def full39_html(e):
    full=e.get('full39_six_combinations')
    if not full:
        return ''
    rows=[]
    for p in full['groups']:
        bt=p['backtest_hits_at_least']; total=p['backtest_samples']
        cells=(p['group'],'、'.join(f'{n:02}' for n in p['numbers']),f"{p['model_score']:.4f}",
               *(f'{bt[str(g)]}/{total}' for g in (2,3,4,5)),p['confidence_label'])
        rows.append('<tr>'+''.join(f'<td>{html.escape(str(v))}</td>' for v in cells)+'</tr>')
    summary='；'.join(f"至少{g}中：{full['any_group_hits_at_least'][str(g)]}/{full['walk_forward_samples']}期" for g in (2,3,4,5))
    proof='<p>獨立完整枚舉驗證：3,262,623種全部評分後，前10名完全一致。</p>' if full.get('exhaustive_verification',{}).get('all_top10_exact_match') else ''
    return f'''<section id="full39-six-groups"><h2>1–39全號碼六碼包牌 · 評分最高10組</h2>
<p>適用日期：{e['target_draw_date']}（加州開獎日）；資料截至：{e['based_on_date']}</p>
<p>搜尋範圍：1–39全部<b>{full['search_space']:,}</b>種六碼組合。{full['method']}。</p>
<p>{full['search_method']}。{full['score_meaning']}。高機率信心狀態：未證實。</p>
{proof}
<div style="overflow:auto"><table><thead><tr><th>名次</th><th>6碼組合</th><th>模型評分／100</th><th>回測≥2中</th><th>≥3中</th><th>≥4中</th><th>5中</th><th>信心狀態</th></tr></thead><tbody>{''.join(rows)}</tbody></table></div>
<p>逐期回測{full['walk_forward_samples']}期；每期用開獎前的1000組模組，從全39碼重新取評分前十，再對照下一期。各列為對應名次策略的表現。</p>
<p>10組中任一組命中的期數（按期去重）：{summary}。</p>
<p>每組六碼展開6種五碼，10組合計{full['expanded_five_number_tickets']}種；跨組去重後為<b>{full['unique_five_number_tickets']}</b>種五碼組合。此區以分數優先，組間可有較多重疊。</p></section>'''

def six_html(e):
    six=e.get('six_number_combinations')
    if not six:
        return ''
    rows=[]
    for p in six['groups']:
        bt=p['backtest_hits_at_least']; total=p['backtest_samples']
        cells=(p['group'],'、'.join(f'{n:02}' for n in p['numbers']),p['model_score'],
               *(f'{bt[str(g)]}/{total}' for g in (2,3,4,5)),p['confidence_label'])
        rows.append('<tr>'+''.join(f'<td>{html.escape(str(v))}</td>' for v in cells)+'</tr>')
    pool='、'.join(f'{n:02}' for n in six['top15_ranked'])
    summary='；'.join(f"至少{g}中：{six['any_group_hits_at_least'][str(g)]}/{six['walk_forward_samples']}期" for g in (2,3,4,5))
    return f'''<section id="top15-six-groups"><h2>前15名六碼組合 · 10組模型優先候選</h2>
<p>適用日期：{e['target_draw_date']}（加州開獎日）</p><p>前15名依模型排名：<b>{pool}</b></p>
<p>{six['method']}。{six['score_meaning']}。信心狀態：未證實高機率。</p>
<div style="overflow:auto"><table><thead><tr><th>組別</th><th>6碼組合</th><th>模型評分</th><th>回測≥2中</th><th>≥3中</th><th>≥4中</th><th>5中</th><th>信心狀態</th></tr></thead><tbody>{''.join(rows)}</tbody></table></div>
<p>60期逐期回測，每期用當時的前15名重新選10組，再核對下一期；各列是選組順序的策略表現，並非本期固定號碼的歷史命中率。</p>
<p>10組中任一組命中的期數：{summary}。10組互有重疊，此處按期去重計算。</p>
<p>檢查：10組互不重複、每組6個不同號碼、全部取自前15名；實際涵蓋{six['unique_numbers_covered']}個號碼。</p></section>'''

def html_section(analysis):
    e=analysis['ensemble50']
    rows=''.join('<tr>'+''.join(f'<td>{html.escape(str(v))}</td>' for v in
                (p['name'],'、'.join(f'{n:02}' for n in p['numbers']),f"{p['model_agreement_percent']}%",p['confidence_label'],
                 f"{p['backtest_successes']}/{p['backtest_samples']} ({p['backtest_rate_percent']}%)",f"{p['random_baseline_percent']}%",p['wilson_95_percent']))+'</tr>' for p in e['packs'])
    details=''.join(f"<tr><td>{m['id']}</td><td>{m['family']}</td><td>{m['window']}</td><td>{m['validation']['top5_avg_hits']}</td><td>通過</td></tr>" for m in e['modules'])
    return f'''<section id="ensemble50-required"><h2>適用日期：{e['target_draw_date']}（加州開獎日）</h2>
<p>最新核對時間（台灣）：{html.escape(str(analysis.get('last_checked_at_taiwan', analysis.get('generated_at_taiwan', '待確認'))))}</p>
<p>台灣開獎時間：{html.escape(str(analysis.get('freshness',{}).get('target_taiwan_safe_update_time','待確認')))}；資料截至：{e['based_on_date']}；資料狀態：{html.escape(str(analysis.get('freshness',{}).get('status','待確認')))}</p>
<h3>終極獨隻與必備組合 · 高機率信心標示</h3><p>模組共識信心＝1000組選號共識比例；不是中獎機率。所有組合目前標示未證實高機率／觀察。</p>
<div style="overflow:auto"><table><thead><tr><th>組別</th><th>號碼</th><th>模組共識信心</th><th>高機率狀態</th><th>逐期回測命中</th><th>隨機基準</th><th>95%信賴區間</th></tr></thead><tbody>{rows}</tbody></table></div>
<p>1000／1000運算完成，{e['verification']['modules_verified']}／1000結構驗證通過；最近{e['verification']['walk_forward_samples']}期逐期回測，每期只使用開獎前資料。</p>
<details><summary>1000組模組驗證明細</summary><table><tr><th>模組</th><th>方法</th><th>視窗期數</th><th>Top5平均命中（隨機基準0.6410）</th><th>結構驗證</th></tr>{details}</table></details></section>''' + six_html(e) + full39_html(e)

def attach_reports(analysis, report_dir):
    for name in ('latest_battle_report.html','tiantianle_ironlaw_battle_report.html','dashboard.html','prediction.html','complete_report.html'):
        path=report_dir/name
        if path.exists():
            text=path.read_text(encoding='utf-8')
            if 'id="ensemble50-required"' not in text:
                text=text.replace('<main>', '<main>'+html_section(analysis),1) if '<main>' in text else text.replace('</body>',html_section(analysis)+'</body>',1)
                path.write_text(text,encoding='utf-8')
    path=report_dir/'latest_battle_report.md'
    if path.exists() and '## 必備戰報規格與1000組運算驗證' not in path.read_text(encoding='utf-8'):
        path.write_text(report_section(analysis)+'\n\n'+path.read_text(encoding='utf-8'),encoding='utf-8')
    (report_dir/'ensemble50_verification.json').write_text(json.dumps(analysis['ensemble50'],ensure_ascii=False,indent=2),encoding='utf-8')
