import streamlit as st
import pandas as pd
import yfinance as yf
import twstock

# 設定頁面
st.set_page_config(page_title="夢想起飛：全台股特搜", layout="wide")

# ==========================================
# 1. 第一階段：取得全台股票清單 (本地端獲取，不需爬蟲)
# ==========================================
@st.cache_data(ttl=86400)
def get_tw_stock_list():
    """
    使用 twstock 套件直接讀取內建的股票清單 (完全避開網路阻擋)
    """
    try:
        # 取得上市與上櫃股票代號
        # twstock.codes 是一個字典，包含所有代號資訊
        all_codes = twstock.codes
        
        candidates = []
        
        for code, info in all_codes.items():
            # 篩選條件：
            # 1. type 為 '股票' (排除權證、ETF等)
            # 2. market 為 '上市' 或 '上櫃'
            if info.type == '股票' and info.market in ['上市', '上櫃']:
                
                # 判斷後綴
                suffix = ".TW" if info.market == '上市' else ".TWO"
                full_ticker = f"{code}{suffix}"
                
                candidates.append({
                    "ticker": code,
                    "full_ticker": full_ticker,
                    "name": info.name,
                    "market": info.market
                })
        
        return pd.DataFrame(candidates)
        
    except Exception as e:
        st.error(f"清單讀取失敗: {e}")
        return pd.DataFrame()

# ==========================================
# 2. 第二階段：計算「近5日」成交量並排序
# ==========================================
@st.cache_data(ttl=1800)
def get_top_500_by_volume(candidates_df):
    
    if candidates_df.empty: return pd.DataFrame()
    
    # 為了節省時間，我們先用 yfinance 批次下載
    # 雖然全台股有 1700+ 檔，yfinance 分批處理還算快
    
    all_tickers = candidates_df['full_ticker'].tolist()
    st.toast(f"正在分析全台 {len(all_tickers)} 檔股票的量能...", icon="🚀")
    
    try:
        # 下載近 5 日資料
        # auto_adjust=True 讓價格更準確
        data = yf.download(all_tickers, period="5d", group_by='ticker', progress=False, threads=True)
        
        vol_data = []
        
        # 遍歷資料
        for index, row in candidates_df.iterrows():
            ft = row['full_ticker']
            
            try:
                # 檢查資料是否存在
                if ft not in data.columns.levels[0]: continue
                
                df_stock = data[ft]
                if df_stock.empty: continue
                
                # 計算 5 日總量
                total_vol = df_stock['Volume'].sum()
                last_price = df_stock['Close'].iloc[-1]
                
                # 排除成交量太小的 (例如 5天加起來不到 500 張)
                if total_vol > 500000: # 500張 * 1000股
                    vol_data.append({
                        "ticker": row['ticker'],
                        "full_ticker": ft,
                        "name": row['name'],
                        "market": row['market'],
                        "5d_vol_sum": int(total_vol),
                        "price": float(last_price)
                    })
            except:
                continue
                
        # 排序並取前 500
        df_res = pd.DataFrame(vol_data)
        df_res = df_res.sort_values(by="5d_vol_sum", ascending=False).head(500)
        
        return df_res
        
    except Exception as e:
        st.error(f"數據下載失敗: {e}")
        return pd.DataFrame()

