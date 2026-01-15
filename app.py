import streamlit as st
import pandas as pd
import yfinance as yf
import requests

st.set_page_config(page_title="夢想起飛：5日量能特搜", layout="wide")

# ==========================================
# 1. 第一階段：取得廣泛的候選名單 (含名稱)
#    從 Yahoo API 抓取上市櫃各前 400 名，共 800 名候選
# ==========================================
@st.cache_data(ttl=600)
def get_candidates_from_yahoo():
    """
    從 Yahoo API 取得上市與上櫃目前活躍的股票清單 (為了取得代號與名稱)
    """
    # 為了確保涵蓋到「近5日」熱門但「今日」可能稍微休息的股，我們抓寬一點 (各400檔)
    fetch_limit = 400
    
    api_urls = [
        {"market": "上市", "url": f"https://tw.stock.yahoo.com/_td-stock/api/resource/StockServices.rank;exchange=TAI;limit={fetch_limit};period=day;rankType=vol"},
        {"market": "上櫃", "url": f"https://tw.stock.yahoo.com/_td-stock/api/resource/StockServices.rank;exchange=TWO;limit={fetch_limit};period=day;rankType=vol"}
    ]
    
    candidates = []
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0 Safari/537.36'}

    try:
        status_text = st.empty()
        status_text.text("正在連線 Yahoo 取得基礎名單...")

        for item in api_urls:
            res = requests.get(item["url"], headers=headers, timeout=10)
            if res.status_code == 200:
                data = res.json()
                stock_list = data.get('list', [])
                for stock in stock_list:
                    symbol = stock.get('symbol', '')
                    name = stock.get('name', '')
                    ticker = symbol.split('.')[0]
                    
                    # 簡單過濾：只留普通股 (4碼)
                    if len(ticker) == 4 and symbol:
                        candidates.append({
                            "ticker": ticker,
                            "full_ticker": symbol,
                            "name": name,
                            "market": item['market']
                        })
        
        status_text.empty()
        return pd.DataFrame(candidates)
        
    except Exception as e:
        st.error(f"基礎名單抓取失敗: {e}")
        return pd.DataFrame()

# ==========================================
# 2. 第二階段：計算「近5日」成交量並排序
# ==========================================
@st.cache_data(ttl=1800)
def get_top_500_by_5day_volume(candidates_df):
    """
    下載候選股近5日資料，計算總量，排序取前 500
    """
    if candidates_df.empty:
        return pd.DataFrame()

    tickers = candidates_df['full_ticker'].tolist()
    st.toast(f"正在計算 {len(tickers)} 檔股票的近5日成交量...", icon="📊")
    
    try:
        # 批次下載近 5 日資料
        data = yf.download(tickers, period="5d", group_by='ticker', progress=False, threads=True)
        
        vol_stats = []
        
        for index, row in candidates_df.iterrows():
            ft = row['full_ticker']
            try:
                if ft not in data.columns.levels[0]: continue
                
                df_stock = data[ft]
                if df_stock.empty: continue
                
                # 計算近 5 日成交量總和
                # yfinance Volume 單位通常是股數
                total_vol = df_stock['Volume'].sum()
                last_price = df_stock['Close'].iloc[-1]
                
                if total_vol > 0:
                    vol_stats.append({
                        "ticker": row['ticker'],
                        "full_ticker": ft,
                        "name": row['name'],
                        "market": row['market'],
                        "5d_vol_sum": int(total_vol), # 5日總量
                        "price": float(last_price)
                    })
            except:
                continue
                
        # 轉 DataFrame 並排序
        df_res = pd.DataFrame(vol_stats)
        df_res = df_res.sort_values(by="5d_vol_sum", ascending=False)
        
        # 取前 500 名
        return df_res.head(500)

    except Exception as e:
        st.error(f"成交量計算錯誤: {e}")
        return pd.DataFrame()

