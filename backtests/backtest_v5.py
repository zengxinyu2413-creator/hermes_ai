"""
HERMES V25 — Hermes Bank Engine (利润提取版)
V19内核 + 资管级护城河: 1.5x提50%/2.0x提30%/3.0x全提重置 + 回撤>25%降半仓
"""
import pandas as pd
import numpy as np
import random
import warnings
warnings.filterwarnings('ignore')

def load_data(fp):
    df=pd.read_csv(fp, skiprows=1)
    df=df[pd.to_numeric(df["open_time"], errors="coerce").notna()].reset_index(drop=True)
    df.rename(columns={c:c.lower() for c in df.columns}, inplace=True)
    for col in ['open','high','low','close','volume']:
        df[col]=pd.to_numeric(df[col], errors='coerce')
    df['open_time']=pd.to_numeric(df['open_time'], errors='coerce').astype(int)
    return df

def calc_indicators(df):
    df['ema20']=df['close'].ewm(span=20,adjust=False).mean()
    df['ema50']=df['close'].ewm(span=50,adjust=False).mean()
    df['ema100']=df['close'].ewm(span=100,adjust=False).mean()
    hl=df['high']-df['low'];hc=np.abs(df['high']-df['close'].shift());lc=np.abs(df['low']-df['close'].shift())
    tr=np.maximum(hl,np.maximum(hc,lc));df['atr']=pd.Series(tr).rolling(14).mean()
    pdm=np.where((df['high']-df['high'].shift())>(df['low'].shift()-df['low']),np.maximum(df['high']-df['high'].shift(),0),0)
    mdm=np.where((df['low'].shift()-df['low'])>(df['high']-df['high'].shift()),np.maximum(df['low'].shift()-df['low'],0),0)
    pdm_s=pd.Series(pdm,index=df.index);mdm_s=pd.Series(mdm,index=df.index);tr_s=pd.Series(tr,index=df.index)
    ts=tr_s.rolling(14).sum()
    pdi=100*(pdm_s.rolling(14).sum()/ts.replace(0,np.nan));mdi=100*(mdm_s.rolling(14).sum()/ts.replace(0,np.nan))
    dx=abs(pdi-mdi)/(pdi+mdi).replace(0,np.nan)*100;df['adx']=dx.rolling(14).mean()
    df['is_up']=df['close']>df['close'].shift(1)
    df['consecutive_up']=df['is_up'].groupby((~df['is_up']).cumsum()).cumsum()
    df['high_20']=df['high'].rolling(20).max().shift(1);df['recent_low']=df['low'].rolling(10).min().shift(1)
    df=df.dropna().reset_index(drop=True);return df

def run_v25(df,init=10000):
    eq=init;bank=0;pos=[];tl=[];cd=0;rl=0;m15=False;m20=False;pk=eq
    for i in range(1,len(df)):
        row=df.iloc[i];pr=df.iloc[i-1];p=row['close'];at=max(row['atr'],0.001);ad=row['adx'];vf=at/p
        if cd>0:cd-=1
        for po in pos[:]:
            pnl=(p-po['avg_price'])/po['avg_price'];po['peak_price']=max(po['peak_price'],p)
            mp=(po['peak_price']-po['avg_price'])/po['avg_price']
            if pnl<=-0.18:
                eq+=po['size']*p;tl.append(pnl);rl+=1;pos.remove(po);continue
            elif pnl<=-0.12 and po['add_count']>0:
                eq+=po['size']*p;tl.append(pnl);rl+=1;pos.remove(po);continue
            elif pnl<=-0.06 and not po.get('ss',False):
                red=po['size']*0.5;eq+=red*p;po['size']-=red;po['ss']=True
            if pnl>=0.08 and po['tp']==0:
                cs=po['initial_size']*0.10
                if cs<po['size']:eq+=cs*p;po['size']-=cs
                po['tp']=1
            if pnl>=0.15 and po['tp']==1:
                cs=po['initial_size']*0.10
                if cs<po['size']:eq+=cs*p;po['size']-=cs
                po['tp']=2
            if pnl>=0.30 and po['tp']==2:
                cs=po['initial_size']*0.15
                if cs<po['size']:eq+=cs*p;po['size']-=cs
                po['tp']=3
            dd2=0
            if mp>0.10 and (po['peak_price']-po['avg_price'])>0:
                dd2=(po['peak_price']-p)/(po['peak_price']-po['avg_price'])
            me=p<(po['peak_price']-6.0*at) or dd2>0.55
            if me and po['tp']>0:
                eq+=po['size']*p;tl.append(pnl)
                if pnl>0:rl=0;pos.remove(po);continue
            if p>row['high_20']*0.995:
                cost=0
                if po['add_count']==0:cost=po['base_val']
                elif po['add_count']==1 and p>po['peak_price']:cost=po['base_val']*1.2
                elif po['add_count']==2 and p>po['peak_price']:cost=po['base_val']*1.5
                if cost>0:
                    sz=cost/p;n=(po['size']*po['avg_price']+cost)/(po['size']+sz)
                    po['avg_price']=n;po['size']+=sz;po['add_count']+=1;eq-=cost
            if not po.get('dom',False):
                if ad>40 and row['consecutive_up']>=4:
                    cost=po['base_val']*2.0;sz=cost/p
                    n=(po['size']*po['avg_price']+cost)/(po['size']+sz)
                    po['avg_price']=n;po['size']+=sz;po['dom']=True;eq-=cost
        # 模块B: 利润提取
        cae=eq+sum([po['size']*p for po in pos])
        pk=max(pk,cae);dd=(pk-cae)/pk if pk>0 else 0
        rm=0.5 if dd>0.25 else 1.0
        if len(pos)==0:
            cp=eq-init
            if cp>0:
                if eq>=init*3.0:
                    bank+=cp;eq=init;m15=False;m20=False;pk=eq
                elif eq>=init*2.0 and not m20:
                    ex=cp*0.30;bank+=ex;eq-=ex;m20=True;pk=eq
                elif eq>=init*1.5 and not m15:
                    ex=cp*0.50;bank+=ex;eq-=ex;m15=True;pk=eq
        # 模块C: 入场
        if len(pos)==0 and cd==0:
            if rl>=3:rl=0;cd=24;continue
            blk=vf<0.02 or vf>0.08 or ad<20 or row['ema20']<=pr['ema20']
            if not blk:
                rb=(p-row['recent_low'])/row['recent_low'] if row['recent_low']>0 else 0
                en=p>row['ema50'] and p>row['ema100'] and ad>20 and ad>pr['adx'] and rb>=max(0.015,0.8*vf)
                if en:
                    bp=0.025 if ad<25 else 0.040 if ad<35 else 0.075
                    bv=eq*bp*rm;sz=bv/p
                    pos.append({'avg_price':p,'initial_size':sz,'size':sz,'base_val':bv,'peak_price':p,'add_count':0,'tp':0,'ss':False,'dom':False})
                    eq-=bv;cd=6
    fp=df.iloc[-1]['close']
    for po in pos:eq+=po['size']*fp
    return tl,eq,bank,eq+bank

