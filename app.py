import streamlit as st
import pandas as pd
import yfinance as yf
import requests

# 設定頁面配置
st.set_page_config(page_title="夢想起飛：全市場動態掃描", layout="wide")

# ==========================================
# 1. 第一步：取得全台所有上市櫃股票代號
#    (來源：證交所與櫃買中心公開網頁)
# ==========================================
@st.cache_data(ttl=86400)  # 快取 1 天，因為股票代號不會天天變
def get_all_tw_ticker_list():
    """
    從證交所本國證券網頁抓取所有股票代號與名稱
    """
    stock_list = []
    
    # 定義來源 URL (證交所公開資訊 - 本國上市/上櫃證券)
    # Mode=2: 上市, Mode=4: 上櫃
    urls = [
        ("https://isin.twse.com.tw/isin/C_public.jsp?strMode=2", ".TW", "上市"),
        ("https://isin.twse.com.tw/isin/C_public.jsp?strMode=4", ".TWO", "上櫃")
    ]
    
    status_text = st.empty()
    status_text.text("正在更新全台股票清單...")

    try:
        for url, suffix, market in urls:
            try:
                # 使用 requests 抓取網頁
                res = requests.get(url)
                # 使用 pandas 讀取 HTML 表格
                dfs = pd.read_html(res.text)
                
                if len(dfs) > 0:
                    df = dfs[0]
                    # 資料整理：第一欄通常是 "有價證券代號及名稱"
                    # 格式如 "2330 　台積電"
                    df.columns = df.iloc[0] # 設定標頭
                    df = df.iloc[1:]
                    
                    # 篩選出 "股票" 類別 (排除權證、債券等)
                    # 證交所表格通常有 "ESVUFR" 或類似分類，我們簡單用代號長度判斷
                    # 一般股票代號為 4 碼
                    
                    col_code_name = df.columns[0]
                    
                    for item in df[col_code_name]:
                        item = str(item)
                        # 分割代號與名稱
                        parts = item.split()
                        if len(parts) >= 2:
                            code = parts[0]
                            name = parts[1]
                            
                            # 只保留 4 位數代號 (排除 ETF、權證、特別股)
                            if len(code) == 4 and code.isdigit():
                                stock_list.append({
                                    "ticker": code,
                                    "full_ticker": f"{code}{suffix}",
                                    "name": name,
                                    "market": market
                                })
            except Exception as e:
                print(f"Error parsing {market}: {e}")
                continue
                
        status_text.empty()
        return pd.DataFrame(stock_list)
        
    except Exception as e:
        status_text.empty()
        st.error(f"無法取得股票清單: {e}")
        return pd.DataFrame()

# ==========================================
# 2. 第二步：找出成交量最大的 500 檔
# ==========================================
@st.cache_data(ttl=1800) # 快取 30 分鐘
def get_top_volume_stocks(limit=500):
    
    # 1. 取得全名單
    df_all = get_all_tw_ticker_list()
    if df_all.empty: return pd.DataFrame()
    
    all_tickers = df_all['full_ticker'].tolist()
    
    # 為了避免一次下載 1800 檔太久，我們分批下載，但 yfinance 批次很快，嘗試直接下
    # 這裡只下載 "近 5 天" 的資料來算成交量，速度會很快
    
    st.toast(f"正在掃描全市場 {len(all_tickers)} 檔股票成交量...", icon="🚀")
    
    try:
        # 批次下載 (Batch Download)
        # threads=True 開啟多執行緒加速
        data = yf.download(all_tickers, period="5d", group_by='ticker', progress=False, threads=True)
        
        volume_data = []
        
        for index, row in df_all.iterrows():
            ticker = row['full_ticker']
            name = row['name']
            
            try:
                # 檢查是否有資料
                if ticker not in data.columns.levels[0]: continue
                
                df_stock = data[ticker]
                if df_stock.empty: continue
                
                # 取得平均成交量 (近5日) 或 最新成交量
                # 這裡取最新一天的量
                latest = df_stock.iloc[-1]
                vol = latest['Volume']
                price = latest['Close']
                
                if pd.isna(vol) or vol == 0: continue
                
                volume_data.append({
                    "ticker": row['ticker'],
                    "full_ticker": ticker,
                    "name": name,
                    "market": row['market'],
                    "volume": int(vol),
                    "price_now": float(price)
                })
            except:
                continue
                
        # 轉成 DataFrame 並排序
        df_vol = pd.DataFrame(volume_data)
        if df_vol.empty: return pd.DataFrame()
        
        # 依成交量排序，取前 limit 名
        df_top = df_vol.sort_values(by="volume", ascending=False).head(limit)
        
        return df_top
        
    except Exception as e:
        st.error(f"成交量掃描失敗: {e}")
        return pd.DataFrame()