# ==========================================
# 3. 第三階段：批量策略分析 (針對 Top 500)
# ==========================================
def run_strategy_batch(top_500_df, strict_mode):
    """
    針對篩選出的 500 檔，批次下載 1 年資料進行策略運算
    """
    tickers = top_500_df['full_ticker'].tolist()
    
    status_text = st.empty()
    status_text.text(f"正在對 {len(tickers)} 檔熱門股進行技術分析 (下載歷史 K 線)...")
    
    # 下載 1 年資料 (計算 MA200 需要)
    # 使用 threads 加速
    try:
        data = yf.download(tickers, period="1y", group_by='ticker', progress=False, threads=True)
    except Exception as e:
        st.error(f"歷史資料下載失敗: {e}")
        return []

    status_text.text("正在執行策略運算...")
    results = []
    
    # 建立進度條
    progress_bar = st.progress(0)
    
    total = len(top_500_df)
    
    for i, (index, row) in enumerate(top_500_df.iterrows()):
        # 更新進度
        progress_val = min((i + 1) / total, 1.0)
        progress_bar.progress(progress_val)
        
        ft = row['full_ticker']
        
        try:
            if ft not in data.columns.levels[0]: continue
            df = data[ft]
            
            # 資料長度檢查 (MA200 至少要 200 根，保險起見設 205)
            # dropna() 確保沒有空值干擾
            df = df.dropna()
            if len(df) < 205: continue
            
            close = df['Close'].squeeze()
            volume = df['Volume'].squeeze()
            
            curr_price = close.iloc[-1]
            
            # --- 計算均線 ---
            ma5 = close.rolling(5).mean().iloc[-1]
            ma20 = close.rolling(20).mean().iloc[-1]
            ma60 = close.rolling(60).mean().iloc[-1]
            ma120 = close.rolling(120).mean().iloc[-1]
            
            ma200_series = close.rolling(200).mean()
            c_ma200 = ma200_series.iloc[-1]
            
            vol_ma20_series = volume.rolling(20).mean()
            
            # --- 條件 1: 均線多頭排列 ---
            # 收盤價 > MA5, MA20, MA60, MA120
            cond_price = (curr_price > ma5) and (curr_price > ma20) and \
                         (curr_price > ma60) and (curr_price > ma120)
            
            if not cond_price: continue
            
            # --- 條件 2: 乖離率 (5, 200) < 30 ---
            bias_val = ((ma5 - c_ma200) / c_ma200) * 100
            cond_bias = bias_val < 30
            
            # --- 條件 3: 趨勢判斷 (MA200 & 均量) ---
            segment_len = 10
            if strict_mode:
                # 嚴格：連續10天 Diff > 0
                cond_ma200 = ma200_series.iloc[-(segment_len+1):].diff().dropna().gt(0).all()
                cond_vol = vol_ma20_series.iloc[-(segment_len+1):].diff().dropna().gt(0).all()
            else:
                # 寬鬆：目前 > 10天前
                cond_ma200 = ma200_series.iloc[-1] > ma200_series.iloc[-(segment_len+1)]
                cond_vol = vol_ma20_series.iloc[-1] > vol_ma20_series.iloc[-(segment_len+1)]

            if cond_bias and cond_ma200 and cond_vol:
                # 轉換 5日總量為「張數」 (股數 / 1000)
                vol_in_sheets = int(row['5d_vol_sum'] / 1000)
                
                results.append({
                    "代號": row['ticker'],
                    "名稱": row['name'],
                    "現價": row['price'],
                    "5日總量(張)": vol_in_sheets,
                    "乖離率": f"{bias_val:.2f}%",
                    "趨勢": "🔥強勢" if strict_mode else "📈向上"
                })
                
        except Exception:
            continue
            
    status_text.empty()
    return results

# ==========================================
# 4. UI 介面
# ==========================================
st.title("🚀 夢想起飛：5日量能特搜")
st.markdown("### 邏輯流程")
st.info("""
1. **廣泛搜查**：掃描上市櫃約 800 檔活躍股。
2. **量能排序**：計算 **近5日成交總量**，取出前 **500大**。
3. **策略篩選**：多頭排列 + 乖離率 < 30% + 年線/均量趨勢向上。
""")

with st.sidebar:
    st.header("⚙️ 參數設定")
    strict_mode = st.checkbox("嚴格模式 (連續10日每日上升)", value=False)
    st.caption("建議：預設關閉嚴格模式，僅判斷10日趨勢方向，較符合實戰。")

if st.button("開始執行 (約需 1-2 分鐘)", type="primary"):
    
    # Step 1
    candidates = get_candidates_from_yahoo()
    if candidates.empty:
        st.error("無法取得基礎名單，請稍後再試。")
        st.stop()
        
    # Step 2
    top_500 = get_top_500_by_5day_volume(candidates)
    if top_500.empty:
        st.error("無法計算成交量，請檢查網路。")
        st.stop()
        
    st.success(f"✅ 已鎖定近5日成交量最大的 500 檔股票 (第1名: {top_500.iloc[0]['name']})")
    
    # Step 3
    results = run_strategy_batch(top_500, strict_mode)
    
    if results:
        df_final = pd.DataFrame(results)
        # 依 5日總量 排序
        df_final = df_final.sort_values(by="5日總量(張)", ascending=False)
        
        st.subheader(f"🎉 篩選結果：共 {len(df_final)} 檔")
        st.dataframe(
            df_final,
            column_config={
                "現價": st.column_config.NumberColumn(format="$%.2f"),
                "5日總量(張)": st.column_config.NumberColumn(format="%d 張"),
            },
            use_container_width=True,
            hide_index=True
        )
    else:
        st.warning("🧐 掃描這 500 檔後，沒有股票符合您的策略條件。")
        st.markdown("建議：**關閉嚴格模式** 或目前市場可能處於修正期。")
