import streamlit as st
import pandas as pd
import yfinance as yf
import requests
import datetime

# 設定頁面
st.set_page_config(page_title="夢想起飛：上市櫃全掃描", layout="wide")

# --- 1. 爬蟲功能：抓取上市與上櫃熱門股 ---
@st.cache_data(ttl=3600)  # 設定快取 1 小時，避免重複爬取變慢
def get_hot_stocks_from_web(limit=100):
    """
    從 Yahoo 股市爬取上市與上櫃的成交量排行，並混合排序
    """
    try:
        # 定義目標網址 (Yahoo 股市排行榜)
        urls = {
            "上市": "https://tw.stock.yahoo.com/rank/volume?exchange=TAI",
            "上櫃": "https://tw.stock.yahoo.com/rank/volume?exchange=TWO"
        }
        
        all_stocks = []

        for market_type, url in urls.items():
            headers = {'User-Agent': 'Mozilla/5.0'}
            response = requests.get(url, headers=headers)
            
            # 使用 pandas 直接解析 HTML 表格 (這招最快)
            dfs = pd.read_html(response.text)
            
            # Yahoo 排行榜通常在第 2 個表格 (索引1) 或視情況而定
            # 我們尋找包含 "股號" 或 "名稱" 的表格
            target_df = None
            for df in dfs:
                if '股號/名稱' in df.columns or '名稱' in df.columns or df.shape[1] > 5:
                    target_df = df
                    break
            
            if target_df is not None:
                # 整理資料
                # 欄位通常是: [名次, 股號/名稱, 股價, 漲跌, ..., 成交量, ...]
                # 我們只需要取出股號 (通常混在字串裡，如 "2330台積電")
                
                # 假設第一欄或第二欄包含股號
                # Yahoo 格式通常是 "2330台積電"，我們切字串取前4碼
                # 注意：有些 ETF 是 5 碼或 6 碼，這裡做簡單處理
                
                col_name = target_df.columns[1] # 假設是 "股號/名稱"
                
                for index, row in target_df.iterrows():
                    raw_txt = str(row[col_name])
                    # 取出前面的數字部分作為代號
                    ticker = ''.join(filter(str.isdigit, raw_txt.split(' ')[0]))
                    
                    if not ticker: continue # 跳過無效資料

                    # 判斷後綴
                    suffix = ".TW" if market_type == "上市" else ".TWO"
                    full_ticker = f"{ticker}{suffix}"
                    
                    # 嘗試抓取成交量 (需處理 '12,345' 這種格式)
                    # 假設成交量在第 8 欄 (索引 7) 或類似位置，這邊用名稱對應比較保險
                    vol_col = [c for c in target_df.columns if '張' in c or '量' in c]
                    volume = 0
                    if vol_col:
                        vol_str = str(row[vol_col[0]]).replace(',', '')
                        if vol_str.isdigit():
                            volume = int(vol_str)

                    all_stocks.append({
                        "ticker": ticker,
                        "full_ticker": full_ticker,
                        "market": market_type,
                        "volume": volume
                    })

        # 將上市上櫃混合，依照成交量排序，取前 N 名
        df_all = pd.DataFrame(all_stocks)
        df_all = df_all.sort_values(by="volume", ascending=False).head(limit)
        
        return df_all
        
    except Exception as e:
        st.error(f"抓取熱門股清單失敗: {e}")
        return pd.DataFrame()

