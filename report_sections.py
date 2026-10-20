"""Dated report sections share the same analysis and navigation."""
import csv
import json
from pathlib import Path
from report539_style import esc, balls, table, navigation, STYLE_FROM_539, EXTRA_STYLE, percentage_map, number_labels


def history_rows(path, analysis):
    with Path(path).open(encoding='utf-8-sig',newline='') as handle:
        rows=[{'index':int(r['local_index']),'date':r['draw_date'],
               'numbers':[int(r['n'+str(i)]) for i in range(1,6)]} for r in csv.DictReader(handle)]
    rows.sort(key=lambda r:(r['date'],r['index']),reverse=True)
    if len(rows)!=analysis['draw_count'] or rows[0]['date']!=analysis['latest_draw']['draw_date'] or sorted(rows[0]['numbers'])!=sorted(analysis['latest_draw']['numbers']):
        raise ValueError('History does not match the current report')
    if any(len(set(r['numbers']))!=5 or any(n<1 or n>39 for n in r['numbers']) for r in rows):
        raise ValueError('Invalid history numbers')
    return rows


def shell(key, title, content, a, cloud_url):
    return f'''<!doctype html><html lang="zh-Hant"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><base href="{esc(cloud_url)}"><title>{title}｜天天樂</title><style>{STYLE_FROM_539}{EXTRA_STYLE}
    .history-controls{{display:flex;flex-wrap:wrap;gap:10px;margin:18px 0}}.history-controls input{{min-width:150px}}.history-controls button{{font-size:13px}}.review-list{{padding-left:20px;font-size:13px;line-height:2}}</style></head>
    <body data-report-section="{key}"><header><div class="brand"><div class="logo">天天樂</div><div>加州 Fantasy 5<span>雲端戰報 · 手機與電腦同步</span></div></div><span class="status"><i></i>同一份報告資料</span></header>{navigation(key)}
    <main><div class="toolbar"><p>最新運算（台灣）：{esc(a['generated_at_taiwan'])}<br>資料截至加州 {esc(a['latest_draw']['draw_date'])} · 本期適用 {esc(a['target_draw_date'])}</p><button type="button" onclick="forceRefresh()">同步最新戰報</button></div>
    <p class="alert" id="localSnapshotNote" hidden>本機離線快照，尚未同步。<a href="{esc(cloud_url+key+'/')}">開啟線上頁面</a></p>
    <div class="page-title"><small>天天樂 · California Fantasy 5</small><h1>{title}</h1></div>{content}</main><footer>天天樂 · California Fantasy 5<br>模型評分與歷史回測不保證下期。</footer></body></html>'''


def review_content(a):
    review=a.get('failure_review',{})
    settled=review.get('last_settled')
    if not settled:
        return '<section class="panel"><h2>尚無已結算紀錄</h2><p>開獎前已保存的預測完成核對後，才顯示命中結果。</p></section>'
    actual=set(settled['actual_numbers'])
    rows=[]
    for key,p in settled.get('strong_pack_hits',{}).items():
        names={'strong_single':'原單碼模型','two_hit_one':'原二碼模型','three_hit_two':'原三碼模型','five_hit_two':'原五碼模型','nine_hit_three':'原九碼模型'}
        hit=len(set(p['numbers']) & actual)
        if hit!=p['hits']:raise ValueError('Settled hit count mismatch')
        rows.append([names.get(key,key),' '.join(f'{n:02d}' for n in p['numbers']),hit,p['hit_goal'],'達標' if hit>=p['hit_goal'] else '未達標'])
    candidates=[[c['rank'],f"{c['number']:02d}",'命中' if c['number'] in actual else '未中'] for c in settled.get('candidate_review',[])]
    recent=[]
    for r in review.get('recent_settled',[]):
        if isinstance(r,dict):recent.append([r.get('target_date',r.get('actual_date','未提供')),r.get('top5_hits','未提供'),r.get('top10_hits','未提供'),r.get('top15_hits','未提供')])
    return f'''<section class="panel"><div class="section-title"><h2>最新一期已結算檢討</h2><small>開獎日 {esc(settled['actual_date'])}</small></div>
    {balls(settled['actual_numbers'],False)}<p class="muted">這是開獎前保存的原模型預測紀錄，與目前1000組融合主選分開核對。未保存的融合預測不事後補算為實戰。</p>
    {table(['封存模型','原預測號碼','實際命中','命中目標','結果'],rows)}</section>
    <section class="panel"><h2>近期已結算結果</h2>{table(['目標開獎日','前五命中','前十命中','前十五命中'],recent) if recent else '<p class="muted">尚無其他近期結算。</p>'}</section>
    <section class="panel"><h2>失準檢討紀錄</h2><ul class="review-list">{''.join('<li>'+esc(x)+'</li>' for x in review.get('actions',[]))}</ul><details><summary>展開上期候選號碼逐號核對</summary>{table(['原排名','號碼','核對結果'],candidates)}</details></section>'''