# ==========================================
# 3. 第三步：策略邏輯 (針對 Top 500 進行詳細分析)
# ==========================================
def check_dream_strategy(row_data, strict_mode=True):
    full_ticker = row_data['full_ticker']
    
    try:
        # 下載歷史資料 (需 1 年以計算 MA200)
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
                "名稱": row_data['name'], # 這裡會顯示個股名稱
                "現價": row_data['price_now'],
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
st.title("🚀 夢想起飛：全市場動態篩選")
st.markdown("### 資料來源：全台 1800+ 檔上市櫃股票動態掃描")
st.caption("流程：1. 抓取所有股票代號 -> 2. yfinance 計算成交量 -> 3. 鎖定前 500 大 -> 4. 策略篩選")

with st.sidebar:
    st.header("⚙️ 設定")
    # 這裡改成鎖定前 500 大
    scan_limit = st.slider("鎖定成交量前 N 大進行分析", 100, 500, 300) 
    strict_mode = st.checkbox("嚴格模式 (連續10日上升)", value=False)
    st.info("💡 建議：先用 300 檔測試速度，若需要更廣範圍再開到 500。")

if st.button("開始掃描 (需耗時約 1-2 分鐘)", type="primary"):
    
    with st.status("正在啟動全市場掃描引擎...", expanded=True) as status:
        
        # 步驟 1 & 2
        st.write("📡 正在取得全台股票清單並計算成交量 (yfinance)...")
        df_hot = get_top_volume_stocks(limit=scan_limit)
        
        if df_hot.empty:
            status.update(label="❌ 數據取得失敗", state="error")
            st.error("無法取得市場數據，請稍後再試。")
            st.stop()
            
        st.write(f"✅ 已鎖定成交量最大的 {len(df_hot)} 檔熱門股 (如: {df_hot.iloc[0]['name']})，開始策略分析...")
        
        # 步驟 3
        results = []
        progress_bar = st.progress(0)
        
        # 使用 enumerate 確保進度條正常
        for i, (index, row) in enumerate(df_hot.iterrows()):
            
            # 安全計算進度
            progress_val = min((i + 1) / len(df_hot), 1.0)
            progress_bar.progress(progress_val)
            
            res = check_dream_strategy(row, strict_mode)
            if res:
                results.append(res)
        
        status.update(label="全市場掃描完成！", state="complete", expanded=False)

    # 步驟 4: 顯示結果
    if results:
        final_df = pd.DataFrame(results)
        final_df = final_df.sort_values(by="成交量", ascending=False)
        
        st.success(f"🎉 從前 {scan_limit} 大熱門股中，篩選出 {len(final_df)} 檔符合條件！")
        
        st.dataframe(
            final_df,
            column_config={
                "現價": st.column_config.NumberColumn(format="$%.2f"),
                "成交量": st.column_config.NumberColumn(format="%d 張"), # 顯示張數
            },
            use_container_width=True,
            hide_index=True
        )
    else:
        st.warning("🧐 掃描完畢，沒有股票符合條件。")
        st.markdown("**建議：** 你的策略非常嚴格，建議關閉「嚴格模式」或檢查目前市場是否處於回檔期。")
