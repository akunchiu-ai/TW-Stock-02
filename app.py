import streamlit as st
import pandas as pd
import yfinance as yf
import requests
import json

# 設定頁面配置
st.set_page_config(page_title="夢想起飛：真實股市掃描", layout="wide")

# --- 1. 核心功能：直接串接 Yahoo 股市 API ---
@st.cache_data(ttl=1800)  # 設定 30 分鐘快取，避免頻繁請求
def get_real_market_rank(limit=100):
    """
    直接呼叫 Yahoo 股市的後端 API 取得上市與上櫃的成交量排行榜 (JSON格式)
    """
    st.toast("正在連線至證券交易所資料...", icon="📡")
    
    # Yahoo 股市 API 端點 (這是瀏覽器在背景偷偷呼叫的網址)
    # rankType=vol (成交量排行), period=day (日)
    api_urls = [
        {"market": "上市", "url": "https://tw.stock.yahoo.com/_td-stock/api/resource/StockServices.rank;exchange=TAI;limit={};period=day;rankType=vol"},
        {"market": "上櫃", "url": "https://tw.stock.yahoo.com/_td-stock/api/resource/StockServices.rank;exchange=TWO;limit={};period=day;rankType=vol"}
    ]
    
    all_stocks = []
    
    # 偽裝成真實瀏覽器 (這是關鍵，避免被擋)
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Referer': 'https://tw.stock.yahoo.com/rank/volume',
        'Accept': 'application/json'
    }

    try:
        for item in api_urls:
            # 格式化 URL，填入數量
            target_url = item["url"].format(limit)
            
            response = requests.get(target_url, headers=headers, timeout=10)
            
            if response.status_code == 200:
                data = response.json()
                
                # 解析 JSON 結構
                # Yahoo API 的結構通常在 ['list'] 裡面
                stock_list = data.get('list', [])
                
                for stock in stock_list:
                    # 取得代號與名稱
                    symbol = stock.get('symbol', '')  # 例如 "2330.TW"
                    name = stock.get('name', '')
                    
                    # 取得成交量 (volInStock 是股數，我們要換算成張數 / 1000)
                    raw_vol = stock.get('volInStock', 0)
                    volume_sheets = int(raw_vol) / 1000 if raw_vol else 0
                    
                    # 取得現價 (price)
                    price = stock.get('price', 0)

                    if symbol:
                        all_stocks.append({
                            "ticker": symbol.split('.')[0], # 只留數字代號
                            "full_ticker": symbol,          # 完整代號 (含 .TW)
                            "name": name,
                            "market": item["market"],
                            "volume": int(volume_sheets),
                            "price_now": price
                        })
            else:
                st.warning(f"無法取得 {item['market']} 資料 (Status: {response.status_code})")

        # 合併上市上櫃並排序
        if not all_stocks:
            return pd.DataFrame()

        df = pd.DataFrame(all_stocks)
        # 依成交量由大到小排序，取前 N 名
        df = df.sort_values(by="volume", ascending=False).head(limit)
        
        return df

    except Exception as e:
        st.error(f"連線發生錯誤: {e}")
        return pd.DataFrame()

