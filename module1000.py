"""19 explicit forecasting algorithms plus a reproducible random control.
1000 experiments are parameter settings, never 1000 independent algorithms.
No shared long-frequency anchor or shared rank blending is applied.
"""
import hashlib
import json
import math
import heapq
import random
from functools import lru_cache
from itertools import combinations
from collections import Counter
from datetime import date, timedelta

WINDOWS=(10,20,30,45,60,90,120,180,365,720)
BLENDS=(0,1,2,3,4) # compatibility export: now algorithm-specific setting indices
FAMILIES=('貝氏頻率','指數濾波','線性趨勢外推','累積和變點','保守信賴下界','更新間隔核密度',
          '離散存活風險','延遲馬可夫','伯努利樸素貝氏','線上邏輯迴歸','自迴歸最小平方法',
          '集合近鄰後繼','形態近鄰後繼','傅立葉週期外推','共現圖隨機漫步','尾數階層模型',
          '星期分層模型','線上專家加權','逆頻率對照','可重現隨機對照')
LOGIC=(
 'Beta後驗均值；以視窗外歷史作先驗，強度依設定變動',
 '遞迴指數濾波；半衰期依設定變動',
 '對各號二元出現序列作OLS直線並外推；外推距離依設定變動',
 '各切點前後平均差的CUSUM最大變點；變點門檻依設定變動',
 'Wilson保守下界；信賴係數依設定變動',
 '歷次出現間隔的Gaussian核密度，預估目前間隔下一格；帶寬依設定變動',
 '條件存活事件／暴露次數加Beta平滑；平滑強度依設定變動',
 '按固定延遲的狀態交集估計後繼條件頻率；延遲為1至5',
 '以最近開出五碼作二元特徵，累加條件對數似然比；Laplace平滑依設定變動',
 '各號獨立SGD邏輯迴歸，特徵為滯後出現、短頻率與間隔；學習率依設定變動',
 '各號AR(1)加ridge的封閉解並外推；正則強度依設定變動',
 '依集合Jaccard距離選K個歷史狀態，平均其後繼；K依設定變動',
 '依和值、跨度、奇數數量距離選K個歷史狀態，平均其後繼；K依設定變動',
 '直接DFT取最大能量的非零頻率外推；保留頻率數依設定變動',
 '歷史同場共現圖，以最新五碼為重啟分布進行PageRank；重啟率依設定變動',
 '先估尾數群率，再以各號群內率作階層收縮；收縮強度依設定變動',
 '按下一期星期分層，以其他星期率作先驗平滑；先驗強度依設定變動',
 '五個滯後專家的指數損失權重，以歷史逐步更新；學習率依設定變動',
 '頻率倒數的反向假設，加入間隔長度次要項；不是熱號加權',
 '只由訓練截止日期、窗口與設定產生固定種子，不使用開獎結果')
MODULE_COUNT=1000
SCHEMA_VERSION='diverse_algorithms_v2_19methods_1control_1000experiments'

def configurations():
    return [{'id':f'M{i+1:04d}','family':f,'window':w,
             'parameters':{'algorithm_setting':k},'logic':LOGIC[FAMILIES.index(f)]}
            for i,(f,w,k) in enumerate((f,w,k) for f in FAMILIES for w in WINDOWS for k in BLENDS)]

def configuration_signature(module):
    return json.dumps({k:module[k] for k in ('family','window','parameters')},sort_keys=True,separators=(',',':'))

def rank_vector(values):
    order=sorted(range(1,40),key=lambda n:(-values.get(n,0.0),n))
    return {n:(39-i)/39 for i,n in enumerate(order)}

