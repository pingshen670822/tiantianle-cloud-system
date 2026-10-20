"""539 report presentation, using only verified Tiantianle report fields."""
import hashlib
import html
import json

STYLE_FROM_539 = ":root{--bg:#f3f5f8;--ink:#182638;--muted:#69798c;--red:#bb2736;--line:#e1e6ed;--blue:#12273b}*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font-family:'Microsoft JhengHei','PingFang TC',sans-serif;font-size:15px;line-height:1.6}a{color:inherit;text-decoration:none}button,input{font:inherit}button{border:0;border-radius:9px;background:var(--red);color:white;padding:11px 17px;font-weight:700;cursor:pointer;white-space:nowrap}button:disabled{opacity:.55;cursor:wait}button.secondary{background:white;border:1px solid #c6cfda;color:var(--ink)}button:focus-visible,a:focus-visible,input:focus-visible,summary:focus-visible{outline:3px solid #e39a27;outline-offset:4px}header{padding:20px max(24px,calc((100% - 1120px)/2));display:flex;align-items:center;justify-content:space-between;background:var(--blue);color:white}.brand{display:flex;align-items:center;gap:12px;font-size:21px;font-weight:800;line-height:1.25}.brand div span{display:block;color:#b3c1cf;font-weight:400;font-size:12px;letter-spacing:3px;margin-top:5px}.logo{border:1px solid #496072;border-radius:8px;padding:9px 11px;font-size:25px;color:#ffb74f}.status{font-size:12px;color:#adcbbf;display:flex;gap:7px;align-items:center}.status i{width:7px;height:7px;background:#61b99a;border-radius:50%}.status.warning{color:#f6bd70}.status.warning i{background:#f6bd70}nav{display:flex;gap:32px;padding:0 max(24px,calc((100% - 1120px)/2));background:white;border-bottom:1px solid var(--line)}nav a{padding:17px 0;color:var(--muted);font-size:14px;font-weight:700;border-bottom:3px solid transparent}nav a.active{color:var(--red);border-color:var(--red)}main{max-width:1120px;margin:auto;padding:24px 20px}.toolbar{display:flex;justify-content:space-between;align-items:center;gap:15px;margin-bottom:20px}.toolbar p{font-size:13px;color:var(--muted);margin:0}.toolbar div{display:flex;gap:9px}.alert{border:1px solid #edc9a2;background:#fff5e6;color:#8c4618;border-radius:10px;padding:12px 16px;margin-bottom:18px}.hero{background:var(--blue);color:white;border-radius:16px;overflow:hidden;margin-bottom:20px;box-shadow:0 6px 20px #11263812}.hero-top{padding:20px 28px 0;display:flex;align-items:center;justify-content:space-between}.hero-top>span{font-size:12px;letter-spacing:2px;color:#ffbd65}.hero-top>small{font-size:12px;background:#ffffff0b;border:1px solid #ffffff22;padding:5px 12px;border-radius:20px}.hero-body{padding:16px 34px 26px;display:flex;align-items:center;justify-content:space-between;gap:25px}.hero h1{font-size:33px;letter-spacing:1px;line-height:1.25;margin:12px 0}.hero h1 small{display:block;font-size:12px;letter-spacing:1px;color:#a7b6c6;font-weight:400;margin-top:9px}.hero p{color:#b9c4d1;font-size:12px}.hero-metrics{display:flex;gap:24px;font-size:12px;margin-top:25px;color:#a7b6c6}.hero-metrics b{color:white;font-size:14px;margin-left:8px}.single{text-align:center;margin-right:28px}.single b{display:block;color:#ffc16c;font-size:110px;font-weight:900;line-height:1.05;letter-spacing:-4px}.single small{font-size:12px;letter-spacing:6px;color:#c8d2dc}.hero-foot{display:flex;justify-content:space-between;gap:20px;border-top:1px solid #ffffff18;color:#92a4b5;font-size:11px;padding:12px 28px}.selection-grid{display:grid;grid-template-columns:1fr 1fr;gap:20px}.panel{background:white;border:1px solid var(--line);border-radius:12px;padding:24px;margin-bottom:20px}.panel h2{font-size:17px;margin:0 0 15px}.section-title{display:flex;justify-content:space-between;align-items:center;gap:12px;margin-bottom:14px}.section-title h2{margin:0}.section-title small,.section-title a{font-size:11px;color:var(--muted)}.section-title a{color:var(--red);font-weight:700}.balls{display:flex;gap:14px;flex-wrap:wrap;padding-top:8px}.balls>span{width:60px;height:60px;display:flex;align-items:center;justify-content:center;background:#fff4e1;border:1px solid #f3d6a7;border-radius:50%;font-size:24px;font-weight:800;color:#764419}.balls.small{gap:9px}.balls.small>span{width:39px;height:39px;font-size:16px;background:#f2f5f9;border-color:#dfe5ed;color:#283f58}.muted{color:var(--muted);font-size:12px;line-height:1.8}.muted a{color:var(--red)}summary{cursor:pointer;font-size:13px;font-weight:700}details[open] summary{margin-bottom:16px}details:not(.panel){margin:20px 0}.table-wrap{overflow:auto;max-height:550px}table{width:100%;border-collapse:collapse;white-space:nowrap;font-size:12px;text-align:left}th{background:#f4f6f9;font-size:11px;color:#6c7b8e;position:sticky;top:0;z-index:1}th,td{padding:12px 14px;border-bottom:1px solid #e9edf2}.hit{color:#27855b!important;font-weight:800}.rank-grid{display:grid;grid-template-columns:repeat(9,1fr);gap:8px;margin:24px 0}.rank-grid div{background:#f6f7fa;border:1px solid #edf0f5;border-radius:8px;text-align:center;padding:10px 3px}.rank-grid div.chosen{background:#fff4e4;border-color:#f3d7ac}.rank-grid small,.rank-grid span{display:block;font-size:10px;color:#7b8895}.rank-grid b{font-size:19px}.page-title{margin:12px 0 26px}.page-title h1{font-size:29px;margin:4px 0}.page-title p{margin:0;font-size:13px;color:var(--muted)}.page-title small{color:var(--red);font-size:11px;letter-spacing:2px}.stats-grid{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin:18px 0}.stat{padding:14px 16px;border-left:2px solid #dbc198;background:#f8f9fb}.stat span,.stat small{display:block;font-size:11px;color:var(--muted)}.stat strong{display:block;font-size:23px;font-weight:800;line-height:1.7;overflow-wrap:anywhere}.stat small{font-size:10px}.year-grid{display:grid;grid-template-columns:repeat(10,1fr);gap:10px}.year-grid div{background:#f6f8fb;border-radius:6px;padding:9px;text-align:center;font-size:11px}.year-grid span{display:block;color:var(--muted)}.hash{font-size:10px;overflow-wrap:anywhere;font-family:monospace;color:var(--muted)}input{border:1px solid #d8dfe8;border-radius:7px;padding:7px 11px;font-size:12px;min-width:240px}.timeline article{display:flex;gap:20px;padding:13px 0;border-bottom:1px solid var(--line);font-size:12px}.timeline article>span{flex:0 0 155px;font-size:10px;color:var(--muted);padding-top:3px}.timeline p{margin:3px 0;color:var(--muted)}.install-box{border-top:1px solid var(--line);padding-top:15px;margin-top:20px}.install-box h3{font-size:14px}.install-box p{font-size:12px;color:var(--muted)}.loading{color:var(--muted)}footer{text-align:center;color:#8c99a8;font-size:10px;padding:16px 0 24px;line-height:2}@media(max-width:700px){header{padding:16px 18px}.brand{font-size:17px}.logo{font-size:21px;padding:7px 9px}.status{font-size:10px}nav{padding:0 18px;gap:0;justify-content:space-between}nav a{font-size:12px;padding:14px 0}main{padding:16px 14px}.toolbar{flex-direction:column;align-items:stretch;gap:10px}.toolbar div button{flex:1;padding:10px;font-size:12px}.toolbar p{font-size:11px}.hero-top{padding:18px 20px 0}.hero-top>span,.hero-top>small{font-size:10px}.hero-body{padding:16px 20px 25px;gap:10px}.hero h1{font-size:23px}.hero p{font-size:10px;max-width:200px}.single{margin-right:0}.single b{font-size:80px}.single small{font-size:10px;letter-spacing:3px}.hero-metrics{flex-direction:column;gap:4px;margin-top:17px;font-size:10px}.hero-metrics b{font-size:12px}.hero-foot{padding:10px 18px;flex-direction:column;gap:2px;font-size:9px}.selection-grid{grid-template-columns:1fr;gap:0}.panel{padding:18px;margin-bottom:14px}.section-title small{font-size:10px}.panel h2{font-size:15px}.balls{gap:13px}.balls>span{width:51px;height:51px;font-size:22px}.balls.small>span{width:30px;height:30px;font-size:13px}.balls.small{gap:7px}.rank-grid{grid-template-columns:repeat(5,1fr)}.stats-grid{grid-template-columns:repeat(2,1fr);gap:8px}.stat{padding:10px 12px}.stat strong{font-size:20px}.year-grid{grid-template-columns:repeat(4,1fr)}.section-title{flex-wrap:wrap}input{min-width:100%;width:100%}.timeline article{gap:9px}.timeline article>span{flex-basis:100px}.page-title h1{font-size:25px}th,td{padding:10px;font-size:11px}.alert{font-size:12px}.section-title a{font-size:10px}}"
EXTRA_STYLE = """
.balls.scored>span{display:flex;flex-direction:column;gap:5px;border:0;border-radius:0;background:transparent;width:54px;height:auto;aspect-ratio:auto;padding:0;color:var(--ink)}
.balls.scored>span>b{display:flex;align-items:center;justify-content:center;border-radius:50%;width:39px;height:39px;background:#f2f5f9;border:1px solid #dfe5ed;font-size:16px;color:#283f58}
.balls.scored>span>small{display:block;white-space:nowrap;font-size:10px;font-weight:700;color:#69501d;margin:0;line-height:1.5}
.six-combination-card .balls.scored>span{max-width:none;width:100%;height:auto;aspect-ratio:auto}.single-percent{display:block;color:#ffce8d;font-size:14px;margin-top:10px}
header .logo{white-space:nowrap;flex-shrink:0}
@media(max-width:420px){header{flex-wrap:wrap;gap:10px}.brand{font-size:17px}.brand div span{font-size:10px;letter-spacing:1px}.status{margin-left:auto}}
.research-group-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(235px,1fr));gap:14px;margin:20px 0}
.research-group-card,.six-combination-card{border:1px solid var(--line);border-radius:14px;padding:18px;min-width:0;background:#f8fafb}
.research-group-card h3,.six-combination-card h3{margin:0 0 12px;font-size:20px}
.research-group-card small{display:block;color:var(--muted);margin-top:12px;font-size:11px}
.six-combination-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:14px;margin:20px 0}
.six-first{border:2px solid #b78945;background:#fffaf0}.six-combination-card .balls{display:grid;grid-template-columns:repeat(6,minmax(0,1fr));gap:6px}
.six-combination-card .balls span{width:100%;max-width:39px;height:auto;aspect-ratio:1}.six-combination-card p{font-size:11px;color:var(--muted)}
.research-qualification{display:block;border:1px solid #e0ab624d;border-radius:6px;padding:8px;margin-top:12px;color:#ffce8d;font-size:11px}
.single-date{display:block;color:#d8e2ec;font-size:12px;margin-top:10px}.hero .confidence-evidence{margin:0 28px 22px;padding:14px;background:#ffffff09;border:1px solid #ffffff20;border-radius:10px;font-size:12px;color:#c8d2dc}
.hero .confidence-evidence strong{color:#ffce8e}.evidence-meta{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:14px;font-size:12px}.evidence-meta dt{color:var(--muted)}.evidence-meta dd{margin:4px 0;overflow-wrap:anywhere}
.action-link{display:inline-flex;align-items:center;background:#fff;border:1px solid var(--line);border-radius:9px;padding:10px 16px;font-size:13px;font-weight:700}.research-label{background:#fbf1dc;color:#6b4b1a;padding:9px 12px;border-radius:8px;font-size:12px}
nav{overflow:auto;white-space:nowrap}.hero-metrics{flex-wrap:wrap}.local-note{margin:12px 0}.full-ranking{gap:6px}.toolbar div{flex-wrap:wrap}
@media(max-width:620px){.hero-body{flex-wrap:wrap}.single{margin:10px auto}.research-group-grid,.six-combination-grid{grid-template-columns:1fr}.hero .confidence-evidence{margin:0 18px 18px}.evidence-meta{grid-template-columns:1fr}.toolbar div>*{flex:1;text-align:center}nav{gap:22px;justify-content:flex-start}.hero h1{font-size:28px}}
"""