# --- 2. 策略邏輯 (技術指標計算) ---
def check_dream_strategy(row_data, strict_mode=True):
    full_ticker = row_data['full_ticker']
    
    try:
        # 下載歷史資料 (yfinance)
        # 注意：我們至少需要 205 天的資料來計算 MA200
        df = yf.download(full_ticker, period="1y", progress=False)
        
        if len(df) < 205: return None
        
        # 處理資料格式 (移除多餘層級)
        close = df['Close'].squeeze()
        volume = df['Volume'].squeeze()
        
        # 取得最新收盤價 (若 API 有即時價則優先參考，或以 K 線最後一根為主)
        curr_price = close.iloc[-1]
        
        # --- 計算均線 (MA) ---
        ma5 = close.rolling(5).mean().iloc[-1]
        ma20 = close.rolling(20).mean().iloc[-1]
        ma60 = close.rolling(60).mean().iloc[-1]
        ma120 = close.rolling(120).mean().iloc[-1]
        ma200_series = close.rolling(200).mean()
        c_ma200 = ma200_series.iloc[-1]
        
        # --- 計算均量 (Vol MA) ---
        vol_ma20_series = volume.rolling(20).mean()
        
        # ==========================
        #    夢想起飛 條件判斷
        # ==========================
        
        # 條件 1: 收盤價 > 5, 20, 60, 120 日均線 (完全多頭排列)
        cond_price = (curr_price > ma5) and (curr_price > ma20) and \
                     (curr_price > ma60) and (curr_price > ma120)
        
        if not cond_price: return None # 提早篩選以加速
        
        # 條件 2: (5, 200) 乖離率 < 30%
        # 公式: (MA5 - MA200) / MA200 * 100
        bias_val = ((ma5 - c_ma200) / c_ma200) * 100
        cond_bias = bias_val < 30
        
        # 條件 3 & 4: MA200 與 均量 連續 10 日上升
        # 取最後 11 筆資料來比較 10 個區間
        segment_len = 10
        ma200_seg = ma200_series.iloc[-(segment_len+1):]
        vol_seg = vol_ma20_series.iloc[-(segment_len+1):]
        
        if strict_mode:
            # 嚴格版：每天都要比前一天大 (Diff 全為正)
            cond_ma200 = ma200_seg.diff().dropna().gt(0).all()
            cond_vol = vol_seg.diff().dropna().gt(0).all()
        else:
            # 寬鬆版：今天的均線 > 10天前的均線 (整體趨勢向上)
            cond_ma200 = ma200_series.iloc[-1] > ma200_series.iloc[-(segment_len+1)]
            cond_vol = vol_ma20_series.iloc[-1] > vol_ma20_series.iloc[-(segment_len+1)]

        # --- 符合所有條件 ---
        if cond_bias and cond_ma200 and cond_vol:
            return {
                "代號": row_data['ticker'],
                "名稱": row_data['name'],
                "現價": round(curr_price, 2),
                "成交量(張)": row_data['volume'],
                "乖離率(%)": round(bias_val, 2),
                "MA200趨勢": "🔥連漲" if strict_mode else "📈向上",
                "均量趨勢": "🔥連漲" if strict_mode else "📈向上"
            }
            
    except Exception:
        return None
    return None

# --- 3. UI 介面設計 ---
st.title("🚀 夢想起飛：台股即時智慧選股")
st.markdown("### 策略來源：真實台灣股市成交量排行")
st.info("本系統直接連線交易所數據，不再使用預設清單。")

# 側邊欄控制
with st.sidebar:
    st.header("⚙️ 參數設定")
    scan_limit = st.slider("掃描熱門股數量 (由成交量排序)", 50, 200, 100, step=10)
    strict_mode = st.checkbox("嚴格模式 (連續10日每日上升)", value=False)
    st.caption("💡 建議：關閉嚴格模式可獲得較多潛力股，開啟則須極強勢股才符合。")

# 執行按鈕
if st.button("開始掃描市場", type="primary"):
    
    # 步驟 1: 獲取即時清單
    with st.status("正在連線市場數據...", expanded=True) as status:
        st.write("🔍 正在從 API 抓取上市櫃成交量排行...")
        df_hot = get_real_market_rank(limit=scan_limit)
        
        if df_hot.empty:
            status.update(label="❌ 數據抓取失敗", state="error")
            st.error("無法連線至報價伺服器，請檢查網路或稍後再試。")
            st.stop()
            
        st.write(f"✅ 成功取得 {len(df_hot)} 檔熱門股票，開始技術分析...")
        
        # 步驟 2: 逐檔運算
        results = []
        progress_bar = st.progress(0)
        
        for i, row in df_hot.iterrows():
            # 更新進度條
            progress_bar.progress((i + 1) / len(df_hot))
            
            # 執行選股策略
            res = check_dream_strategy(row, strict_mode)
            if res:
                results.append(res)
                
        status.update(label="分析完成！", state="complete", expanded=False)

    # 步驟 3: 顯示結果
    if results:
        final_df = pd.DataFrame(results)
        # 再次依照成交量排序
        final_df = final_df.sort_values(by="成交量(張)", ascending=False)
        
        st.success(f"🎉 篩選出 {len(final_df)} 檔符合「夢想起飛」條件的股票！")
        
        st.dataframe(
            final_df,
            column_config={
                "現價": st.column_config.NumberColumn(format="$%.2f"),
                "成交量(張)": st.column_config.NumberColumn(format="%d 張"),
                "乖離率(%)": st.column_config.NumberColumn(format="%.2f%%"),
            },
            use_container_width=True,
            hide_index=True
        )
    else:
        st.warning("🧐 掃描完畢，沒有股票符合如此嚴格的條件。")
        st.markdown("""
        **建議嘗試：**
        1. 關閉左側的「嚴格模式」。
        2. 增加「掃描熱門股數量」至 150 或 200。
        """)