@lru_cache(maxsize=32)
def fourier_basis(length):
    return [(f,tuple(math.cos(2*math.pi*f*i/length) for i in range(length)),tuple(math.sin(2*math.pi*f*i/length) for i in range(length))) for f in range(1,min(length//2,20)+1)]

@lru_cache(maxsize=512)
def spectral_coefficients(y):
    length=len(y);mean=sum(y)/length;centred=[v-mean for v in y];result=[]
    for f,cs,ss in fourier_basis(length):
        a=2/length*sum(v*c for v,c in zip(centred,cs));b=2/length*sum(v*c for v,c in zip(centred,ss))
        result.append((a*a+b*b,f,a,b))
    return sorted(result,reverse=True)

def features(draws,window,setting=0):
    k=setting;rows=[set(d['numbers']) for d in draws[-window:]];L=len(rows)
    series={n:[int(n in r) for r in rows] for n in range(1,40)}
    counts={n:sum(y) for n,y in series.items()};prev=rows[-1];p=5/39
    older=draws[max(0,len(draws)-window-720):max(0,len(draws)-window)]
    prior=Counter(n for d in older for n in d['numbers']);strength=(1,5,15,40,100)[k]
    out={FAMILIES[0]:{n:(counts[n]+strength*((prior[n]+p)/(len(older)+1)))/(L+strength) for n in series}}
    weights=[math.exp(-math.log(2)*i/max(1,window/(2,4,6,8,12)[k])) for i in range(L)]
    out[FAMILIES[1]]={n:sum(a*b for a,b in zip(reversed(y),weights))/sum(weights) for n,y in series.items()}
    xs=[i-(L-1)/2 for i in range(L)];den=sum(x*x for x in xs) or 1
    out[FAMILIES[2]]={n:counts[n]/L+sum(x*v for x,v in zip(xs,y))/den*((L-1)/2+(1,2,4,8,16)[k]) for n,y in series.items()}
    change={};lower={};density={};hazard={};ar={}
    for n,y in series.items():
        total=counts[n];acc=0;best=(0,None)
        for i,v in enumerate(y[:-1],1):
            acc+=v
            if min(i,L-i)<max(2,L//(3+k)):continue
            diff=(total-acc)/(L-i)-acc/i;stat=abs(diff)*math.sqrt(i*(L-i)/L)
            if stat>best[0]:best=(stat,(total-acc)/(L-i))
        change[n]=best[1] if best[1] is not None and best[0]>(.1,.2,.3,.5,.8)[k] else total/L
        z=(.5,1,1.645,1.96,2.576)[k];q=total/L
        lower[n]=(q+z*z/(2*L)-z*math.sqrt(q*(1-q)/L+z*z/(4*L*L)))/(1+z*z/L)
        pos=[i for i,v in enumerate(y) if v];g=L-1-pos[-1] if pos else L
        gaps=[b-a for a,b in zip(pos,pos[1:])];bw=(.5,1,2,4,8)[k]
        density[n]=sum(math.exp(-.5*((v-g-1)/bw)**2) for v in gaps)/(max(1,len(gaps))*bw)
        risk=sum(v>g for v in gaps);ev=sum(v==g+1 for v in gaps)
        hazard[n]=(ev+strength*p)/(risk+strength)
        xx=y[:-1];yy=y[1:];mx=sum(xx)/max(1,len(xx));my=sum(yy)/max(1,len(yy))
        slope=sum((a-mx)*(b-my) for a,b in zip(xx,yy))/(sum((a-mx)**2 for a in xx)+(0.1,1,3,10,30)[k])
        ar[n]=my+slope*(y[-1]-mx)
    for name,v in zip(FAMILIES[3:7],(change,lower,density,hazard)):out[name]=v
    lag=k+1;anchor=rows[-lag] if L>=lag else prev;transition=Counter();d=0
    for before,after in zip(rows,rows[lag:]):
        w=len(before&anchor)/5;d+=w
        for n in after:transition[n]+=w
    out[FAMILIES[7]]={n:(transition[n]+p)/(d+1) for n in series}
    nb={};lr={};alpha=(.25,.5,1,2,4)[k]
    for n,y in series.items():
        positive=sum(y[1:]);negative=L-1-positive;score=math.log((positive+alpha)/(negative+alpha))
        for feature in prev:
            a=sum(feature in r and target for r,target in zip(rows[:-1],y[1:]));b=sum(feature in r and not target for r,target in zip(rows[:-1],y[1:]))
            score+=math.log((a+alpha)/(positive+2*alpha))-math.log((b+alpha)/(negative+2*alpha))
        nb[n]=score
        beta=[math.log(p/(1-p)),0.,0.,0.];eta=(.01,.03,.07,.15,.3)[k];running=gap=0
        for i,v in enumerate(y):
            if i:
                x=[1,y[i-1],running/i,min(gap,40)/40];z=max(-25,min(25,sum(a*b for a,b in zip(beta,x))));error=v-1/(1+math.exp(-z))
                beta=[b+eta*(error*a-.01*b*(j>0)) for j,(a,b) in enumerate(zip(x,beta))]
            running+=v;gap=0 if v else gap+1
        x=[1,y[-1],running/L,min(gap,40)/40];lr[n]=1/(1+math.exp(-max(-25,min(25,sum(a*b for a,b in zip(beta,x))))))
    out[FAMILIES[8]]=nb;out[FAMILIES[9]]=lr;out[FAMILIES[10]]=ar
    def shape(r):return (sum(r)/50,(max(r)-min(r))/15,sum(v%2 for v in r)/2)
    target=shape(prev);K=(2,4,8,16,32)[k]
    for label,metric in [(FAMILIES[11],lambda r:1-len(r&prev)/len(r|prev)),(FAMILIES[12],lambda r:sum((a-b)**2 for a,b in zip(shape(r),target)))]:
        near=sorted(enumerate(rows[:-1]),key=lambda it:(metric(it[1]),-it[0]))[:K]
        out[label]={n:sum(n in rows[i+1] for i,_ in near)/max(1,len(near)) for n in series}
    spectral={n:counts[n]/L+sum(a for _,f,a,b in spectral_coefficients(tuple(y))[:k+1]) for n,y in series.items()}
    out[FAMILIES[13]]=spectral
    edges={n:Counter() for n in series}
    for r in rows:
        for n in r:edges[n].update(r-{n})
    restart=(.1,.25,.4,.6,.85)[k];mass={n:float(n in prev)/5 for n in series}
    for _ in range(15):
        nxt={n:restart*(n in prev)/5 for n in series}
        for n in series:
            den=sum(edges[n].values())
            if den:
                for v,w in edges[n].items():nxt[v]+=(1-restart)*mass[n]*w/den
            else:
                for v in series:nxt[v]+=(1-restart)*mass[n]/39
        mass=nxt
    out[FAMILIES[14]]=mass
    tails=Counter(n%10 for r in rows for n in r)
    out[FAMILIES[15]]={n:(counts[n]+strength*tails[n%10]/(L*sum(v%10==n%10 for v in series)))/(L+strength) for n in series}
    targetday=(date.fromisoformat(draws[-1]['draw_date'])+timedelta(days=1)).weekday()
    same=[r for r,d in zip(rows,draws[-window:]) if date.fromisoformat(d['draw_date']).weekday()==targetday]
    out[FAMILIES[16]]={n:(sum(n in r for r in same)+strength*counts[n]/L)/(len(same)+strength) for n in series}
    expert={};eta=(.1,.3,.7,1.5,3)[k]
    for n,y in series.items():
        losses=[0.]*5
        for i in range(5,L):
            for j in range(5):losses[j]+=(y[i-j-1]-y[i])**2
        low=min(losses);ws=[math.exp(-eta*(v-low)) for v in losses]
        expert[n]=sum(w*y[-j-1] for j,w in enumerate(ws))/sum(ws)
    out[FAMILIES[17]]=expert
    out[FAMILIES[18]]={n:1/(counts[n]+1)+(k+1)*next((i for i,v in enumerate(reversed(y)) if v),L)/(100*L) for n,y in series.items()}
    rng=random.Random(f"control|{draws[-1]['draw_date']}|{window}|{k}")
    out[FAMILIES[19]]={n:rng.random() for n in series}
    return out

def rank_modules(draws):
    if len(draws)<3:raise ValueError('At least three historical draws required')
    spectral_coefficients.cache_clear()
    prepared={(w,k):features(draws,w,k) for w in WINDOWS for k in BLENDS}
    result=[]
    for c in configurations():
        scores=prepared[c['window'],c['parameters']['algorithm_setting']][c['family']]
        if not all(math.isfinite(v) for v in scores.values()):raise ValueError('Nonfinite score')
        result.append({**c,'ranking':sorted(scores,key=lambda n:(-scores[n],n)),'scores':scores})
    return result


def forecast_hash(modules):
    digest=hashlib.sha256()
    for module in modules:
        digest.update(module['id'].encode());digest.update(configuration_signature(module).encode());digest.update(bytes(module['ranking']))
        for n in range(1,40):
            digest.update(float(module['scores'][n]).hex().encode()+b';')
    return digest.hexdigest()


def verify_exact_six(modules, expected_groups):
    """Independent complete enumeration, without the searcher's branch bounds."""
    modules=[m for m in modules if m.get("family") != FAMILIES[-1]]
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
