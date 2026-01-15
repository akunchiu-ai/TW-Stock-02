import streamlit as st
import pandas as pd
import yfinance as yf
import requests

# 設定頁面配置
st.set_page_config(page_title="夢想起飛：全動態掃描", layout="wide")

# ==========================================
# 1. 第一步：從 Yahoo API 動態取得 "量大" 股票清單
#    (包含：代號、名稱、即時成交量)
# ==========================================
@st.cache_data(ttl=600)  # 快取 10 分鐘
def get_dynamic_top_stocks(total_limit=500):
    """
    不使用內建清單，而是向 Yahoo 請求上市與上櫃成交量最大的股票
    """
    # 我們分別抓取上市前 300 名和上櫃前 300 名，這樣加起來就有 600 檔候選股
    # 足夠我們篩選出全市場成交量最大的 500 檔
    fetch_limit = 300 
    
    api_urls = [
        # 上市 (TAI)
        {"market": "上市", "url": f"https://tw.stock.yahoo.com/_td-stock/api/resource/StockServices.rank;exchange=TAI;limit={fetch_limit};period=day;rankType=vol"},
        # 上櫃 (TWO)
        {"market": "上櫃", "url": f"https://tw.stock.yahoo.com/_td-stock/api/resource/StockServices.rank;exchange=TWO;limit={fetch_limit};period=day;rankType=vol"}
    ]
    
    all_candidates = []
    
    # 偽裝 Header (避免被擋)
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0 Safari/537.36'
    }

    try:
        # 顯示狀態
        status_text = st.empty()
        status_text.text("正在連線 Yahoo 股市資料庫 (API)...")

        for item in api_urls:
            try:
                response = requests.get(item["url"], headers=headers, timeout=10)
                if response.status_code == 200:
                    data = response.json()
                    stock_list = data.get('list', [])
                    
                    for stock in stock_list:
                        symbol = stock.get('symbol', '')  # 格式如 "2330.TW"
                        name = stock.get('name', '')      # 格式如 "台積電"
                        price = stock.get('price', 0)
                        
                        # 成交量 (原始資料是股數，除以 1000 變張數)
                        raw_vol = stock.get('volInStock', 0)
                        vol_sheets = int(int(raw_vol) / 1000) if raw_vol else 0
                        
                        # 排除權證 (通常是 6 碼) 或其他非股票，這裡簡單篩選長度
                        # 一般股票代號不含後綴通常是 4 碼
                        ticker_code = symbol.split('.')[0]
                        
                        if len(ticker_code) == 4 and symbol:
                            all_candidates.append({
                                "ticker": ticker_code,
                                "full_ticker": symbol,
                                "name": name,
                                "volume": vol_sheets,
                                "price_now": price
                            })
            except Exception as e:
                print(f"API Fetch Error: {e}")
                continue

        status_text.empty()

        if not all_candidates:
            return pd.DataFrame()

        # 轉成 DataFrame
        df = pd.DataFrame(all_candidates)
        
        # 混合上市上櫃後，依照「成交量」由大到小排序
        df = df.sort_values(by="volume", ascending=False)
        
        # 取出使用者指定的前 N 大 (例如 500)
        df_final = df.head(total_limit)
        
        return df_final

    except Exception as e:
        st.error(f"連線失敗: {e}")
        return pd.DataFrame()

# ==========================================
# 2. 第二步：策略邏輯 (針對篩選出的熱門股進行分析)
# ==========================================
def check_dream_strategy(row_data, strict_mode=True):
    full_ticker = row_data['full_ticker']
    
    try:
        # 下載歷史資料 (yfinance)
        # 需要約 1 年資料來計算 MA200 (年線)
        df = yf.download(full_ticker, period="1y", progress=False)
        
        if len(df) < 205: return None
        
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
        cond_price = (curr_price > ma5) and (curr_price > ma20) and \
                     (curr_price > ma60) and (curr_price > ma120)
        
        if not cond_price: return None
        
        # --- 條件 2: 乖離率 < 30 ---
        bias_val = ((ma5 - c_ma200) / c_ma200) * 100
        cond_bias = bias_val < 30
        
        # --- 條件 3: 趨勢判斷 ---
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
            return {
                "代號": row_data['ticker'],
                "名稱": row_data['name'], # 這裡有 API 抓到的名稱
                "現價": row_data['price_now'], # API 抓到的即時價
                "成交量": row_data['volume'], # API 抓到的即時量
                "乖離率": f"{bias_val:.2f}%",
                "趨勢": "🔥強勢" if strict_mode else "📈向上"
            }
            
    except Exception:
        return None
    return None

# ==========================================
# 3. UI 介面
# ==========================================
st.title("🚀 夢想起飛：全市場動態掃描")
st.markdown("### 模式：全自動抓取市場最熱門股票")
st.caption("來源：Yahoo 股市 API (上市+上櫃) -> 自動排序 -> 策略篩選")

with st.sidebar:
    st.header("⚙️ 設定")
    # 讓使用者決定要分析前幾名，預設 300 比較快，最大 500
    scan_limit = st.slider("鎖定成交量前 N 大進行分析", 100, 500, 300) 
    strict_mode = st.checkbox("嚴格模式 (連續10日上升)", value=False)
    st.info("💡 建議：數量越多，計算時間越久 (300檔約需 1 分鐘)。")

if st.button("開始掃描", type="primary"):
    
    with st.status("正在啟動掃描引擎...", expanded=True) as status:
        
        # 步驟 1: 從 API 抓清單
        st.write(f"📡 正在從市場抓取成交量前 {scan_limit} 大股票 (含名稱)...")
        
        df_hot = get_dynamic_top_stocks(total_limit=scan_limit)
        
        if df_hot.empty:
            status.update(label="❌ 連線失敗", state="error")
            st.error("無法連線至報價伺服器，請稍後再試。")
            st.stop()
            
        st.write(f"✅ 成功鎖定 {len(df_hot)} 檔熱門股 (如: {df_hot.iloc[0]['name']})，開始技術分析...")
        
        # 步驟 2: 進行策略運算
        results = []
        progress_bar = st.progress(0)
        
        # 使用 enumerate 來確保進度條正確
        for i, (index, row) in enumerate(df_hot.iterrows()):
            
            # 計算進度
            progress_val = min((i + 1) / len(df_hot), 1.0)
            progress_bar.progress(progress_val)
            
            res = check_dream_strategy(row, strict_mode)
            if res:
                results.append(res)
        
        status.update(label="全市場掃描完成！", state="complete", expanded=False)

    # 步驟 3: 顯示結果
    if results:
        final_df = pd.DataFrame(results)
        # 依照成交量排序顯示
        final_df = final_df.sort_values(by="成交量", ascending=False)
        
        st.success(f"🎉 從前 {scan_limit} 大熱門股中，篩選出 {len(final_df)} 檔潛力股！")
        
        st.dataframe(
            final_df,
            column_config={
                "現價": st.column_config.NumberColumn(format="$%.2f"),
                "成交量": st.column_config.NumberColumn(format="%d 張"),
            },
            use_container_width=True,
            hide_index=True
        )
    else:
        st.warning("🧐 掃描完畢，沒有股票符合條件。")
        st.markdown("**建議：** 嘗試關閉「嚴格模式」或檢查是否因為盤勢不佳導致無人符合條件。")
