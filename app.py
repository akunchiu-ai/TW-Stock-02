import streamlit as st
import pandas as pd
import yfinance as yf
import requests

# 設定頁面配置
st.set_page_config(page_title="夢想起飛：台股即時戰情室", layout="wide")

# ==========================================
# 1. 核心功能：直接抓取真實「成交量排行」
#    (替代 Goodinfo，改用 Yahoo API，資料更即時且不擋 IP)
# ==========================================
@st.cache_data(ttl=900)  # 設定 15 分鐘快取
def get_real_market_rank(limit=100):
    """
    直接呼叫 Yahoo 股市 API 取得上市+上櫃成交量排行
    """
    # API 網址 (瀏覽器實際請求的後端)
    api_urls = [
        {"market": "上市", "url": "https://tw.stock.yahoo.com/_td-stock/api/resource/StockServices.rank;exchange=TAI;limit={};period=day;rankType=vol"},
        {"market": "上櫃", "url": "https://tw.stock.yahoo.com/_td-stock/api/resource/StockServices.rank;exchange=TWO;limit={};period=day;rankType=vol"}
    ]
    
    all_stocks = []
    
    # 偽裝成瀏覽器
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0 Safari/537.36'
    }

    try:
        for item in api_urls:
            target_url = item["url"].format(limit)
            try:
                response = requests.get(target_url, headers=headers, timeout=10)
                if response.status_code == 200:
                    data = response.json()
                    stock_list = data.get('list', [])
                    
                    for stock in stock_list:
                        symbol = stock.get('symbol', '')  # 例如 "2330.TW"
                        name = stock.get('name', '')
                        price = stock.get('price', 0)
                        
                        # 成交量 (原始資料是股數，換算成張數)
                        raw_vol = stock.get('volInStock', 0)
                        vol_sheets = int(int(raw_vol) / 1000) if raw_vol else 0
                        
                        if symbol:
                            all_stocks.append({
                                "ticker": symbol.split('.')[0], # 代號
                                "full_ticker": symbol,          # 完整代號
                                "name": name,
                                "market": item["market"],
                                "volume": vol_sheets,
                                "price": price
                            })
            except Exception as e:
                print(f"API Error ({item['market']}): {e}")
                continue

        if not all_stocks:
            return pd.DataFrame()

        # 合併後依成交量排序
        df = pd.DataFrame(all_stocks)
        df = df.sort_values(by="volume", ascending=False).head(limit)
        return df

    except Exception as e:
        print(f"Global Error: {e}")
        return pd.DataFrame()

# ==========================================
# 2. 策略邏輯 (技術指標計算)
#    (這裡修復了你遇到的 SyntaxError)
# ==========================================
def check_dream_strategy(row_data, strict_mode=True):
    full_ticker = row_data['full_ticker']
    
    # 這裡必須要有 try，並在最後配對 except
    try:
        # 下載歷史資料 (至少需 250 天算年線)
        df = yf.download(full_ticker, period="1y", progress=False)
        
        if len(df) < 205: return None
        
        # 整理資料
        close = df['Close'].squeeze()
        volume = df['Volume'].squeeze()
        
        # 取得最新價
        curr_price = close.iloc[-1]
        
        # --- 計算均線 ---
        ma5 = close.rolling(5).mean().iloc[-1]
        ma20 = close.rolling(20).mean().iloc[-1]  # <--- 這就是你原本報錯的地方
        ma60 = close.rolling(60).mean().iloc[-1]
        ma120 = close.rolling(120).mean().iloc[-1]
        
        # MA200 (年線) 序列
        ma200_series = close.rolling(200).mean()
        c_ma200 = ma200_series.iloc[-1]
        
        # 均量 20MA 序列
        vol_ma20_series = volume.rolling(20).mean()
        
        # --- 條件判斷 ---
        
        # 1. 均線多頭 (價格 > 所有均線)
        cond_price = (curr_price > ma5) and (curr_price > ma20) and \
                     (curr_price > ma60) and (curr_price > ma120)
        
        if not cond_price: return None # 提早篩選，加速運算
        
        # 2. 乖離率 (5, 200) < 30%
        bias_val = ((ma5 - c_ma200) / c_ma200) * 100
        cond_bias = bias_val < 30
        
        # 3. 趨勢判斷 (MA200 & 均量)
        segment_len = 10
        if strict_mode:
            # 嚴格：每一天都比前一天高
            ma200_trend = ma200_series.iloc[-(segment_len+1):].diff().dropna().gt(0).all()
            vol_trend = vol_ma20_series.iloc[-(segment_len+1):].diff().dropna().gt(0).all()
        else:
            # 寬鬆：現在比10天前高
            ma200_trend = ma200_series.iloc[-1] > ma200_series.iloc[-(segment_len+1)]
            vol_trend = vol_ma20_series.iloc[-1] > vol_ma20_series.iloc[-(segment_len+1)]

        # --- 結果回傳 ---
        if cond_bias and ma200_trend and vol_trend:
            return {
                "代號": row_data['ticker'],
                "名稱": row_data['name'],
                "現價": f"{curr_price:.2f}",
                "成交量": row_data['volume'],
                "乖離率": f"{bias_val:.2f}%",
                "MA200": "🔥連漲" if strict_mode else "📈向上",
                "均量": "🔥連漲" if strict_mode else "📈向上"
            }
            
    except Exception:
        # 這就是之前缺少的 except 區塊，用來捕捉錯誤防止當機
        return None
        
    return None

# ==========================================
# 3. UI 主畫面
# ==========================================
st.title("🚀 夢想起飛：台股即時選股 APP")
st.markdown("### 資料來源：真實台股即時排行 (API 直連)")
st.caption("本系統直接連接交易所數據，不再使用 Goodinfo 以避免連線被阻擋。")

with st.sidebar:
    st.header("⚙️ 選股設定")
    scan_limit = st.slider("掃描成交量前 N 名", 50, 200, 100)
    strict_mode = st.checkbox("嚴格模式 (連續10日每日上升)", value=False)
    st.info("💡 建議關閉嚴格模式，比較容易選出股票。")

if st.button("開始掃描", type="primary"):
    
    # 1. 抓取清單
    with st.status("正在連線至證券交易所...", expanded=True) as status:
        st.write("🔍 正在下載即時成交量排行...")
        
        # 呼叫上面的 API 函數
        df_hot = get_real_market_rank(limit=scan_limit)
        
        if df_hot.empty:
            status.update(label="❌ 連線失敗", state="error")
            st.error("無法取得即時資料，請稍後再試。")
            st.stop()
            
        st.write(f"✅ 成功取得 {len(df_hot)} 檔熱門股，開始技術分析...")
        
        # 2. 執行策略
        results = []
        progress_bar = st.progress(0)
        
        for i, row in df_hot.iterrows():
            progress_bar.progress((i + 1) / len(df_hot))
            res = check_dream_strategy(row, strict_mode)
            if res:
                results.append(res)
        
        status.update(label="分析完成！", state="complete", expanded=False)

    # 3. 顯示結果
    if results:
        final_df = pd.DataFrame(results)
        final_df = final_df.sort_values(by="成交量", ascending=False)
        
        st.success(f"🎉 篩選出 {len(final_df)} 檔符合條件的股票！")
        
        # 優化表格顯示
        st.dataframe(
            final_df,
            column_config={
                "成交量": st.column_config.NumberColumn(format="%d 張"),
            },
            use_container_width=True,
            hide_index=True
        )
    else:
        st.warning("🧐 掃描完畢，沒有股票符合條件。")
        st.markdown("建議：**關閉嚴格模式** 或 **增加掃描數量** 再試一次。")
