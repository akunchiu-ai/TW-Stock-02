import streamlit as st
import pandas as pd
import yfinance as yf

# 設定頁面配置
st.set_page_config(page_title="夢想起飛：全市場掃描", layout="wide")

# ==========================================
# 1. 定義「台股宇宙」 (Top 300 權值與熱門股)
# ==========================================
STOCK_UNIVERSE = [
    # 半導體/AI
    "2330.TW", "2317.TW", "2454.TW", "2303.TW", "2308.TW", "2382.TW", "3231.TW", "2357.TW", "2376.TW", "2356.TW",
    "2379.TW", "2383.TW", "2368.TW", "2353.TW", "2324.TW", "2344.TW", "2449.TW", "2408.TW", "3443.TW", "3034.TW",
    "3711.TW", "3037.TW", "3035.TW", "3017.TW", "3008.TW", "3189.TW", "3532.TW", "3661.TW", "4938.TW", "4958.TW",
    "5269.TW", "5274.TWO", "6669.TW", "6415.TW", "6531.TW", "6770.TW", "8046.TW", "8210.TW", "3653.TW",
    # 航運/傳產
    "2603.TW", "2609.TW", "2615.TW", "2618.TW", "2610.TW", "2605.TW", "2606.TW", "2637.TW", "2634.TW",
    "1605.TW", "1609.TW", "1513.TW", "1519.TW", "1503.TW", "1504.TW", "1514.TW", "2002.TW", "2014.TW", "2027.TW",
    "1101.TW", "1102.TW", "1301.TW", "1303.TW", "1326.TW", "1907.TW", "9904.TW", "9945.TW", "2515.TW",
    # 金融
    "2881.TW", "2882.TW", "2891.TW", "2886.TW", "2884.TW", "2892.TW", "2880.TW", "2885.TW", "2883.TW", "2890.TW",
    "2887.TW", "2834.TW", "5880.TW", "5871.TW", "5876.TW", "2812.TW", "2801.TW",
    # 光電/網通/其他電子
    "2409.TW", "3481.TW", "6116.TW", "2481.TW", "3019.TW", "2313.TW", "3062.TW", "3596.TWO", "4906.TW", "5388.TWO",
    "6285.TW", "8069.TWO", "3707.TW", "2392.TW", "6239.TW", "6278.TW", "3583.TW", "3376.TW", "6213.TW", "3044.TW",
    # 上櫃熱門/生技
    "6446.TWO", "6472.TWO", "4114.TWO", "4128.TWO", "4743.TWO", "6180.TWO", "5347.TWO", "3293.TWO", "3324.TWO",
    "6147.TWO", "8044.TWO", "8299.TWO", "3105.TWO", "3374.TWO", "3693.TWO", "3529.TWO", "3548.TWO", "3264.TWO",
    "4966.TWO", "4979.TWO", "5371.TWO", "5483.TWO", "6121.TWO", "6182.TWO", "6217.TWO", "6223.TWO", "6274.TWO",
    "6547.TWO", "6589.TWO", "8086.TWO", "8255.TWO", "8358.TWO", "8936.TWO", "8050.TWO", "6104.TWO", "3680.TWO",
    "3260.TWO", "3227.TWO", "3218.TWO", "3163.TWO", "3141.TWO", "3128.TWO", "1795.TWO", "1565.TWO",
    # 更多大型權值
    "1216.TW", "1402.TW", "1476.TW", "2105.TW", "2207.TW", "2345.TW", "2395.TW", "2412.TW", "2474.TW", "2492.TW",
    "2912.TW", "3045.TW", "3702.TW", "4915.TW", "5871.TW", "6505.TW", "9910.TW", "9921.TW", "9941.TW"
]

# ==========================================
# 2. 核心功能：批量下載與排序
# ==========================================
@st.cache_data(ttl=600)  # 快取 10 分鐘
def get_sorted_market_data(limit=100):
    try:
        # 使用 yfinance 批量下載
        data = yf.download(STOCK_UNIVERSE, period="5d", group_by='ticker', progress=False)
        
        if data.empty: return pd.DataFrame()

        snapshot = []
        
        for ticker in STOCK_UNIVERSE:
            try:
                if ticker not in data.columns.levels[0]: continue
                
                df_stock = data[ticker]
                if df_stock.empty: continue
                
                latest = df_stock.iloc[-1]
                vol = latest['Volume']
                price = latest['Close']
                
                if pd.isna(vol) or vol == 0: continue
                
                snapshot.append({
                    "ticker": ticker.split('.')[0],
                    "full_ticker": ticker,
                    "volume": int(vol),
                    "price": float(price)
                })
            except:
                continue
        
        df_all = pd.DataFrame(snapshot)
        
        if df_all.empty: return pd.DataFrame()
        
        # 排序後，這裡的索引(Index)會變亂，例如 [5, 23, 1...]
        df_sorted = df_all.sort_values(by="volume", ascending=False).head(limit)
        
        return df_sorted

    except Exception as e:
        print(f"Data Fetch Error: {e}")
        return pd.DataFrame()

