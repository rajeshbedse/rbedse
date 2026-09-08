"""
RYB Finserv – NSE Insider Scan Portal
Flask application — serves backdated scan results from output/
"""
from __future__ import annotations
import hashlib, json, logging, math, os, secrets
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
import pandas as pd
from flask import Flask, abort, jsonify, render_template, request
from markupsafe import Markup
log = logging.getLogger(__name__)
BASE_DIR = Path(__file__).parent.parent
OUTPUT_DIR = BASE_DIR / "output"
_CSS_PATH = Path(__file__).parent / "static" / "css" / "main.css"
app = Flask(__name__, template_folder="templates", static_folder="static")
app.config["SEND_FILE_MAX_AGE_DEFAULT"] = 3600
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY") or secrets.token_hex(32)
_STATIC_DIR = Path(__file__).parent / "static"
def _file_hash(p: Path) -> str:
    try: return hashlib.md5(p.read_bytes()).hexdigest()[:8]
    except Exception: return "1"
_CSS_VERSION = _file_hash(_CSS_PATH)
_MAIN_JS_VERSION = _file_hash(_STATIC_DIR / "js" / "main.js")
_SCAN_JS_VERSION = _file_hash(_STATIC_DIR / "js" / "scan.js")
def _ryb_watermark_svg() -> Markup:
    size=1000; pad=size*.047; ratio=1.1; avail=size-2*pad; r=min(avail/(ratio+2), avail/(ratio*math.sqrt(3)/2+2)); s=r*ratio; h=s*math.sqrt(3)/2; ctv=h*2/3; cx=size/2; cy=((pad+ctv+r)+(size-pad-ctv/2-r))/2; bx,by=cx,cy-ctv; rx,ry=cx-s/2,cy+ctv/2; yx,yy=cx+s/2,cy+ctv/2
    def c(x,y): return f'cx="{x:.1f}" cy="{y:.1f}" r="{r:.1f}"'
    return Markup(f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {size} {size}" aria-hidden="true" focusable="false" style="position:fixed;top:0;left:0;width:100vw;height:100vh;pointer-events:none;z-index:0;opacity:0.06;overflow:visible;"><defs><clipPath id="cRwm"><circle {c(rx,ry)}/></clipPath><clipPath id="cYwm"><circle {c(yx,yy)}/></clipPath></defs><circle {c(rx,ry)} fill="#e32636"/><circle {c(yx,yy)} fill="#f5c800"/><circle {c(bx,by)} fill="#1a56db"/><g clip-path="url(#cRwm)"><circle {c(yx,yy)} fill="#ff8c00"/></g><g clip-path="url(#cRwm)"><circle {c(bx,by)} fill="#7b2d8b"/></g><g clip-path="url(#cYwm)"><circle {c(bx,by)} fill="#2e8b57"/></g><g clip-path="url(#cRwm)"><g clip-path="url(#cYwm)"><circle {c(bx,by)} fill="#6b3a2a"/></g></g></svg>')
def _ryb_logo_svg(size:int=32,id_suffix:str="a") -> Markup:
    pad=size*.047; ratio=1.1; avail=size-2*pad; r=min(avail/(ratio+2),avail/(ratio*math.sqrt(3)/2+2)); s=r*ratio; h=s*math.sqrt(3)/2; ctv=h*2/3; cx=size/2; cy=((pad+ctv+r)+(size-pad-ctv/2-r))/2; bx,by=cx,cy-ctv; rx,ry=cx-s/2,cy+ctv/2; yx,yy=cx+s/2,cy+ctv/2
    def c(x,y): return f"cx='{x:.3f}' cy='{y:.3f}' r='{r:.3f}'"
    i=id_suffix
    return Markup(f'''<svg width="{size}" height="{size}" viewBox="0 0 {size} {size}" xmlns="http://www.w3.org/2000/svg" role="img" aria-label="RYB logo"><defs><clipPath id="cR{i}"><circle {c(rx,ry)}/></clipPath><clipPath id="cY{i}"><circle {c(yx,yy)}/></clipPath><clipPath id="cB{i}"><circle {c(bx,by)}/></clipPath><clipPath id="cRY{i}"><circle {c(rx,ry)}/></clipPath><clipPath id="cRB{i}"><circle {c(rx,ry)}/></clipPath><clipPath id="cYB{i}"><circle {c(yx,yy)}/></clipPath><clipPath id="cRYB{i}"><circle {c(rx,ry)}/></clipPath></defs><circle {c(rx,ry)} fill="#e32636"/><circle {c(yx,yy)} fill="#f5c800"/><circle {c(bx,by)} fill="#1a56db"/><g clip-path="url(#cRY{i})"><circle {c(yx,yy)} fill="#ff8c00"/></g><g clip-path="url(#cRB{i})"><circle {c(bx,by)} fill="#7b2d8b"/></g><g clip-path="url(#cYB{i})"><circle {c(bx,by)} fill="#2e8b57"/></g><g clip-path="url(#cRYB{i})"><g clip-path="url(#cY{i})"><circle {c(bx,by)} fill="#6b3a2a"/></g></g></svg>''')
@app.context_processor
def inject_globals(): return {"now_year":datetime.now(timezone.utc).year,"ryb_logo_svg":_ryb_logo_svg,"ryb_watermark_svg":_ryb_watermark_svg(),"css_version":_CSS_VERSION,"main_js_version":_MAIN_JS_VERSION,"scan_js_version":_SCAN_JS_VERSION}
def _file_mtime(p:Path)->float:
    try:return p.stat().st_mtime
    except OSError:return 0.0
@lru_cache(maxsize=64)
def _cached_excel(path_str:str,_mtime:float)->pd.DataFrame|None:
    try:
        xl=pd.ExcelFile(path_str); sheet="ScoredStocks" if "ScoredStocks" in xl.sheet_names else "FilteredStocks"; return xl.parse(sheet)
    except Exception as e: log.warning("Could not read excel %s: %s",path_str,e); return None
@lru_cache(maxsize=64)
def _cached_csv(path_str:str,_mtime:float)->pd.DataFrame|None:
    try:return pd.read_csv(path_str,encoding="utf-8-sig")
    except Exception as e:log.warning("Could not read csv %s: %s",path_str,e);return None
@lru_cache(maxsize=64)
def _cached_meta(path_str:str,_mtime:float)->dict|None:
    try:return json.loads(Path(path_str).read_text(encoding="utf-8"))
    except Exception as e:log.warning("Could not read meta %s: %s",path_str,e);return None
def _load_filtered(date_str):
    p=OUTPUT_DIR/date_str/"enriched_analysis.xlsx"; return _cached_excel(str(p),_file_mtime(p)) if p.exists() else None
def _load_full(date_str):
    p=OUTPUT_DIR/date_str/"enriched_full.csv"; return _cached_csv(str(p),_file_mtime(p)) if p.exists() else None
def _load_meta(date_str):
    p=OUTPUT_DIR/date_str/"meta.json"; return _cached_meta(str(p),_file_mtime(p)) if p.exists() else None
@lru_cache(maxsize=64)
def _cached_trades(path_str:str,_mtime:float)->dict|None:
    try:
        df=pd.read_csv(path_str,encoding="utf-8-sig",dtype=str).fillna(""); df.columns=df.columns.str.strip(); date_to=pd.to_datetime(df.get("Date To",""),format="%d-%m-%Y",errors="coerce") if "Date To" in df.columns else pd.Series(pd.NaT,index=df.index); date_from=pd.to_datetime(df.get("Date From",""),format="%d-%m-%Y",errors="coerce") if "Date From" in df.columns else pd.Series(pd.NaT,index=df.index); df["__transaction_date"]=date_to.fillna(date_from); df=df.sort_values("__transaction_date",ascending=False,na_position="last",kind="stable"); trades={}
        for r in df.to_dict(orient="records"):
            sym=r.get("Symbol","").strip()
            if sym:r.pop("__transaction_date",None);trades.setdefault(sym,[]).append(r)
        return trades
    except Exception as e:log.warning("Could not read trades %s: %s",path_str,e);return None
def _load_trades(date_str):
    p=OUTPUT_DIR/date_str/"promoter_trades.csv"; return _cached_trades(str(p),_file_mtime(p)) if p.exists() else None
def _scan_dates():
    dates=[]
    if not OUTPUT_DIR.exists():return dates
    for d in sorted(OUTPUT_DIR.iterdir(),reverse=True):
        if not d.is_dir():continue
        try:dt=datetime.strptime(d.name,"%Y-%m-%d")
        except ValueError:continue
        has_excel=(d/"enriched_analysis.xlsx").exists(); has_full=(d/"enriched_full.csv").exists()
        if not has_excel and not has_full:continue
        meta=_load_meta(d.name)
        if meta:shortlist=meta.get("shortlisted",0);candidates=meta.get("candidates",0)
        else:
            shortlist=0;candidates=0
            if has_excel:
                x=_load_filtered(d.name);shortlist=len(x) if x is not None else 0
            if has_full:
                x=_load_full(d.name);candidates=len(x) if x is not None else 0
        dates.append({"date_str":d.name,"display":dt.strftime("%d %b %Y"),"weekday":dt.strftime("%A"),"has_excel":has_excel,"has_full":has_full,"shortlist":shortlist,"candidates":candidates})
    return dates
def _band_label(pct:float)->str:
    a=abs(pct); return "within10" if a<=10 else "within20" if a<=20 else "within30" if a<=30 else "beyond30"
_CATEGORY_CSS={"Strong Buy Setup":"strong-buy","Buy on Breakout":"buy-breakout","Watchlist":"watchlist","Fundamental Watch":"fund-watch","Avoid":"avoid"}
def _clean(v):
    if isinstance(v,float) and (math.isnan(v) or math.isinf(v)):return None
    return v
def _all_signals(r):
    last_price=_clean(r.get("LastPrice")) or 0.0; avg_price=_clean(r.get("AvgPrice")) or 0.0; pct=float(r.get("PriceDiffPct") or 0); num_txn=int(r.get("NumBuyTxn") or 0); value_cr=_clean(r.get("ValueCr")) or 0.0; holding=_clean(r.get("PromoHolding")) or 0.0; market_cap=_clean(r.get("MarketCapCr")); has_pledge=bool(r.get("HasPledging",False)); has_sell=bool(r.get("HasMarketSell",False)); dma50=_clean(r.get("DMA50")); dma200=_clean(r.get("DMA200")); six_m=_clean(r.get("SixMonthReturn")); opm=_clean(r.get("OPMPct")); pe=_clean(r.get("PE")); rev_g=_clean(r.get("RevGrowthPct")); ebi_g=_clean(r.get("EBITDAGrowthPct")); pat_g=_clean(r.get("PATGrowthPct")); eps_g=_clean(r.get("EPSGrowthPct")); roce=_clean(r.get("ROCEPct")); de=_clean(r.get("DE_Ratio")); ocf=r.get("OCFPositive"); conv_pct=_clean(r.get("PromoConvictionPct"))
    conviction_ok=(value_cr/market_cap*100>=.25) if market_cap and market_cap>0 else value_cr>=10
    promo=[{"label":"Market Buy","pts":5,"triggered":True,"note":f"₹{value_cr:.2f} Cr bought"},{"label":"Multi-transaction","pts":3,"triggered":num_txn>=3,"note":f"{num_txn} buy txn"+(" ≥3 ✓" if num_txn>=3 else " (need ≥3)")},{"label":"High conviction","pts":5,"triggered":conviction_ok,"note":f"{conv_pct:.3f}% of mkt cap" if conv_pct is not None else (f"₹{value_cr:.1f} Cr abs." if value_cr>=10 else "< 0.25% of mkt cap")},{"label":"Holding > 65%","pts":5,"triggered":holding>65,"note":f"{holding:.1f}%"},{"label":"No insider sell","pts":2,"triggered":not has_sell,"note":"No market sell" if not has_sell else "Market sell detected"},{"label":"No pledge","pts":5,"triggered":not has_pledge,"note":"No pledge" if not has_pledge else "Pledge detected"}]
    def fmt(v,t=15):return "N/A" if v is None else f"{v:+.1f}%"+(" ✓" if v>t else f" (need >{t}%)")
    fund=[{"label":"Revenue growth","pts":5,"triggered":rev_g is not None and rev_g>15,"note":fmt(rev_g)},{"label":"EBITDA growth","pts":5,"triggered":ebi_g is not None and ebi_g>15,"note":fmt(ebi_g)},{"label":"PAT growth","pts":7,"triggered":pat_g is not None and pat_g>15,"note":fmt(pat_g)},{"label":"EPS growth","pts":5,"triggered":eps_g is not None and eps_g>15,"note":fmt(eps_g)},{"label":"ROCE > 15%","pts":4,"triggered":roce is not None and roce>15,"note":f"{roce:.1f}%" if roce is not None else "N/A"},{"label":"D/E < 0.5","pts":3,"triggered":de is not None and de<.5,"note":f"D/E {de:.2f}" if de is not None else "N/A"},{"label":"Positive OCF","pts":6,"triggered":ocf is True,"note":"Positive" if ocf is True else ("Negative" if ocf is False else "N/A")}]
    sig_above_ref=bool(last_price>avg_price>0);sig_above_50dma=bool(dma50 and last_price>dma50);sig_above_200dma=bool(dma200 and last_price>dma200);sig_golden=bool(dma50 and dma200 and dma50>dma200);sig_vol=bool(pct>5 and num_txn>=2);sig_rel=bool(six_m>0) if six_m is not None else bool(pct>10);rel_note=f"6M return {six_m:+.1f}%" if six_m is not None else f"price {pct:+.1f}% vs ref (proxy)"
    tech=[{"label":"Price > Promoter Avg","pts":5,"triggered":sig_above_ref,"note":f"₹{last_price:.2f} vs ₹{avg_price:.2f}" if avg_price>0 else "avg price unavailable"},{"label":"Price > 50 DMA","pts":5,"triggered":sig_above_50dma,"note":f"₹{last_price:.2f} vs ₹{dma50:.2f}" if dma50 else "N/A"},{"label":"Price > 200 DMA","pts":5,"triggered":sig_above_200dma,"note":f"₹{last_price:.2f} vs ₹{dma200:.2f}" if dma200 else "N/A"},{"label":"Golden Cross","pts":5,"triggered":sig_golden,"note":f"50DMA {dma50:.0f} > 200DMA {dma200:.0f}" if dma50 and dma200 else "N/A"},{"label":"Vol. expansion","pts":5,"triggered":sig_vol,"note":f"{pct:+.1f}% · {num_txn} txn"},{"label":"Rel. strength","pts":5,"triggered":sig_rel,"note":rel_note}]
    risk=[{"label":"No pledge","pts":-5,"triggered":has_pledge,"note":"Pledge detected" if has_pledge else "Clear"},{"label":"OPM ≥ 5%","pts":-2,"triggered":bool(opm is not None and opm<5),"note":f"OPM {opm:.1f}% — thin" if opm is not None and opm<5 else (f"OPM {opm:.1f}%" if opm is not None else "N/A")},{"label":"PE ≤ 60","pts":-3,"triggered":bool(pe is not None and pe>60),"note":f"PE {pe:.1f} — high" if pe is not None and pe>60 else (f"PE {pe:.1f}" if pe is not None else "N/A")}]
    return promo,fund,tech,risk
def _timing_fields(r:dict)->dict:
    return {"promoter_avg_price":_clean(r.get("PromoterAvgPrice")),"cmp_vs_promoter_avg_pct":_clean(r.get("CMPvsPromoterAvgPct")),"freshness":r.get("Freshness") or "No Signal","accumulation_stage":r.get("AccumulationStage") or "No Signal","signal_stage":r.get("SignalStage") or "No Signal","first_buy_date":r.get("FirstBuyDate"),"last_buy_date":r.get("LastBuyDate"),"accumulation_days":_clean(r.get("AccumulationDays")),"days_since_last_buy":_clean(r.get("DaysSinceLastBuy")),"buy_txn_30d":_clean(r.get("BuyTxn30D"))}
def _df_to_rows(df,include_flags=False):
    rows=[]
    for idx,r in enumerate(df.to_dict(orient="records")):
        pct=float(r.get("PriceDiffPct") or 0);score=r.get("Score");category=r.get("Category") or "";promo,fund,tech,risk=_all_signals(r)
        entry={"_row_index":idx,"symbol":r.get("Symbol",""),"company":r.get("CompanyName",""),"last_price":_clean(r.get("LastPrice")),"avg_price":_clean(r.get("AvgPrice")),"price_diff_pct":pct,"promo_holding":_clean(r.get("PromoHolding")),"value_cr":_clean(r.get("ValueCr")),"num_buy_txn":r.get("NumBuyTxn"),"reported_buy_txn":r.get("ReportedBuyTxn"),"priced_value_purchased":_clean(r.get("PricedValuePurchased")),"missing_value_qty":_clean(r.get("MissingValueQty")),"missing_value_txn":r.get("MissingValueTxn"),"market_buy_value":_clean(r.get("MarketBuyValue")),"market_sell_value":_clean(r.get("MarketSellValue")),"net_buy_value":_clean(r.get("NetBuyValue")),"sell_buy_ratio_pct":_clean(r.get("SellBuyRatioPct")),"has_market_sell":bool(r.get("HasMarketSell",False)),"sell_buy_exclusion":bool(r.get("SellBuyExclusion",False)),"acq_to_dt":r.get("acqtoDt",""),"band":_band_label(pct),"score":int(score) if score is not None and str(score) not in ("","nan") else None,"category":category,"category_css":_CATEGORY_CSS.get(category,""),"score_promo":r.get("ScorePromo"),"score_fund":r.get("ScoreFund"),"score_tech":r.get("ScoreTech"),"score_risk":r.get("ScoreRisk"),"promo_signals":promo,"fund_signals":fund,"tech_signals":tech,"risk_signals":risk,"market_cap_cr":_clean(r.get("MarketCapCr")),"pe":_clean(r.get("PE")),"promo_conviction_pct":_clean(r.get("PromoConvictionPct")),"rev_growth_pct":_clean(r.get("RevGrowthPct")),"ebitda_growth_pct":_clean(r.get("EBITDAGrowthPct")),"pat_growth_pct":_clean(r.get("PATGrowthPct")),"eps_growth_pct":_clean(r.get("EPSGrowthPct")),"roce_pct":_clean(r.get("ROCEPct")),"de_ratio":_clean(r.get("DE_Ratio")),"ocf_positive":r.get("OCFPositive"),"opm_pct":_clean(r.get("OPMPct")),"six_month_return":_clean(r.get("SixMonthReturn")),"dma50":_clean(r.get("DMA50")),"dma200":_clean(r.get("DMA200")),"week52_high":_clean(r.get("52WeekHigh")),"week52_low":_clean(r.get("52WeekLow"))}
        entry.update(_timing_fields(r)); rows.append(entry)
    return rows
def _row_summary(r,idx,include_flags=False):
    score=r.get("Score");pct=float(r.get("PriceDiffPct") or 0)
    entry={"_row_index":idx,"symbol":r.get("Symbol",""),"company":r.get("CompanyName",""),"last_price":_clean(r.get("LastPrice")),"avg_price":_clean(r.get("AvgPrice")),"price_diff_pct":pct,"promo_holding":_clean(r.get("PromoHolding")),"value_cr":_clean(r.get("ValueCr")),"num_buy_txn":int(r.get("NumBuyTxn") or 0),"acq_to_dt":r.get("acqtoDt",""),"score":int(score) if score is not None and str(score) not in ("","nan") else None,"category":r.get("Category") or "","category_css":_CATEGORY_CSS.get(r.get("Category") or "",""),"band":_band_label(pct),"dma50":_clean(r.get("DMA50")),"dma200":_clean(r.get("DMA200")),"week52_high":_clean(r.get("52WeekHigh")),"week52_low":_clean(r.get("52WeekLow"))}
    entry.update(_timing_fields(r)); return entry
def _summary_rows(df,include_flags=False):
    if df is None or df.empty:return []
    return [_row_summary(r,idx,include_flags) for idx,r in enumerate(df.to_dict(orient="records"))]
_CAT_ORDER=[("Strong Buy Setup","strong-buy","#16a34a"),("Buy on Breakout","buy-breakout","#1a56db"),("Watchlist","watchlist","#f5c800"),("Fundamental Watch","fund-watch","#ff8c00"),("Avoid","avoid","#e32636")]
def _latest_stats(date_str):
    empty=dict(cat_breakdown=[],above_ref=0,below_ref=0,total=0,score_avg=None,top3=[],featured=None);df=_load_filtered(date_str)
    if df is None or df.empty:return empty
    total=len(df);cat_counts=df["Category"].value_counts().to_dict() if "Category" in df.columns else {};cat_breakdown=[]
    for label,css,color in _CAT_ORDER:
        cnt=cat_counts.get(label,0)
        if cnt:cat_breakdown.append({"label":label,"css":css,"color":color,"count":cnt,"pct":round(cnt/total*100)})
    above_ref=below_ref=0
    if "PriceDiffPct" in df.columns:
        s=pd.to_numeric(df["PriceDiffPct"],errors="coerce").fillna(0);above_ref=int((s>0).sum());below_ref=int((s<=0).sum())
    score_avg=None
    if "Score" in df.columns:
        s=pd.to_numeric(df["Score"],errors="coerce").dropna();score_avg=round(float(s.mean()),1) if len(s) else None
    top3=[]
    if "Score" in df.columns:
        d2=df.copy();d2["_score"]=pd.to_numeric(d2["Score"],errors="coerce")
        for _,row in d2.nlargest(3,"_score").iterrows():top3.append({"symbol":row.get("Symbol",""),"score":int(row["_score"]) if not math.isnan(row["_score"]) else None,"category_css":_CATEGORY_CSS.get(row.get("Category",""),""),"diff_pct":round(float(row.get("PriceDiffPct") or 0),1)})
    featured=None
    if top3:
        m=df[df["Symbol"].astype(str)==str(top3[0]["symbol"])]
        if not m.empty:
            row=m.iloc[0];featured={"symbol":row.get("Symbol",""),"company":row.get("CompanyName",""),"score":top3[0]["score"],"category":row.get("Category",""),"diff_pct":top3[0]["diff_pct"],"promo_holding":_clean(row.get("PromoHolding")),"value_cr":_clean(row.get("ValueCr")),"num_buy_txn":int(row.get("NumBuyTxn") or 0)}
    return dict(cat_breakdown=cat_breakdown,above_ref=above_ref,below_ref=below_ref,total=total,score_avg=score_avg,top3=top3,featured=featured)
@app.route("/")
def index():
    dates=_scan_dates();total_scans=len(dates);total_shortlist=sum(d["shortlist"] for d in dates);latest=dates[0] if dates else None;latest_stats=_latest_stats(latest["date_str"]) if latest else {}
    return render_template("index.html",dates=dates,total_scans=total_scans,total_shortlist=total_shortlist,latest=latest,latest_stats=latest_stats)
def _validate_scan_date(date_str):
    try:dt=datetime.strptime(date_str,"%Y-%m-%d")
    except ValueError:abort(404)
    if not (OUTPUT_DIR/date_str).is_dir():abort(404)
    return dt
@app.route("/scan/<date_str>")
def scan_detail(date_str):
    dt=_validate_scan_date(date_str);df_filtered=_load_filtered(date_str);df_full=_load_full(date_str)
    return render_template("scan.html",date_str=date_str,display_date=dt.strftime("%d %b %Y"),weekday=dt.strftime("%A"),shortlist_count=len(df_filtered) if df_filtered is not None else 0,reviewed_count=len(df_full) if df_full is not None else 0)
@app.get("/api/scan/<date_str>/summary")
def scan_summary(date_str):
    _validate_scan_date(date_str);view=request.args.get("view","shortlist")
    if view=="candidates":
        full_df=_load_full(date_str);shortlist_df=_load_filtered(date_str);rows=_summary_rows(full_df,include_flags=True);shortlisted_symbols=set()
        if shortlist_df is not None and not shortlist_df.empty and "Symbol" in shortlist_df.columns:shortlisted_symbols=set(shortlist_df["Symbol"].astype(str).str.upper())
        for row in rows:row["is_shortlisted"]=row.get("symbol","").upper() in shortlisted_symbols
    else:
        rows=_summary_rows(_load_filtered(date_str),include_flags=False)
        for row in rows:row["is_shortlisted"]=True
    return jsonify({"date":date_str,"view":view,"rows":rows})
@app.get("/api/scan/<date_str>/stock/<symbol>")
def scan_stock_detail(date_str,symbol):
    _validate_scan_date(date_str);symbol=symbol.strip().upper()
    if not symbol or len(symbol)>30 or not all(ch.isalnum() or ch in "&-_" for ch in symbol):abort(404)
    df=_load_filtered(date_str)
    matches=df[df["Symbol"].astype(str).str.upper()==symbol] if df is not None and not df.empty and "Symbol" in df.columns else pd.DataFrame()
    if matches.empty:
        df=_load_full(date_str)
        if df is None or df.empty or "Symbol" not in df.columns:abort(404)
        matches=df[df["Symbol"].astype(str).str.upper()==symbol]
    if matches.empty:abort(404)
    raw=matches.iloc[0].to_dict();full_df=_load_full(date_str)
    if full_df is not None and not full_df.empty and "Symbol" in full_df.columns:
        full_matches=full_df[full_df["Symbol"].astype(str).str.upper()==symbol]
        if not full_matches.empty:
            full_raw=full_matches.iloc[0].to_dict()
            for field in ["ReportedBuyTxn","PricedValuePurchased","MissingValueQty","MissingValueTxn","MarketBuyValue","MarketSellValue","NetBuyValue","SellBuyRatioPct","HasMarketSell","SellBuyExclusion","DMA50","DMA200","52WeekHigh","52WeekLow"]:
                if field in full_raw and _clean(full_raw[field]) is not None:
                    raw[field]=full_raw[field]
    row=_df_to_rows(pd.DataFrame([raw]),include_flags=True)[0];row["trades"]=(_load_trades(date_str) or {}).get(symbol,[])
    return jsonify(row)
@app.get("/healthz")
def healthz():return {"status":"ok"},200
@app.errorhandler(404)
def not_found(e):return render_template("404.html"),404
if __name__=="__main__":
    port=int(os.environ.get("PORT",5000));debug=os.environ.get("FLASK_DEBUG","0")=="1";host=os.environ.get("HOST","0.0.0.0");app.run(debug=debug,host=host,port=port)