def esc(value):
    return html.escape(str(value), quote=True)


def balls(numbers, small=True, percentages=None):
    if percentages is not None:
        return '<div class="balls scored' + (' small' if small else '') + '">' + ''.join(
            f'<span data-scored-number="{n}" data-ranking-percent="{percentages[n]:.4f}"><b>{n:02d}</b><small>{percentages[n]:.2f}％</small></span>' for n in numbers) + '</div>'
    return '<div class="balls' + (' small' if small else '') + '">' + ''.join(
        f'<span>{n:02d}</span>' for n in numbers) + '</div>'


def percentage_data(e):
    from ensemble50 import number_percentages
    calculated=number_percentages(e['modules'])
    if e.get('number_percentages',calculated)!=calculated:
        raise ValueError('Single-number percentages do not match the module rankings')
    return calculated


def percentage_map(e):
    return {r['number']:r['ranking_score_percent'] for r in percentage_data(e)['numbers']}


def number_labels(numbers, percentages):
    return '　'.join(f'{n:02d}（{percentages[n]:.2f}％）' for n in numbers)


NAVIGATION = (('forecast','./','預測戰報'),('review','review/','開獎檢討'),
              ('history','history/','歷史資料'),('models','models/','候選模型'),('system','system/','更新與檢修'))


