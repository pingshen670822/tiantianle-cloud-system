"""20 statistical families x 10 windows x 5 explicit rank-blend settings.

These are 1000 configurations, not 1000 independent algorithms or win proofs.
Every feature below reads only the history prefix supplied by the caller.
"""
import hashlib
import json
import math
import heapq
from itertools import combinations
from collections import Counter
from datetime import date, timedelta

WINDOWS=(10,20,30,45,60,90,120,180,365,720)
BLENDS=(0.0,0.1,0.25,0.4,0.6)
FAMILIES=('近期頻率','指數衰減','線性衰減','短長動量','分段加速度','頻率穩定度',
          '間隔條件頻率','間隔分布核平滑','一期轉移','二期轉移','三期轉移','同場共現',
          '鄰號條件','尾數條件','區間條件','星期條件','月日條件','相似交集後繼','相似形態後繼','連續出現條件')
MODULE_COUNT=len(FAMILIES)*len(WINDOWS)*len(BLENDS)
SCHEMA_VERSION='ensemble1000_v1_20families_10windows_5blends'


def configurations():
    return [{'id':f'M{i+1:04d}','family':family,'window':window,
             'parameters':{'long_frequency_rank_blend':blend}}
            for i,(family,window,blend) in enumerate((f,w,b) for f in FAMILIES for w in WINDOWS for b in BLENDS)]


def configuration_signature(module):
    return json.dumps({k:module[k] for k in ('family','window','parameters')},sort_keys=True,separators=(',',':'))


def rank_vector(values):
    order=sorted(range(1,40),key=lambda n:(-values.get(n,0.0),n))
    return {n:(39-i)/39 for i,n in enumerate(order)}


