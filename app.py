import streamlit as st
import pandas as pd
import yfinance as yf
import requests

# 設定頁面
st.set_page_config(page_title="夢想起飛：上市櫃全掃描", layout="wide")

# --- 0. 內建備用熱門股清單 (救生圈) ---
# 當爬蟲失效時，自動使用這份清單，確保 APP 能運作
FALLBACK_STOCKS = [
    # 上市熱門 (電子/航運/AI/重電)
    "2330.TW", "2317.TW", "2454.TW", "2303.TW", "2308.TW", "2382.TW", "3231.TW", "2357.TW", "2376.TW", "2356.TW",
    "2603.TW", "2609.TW", "2615.TW", "2618.TW", "2610.TW", "2605.TW", "2606.TW",
    "3037.TW", "3035.TW", "3017.TW", "3481.TW", "2409.TW", "2481.TW", "2408.TW",
    "1513.TW", "1519.TW", "1504.TW", "1514.TW", "1609.TW", "1605.TW",
    "2891.TW", "2881.TW", "2882.TW", "2886.TW", "2892.TW", "2884.TW", "2890.TW", "2885.TW", "2880.TW", "2883.TW",
    "1101.TW", "1605.TW", "2002.TW", "2324.TW", "2353.TW", "2354.TW", "2368.TW", "2379.TW", "2383.TW", "2385.TW",
    "2449.TW", "2498.TW", "2515.TW", "3008.TW", "3034.TW", "3044.TW", "3189.TW", "3231.TW", "3443.TW", "3532.TW",
    "3661.TW", "3711.TW", "4938.TW", "5871.TW", "5876.TW", "6239.TW", "6669.TW", "8046.TW", "9904.TW", "9945.TW",
    "3019.TW", "2421.TW", "2363.TW", "8210.TW", "3653.TW", "6285.TW", "2344.TW", "3583.TW", "6176.TW", "2313.TW",
    
    # 上櫃熱門 (生技/半導體/光電)
    "8069.TWO", "5347.TWO", "6180.TWO", "3293.TWO", "3105.TWO", "3324.TWO", "3374.TWO", "3529.TWO", "3264.TWO",
    "3548.TWO", "3680.TWO", "3693.TWO", "4105.TWO", "4114.TWO", "4128.TWO", "4162.TWO", "4743.TWO", "4966.TWO",
    "4979.TWO", "5009.TWO", "5274.TWO", "5371.TWO", "5483.TWO", "6121.TWO", "6138.TWO", "6147.TWO", "6182.TWO",
    "6217.TWO", "6223.TWO", "6274.TWO", "6446.TWO", "6472.TWO", "6488.TWO", "6547.TWO", "6589.TWO", "8044.TWO",
    "8086.TWO", "8255.TWO", "8299.TWO", "8358.TWO", "8936.TWO", "8050.TWO", "6104.TWO", "3363.TWO", "3141.TWO"
]

# --- 1. 爬蟲功能 (含自動備援機制) ---
@st.cache_data(ttl=3600)
def get_hot_stocks_smart(limit=100):
    """
    嘗試抓取網路排行，若失敗則回傳內建備用清單
    """
    # 嘗試抓取 (HiStock)
    try:
        url_tw = "https://histock.tw/stock/rank.aspx?m=tw"
        url_two = "https://histock.tw/stock/rank.aspx?m=otc"
        
        all_stocks = []
        headers = {'User-Agent': 'Mozilla/5.0'} # 簡單 Header
        
        for url, suffix, market in [(url_tw, ".TW", "上市"), (url_two, ".TWO", "上櫃")]:
            try:
                dfs = pd.read_html(url, encoding='utf-8', header=0)
                if dfs:
                    df = dfs[0]
                    # 尋找代號欄位
                    col_code = [c for c in df.columns if "代號" in c][0]
                    col_vol = [c for c in df.columns if "成交量" in c][0]
                    
                    for i, row in df.iterrows():
                        code = str(row[col_code]).replace("'", "").strip()
                        # 處理代號，只留數字
                        code = ''.join(filter(str.isdigit, code))
                        if not code: continue
                        
                        full_ticker = f"{code}{suffix}"
                        
                        # 處理成交量
                        vol = 0
                        try:
                            vol = int(str(row[col_vol]).replace(',', ''))
                        except:
                            vol = 0
                            
                        all_stocks.append({
                            "ticker": code,
                            "full_ticker": full_ticker,
                            "market": market,
                            "volume": vol
                        })
            except:
                continue

        if len(all_stocks) > 10:
            df_res = pd.DataFrame(all_stocks)
            df_res = df_res.sort_values(by="volume", ascending=False).head(limit)
            return df_res, "網路即時排行"
            
    except Exception:
        pass

    # --- 如果上面失敗，執行這裡 (B計畫) ---
    fallback_data = []
    for ticker in FALLBACK_STOCKS:
        code = ticker.split('.')[0]
        mkt = "上市" if "TW" in ticker and "TWO" not in ticker else "上櫃"
        fallback_data.append({
            "ticker": code,
            "full_ticker": ticker,
            "market": mkt,
            "volume": 0 # 備用清單無即時量，設為0
        })
    
    return pd.DataFrame(fallback_data).head(limit), "⚠️ 內建熱門清單 (網路抓取受阻)"