# ==========================================
# 3. 策略邏輯 (單檔分析)
# ==========================================
def check_dream_strategy(row_data, strict_mode=True):
    full_ticker = row_data['full_ticker']
    
    try:
        df = yf.download(full_ticker, period="1y", progress=False)
        
        if len(df) < 205: return None
        
        close = df['Close'].squeeze()
        volume = df['Volume'].squeeze()
        curr_price = close.iloc[-1]
        
        # --- 計算指標 ---
        ma5 = close.rolling(5).mean().iloc[-1]
        ma20 = close.rolling(20).mean().iloc[-1]
        ma60 = close.rolling(60).mean().iloc[-1]
        ma120 = close.rolling(120).mean().iloc[-1]
        
        ma200_series = close.rolling(200).mean()
        c_ma200 = ma200_series.iloc[-1]
        
        vol_ma20_series = volume.rolling(20).mean()
        
        # --- 條件 ---
        cond_price = (curr_price > ma5) and (curr_price > ma20) and \
                     (curr_price > ma60) and (curr_price > ma120)
        
        if not cond_price: return None
        
        bias_val = ((ma5 - c_ma200) / c_ma200) * 100
        cond_bias = bias_val < 30
        
        segment_len = 10
        if strict_mode:
            cond_ma200 = ma200_series.iloc[-(segment_len+1):].diff().dropna().gt(0).all()
            cond_vol = vol_ma20_series.iloc[-(segment_len+1):].diff().dropna().gt(0).all()
        else:
            cond_ma200 = ma200_series.iloc[-1] > ma200_series.iloc[-(segment_len+1)]
            cond_vol = vol_ma20_series.iloc[-1] > vol_ma20_series.iloc[-(segment_len+1)]

        if cond_bias and cond_ma200 and cond_vol:
            return {
                "代號": row_data['ticker'],
                "現價": row_data['price'],
                "成交量": row_data['volume'],
                "乖離率": f"{bias_val:.2f}%",
                "趨勢": "🔥強勢" if strict_mode else "📈向上"
            }
            
    except Exception:
        return None
    return None

# ==========================================
# 4. UI 介面
# ==========================================
st.title("🚀 夢想起飛：台股掃描器 (雲端穩定版)")
st.markdown("### 資料來源：全市場重點掃描 (避開防火牆)")
st.caption("此版本內建 150+ 檔台股重點股票，自動抓取並依成交量排序，保證在手機/雲端皆可運行。")

with st.sidebar:
    st.header("⚙️ 設定")
    scan_count = st.slider("掃描前幾大熱門股", 30, 150, 80)
    strict_mode = st.checkbox("嚴格模式 (連續10日上升)", value=False)
    st.info("💡 小撇步：若找不到股票，請關閉嚴格模式。")

if st.button("開始執行選股", type="primary"):
    
    with st.status("正在連線至市場數據...", expanded=True) as status:
        st.write("📡 正在批量下載台股報價...")
        
        df_hot = get_sorted_market_data(limit=scan_count)
        
        if df_hot.empty:
            status.update(label="❌ 下載失敗", state="error")
            st.error("無法取得報價，請稍後再試。")
            st.stop()
            
        st.write(f"✅ 成功取得成交量前 {len(df_hot)} 名股票，開始分析...")
        
        results = []
        progress_bar = st.progress(0)
        
        # --- 修正重點在這裡 ---
        # 使用 enumerate 強制取得新的計數器 i (0, 1, 2...)
        # 同時取得 row (資料)
        for i, (index, row) in enumerate(df_hot.iterrows()):
            
            # 計算進度百分比 (確保不超過 1.0)
            progress_val = min((i + 1) / len(df_hot), 1.0)
            progress_bar.progress(progress_val)
            
            res = check_dream_strategy(row, strict_mode)
            if res:
                results.append(res)
        
        status.update(label="分析完成！", state="complete", expanded=False)

    if results:
        final_df = pd.DataFrame(results)
        final_df = final_df.sort_values(by="成交量", ascending=False)
        
        st.success(f"🎉 篩選出 {len(final_df)} 檔潛力股！")
        
        st.dataframe(
            final_df,
            column_config={
                "現價": st.column_config.NumberColumn(format="$%.2f"),
                "成交量": st.column_config.NumberColumn(format="%d"),
            },
            use_container_width=True,
            hide_index=True
        )
    else:
        st.warning("🧐 掃描完畢，沒有股票符合條件。")
        st.markdown("**建議：** 嘗試關閉「嚴格模式」再試一次。")