# ==========================================
# 3. 第三階段：策略運算
# ==========================================
def run_strategy_on_top500(top_500_df, strict_mode):
    
    tickers = top_500_df['full_ticker'].tolist()
    
    status_text = st.empty()
    status_text.text(f"正在對前 500 大熱門股進行深度掃描...")
    
    try:
        # 下載 1 年資料用於均線計算
        data = yf.download(tickers, period="1y", group_by='ticker', progress=False, threads=True)
    except:
        return []
        
    results = []
    progress_bar = st.progress(0)
    total = len(top_500_df)
    
    for i, (index, row) in enumerate(top_500_df.iterrows()):
        progress_val = min((i + 1) / total, 1.0)
        progress_bar.progress(progress_val)
        
        ft = row['full_ticker']
        
        try:
            if ft not in data.columns.levels[0]: continue
            df = data[ft].dropna()
            
            if len(df) < 205: continue
            
            close = df['Close'].squeeze()
            volume = df['Volume'].squeeze()
            curr_price = close.iloc[-1]
            
            # --- 指標計算 ---
            ma5 = close.rolling(5).mean().iloc[-1]
            ma20 = close.rolling(20).mean().iloc[-1]
            ma60 = close.rolling(60).mean().iloc[-1]
            ma120 = close.rolling(120).mean().iloc[-1]
            
            ma200_series = close.rolling(200).mean()
            c_ma200 = ma200_series.iloc[-1]
            
            vol_ma20_series = volume.rolling(20).mean()
            
            # --- 篩選 ---
            # 1. 均線排列
            cond_price = (curr_price > ma5) and (curr_price > ma20) and \
                         (curr_price > ma60) and (curr_price > ma120)
            if not cond_price: continue
            
            # 2. 乖離率
            bias_val = ((ma5 - c_ma200) / c_ma200) * 100
            cond_bias = bias_val < 30
            
            # 3. 趨勢
            segment_len = 10
            if strict_mode:
                cond_ma200 = ma200_series.iloc[-(segment_len+1):].diff().dropna().gt(0).all()
                cond_vol = vol_ma20_series.iloc[-(segment_len+1):].diff().dropna().gt(0).all()
            else:
                cond_ma200 = ma200_series.iloc[-1] > ma200_series.iloc[-(segment_len+1)]
                cond_vol = vol_ma20_series.iloc[-1] > vol_ma20_series.iloc[-(segment_len+1)]
            
            if cond_bias and cond_ma200 and cond_vol:
                results.append({
                    "代號": row['ticker'],
                    "名稱": row['name'],
                    "現價": row['price'],
                    "5日總量(張)": int(row['5d_vol_sum'] / 1000),
                    "乖離率": f"{bias_val:.2f}%",
                    "趨勢": "🔥強勢" if strict_mode else "📈向上"
                })
                
        except:
            continue
            
    status_text.empty()
    return results

# ==========================================
# 4. UI 介面
# ==========================================
st.title("🚀 夢想起飛：全台股特搜 (Twstock版)")
st.info("本版本使用 twstock 內建清單，保證不被防火牆阻擋。")

with st.sidebar:
    st.header("⚙️ 參數")
    strict_mode = st.checkbox("嚴格模式", value=False)
    st.caption("說明：掃描全台 1700+ 檔股票 -> 取近5日成交量前 500 大 -> 策略過濾")

if st.button("開始執行 (約 1-2 分鐘)", type="primary"):
    
    # Step 1
    with st.spinner("正在讀取全台股票清單 (本地)..."):
        candidates = get_tw_stock_list()
        if candidates.empty:
            st.error("清單建立失敗，請檢查 twstock 套件是否安裝。")
            st.stop()
        st.write(f"✅ 成功載入 {len(candidates)} 檔上市櫃股票。")
        
    # Step 2
    with st.spinner("正在計算全市場量能排序..."):
        top_500 = get_top_500_by_volume(candidates)
        if top_500.empty:
            st.error("無法下載市場數據。")
            st.stop()
        st.write(f"✅ 已鎖定 5日成交量最大的 500 檔 (龍頭: {top_500.iloc[0]['name']})")
        
    # Step 3
    results = run_strategy_on_top500(top_500, strict_mode)
    
    if results:
        df_res = pd.DataFrame(results)
        df_res = df_res.sort_values(by="5日總量(張)", ascending=False)
        
        st.success(f"🎉 篩選完成！共 {len(df_res)} 檔")
        st.dataframe(
            df_res,
            column_config={
                "現價": st.column_config.NumberColumn(format="$%.2f"),
                "5日總量(張)": st.column_config.NumberColumn(format="%d 張"),
            },
            use_container_width=True,
            hide_index=True
        )
    else:
        st.warning("🧐 掃描完畢，無股票符合條件。建議關閉嚴格模式。")
