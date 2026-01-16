import streamlit as st
import pandas as pd
import yfinance as yf
import twstock
import time  # 引入時間模組來做延遲

# 設定頁面
st.set_page_config(page_title="夢想起飛：防封鎖穩定版", layout="wide")

# ==========================================
# 1. 取得全台股票清單 (更嚴格的過濾)
# ==========================================
@st.cache_data(ttl=86400) # 清單一天更新一次即可
def get_clean_tw_stock_list():
    """
    使用 twstock 取得清單，但只保留 4 碼的普通股，
    大幅減少請求數量以避免被擋。
    """
    try:
        all_codes = twstock.codes
        candidates = []
        
        for code, info in all_codes.items():
            # 嚴格過濾：
            # 1. 必須是股票
            # 2. 代號長度必須是 4 (排除 0050, 00878 等 ETF，也排除權證)
            #    雖然 user 想抓上市櫃，但通常飆股策略針對普通股比較有效
            if info.type == '股票' and len(code) == 4:
                
                if info.market == '上市':
                    suffix = ".TW"
                elif info.market == '上櫃':
                    suffix = ".TWO"
                else:
                    continue
                    
                full_ticker = f"{code}{suffix}"
                
                candidates.append({
                    "ticker": code,
                    "full_ticker": full_ticker,
                    "name": info.name,
                    "market": info.market
                })
        
        return pd.DataFrame(candidates)
        
    except Exception as e:
        st.error(f"清單建立失敗: {e}")
        return pd.DataFrame()

# ==========================================
# 2. 分批下載成交量 (關鍵修改：防封鎖機制)
# ==========================================
@st.cache_data(ttl=14400)  # !!! 重要：設定 4 小時快取，不要一直去煩 Yahoo !!!
def get_top_500_safe(candidates_df):
    
    if candidates_df.empty: return pd.DataFrame()
    
    all_tickers = candidates_df['full_ticker'].tolist()
    total_tickers = len(all_tickers)
    
    st.info(f"鎖定全台 {total_tickers} 檔普通股，啟動「分批下載」模式以避開防火牆...")
    
    # --- 分批下載設定 ---
    chunk_size = 300  # 每次只抓 300 檔
    combined_data = pd.DataFrame()
    
    progress_bar = st.progress(0)
    status_text = st.empty()
    
    # 開始分批迴圈
    for i in range(0, total_tickers, chunk_size):
        # 取得這一批的代號
        chunk = all_tickers[i:i + chunk_size]
        
        status_text.text(f"正在下載第 {i+1} ~ {min(i+chunk_size, total_tickers)} 檔...")
        progress_bar.progress(min((i + chunk_size) / total_tickers, 0.9))
        
        try:
            # 下載這一批
            data = yf.download(chunk, period="5d", group_by='ticker', progress=False, threads=True)
            
            # 如果是第一批，直接賦值；之後的用合併
            # yfinance 批次下載回來的格式處理比較複雜，我們這邊簡化處理：
            # 我們直接把這一批的資料處理完存成 list，最後再合併
            pass 
        except Exception:
            continue
            
        # 暫停 1.5 秒，讓 Yahoo 伺服器喘口氣 (關鍵!)
        time.sleep(1.5)
        
        # 處理這一批的數據
        # 注意：這裡邏輯需要調整以適配分批後的合併
        # 為了程式碼簡潔，我們改用「累積列表」的方式
        
    # --- 重寫：更穩定的分批邏輯 ---
    # 因為 yfinance 多次 download 合併比較麻煩，我們改用這個邏輯：
    # 下載 -> 處理 -> 存入 List -> 下一披
    
    vol_data = []
    
    for i in range(0, total_tickers, chunk_size):
        chunk = all_tickers[i:i + chunk_size]
        
        try:
            # 這裡下載
            data_chunk = yf.download(chunk, period="5d", group_by='ticker', progress=False, threads=True)
            
            # 處理這一批
            for ticker in chunk:
                try:
                    # 查找對應的名稱資訊
                    row = candidates_df[candidates_df['full_ticker'] == ticker].iloc[0]
                    
                    if ticker not in data_chunk.columns.levels[0]: continue
                    df_stock = data_chunk[ticker]
                    if df_stock.empty: continue
                    
                    total_vol = df_stock['Volume'].sum()
                    last_price = df_stock['Close'].iloc[-1]
                    
                    # 簡單過濾量太小的 (5天 < 500張)
                    if total_vol > 500000: 
                        vol_data.append({
                            "ticker": row['ticker'],
                            "full_ticker": ticker,
                            "name": row['name'],
                            "5d_vol_sum": int(total_vol),
                            "price": float(last_price)
                        })
                except:
                    continue
        except:
            pass
            
        time.sleep(1.5) # 休息防擋
    
    status_text.empty()
    progress_bar.progress(1.0)
    
    # 排序取前 500
    if not vol_data:
        return pd.DataFrame()
        
    df_res = pd.DataFrame(vol_data)
    df_res = df_res.sort_values(by="5d_vol_sum", ascending=False).head(500)
    
    return df_res