# --- 2. 策略邏輯 ---
def check_strategy(row_data, strict_mode=True):
    ticker = row_data['ticker']
    full_ticker = row_data['full_ticker']
    
    try:
        # 下載資料
        df = yf.download(full_ticker, period="18mo", progress=False)
        
        if len(df) < 210: return None
        
        # 處理資料 (去除 MultiIndex)
        close = df['Close'].squeeze()
        volume = df['Volume'].squeeze()
        
        # 取得當前值
        curr_price = close.iloc[-1]
        
        # 計算均線
        ma5 = close.rolling(5).mean().iloc[-1]
        ma20 = close.rolling(20).mean().iloc[-1]
        ma60 = close.rolling(60).mean().iloc[-1]
        ma120 = close.rolling(120).mean().iloc[-1]
        
        # 計算 MA200 序列
        ma200_series = close.rolling(200).mean()
        c_ma200 = ma200_series.iloc[-1]
        
        # 計算均量 20MA 序列
        vol_ma20_series = volume.rolling(20).mean()
        
        # --- 條件 1: 均線多頭 (價格 > 各均線) ---
        cond_price = (curr_price > ma5) and (curr_price > ma20) and \
                     (curr_price > ma60) and (curr_price > ma120)
        
        # --- 條件 2: (5,200) 乖離率 < 30 ---
        # 乖離率公式: (MA5 - MA200) / MA200 * 100
        bias_val = ((ma5 - c_ma200) / c_ma200) * 100
        cond_bias = bias_val < 30
        
        # --- 條件 3 & 4: 趨勢判斷 (MA200 & 均量) ---
        # 嚴格模式：連續 10 天數值上升
        # 寬鬆模式：目前值 > 10天前的值 (整體趨勢向上)
        
        segment_len = 10
        ma200_seg = ma200_series.iloc[-segment_len-1:]
        vol_seg = vol_ma20_series.iloc[-segment_len-1:]
        
        if strict_mode:
            # diff() > 0 表示每天都比前一天大
            cond_ma200_trend = ma200_seg.diff().dropna().gt(0).all()
            cond_vol_trend = vol_seg.diff().dropna().gt(0).all()
        else:
            # 寬鬆版：只看頭尾 (斜率為正)
            cond_ma200_trend = ma200_series.iloc[-1] > ma200_series.iloc[-11]
            cond_vol_trend = vol_ma20_series.iloc[-1] > vol_ma20_series.iloc[-11]

        # 總結
        if cond_price and cond_bias and cond_ma200_trend and cond_vol_trend:
            return {
                "股票代號": ticker,
                "市場": row_data['market'],
                "現價": round(curr_price, 2),
                "乖離率(%)": round(bias_val, 2),
                "MA200趨勢": "連漲" if strict_mode else "向上",
                "均量趨勢": "連漲" if strict_mode else "向上",
                "當日成交量": int(row_data['volume'])
            }
        
    except Exception as e:
        return None
    return None

# --- 3. UI 介面 ---
st.title("🚀 夢想起飛：上市櫃全掃描 APP")
st.markdown("""
**選股條件：**
1. 收盤價 > MA5, MA20, MA60, MA120 (站上所有均線)
2. (5, 200) 乖離率 < 30%
3. MA200 (年線) 連續 10 日上升
4. 20日均量 連續 10 日上升
""")

col1, col2 = st.columns(2)
with col1:
    scan_limit = st.slider("掃描熱門股數量 (上市+上櫃)", 50, 300, 100)
with col2:
    strict_mode = st.checkbox("開啟嚴格模式 (連續10日每日上升)", value=False, 
                            help="若勾選，需連續10天每天數值都增加；若取消，僅需10天前到現在整體趨勢向上。建議取消以獲得更多結果。")

if st.button("開始執行選股", type="primary"):
    
    # 1. 抓取清單
    with st.status("正在抓取上市櫃熱門股清單...", expanded=True) as status:
        df_hot = get_hot_stocks_from_web(limit=scan_limit)
        st.write(f"已取得 {len(df_hot)} 檔熱門股資料 (含上市與上櫃)")
        
        if df_hot.empty:
            st.error("無法抓取排行榜資料，請稍後再試。")
            st.stop()
            
        # 2. 逐一分析
        results = []
        progress_bar = st.progress(0)
        status.update(label="正在計算技術指標...", state="running")
        
        total_stocks = len(df_hot)
        for i, row in df_hot.iterrows():
            # 更新進度條
            progress_bar.progress((i + 1) / total_stocks)
            
            res = check_strategy(row, strict_mode)
            if res:
                results.append(res)
        
        status.update(label="分析完成！", state="complete", expanded=False)

    # 3. 顯示結果
    if results:
        final_df = pd.DataFrame(results)
        # 依成交量排序
        final_df = final_df.sort_values(by="當日成交量", ascending=False)
        
        st.success(f"🎉 成功篩選出 {len(final_df)} 檔潛力股！")
        
        # 美化顯示
        st.dataframe(
            final_df,
            column_config={
                "當日成交量": st.column_config.NumberColumn(format="%d 張"),
                "現價": st.column_config.NumberColumn(format="$%.2f"),
                "乖離率(%)": st.column_config.NumberColumn(format="%.2f%%"),
            },
            use_container_width=True,
            hide_index=True
        )
    else:
        st.warning("🧐 掃描完畢，但沒有股票符合條件。")
        st.info("建議：嘗試關閉「嚴格模式」或增加「掃描熱門股數量」。")