def history_content(rows):
    encoded=json.dumps(rows,ensure_ascii=False,separators=(',',':')).replace('<','\\u003c')
    return f'''<section class="panel"><div class="section-title"><h2>完整開獎歷史</h2><small>{len(rows):,} 期 · {rows[-1]['date']} 至 {rows[0]['date']}</small></div>
    <p class="muted">資料序號是系統歷史索引。每頁50期；可依開獎日期篩選。</p><div class="history-controls"><input id="historyDate" type="date" aria-label="篩選開獎日期"><button id="historySearch">查詢日期</button><button class="secondary" id="historyAll">全部歷史</button><a class="action-link" href="history.csv" download>下載完整CSV</a></div>
    <p id="historySummary" role="status"></p><div class="table-wrap"><table><thead><tr><th>資料序號</th><th>開獎日期</th><th>開獎號碼</th></tr></thead><tbody id="historyRows"></tbody></table></div>
    <div class="history-controls"><button class="secondary" id="historyPrevious">上一頁</button><button id="historyNext">下一頁</button></div></section>
    <script id="historyData" type="application/json">{encoded}</script><script>
    (()=>{{const all=JSON.parse(document.getElementById('historyData').textContent);let current=all,page=0;const size=50;
    function render(){{const start=page*size;document.getElementById('historyRows').innerHTML=current.slice(start,start+size).map(r=>'<tr><td>'+r.index+'</td><td>'+r.date+'</td><td>'+r.numbers.map(n=>String(n).padStart(2,'0')).join('　')+'</td></tr>').join('');document.getElementById('historySummary').textContent='共 '+current.length+' 期 · 第 '+(current.length?page+1:0)+'／'+Math.ceil(current.length/size)+' 頁';document.getElementById('historyPrevious').disabled=page===0;document.getElementById('historyNext').disabled=start+size>=current.length;}}
    document.getElementById('historySearch').onclick=()=>{{const value=document.getElementById('historyDate').value;current=value?all.filter(r=>r.date===value):all;page=0;render();}};
    document.getElementById('historyAll').onclick=()=>{{document.getElementById('historyDate').value='';current=all;page=0;render();}};
    document.getElementById('historyPrevious').onclick=()=>{{if(page>0)page--;render();}};document.getElementById('historyNext').onclick=()=>{{if((page+1)*size<current.length)page++;render();}};render();}})();</script>'''


def algorithm_evidence(e):
    report=e['algorithm_report'];rows=[];cards=[];percentages=percentage_map(e)
    for m in report['representatives']:
        v=m['validation'];scores={int(n):x for n,x in m['scores'].items()}
        raw=' / '.join(f"{n:02d}: {scores[n]:.5g}" for n in m['ranking'][:5])
        blocks=' / '.join(f"{b['single_hits']}/{b['samples']}；{b['top5_avg_hits']:.3f}" for b in v['blocks'])
        rows.append([m['family'],m['id'],raw,number_labels(m['ranking'][:5],percentages),f"{v['single_hits']}/{v['samples']}",v['top5_avg_hits'],v['top5_excess_over_random'],blocks])
        trace=[[r['target_date'],r['top1'],' '.join(f'{n:02d}' for n in r['top5']),' '.join(f'{n:02d}' for n in r['actual']),r['top5_hits']] for r in m['trace']]
        cards.append(f"<details class='panel' data-algorithm='{esc(m['family'])}'><summary>{esc(m['family'])} · 公式、原始分數及逐期回測</summary><p>{esc(m['logic'])}</p><p>固定代表：90期視窗，設定2。原始分數尺度因算法而異，不跨算法比較，也不是開出機率。</p>{table(['目標日期','預測獨隻','預測前五','實際五碼','前五命中'],trace)}</details>")
    alternative=report['alternative_validation']
    alternatives={r['id']:r for r in alternative['results']}
    comparison=[[m['family'],f"{m['validation']['single_hits']}/60",m['validation']['top5_avg_hits'],f"{alternatives[m['id']]['frozen_single_hits']}/60",alternatives[m['id']]['frozen_top5_mean_hits'],alternatives[m['id']]['permutation_p_exploratory'],alternatives[m['id']]['permutation_p_holm']] for m in report['representatives']]
    alternative_html=f"<section class='panel' id='alternative-validation'><h2>不同回測方式分開比較</h2><p>逐期回測：每期重新訓練。保留測試：每20期開始前訓練一次，整段沿用該次固定選號。兩者使用相同60個目標日，各自計分。</p>{table(['方法','逐期獨隻','逐期前五均中','固定20期獨隻','固定20期前五均中','打亂對照p（探索）','Holm調整p'],comparison)}<p>{esc(alternative['permutation_limit'])}。p值不是號碼開出百分比。</p></section>"
    pairs=report['pairwise_diversity']
    same=sum(p['top5_overlap']==5 for p in pairs)
    pairrows=[[p['a'],p['b'],p['spearman'],p['top5_overlap']] for p in pairs]
    return f"""<section class='panel' id='algorithm-evidence'><h2>19種預測算法＋1種隨機對照</h2><p>1000是參數實驗數，不是1000種算法。已移除共同長期頻率混合；每種方法直接使用自己的原始評分公式。950組預測配置參與融合，50組隨機對照只做比較。</p><p>{esc(report['representative_rule'])}。{esc(report['evaluation_rule'])}</p><p>公平隨機基準：獨隻5/39＝12.82%；前五平均25/39＝0.6410顆。號碼旁百分比仍為全系統融合排名分數；各算法原始分數另欄列示。下表超額為前五平均減0.6410；正數也不代表已證實優勢。三段依日期順序各20期，顯示獨隻命中／樣本、前五平均。</p>{table(['方法','固定代表','本期前五：各自原始分數','前五：全系統融合分數％','獨隻命中','前五平均','較隨機超額','三段回測：獨隻；前五'],rows)}<p>{esc(report['limits'])}</p><p>20個代表兩兩比較共{len(pairs)}對；本期前五完全相同{same}對。排名相關與選號重疊可在下方逐對核對。</p><details><summary>展開190對算法差異：Spearman相關與前五交集</summary>{table(['方法A','方法B','排名相關−1至1','前五交集0至5'],pairrows)}</details></section>{alternative_html}{''.join(cards)}"""