def navigation(active='forecast'):
    return '<nav aria-label="主導覽">' + ''.join(
        f'<a class="{"active" if key == active else ""}" href="{href}"'
        + (' aria-current="page"' if key == active else '') + f'>{name}</a>'
        for key,href,name in NAVIGATION) + '</nav>'


def table(headers, rows):
    return '<div class="table-wrap"><table><thead><tr>' + ''.join(f'<th>{esc(v)}</th>' for v in headers) + '</tr></thead><tbody>' + ''.join(
        '<tr>' + ''.join(f'<td>{esc(v)}</td>' for v in row) + '</tr>' for row in rows) + '</tbody></table></div>'


def six_section(e, key, section_id, title):
    block = e[key]
    percentages=percentage_map(e)
    cards = []
    rows = []
    for i, group in enumerate(block['groups']):
        stats = group['backtest_hits_at_least']
        samples = group['backtest_samples']
        cards.append(f'''<article class="six-combination-card {'six-first' if i == 0 else ''}" data-six-group="{i+1}">
        <div class="section-title"><h3>第 {i+1} 組</h3><small>模型評分 {group['model_score']:.4f}</small></div>
        {balls(group['numbers'],percentages=percentages)}<p>適用 {esc(e['target_draw_date'])} · 單號下方為融合排名分數％</p>
        <p>回測至少2中 {stats['2']}／{samples} · 至少3中 {stats['3']}／{samples}</p></article>''')
        rows.append([i+1, number_labels(group['numbers'],percentages), f"{group['model_score']:.4f}",
                     *(f"{stats[str(g)]}／{samples}" for g in (2,3,4,5))])
    pool = balls(block['top15_ranked'],percentages=percentages) if key == 'six_number_combinations' else ''
    extra = f"搜尋全部 {block['search_space']:,} 種六碼組合；跨組去重後展開 {block['unique_five_number_tickets']} 種五碼。" if key == 'full39_six_combinations' else '候選池為本期融合排名前15名。'
    return f'''<section class="panel six-combinations-panel" id="{section_id}">
    <div class="section-title"><h2>{title}</h2><small>適用 {esc(e['target_draw_date'])}</small></div>
    <p class="muted">{extra}</p>{pool}<p class="research-label">信心等級：研究參考。未證實高機率；模型評分不是中獎機率。</p>
    <div class="six-combination-grid">{''.join(cards)}</div>
    <details><summary>展開10組評分與60期逐期回測</summary>{table(['組別','六碼','模型評分','至少2中','至少3中','至少4中','5中'], rows)}
    <p class="muted">每期先用當時資料重新選組，再對照下一期。各列是對應選組策略的歷史表現，並非本期固定六碼的歷史命中率；10組互有重疊。</p>
    <p class="muted">{esc(block['method'])}。{esc(block['score_meaning'])}</p></details></section>'''