# --- 2. 策略邏輯 ---
def check_strategy(row_data, strict_mode=True):
    ticker = row_data['ticker']
    full_ticker = row_data['full_ticker']
    
    try:
        # 下載資料
        df = yf.download(full_ticker, period="18mo", progress=False)
        
        if len(df) < 210: return None
        
        # 處理資料
        close = df['Close'].squeeze()
        volume = df['Volume'].squeeze()
        
        curr_price = close.iloc[-1]
        
        # 計算均線
        ma5 = close.rolling(5).mean().iloc[-1]
        ma20 = close.rolling(20).mean().iloc[-1]
        ma60 = close.rolling(60).mean().iloc[-1]
        ma120 = close.rolling(120).mean().iloc[-1]
        
        # MA200 序列
        ma200_series = close.rolling(200).mean()
        c_ma200 = ma200_series.iloc[-1]
        
        # 均量 20MA
        vol_ma20_series = volume.rolling(20).mean()
        
        # --- 條件 ---
        # 1. 均線多頭
        cond_price = (curr_price > ma5) and (curr_price > ma20) and \
                     (curr_price > ma60) and (curr_price > ma120)
        
        # 2. 乖離率 (5,200) < 30
        bias_val = ((ma5 - c_ma200) / c_ma200) * 100
        cond_bias = bias_val < 30
        
        # 3 & 4. 趨勢判斷
        segment_len = 10
        if strict_mode:
            ma200_seg = ma200_series.iloc[-segment_len-1:]
            vol_seg = vol_ma20_series.iloc[-segment_len-1:]
            cond_ma200_trend = ma200_seg.diff().dropna().gt(0).all()
            cond_vol_trend = vol_seg.diff().dropna().gt(0).all()
        else:
            cond_ma200_trend = ma200_series.iloc[-1] > ma200_series.iloc[-11]
            cond_vol_trend = vol_ma20_series.iloc[-1] > vol_ma20_series.iloc[-11]

        if cond_price and cond_bias and cond_ma200_trend and cond_vol_trend:
            # 如果是備用清單，補上最新的成交量
            display_vol = int(volume.iloc[-1])
            
            return {
                "股票代號": ticker,
                "市場": row_data['market'],
                "現價": round(curr_price, 2),
                "乖離率(%)": round(bias_val, 2),
                "MA200趨勢": "連漲" if strict_mode else "向上",
                "均量趨勢": "連漲" if strict_mode else "向上",
                "成交量": display_vol
            }
        
    except Exception:
        return None
    return None

# --- 3. UI 介面 ---
st.title("🚀 夢想起飛：上市櫃選股 APP")
st.markdown("""
**選股條件：** 收盤 > MA5/20/60/120 且 (5,200)乖離 < 30% 且 MA200/均量趨勢向上
""")

col1, col2 = st.columns(2)
with col1:
    scan_limit = st.slider("掃描股票數量", 50, 150, 100)
with col2:
    strict_mode = st.checkbox("嚴格模式 (每日上升)", value=False)

if st.button("開始選股", type="primary"):
    
    with st.status("正在準備資料...", expanded=True) as status:
        # 取得清單 (自動切換)
        df_hot, source_name = get_hot_stocks_smart(limit=scan_limit)
        
        if "內建" in source_name:
            st.warning(f"注意：無法抓取即時排行 (可能被阻擋)，已切換至「{source_name}」模式，分析約 150 檔權值熱門股。")
        else:
            st.info(f"成功取得：{source_name}")

        status.update(label="正在計算技術指標 (約需 30-60 秒)...", state="running")
        
        results = []
        progress_bar = st.progress(0)
        total_stocks = len(df_hot)
        
        for i, row in df_hot.iterrows():
            progress_bar.progress((i + 1) / total_stocks)
            res = check_strategy(row, strict_mode)
            if res:
                results.append(res)
        
        status.update(label="分析完成！", state="complete", expanded=False)

    # 顯示結果
    if results:
        final_df = pd.DataFrame(results)
        final_df = final_df.sort_values(by="成交量", ascending=False)
        
        st.success(f"🎉 找到 {len(final_df)} 檔符合條件的股票！")
        st.dataframe(
            final_df,
            column_config={
                "成交量": st.column_config.NumberColumn(format="%d 張"),
                "現價": st.column_config.NumberColumn(format="$%.2f"),
                "乖離率(%)": st.column_config.NumberColumn(format="%.2f%%"),
            },
            use_container_width=True,
            hide_index=True
        )
    else:
        st.warning("🧐 掃描完畢，沒有股票符合條件。建議關閉「嚴格模式」再試一次。")