def models_content(a):
    e=a['ensemble50'];percentages=percentage_map(e)
    rows=[[m['id'],m['family'],m['window'],m['parameters']['algorithm_setting'],number_labels(m['ranking'][:5],percentages),m['validation']['single_hits'],m['validation']['top5_avg_hits'],m['validation']['samples']] for m in e['modules']]
    return algorithm_evidence(e)+f"<p><a class='action-link' href='latest_analysis.json' download>下載各算法原始分數及完整回測JSON</a></p><section class='panel'><details><summary>1000組參數實驗明細（非1000種算法）</summary>{table(['配置','方法','視窗','算法設定','自身前五（融合分數％）','獨隻命中','前五平均','期數'],rows)}</details></section>"


def system_content(a,workflow_url):
    e=a['ensemble50']
    rescue=workflow_url.replace('tiantianle-cloud-auto-update.yml','tiantianle-cloud-self-heal.yml')
    return f'''<section class="panel"><h2>更新與故障檢修</h2><p>雲端負責抓取資料、運算、驗證及發布。開啟以下更新頁面，登入你的GitHub帳號後按「Run workflow」執行。</p>
    <div class="history-controls"><a class="action-link" href="{esc(workflow_url)}" target="_blank" rel="noopener">手動更新最新 · 開啟雲端更新</a><a class="action-link" href="{esc(rescue)}" target="_blank" rel="noopener">故障檢修 · 開啟救援流程</a><button class="secondary" onclick="forceRefresh()">重新同步戰報</button></div>
    <div class="stats-grid"><div class="stat"><span>最新開獎日期（加州）</span><strong>{esc(a['latest_draw']['draw_date'])}</strong></div><div class="stat"><span>本期適用日期（加州）</span><strong>{esc(a['target_draw_date'])}</strong></div><div class="stat"><span>模組結構驗證</span><strong>{e['verification']['modules_verified']}／1000</strong></div><div class="stat"><span>逐期回測</span><strong>{e['verification']['walk_forward_samples']} 期</strong></div></div>
    <p class="muted">以上是目前發布報告的資訊；雲端任務的即時執行結果請查看更新頁面。</p>
    <a class="action-link" href="repair_validation.json" target="_blank" rel="noopener">查看本次戰報驗證結果</a><a class="action-link" href="reset.html">清除舊快取並重讀</a></section>'''


def render_sections(a, rows, cloud_url, workflow_url):
    content={'review':('開獎檢討',review_content(a)), 'history':('歷史資料',history_content(rows)),
             'models':('候選模型',models_content(a)), 'system':('更新與檢修',system_content(a,workflow_url))}
    return {key:shell(key,title,body,a,cloud_url) for key,(title,body) in content.items()}