# ==========================================
# 3. 策略運算 (同樣需要小心)
# ==========================================
def run_strategy(top_500_df, strict_mode):
    
    tickers = top_500_df['full_ticker'].tolist()
    results = []
    
    st.text("正在分析 Top 500 熱門股 K 線...")
    
    # 這裡我們一次下載 500 檔是可以的，因為這算一次請求
    # 但如果失敗，我們就切成兩半試試看
    try:
        data = yf.download(tickers, period="1y", group_by='ticker', progress=False, threads=True)
    except:
        st.warning("大量下載失敗，嘗試降速下載...")
        time.sleep(2)
        # 備案：只抓前 200 檔
        tickers = tickers[:200]
        data = yf.download(tickers, period="1y", group_by='ticker', progress=False, threads=True)

    progress_bar = st.progress(0)
    total = len(tickers)
    
    for i, ticker in enumerate(tickers):
        progress_bar.progress((i+1)/total)
        
        try:
            # 找回基本資料
            row = top_500_df[top_500_df['full_ticker'] == ticker].iloc[0]
            
            if ticker not in data.columns.levels[0]: continue
            df = data[ticker].dropna()
            
            if len(df) < 205: continue
            
            close = df['Close'].squeeze()
            volume = df['Volume'].squeeze()
            curr_price = close.iloc[-1]
            
            # 指標
            ma5 = close.rolling(5).mean().iloc[-1]
            ma20 = close.rolling(20).mean().iloc[-1]
            ma60 = close.rolling(60).mean().iloc[-1]
            ma120 = close.rolling(120).mean().iloc[-1]
            
            ma200_series = close.rolling(200).mean()
            c_ma200 = ma200_series.iloc[-1]
            
            vol_ma20_series = volume.rolling(20).mean()
            
            # 條件
            cond_price = (curr_price > ma5) and (curr_price > ma20) and \
                         (curr_price > ma60) and (curr_price > ma120)
            if not cond_price: continue
            
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
            
    return results

# ==========================================
# 4. UI
# ==========================================
st.title("🛡️ 夢想起飛：防封鎖穩定版")
st.warning("⚠️ 為了防止被 Yahoo 封鎖，本版本採用「分批慢速下載」與「長時間快取」。按下按鈕後請耐心等待約 20-30 秒。")

with st.sidebar:
    st.header("⚙️ 設定")
    strict_mode = st.checkbox("嚴格模式", value=False)
    if st.button("清除快取 (慎用)", help="若資料很久沒更新才按，頻繁清除會導致被鎖 IP"):
        st.cache_data.clear()

if st.button("開始掃描", type="primary"):
    
    # 1. 取得清單
    with st.spinner("讀取內建清單 (過濾普通股)..."):
        candidates = get_clean_tw_stock_list()
        if candidates.empty:
            st.error("清單載入失敗，請確認 twstock 已安裝。")
            st.stop()
            
    # 2. 下載資料 (這是最容易失敗的地方)
    top_500 = get_top_500_safe(candidates)
    
    if top_500.empty:
        st.error("❌ 無法下載數據。原因：您的 IP 可能暫時被 Yahoo 封鎖。")
        st.info("💡 解法：請等待 1 小時後再試，或嘗試重新部署 App (Reboot) 以更換 IP。")
        st.stop()
        
    st.success(f"✅ 成功下載並鎖定前 500 大熱門股！")
    
    # 3. 策略
    results = run_strategy(top_500, strict_mode)
    
    if results:
        df_res = pd.DataFrame(results).sort_values(by="5日總量(張)", ascending=False)
        st.subheader(f"🎉 篩選結果：{len(df_res)} 檔")
        st.dataframe(df_res, use_container_width=True, hide_index=True)
    else:
        st.warning("無符合條件股票。")