def mc(tl,ns=10000,mt=1000,init=10000.0):
    if len(tl)<5:return {'ror_0':0,'ror_50':0,'var_95':0,'cvar_99':0}
    terms,dds=[],[]
    for _ in range(ns):
        eq,pk,md=init,init,0.0;ru=False
        for _ in range(mt):
            eq+=random.choice(tl)
            if eq<=0:ru=True;break
            pk=max(pk,eq);md=max(md,(pk-eq)/pk)
        terms.append(eq if not ru else 0);dds.append(md)
    te=np.array(terms);dd=np.array(dds)
    return {'ror_0':float(np.mean(te<=0)*100),'ror_50':float(np.mean(te<init*0.5)*100),
            'var_95':float(np.percentile(dd,95)*100),'cvar_99':float(np.mean(dd[dd>=np.percentile(dd,99)])*100),
            'median_end':float(np.median(te)),'sample_n':len(tl)}

if __name__=="__main__":
    print("="*72)
    print("  HERMES V25 — Hermes Bank Engine")
    print("  V19内核 | 1.5x/2.0x/3.0x利润提取 | 回撤>25%降半仓")
    print("="*72)
    df=load_data('data/SOLUSDT_2024_1h.csv')
    print(f"  原始数据: {len(df):,} 行 | {df.index[0]} → {df.index[-1]}")
    df=calc_indicators(df)
    print(f"  指标计算: {len(df):,} 行")
    tl,ae,bank,tv=run_v25(df,10000)
    n=len(tl);pnl_total=ae-10000;ret=(tv-10000)/10000*100
    mabs=np.mean(tl) if tl else 0;wr=sum(1 for x in tl if x>0)/n*100 if n>0 else 0
    pos_=[x for x in tl if x>0];neg_=[x for x in tl if x<0]
    print(f"\n{'─'*66}")
    print(f"  【V25 Backtest Core Metrics】")
    print(f"{'─'*66}")
    print(f"  清算次数:{n}");print(f"  Trade Mean (%):{mabs:+.4f}%")
    print(f"  胜率:{wr:.1f}%")
    if pos_:print(f"  盈利均值(%):{np.mean(pos_):+.2f}%")
    if neg_:print(f"  亏损均值(%):{np.mean(neg_):+.2f}%")
    print(f"  ───────────────")
    print(f"  💰 场内资金: ${ae:.2f}")
    print(f"  🏦 已落袋:   ${bank:.2f}")
    print(f"  🏆 总资产:   ${tv:.2f} ({ret:+.2f}%)")
    m=mc(tl,ns=10000,mt=1000)
    print(f"\n{'─'*66}")
    print(f"  【Monte Carlo (10,000 × 1,000)】")
    print(f"{'─'*66}")
    print(f"  RoR(归零):{m['ror_0']:.4f}%")
    print(f"  99% CVaR:{m['cvar_99']:.2f}%")
    print(f"  中位终结:${m['median_end']:.2f}")
    print(f"\n{'═'*66}")
    print(f"  《Hermes 量化策略评估风控清单》V25")
    print(f"{'═'*66}")
    chk=[('1.Trade Count(>=30)',n>=30,str(n)),
         ('2.Trade Mean%(>=+0.5%)',mabs>=0.5,f"{mabs:+.4f}%"),
         ('3.RoR(0)(<30%)',m['ror_0']<30,f"{m['ror_0']:.4f}%"),
         ('4.99% CVaR(<30%)',m['cvar_99']<30,f"{m['cvar_99']:.2f}%"),
         ('5.Net PnL(>$0)',tv>10000,f"${tv:+.2f}"),]
    print(f"  {'Check':<28s}{'Value':>12s}{'Status':>10s}")
    print(f"  {'─'*50}")
    p=0
    for lb,ok,vl in chk:
        s="✅" if ok else "❌"
        if ok:p+=1
        print(f"  {lb:<28s}{vl:>12s}{s:>10s}")
    v="✅ 实盘准入" if p>=5 else "⚠️  有条件准入" if p>=3 else "❌ 否决"
    print(f"\n  Verdict:{v} ({p}/{len(chk)})")
    print(f"{'═'*66}")
