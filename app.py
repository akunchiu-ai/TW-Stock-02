import streamlit as st
import pandas as pd
import yfinance as yf
import requests
import time
import random

# 設定頁面
st.set_page_config(page_title="夢想起飛：Goodinfo 選股", layout="wide")

# --- 1. Goodinfo 爬蟲功能 ---
@st.cache_data(ttl=3600)
def get_goodinfo_hot_stocks(limit=100):
    """
    從 Goodinfo 抓取熱門成交量排行
    """
    # Goodinfo 熱門排行 - 成交量排行 (張數)
    target_url = "https://goodinfo.tw/tw/StockList.asp?MARKET_CAT=%E7%86%B1%E9%96%80%E6%8E%92%E8%A1%8C&INDUSTRY_CAT=%E6%88%90%E4%BA%A4%E9%87%8F%28%E5%BC%B5%29%40%40%E6%88%90%E4%BA%A4%E9%87%8F%40%40%E5%BC%B5%E6%95%B8"
    
    # 偽裝成真人瀏覽器的 Header (非常重要)
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Referer': 'https://goodinfo.tw/tw/index.asp',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',
        'Accept-Language': 'zh-TW,zh;q=0.9,en-US;q=0.8,en;q=0.7',
        'Connection': 'keep-alive'
    }

    try:
        # 稍微延遲一下，避免太像機器人
        time.sleep(random.uniform(0.5, 1.5))
        
        response = requests.get(target_url, headers=headers, timeout=15)
        response.encoding = 'utf-8' # 強制編碼
        
        if response.status_code != 200:
            st.error(f"Goodinfo 拒絕連線 (狀態碼: {response.status_code})，可能是 IP 被封鎖。")
            return pd.DataFrame()

        # 使用 pandas 解析表格
        # Goodinfo 的主要資料通常在很大的表格裡，我們找含有 "代號" 的表格
        dfs = pd.read_html(response.text)
        
        target_df = None
        for df in dfs:
            # Goodinfo 的表格標頭很亂，我們找 columns 裡包含 '代號' 或第一列包含 '代號' 的
            # 轉換 columns 為字串並檢查
            col_str = str(df.columns)
            if '代號' in col_str or (len(df) > 0 and '代號' in str(df.iloc[0].values)):
                target_df = df
                break
        
        if target_df is None:
            return pd.DataFrame()

        # --- 資料清洗 ---
        # Goodinfo 表格會有重複的 Header 列，需要過濾
        # 通常欄位名稱在某一列，我們需要重設 header
        
        # 簡單處理：把所有資料轉成字串，尋找由數字組成的代號
        clean_list = []
        
        # 尋找 "代號" 所在的 index
        code_col_idx = -1
        name_col_idx = -1
        vol_col_idx = -1
        
        # 嘗試自動對應欄位 (因為 Goodinfo 欄位常變)
        # 我們直接遍歷每一行，判斷格式
        for i, row in target_df.iterrows():
            row_list = [str(x) for x in row.values]
            
            # 判斷是否為標題列
            if '代號' in row_list:
                continue
                
            # 尋找代號 (通常是 4 碼數字)
            ticker = None
            name = None
            volume = 0
            
            for item in row_list:
                # 檢查是否為股票代號 (4碼數字)
                if item.isdigit() and len(item) == 4:
                    ticker = item
                # 檢查是否為成交量 (含有數字且可能大於 1000)
                # 這裡比較難精準，我們先取代號，成交量留給 yfinance 抓最新
            
            if ticker:
                # 判斷是上市(.TW) 還是上櫃(.TWO)
                # 由於 Goodinfo 混在一起，我們簡單判斷：
                # 這裡先預設 .TW，如果 yfinance 抓不到再試 .TWO (但在這先統一加 .TW 讓後面邏輯處理)
                # 更好的方式：Goodinfo 點進去網址會有 TYPE=STOCK (上市) 或 TYPE=OTC (上櫃)
                # 但為了速度，我們先存純代號，後面檢查
                
                clean_list.append({
                    "ticker": ticker,
                    "full_ticker": f"{ticker}.TW" # 先預設上市
                })

        # 轉成 DataFrame 並去重
        df_res = pd.DataFrame(clean_list).drop_duplicates(subset=['ticker'])
        
        return df_res.head(limit)

    except Exception as e:
        print(f"Goodinfo Error: {e}")
        return pd.DataFrame()

# --- 2. 策略邏輯 (與之前相同，但增加上市櫃判斷) ---
def check_dream_strategy(ticker_info, strict_mode=True):
    ticker = ticker_info['ticker']
    
    # 嘗試下載資料，先試 .TW (上市)
    stock_id = f"{ticker}.TW"
    df = yf.download(stock_id, period="1y", progress=False)
    
    # 如果抓不到資料 (可能為上櫃 .TWO)
    if df.empty:
        stock_id = f"{ticker}.TWO"
        df = yf.download(stock_id, period="1y", progress=False)
        if df.empty: return None # 真的抓不到
        
    try:
        if len(df) < 205: return None
        
        close = df['Close'].squeeze()
        volume = df['Volume'].squeeze()
        curr_price = close.iloc[-1]
        
        # 計算均線
        ma5 = close.rolling(5).mean().iloc[-1]
        ma20 = close.rolling(20).mean().iloc[-1]