def features(draws, window):
    rows=[set(d['numbers']) for d in draws[-window:]]
    dates=[date.fromisoformat(d['draw_date']) for d in draws[-window:]]
    length=len(rows);previous=rows[-1];counts=Counter(n for r in rows for n in r)
    base={n:(counts[n]+10*5/39)/(length+10) for n in range(1,40)}
    vectors={'近期頻率':base}
    for label,weights in [('指數衰減',[math.exp(-i/max(2,window/4)) for i in range(length)]),
                          ('線性衰減',[(length-i)/length for i in range(length)])]:
        score=Counter()
        for r,weight in zip(reversed(rows),weights):
            for n in r:score[n]+=weight
        vectors[label]={n:score[n]/sum(weights) for n in range(1,40)}
    block=max(1,length//3)
    partitions=[rows[-block:],rows[-2*block:-block],rows[:-2*block] or rows[:1]]
    rates=[{n:sum(n in r for r in segment)/len(segment) for n in range(1,40)} for segment in partitions]
    vectors['短長動量']={n:rates[0][n]-rates[1][n]+base[n] for n in range(1,40)}
    vectors['分段加速度']={n:rates[0][n]-2*rates[1][n]+rates[2][n] for n in range(1,40)}
    vectors['頻率穩定度']={n:base[n]-(max(r[n] for r in rates)-min(r[n] for r in rates))/2 for n in range(1,40)}
    hazard={};kernel={};run_score={}
    for n in range(1,40):
        positions=[i for i,r in enumerate(rows) if n in r]
        gap=length-1-positions[-1] if positions else length
        gaps=[b-a for a,b in zip(positions,positions[1:])]
        risk=sum(g>gap for g in gaps);events=sum(g==gap+1 for g in gaps)
        hazard[n]=(events+10*5/39)/(risk+10)
        kernel[n]=(sum(math.exp(-abs(g-gap-1)/2) for g in gaps)+5/39)/(len(gaps)+1)
        current_run=0
        for r in reversed(rows):
            if n not in r:break
            current_run+=1
        successes=trials=streak=0
        for before,after in zip(rows,rows[1:]):
            streak=streak+1 if n in before else 0
            if streak==current_run:trials+=1;successes+=n in after
        run_score[n]=(successes+10*5/39)/(trials+10)
    vectors['間隔條件頻率']=hazard;vectors['間隔分布核平滑']=kernel;vectors['連續出現條件']=run_score
    for lag,label in [(1,'一期轉移'),(2,'二期轉移'),(3,'三期轉移')]:
        scores=Counter();den=10.0;anchor=rows[-lag] if length>=lag else previous
        for before,after in zip(rows,rows[lag:]):
            weight=len(before & anchor)/5;den+=weight
            for n in after:scores[n]+=weight
        vectors[label]={n:(scores[n]+10*5/39)/den for n in range(1,40)}
    co=Counter();neighbors=Counter();tails=Counter();zones=Counter()
    near={n+d for n in previous for d in (-1,1) if 1<=n+d<=39}
    for r in rows:
        overlap=len(r & previous)
        for n in r:
            co[n]+=overlap-(n in previous)
            neighbors[n]+=len(r & near)-(n in near)
            tails[n%10]+=1;zones[(n-1)//10]+=1
    vectors['同場共現']={n:(co[n]+.5)/(counts[n]+5) for n in range(1,40)}
    vectors['鄰號條件']={n:(neighbors[n]+.5)/(counts[n]+5) for n in range(1,40)}
    vectors['尾數條件']={n:tails[n%10]/sum(k%10==n%10 for k in range(1,40))+counts[n]/10 for n in range(1,40)}
    vectors['區間條件']={n:zones[(n-1)//10]/sum((k-1)//10==(n-1)//10 for k in range(1,40))+counts[n]/10 for n in range(1,40)}
    target=dates[-1]+timedelta(days=1)
    for label,weights in [('星期條件',[1.0 if d.weekday()==target.weekday() else .1 for d in dates]),
                          ('月日條件',[math.exp(-min(abs(d.day-target.day),31-abs(d.day-target.day))/3) for d in dates])]:
        scores=Counter();den=sum(weights)+10
        for r,weight in zip(rows,weights):
            for n in r:scores[n]+=weight
        vectors[label]={n:(scores[n]+10*5/39)/den for n in range(1,40)}
    def shape(r):return (sum(r),max(r)-min(r),sum(n%2 for n in r),sum(n<=19 for n in r))
    current_shape=shape(previous)
    for label in ('相似交集後繼','相似形態後繼'):
        scores=Counter();den=10.0
        for before,after in zip(rows,rows[1:]):
            if label=='相似交集後繼':weight=(len(before & previous)/len(before | previous))**2
            else:
                s=shape(before);distance=sum(abs(a-b)/scale for a,b,scale in zip(s,current_shape,(50,15,2,2)))
                weight=math.exp(-distance)
            den+=weight
            for n in after:scores[n]+=weight
        vectors[label]={n:(scores[n]+10*5/39)/den for n in range(1,40)}
    return vectors


def rank_modules(draws):
    if len(draws)<3:raise ValueError('At least three historical draws required')
    long_counts=Counter(n for d in draws[-720:] for n in d['numbers'])
    anchor=rank_vector(long_counts)
    prepared={w:{family:rank_vector(scores) for family,scores in features(draws,w).items()} for w in WINDOWS}
    result=[]
    for config in configurations():
        base=prepared[config['window']][config['family']]
        blend=config['parameters']['long_frequency_rank_blend']
        scores={n:(1-blend)*base[n]+blend*anchor[n] for n in range(1,40)}
        if not all(math.isfinite(s) for s in scores.values()):raise ValueError('Nonfinite module score')
        order=sorted(scores,key=lambda n:(-scores[n],n))
        result.append({**config,'ranking':order,'scores':scores})
    return result


def forecast_hash(modules):
    digest=hashlib.sha256()
    for module in modules:
        digest.update(module['id'].encode());digest.update(bytes(module['ranking']))
    return digest.hexdigest()


def verify_exact_six(modules, expected_groups):
    """Independent complete enumeration, without the searcher's branch bounds."""
    points=[0]*39;pair=[[0]*39 for _ in range(39)]
    for m in modules:
        for position,n in enumerate(m['ranking']):points[n-1]+=39-position
        for a,b in combinations(sorted(m['ranking'][:9]),2):pair[a-1][b-1]+=1
    linear=[10*p for p in points]
    edges=[[39*p for p in row] for row in pair]
    best=[];count=0;k=len(expected_groups)
    for a,b,c,d,e in combinations(range(38),5):
        base=linear[a]+linear[b]+linear[c]+linear[d]+linear[e]+edges[a][b]+edges[a][c]+edges[a][d]+edges[a][e]+edges[b][c]+edges[b][d]+edges[b][e]+edges[c][d]+edges[c][e]+edges[d][e]
        for f in range(e+1,39):
            count+=1;score=base+linear[f]+edges[a][f]+edges[b][f]+edges[c][f]+edges[d][f]+edges[e][f]
            if len(best)<k or score>=best[0][0]:
                ns=(a+1,b+1,c+1,d+1,e+1,f+1);entry=(score,tuple(-n for n in ns),ns)
                if len(best)<k:heapq.heappush(best,entry)
                elif entry>best[0]:heapq.heapreplace(best,entry)
    observed=[(score,list(ns)) for score,_,ns in sorted(best,reverse=True)]
    expected=[(g['score_units'],g['numbers']) for g in expected_groups]
    if count!=math.comb(39,6) or observed!=expected:raise RuntimeError('Independent full39 enumeration mismatch')
    return {'combinations_scored':count,'all_top10_exact_match':True,'method':'獨立完整枚舉全部六碼組合，整數評分與前十名完全一致'}