def render_report(analysis, cloud_url, workflow_url):
    e = analysis['ensemble50']
    percentages=percentage_map(e)
    number_data=percentage_data(e)
    if e['module_count'] != 1000 or e['verification']['modules_verified'] != 1000 or e['verification']['status'] != 'passed':
        raise ValueError('Cannot render unverified 1000-module report')
    target = e['target_draw_date']
    if target != analysis['target_draw_date'] or e['based_on_date'] != analysis['latest_draw']['draw_date']:
        raise ValueError('Report dates are inconsistent')
    packs = {p['name']: p for p in e['packs']}
    single = packs['終極獨隻']
    generated = analysis['generated_at_taiwan']
    digest = hashlib.sha256(json.dumps(analysis,sort_keys=True,ensure_ascii=False,separators=(',',':'),allow_nan=False).encode()).hexdigest()
    group_cards = ''.join(f'''<article class="research-group-card" data-target-group="{esc(name)}"><h3>{esc(name)}</h3>{balls(packs[name]['numbers'],percentages=percentages)}
    <small>適用 {esc(target)} · 目標命中 {packs[name]['hit_goal']} 顆</small></article>''' for name in ('2中2','3中3','5中5','7中5','9中5'))
    pack_rows = [[p['name'], f"{p['backtest_successes']}／{p['backtest_samples']}", f"{p['backtest_rate_percent']}％", f"{p['random_baseline_percent']}％", f"{p['wilson_95_percent'][0]}～{p['wilson_95_percent'][1]}％",f"{p['model_agreement_percent']}％"] for p in e['packs']]
    module_rows = [[i+1,m['id'],m['family'],m['window'],m['parameters']['long_frequency_rank_blend'],number_labels(m['ranking'][:1],percentages),m['validation']['single_hits'],m['validation']['top5_avg_hits'],m['validation']['samples'],'通過' if m['validation']['structural_pass'] else '未通過'] for i,m in enumerate(e['modules'])]
    number_rows=[[r['rank'],f"{r['number']:02d}",f"{r['ranking_score_percent']:.2f}％",f"{r['top9_support_percent']:.2f}％",r['ranking_points']] for r in number_data['numbers']]
    metrics = f'<span>模組實算 <b>1000／1000組</b></span><span>模組結構驗證 <b>{e["verification"]["modules_verified"]}／1000組</b></span><span>逐期回測 <b>{e["verification"]["walk_forward_samples"]}期</b></span>'
    return f'''<!doctype html><html lang="zh-Hant"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
    <base href="{esc(cloud_url)}"><title>天天樂｜539同規格戰報 · {esc(target)}</title><style>{STYLE_FROM_539}{EXTRA_STYLE}</style></head>
    <body data-report-layout="539-v23-compatible"><header><div class="brand"><div class="logo">天天樂</div><div>加州 Fantasy 5<span>雲端戰報 · 539同規格版面</span></div></div><span class="status"><i></i>1000組模組已驗證</span></header>
    {navigation()}
    <main><div class="toolbar"><p>最新運算（台灣）：{esc(generated)}<br>資料截至加州 {esc(e['based_on_date'])} · 每日開獎，適用日期依加州日曆</p>
    <div><button type="button" onclick="forceRefresh()">同步最新戰報</button><a class="action-link" href="{esc(workflow_url)}">雲端更新與檢修</a></div></div>
    <p class="alert local-note" id="localSnapshotNote" hidden>本機離線快照，尚未同步。<a href="{esc(cloud_url)}">開啟線上戰報</a></p>
    <section class="hero forecast-hero" id="ensemble50-required"><div class="hero-top"><span>本期融合研究結果</span><small>適用日期 · 加州開獎日</small></div>
    <div class="hero-body"><div><h1>{esc(target)}<small>目標開獎日期 · America/Los_Angeles</small></h1><p>輸入截止 {esc(e['based_on_date'])}<br>完整歷史 {analysis['draw_count']:,} 期<br>對應台灣時間：{esc(analysis.get('freshness',{}).get('target_taiwan_safe_update_time','待確認'))}</p><div class="hero-metrics">{metrics}</div></div>
    <div class="single"><small>終極獨隻（研究）</small><b data-ultimate-single="{single['numbers'][0]}">{single['numbers'][0]:02d}</b><span class="single-percent" data-scored-number="{single['numbers'][0]}" data-ranking-percent="{percentages[single['numbers'][0]]:.4f}">融合排名分數 {percentages[single['numbers'][0]]:.2f}％</span><span class="single-date">適用 {esc(target)}</span><span class="research-qualification">信心等級：研究參考<br>高信心命中資格尚未通過</span></div></div>
    <div class="confidence-evidence"><strong>高機率／信心標註</strong><p>1000組固定配置、20個算法家族、10種視窗、5種長期頻率排名混合，固定等權融合。獨隻模組共識 {single['model_agreement_percent']}％；60期逐期回測命中 {single['backtest_successes']}／{single['backtest_samples']}。共識比例不是開出機率；運算通過不代表高信心命中資格。</p></div>
    <div class="hero-foot"><span>最新一期實際開獎：{esc(e['based_on_date'])} · {' '.join(f'{n:02d}' for n in analysis['latest_draw']['numbers'])}</span><span>天天樂資料與玩法 · 539版面規格</span></div></section>
    <section class="panel" id="target-groups"><div class="section-title"><h2>本期五組命中目標</h2><small>適用 {esc(target)}</small></div><p class="muted">全部取自同一份1000組融合排序，與終極獨隻同源。各組彼此包含，目標不是必中保證。</p>
    <p class="research-label">每個預測號碼下方為融合排名分數百分比，不是開出機率；同一號碼在所有組合使用相同本期分數。</p><div class="research-group-grid">{group_cards}</div><details><summary>展開五組與獨隻回測、理論對照及信心依據</summary>{table(['目標','回測達標','回測比率','公平理論對照','95％區間','模組共識'],pack_rows)}<p class="muted">公平理論值及歷史比率均不是本模型下期成功率；共用資料與參數變體不代表1000份獨立證據。</p></details></section>
    <section class="panel" id="number-percentages"><h2>1–39全號碼運算百分比</h2><p class="muted">{esc(number_data['method'])}。{esc(number_data['meaning'])}。此分數與主選使用同一個1000組排名，未改動選號排序。</p>{table(['融合排名','號碼','融合排名分數％','進入模組前九比例％','名次積分'],number_rows)}</section>
    {six_section(e,'six_number_combinations','top15-six-groups','前15名六碼組合 · 10組')}
    {six_section(e,'full39_six_combinations','full39-six-groups','1–39全號碼六碼包牌 · 評分最高10組')}
    <section class="panel" id="verification"><div class="section-title"><h2>本期出報告驗證</h2><strong class="hit">1000／1000 模組結構通過</strong></div><p>全部模組排名包含39個不同號碼；使用60期先預測再評分的逐期回測。完成雙輪重算並核對每期排名指紋；這是60期逐期回測，不是全歷史逐期回測。</p>
    <div class="stats-grid"><div class="stat"><span>完整資料筆數</span><strong>{analysis['draw_count']:,}</strong></div><div class="stat"><span>算法家族</span><strong>20 家族</strong></div><div class="stat"><span>逐期回測</span><strong>60 期</strong></div><div class="stat"><span>六碼組合</span><strong>10＋10 組</strong></div></div>
    <p class="muted">1000種唯一配置 · 本期實際不同排名 {e['verification']['unique_current_rankings']} 種 · 雙輪重算 {e['verification']['replay_rounds']} 輪 · 每輪歷史預測 {e['verification']['module_forecasts']:,} 次。相同排名不是另外的獨立證據。</p>
    <details><summary>展開1000組算法、信心依據與完整驗證</summary>{table(['序','模組','家族','歷史窗口','長期混合比','當期第一名','獨支命中／60','回測前五平均中','回測期數','結構驗證'],module_rows)}<p class="muted">{esc(e['verification']['note'])}</p></details>
    <details><summary>展開資料與戰報同步識別</summary><dl class="evidence-meta"><div><dt>最新運算時間（台灣）</dt><dd>{esc(generated)}</dd></div><div><dt>適用日期（加州）</dt><dd>{esc(target)}</dd></div><div><dt>資料來源</dt><dd>{esc(analysis['latest_draw']['source'])}</dd></div><div><dt>報告資料識別</dt><dd class="hash">{digest}</dd></div></dl><p class="muted">同一份報告的號碼、回測及識別碼同源呈現。本機離線副本會保留當時資料；連線後開啟同一個雲端入口。</p></details></section>
    <details class="panel"><summary>舊模型原始報告</summary><p class="muted">原模型為不同算法結果，已移出主推薦版面。<a href="legacy_model_report.html">展開舊模型原始報告</a></p></details>
    </main><footer>天天樂 · California Fantasy 5<br>模型評分與歷史回測不保證下期；本頁使用539版面，全部號碼仍由天天樂模型運算。</footer></body></html>'''
