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


def models_content(a):
    e=a['ensemble50']
    percentages=percentage_map(e)
    rows=[[i+1,m['id'],m['family'],m['window'],m['parameters']['long_frequency_rank_blend'],number_labels(m['ranking'][:1],percentages),number_labels(m['ranking'][:5],percentages),m['validation']['single_hits'],m['validation']['top5_avg_hits'],m['validation']['samples']] for i,m in enumerate(e['modules'])]
    return f'''<section class="panel"><h2>1000組候選模組</h2><p class="muted">20個算法家族、10種視窗、5種長期頻率排名混合。下表顯示每組配置、實際首選、前五名單與60期逐期回測；固定等權融合，不以事後最高成績取代融合結果。號碼旁百分比統一使用本期1000組融合排名分數，個別模組的選號順序仍依其自身排名。</p><p class="muted">本期實際不同排名 {e['verification']['unique_current_rankings']} 種；雙輪重算 {e['verification']['replay_rounds']} 輪，每輪回測 {e['verification']['module_forecasts']:,} 次模組預測。</p>{table(['序','模組','算法家族','歷史窗口','長期混合比','本期首選（融合分數％）','本期前五（融合分數％）','獨支命中／60','前五平均命中','回測期數'],rows)}<p class="research-label">信心等級：研究參考。這些模組共用資料，不能視為1000份獨立證據。</p></section>'''


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
