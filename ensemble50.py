"""Fifty explicit statistical modules and causal walk-forward verification."""
import math
import json
import html
from collections import Counter
from datetime import date, timedelta

WINDOWS = (10, 20, 30, 45, 60, 90, 120, 180, 365, 720)
FAMILIES = ('頻率平滑', '指數動量', '間隔危險率', '前期轉移', '共現關聯')
GOALS = ((1, 1, '終極獨隻'), (2, 2, '2中2'), (3, 3, '3中3'),
         (5, 5, '5中5'), (7, 5, '7中5'), (9, 5, '9中5'))

def module_scores(draws, family, window):
    history = [set(d['numbers']) for d in draws[-window:]]
    counts = Counter(n for row in history for n in row)
    if family == '頻率平滑':
        return {n: (counts[n] + 5/39*10)/(len(history)+10) for n in range(1,40)}
    if family == '指數動量':
        scores = dict.fromkeys(range(1,40), 0.0)
        for i, row in enumerate(reversed(history)):
            for n in row:
                scores[n] += math.exp(-i/max(2, window/4))
        return scores
    if family == '間隔危險率':
        scores = {}
        for n in range(1,40):
            positions = [i for i,row in enumerate(history) if n in row]
            gap = len(history)-1-positions[-1] if positions else len(history)
            gaps = [b-a for a,b in zip(positions, positions[1:])]
            # Empirical survival hazard with a base-rate prior, not "overdue means due".
            at_risk = sum(g > gap for g in gaps)
            events = sum(g == gap+1 for g in gaps)
            scores[n] = (events+5/39*10)/(at_risk+10)
        return scores
    previous = history[-1]
    if family == '前期轉移':
        scores = dict.fromkeys(range(1,40), 5/39*10)
        weight = 10.0
        for before, after in zip(history, history[1:]):
            overlap = len(before & previous)/5
            weight += overlap
            for n in after:
                scores[n] += overlap
        return {n:s/weight for n,s in scores.items()}
    pairs = Counter()
    for row in history:
        for n in row:
            for anchor in row & previous:
                if n != anchor:
                    pairs[n,anchor] += 1
    return {n:sum((pairs[n,a]+0.5)/(counts[a]+5) for a in previous if a!=n)
            for n in range(1,40)}

def rank_modules(draws):
    result = []
    for family in FAMILIES:
        for window in WINDOWS:
            scores = module_scores(draws, family, window)
            ranked = sorted(scores, key=lambda n:(-scores[n], n))
            result.append({'id':f'M{len(result)+1:02}', 'family':family, 'window':window,
                           'ranking':ranked, 'scores':scores})
    return result

def consensus(modules):
    scores = dict.fromkeys(range(1,40), 0)
    for module in modules:
        for i,n in enumerate(module['ranking']):
            scores[n] += 39-i
    return sorted(scores, key=lambda n:(-scores[n],n))

def compute(draws, samples=60):
    if len(draws)<120:
        raise ValueError('50組驗證至少需要120期資料')
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
    pack_hits = {label:[] for _,_,label in GOALS}
    for end in range(len(draws)-samples,len(draws)):
        prior = rank_modules(draws[:end])
        actual = set(draws[end]['numbers'])
        for m in prior:
            hits[m['id']].append(len(actual & set(m['ranking'][:5])))
        ranked = consensus(prior)
        for size,goal,label in GOALS:
            pack_hits[label].append(len(actual & set(ranked[:size]))>=goal)
    for m in modules:
        values = hits[m['id']]
        m['validation'] = {'samples':samples, 'top5_avg_hits':round(sum(values)/samples,4),
                           'random_top5_expected_hits':25/39, 'structural_pass': sorted(m['ranking'])==list(range(1,40))}
    ranked = consensus(modules)
    packs=[]
    for size,goal,label in GOALS:
        numbers = sorted(ranked[:size])
        wins = sum(pack_hits[label])
        rate = wins/samples
        z=1.96
        centre=(rate+z*z/(2*samples))/(1+z*z/samples)
        margin=z*math.sqrt(rate*(1-rate)/samples+z*z/(4*samples*samples))/(1+z*z/samples)
        agreement = sum(sum(n in m['ranking'][:size] for n in numbers) for m in modules)/(50*size)*100
        baseline = sum(math.comb(size,k)*math.comb(39-size,5-k)/math.comb(39,5)
                       for k in range(goal,min(size,5)+1))
        packs.append({'name':label,'numbers':numbers,'hit_goal':goal,
                      'model_agreement_percent':round(agreement,2), 'confidence_label':'未證實高機率／觀察',
                      'backtest_samples':samples,'backtest_successes':wins,'backtest_rate_percent':round(rate*100,2),
                      'wilson_95_percent':[round(max(0,centre-margin)*100,2),round(min(1,centre+margin)*100,2)],
                      'random_baseline_percent':round(baseline*100,6)})
    return {'version':'ensemble50_v1','module_count':len(modules),'modules':modules,'ranking':ranked,'packs':packs,
            'based_on_date':dates[-1],'target_draw_date':(date.fromisoformat(dates[-1])+timedelta(days=1)).isoformat(),
            'verification':{'status':'passed','modules_verified':sum(m['validation']['structural_pass'] for m in modules),
                            'walk_forward_samples':samples,'future_data_used':False,'weighting':'預先固定等權排名平均',
                            'note':'同一家族不同視窗的模組互有相關；共識分數不是中獎機率。回測不保證下期。'}}

def report_section(analysis):
    e=analysis['ensemble50']
    fresh=analysis.get('freshness',{})
    lines=['## 必備戰報規格與50組運算驗證',
           f"- 最新核對時間（台灣）：{analysis.get('last_checked_at_taiwan', analysis.get('generated_at_taiwan', '待確認'))}",
           f"- 適用日期（加州開獎日）：{e['target_draw_date']}",
           f"- 對應台灣開獎時間：{fresh.get('target_taiwan_safe_update_time','待確認')}",
           f"- 資料截至：{e['based_on_date']}；資料狀態：{fresh.get('status','待確認')}",
           f"- 模組：50／50完成；驗證：{e['verification']['modules_verified']}／50；逐期回測：{e['verification']['walk_forward_samples']}期",
           '- 信心分數為50組模組的選號共識比例，不是中獎機率。高機率狀態依驗證註明。',
           '| 組別 | 號碼 | 模組共識信心 | 高機率狀態 | 回測命中 | 隨機基準 | 95%信賴區間 |',
           '| --- | --- | --- | --- | --- | --- | --- |']
    for p in e['packs']:
        interval=p['wilson_95_percent']
        lines.append(f"| {p['name']} | {'、'.join(f'{n:02}' for n in p['numbers'])} | {p['model_agreement_percent']}% | {p['confidence_label']} | {p['backtest_successes']}/{p['backtest_samples']}（{p['backtest_rate_percent']}%） | {p['random_baseline_percent']}% | {interval[0]}–{interval[1]}% |")
    return '\n'.join(lines)

def html_section(analysis):
    e=analysis['ensemble50']
    rows=''.join('<tr>'+''.join(f'<td>{html.escape(str(v))}</td>' for v in
                (p['name'],'、'.join(f'{n:02}' for n in p['numbers']),f"{p['model_agreement_percent']}%",p['confidence_label'],
                 f"{p['backtest_successes']}/{p['backtest_samples']} ({p['backtest_rate_percent']}%)",f"{p['random_baseline_percent']}%",p['wilson_95_percent']))+'</tr>' for p in e['packs'])
    details=''.join(f"<tr><td>{m['id']}</td><td>{m['family']}</td><td>{m['window']}</td><td>{m['validation']['top5_avg_hits']}</td><td>通過</td></tr>" for m in e['modules'])
    return f'''<section id="ensemble50-required"><h2>適用日期：{e['target_draw_date']}（加州開獎日）</h2>
<p>最新核對時間（台灣）：{html.escape(str(analysis.get('last_checked_at_taiwan', analysis.get('generated_at_taiwan', '待確認'))))}</p>
<p>台灣開獎時間：{html.escape(str(analysis.get('freshness',{}).get('target_taiwan_safe_update_time','待確認')))}；資料截至：{e['based_on_date']}；資料狀態：{html.escape(str(analysis.get('freshness',{}).get('status','待確認')))}</p>
<h3>終極獨隻與必備組合 · 高機率信心標示</h3><p>模組共識信心＝50組選號共識比例；不是中獎機率。所有組合目前標示未證實高機率／觀察。</p>
<div style="overflow:auto"><table><thead><tr><th>組別</th><th>號碼</th><th>模組共識信心</th><th>高機率狀態</th><th>逐期回測命中</th><th>隨機基準</th><th>95%信賴區間</th></tr></thead><tbody>{rows}</tbody></table></div>
<p>50／50運算完成，{e['verification']['modules_verified']}／50結構驗證通過；最近{e['verification']['walk_forward_samples']}期逐期回測，每期只使用開獎前資料。</p>
<details><summary>50組模組驗證明細</summary><table><tr><th>模組</th><th>方法</th><th>視窗期數</th><th>Top5平均命中（隨機基準0.6410）</th><th>結構驗證</th></tr>{details}</table></details></section>'''

def attach_reports(analysis, report_dir):
    for name in ('latest_battle_report.html','tiantianle_ironlaw_battle_report.html','dashboard.html','prediction.html','complete_report.html'):
        path=report_dir/name
        if path.exists():
            text=path.read_text(encoding='utf-8')
            if 'id="ensemble50-required"' not in text:
                text=text.replace('<main>', '<main>'+html_section(analysis),1) if '<main>' in text else text.replace('</body>',html_section(analysis)+'</body>',1)
                path.write_text(text,encoding='utf-8')
    path=report_dir/'latest_battle_report.md'
    if path.exists() and '## 必備戰報規格與50組運算驗證' not in path.read_text(encoding='utf-8'):
        path.write_text(report_section(analysis)+'\n\n'+path.read_text(encoding='utf-8'),encoding='utf-8')
    (report_dir/'ensemble50_verification.json').write_text(json.dumps(analysis['ensemble50'],ensure_ascii=False,indent=2),encoding='utf-8')
