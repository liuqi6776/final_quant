import os
import numpy as np
import pandas as pd

# ── 路径配置 ──────────────────────────────────────────────────────────
PROJECT_DIR = r"C:\Users\liuqi\.gemini\antigravity\worktrees\quant_system_v2\factor-neutralization-alpha-research"
DATA_DIR = os.path.join(PROJECT_DIR, 'smart-beta-research', 'data')
PRED_DIR = os.path.join(PROJECT_DIR, 'smart-beta-research', 'predictions')

PRED_FILE = os.path.join(PRED_DIR, 'predictions_longterm.parquet')
FEATURES_FILE = os.path.join(DATA_DIR, 'features_longterm.parquet')
INDEX_FILE = os.path.join(DATA_DIR, 'index_regime.csv')

# 策略参数 (这里固定持股数为 30)
PORTFOLIO_SIZE = 30
MAX_WEIGHT_PER_INDUSTRY = 0.25
INITIAL_CAPITAL = 1000000.0
BUY_COST_RATE = 0.002
SELL_COST_RATE = 0.003

def is_limit_up(open_price, prev_close, code):
    limit = 0.198 if (code.startswith('30') or code.startswith('68')) else 0.098
    return open_price >= prev_close * (1 + limit)

def is_limit_down(open_price, prev_close, code):
    limit = 0.198 if (code.startswith('30') or code.startswith('68')) else 0.098
    return open_price <= prev_close * (1 - limit)

def simulate_strategy_holding(df_by_date, trade_dates, holding_days, filter_type='ma20_3stage'):
    rebalance_dates = set(trade_dates[::holding_days])
    current_holdings = {}
    cash = INITIAL_CAPITAL
    daily_navs = []
    
    for idx, dt in enumerate(trade_dates):
        if dt not in df_by_date:
            prev_nav = daily_navs[-1]['nav'] if daily_navs else INITIAL_CAPITAL
            daily_navs.append({'trade_date': dt, 'nav': prev_nav, 'cash': cash, 'holdings_val': 0})
            continue
            
        day_data = df_by_date[dt]
        day_prices = day_data.set_index('ts_code').to_dict(orient='index')
        
        # 1. Update holdings valuation
        holdings_val = 0
        if current_holdings:
            updated_holdings = {}
            for code, prev_item in current_holdings.items():
                prev_val = prev_item['val']
                shares = prev_item.get('shares', 0)
                if code in day_prices:
                    pct_chg = day_prices[code]['pct_chg']
                    if pd.isna(pct_chg): pct_chg = 0.0
                    close_price = day_prices[code]['close']
                    
                    if shares > 0:
                        val = shares * close_price
                    else:
                        if prev_item['is_first_day']:
                            buy_price = prev_item['buy_price']
                            val = prev_val * (close_price / buy_price) if buy_price > 0 else prev_val * (1 + pct_chg)
                        else:
                            val = prev_val * (1 + pct_chg)
                            
                    updated_holdings[code] = {
                        'val': val,
                        'buy_price': None,
                        'is_first_day': False,
                        'shares': shares
                    }
                    holdings_val += val
                else:
                    updated_holdings[code] = {
                        'val': prev_val,
                        'buy_price': prev_item['buy_price'],
                        'is_first_day': prev_item['is_first_day'],
                        'shares': shares
                    }
                    holdings_val += prev_val
            current_holdings = updated_holdings
            
        current_nav = cash + holdings_val
        daily_navs.append({
            'trade_date': dt,
            'nav': current_nav,
            'cash': cash,
            'holdings_val': holdings_val
        })
        
        # Calculate target position weight factor for this day
        weight_factor = 1.0
        if len(day_data) > 0:
            ratio = day_data['index_ratio'].iloc[0] if 'index_ratio' in day_data.columns else 1.0
            if ratio > 1.02:
                weight_factor = 1.0
            elif ratio >= 0.98:
                weight_factor = 0.5
            else:
                weight_factor = 0.0
                    
        # 3. Rebalancing
        if dt in rebalance_dates:
            if idx + 1 >= len(trade_dates): continue
            next_dt = trade_dates[idx+1]
            if next_dt not in df_by_date: continue
            
            next_day_prices = df_by_date[next_dt].set_index('ts_code').to_dict(orient='index')
            
            forced_holdings = {}
            for code, prev_item in current_holdings.items():
                val = prev_item['val']
                shares = prev_item.get('shares', 0)
                untradeable = False
                if code not in next_day_prices:
                    untradeable = True
                else:
                    row = next_day_prices[code]
                    if row['vol'] == 0:
                        untradeable = True
                    else:
                        prev_close = day_prices.get(code, {}).get('close', np.nan)
                        open_price = row.get('open', np.nan)
                        if pd.isna(prev_close) or pd.isna(open_price):
                            untradeable = True
                        elif is_limit_down(open_price, prev_close, code):
                            untradeable = True
                if untradeable:
                    forced_holdings[code] = {
                        'val': val,
                        'buy_price': None,
                        'is_first_day': False,
                        'shares': shares
                    }
                else:
                    sell_price = next_day_prices[code]['open']
                    sell_val = shares * sell_price
                    cost = sell_val * SELL_COST_RATE
                    cash += (sell_val - cost)
                    
            holdings_val_forced = sum(item['val'] for item in forced_holdings.values())
            temp_nav = cash + holdings_val_forced
            
            target_stock_val = temp_nav * weight_factor
            cash_to_spend = target_stock_val - holdings_val_forced
            
            if cash_to_spend > 0:
                candidates = day_data[day_data['pred_score'].notna()].copy()
                candidates = candidates.merge(
                    df_by_date[next_dt][['ts_code', 'open', 'vol']], 
                    on='ts_code', 
                    suffixes=('', '_next')
                )
                candidates = candidates.rename(columns={'open_next': 'open_execution', 'vol_next': 'vol_execution'})
                
                def check_buy_limit_up(r):
                    open_p = r['open_execution']
                    prev_c = r['close']
                    code = r['ts_code']
                    if pd.isna(open_p) or pd.isna(prev_c): return True
                    return is_limit_up(open_p, prev_c, code)
                    
                candidates = candidates[
                    (candidates['vol_execution'] > 0) & 
                    (~candidates.apply(check_buy_limit_up, axis=1))
                ]
                candidates = candidates.sort_values(by='pred_score', ascending=False)
                
                selected_codes = []
                industry_counts = {}
                max_stocks_per_industry = int(PORTFOLIO_SIZE * MAX_WEIGHT_PER_INDUSTRY)
                if max_stocks_per_industry < 1:
                    max_stocks_per_industry = 1
                
                for code in forced_holdings.keys():
                    ind = day_prices.get(code, {}).get('industry', 'Unknown')
                    industry_counts[ind] = industry_counts.get(ind, 0) + 1
                    
                for _, row in candidates.iterrows():
                    if len(selected_codes) + len(forced_holdings) >= PORTFOLIO_SIZE:
                        break
                    code = row['ts_code']
                    if code in forced_holdings: continue
                    ind = row['industry']
                    count = industry_counts.get(ind, 0)
                    if count < max_stocks_per_industry:
                        selected_codes.append((code, row['open_execution']))
                        industry_counts[ind] = count + 1
                        
                new_holdings = {code: item for code, item in forced_holdings.items()}
                if len(selected_codes) > 0:
                    buy_value_per_stock = cash_to_spend / len(selected_codes)
                    for code, buy_price in selected_codes:
                        shares = np.floor(buy_value_per_stock / buy_price / 100.0) * 100.0
                        if shares > 0:
                            actual_spend = shares * buy_price
                            cost = actual_spend * BUY_COST_RATE
                            new_holdings[code] = {
                                'val': actual_spend,
                                'buy_price': buy_price,
                                'is_first_day': True,
                                'shares': shares
                            }
                            cash -= (actual_spend + cost)
                current_holdings = new_holdings
            else:
                current_holdings = forced_holdings
                
    nav_df = pd.DataFrame(daily_navs)
    nav_df['trade_date'] = pd.to_datetime(nav_df['trade_date'])
    nav_df = nav_df.set_index('trade_date')
    return nav_df

def calc_max_dd(nav_series):
    peak = nav_series.cummax()
    dd = (nav_series - peak) / peak
    return dd.min()

def run_holding_analysis():
    print("Loading data files...")
    pred_df = pd.read_parquet(PRED_FILE)
    pred_df = pred_df.drop_duplicates(subset=['trade_date', 'ts_code'])
    
    feat_df = pd.read_parquet(FEATURES_FILE, columns=['trade_date', 'ts_code', 'vol'])
    feat_df = feat_df.drop_duplicates(subset=['trade_date', 'ts_code'])
    
    df = pred_df.merge(feat_df, on=['trade_date', 'ts_code'], how='left')
    df['vol'] = df['vol'].fillna(0)
    
    # Calculate index trend
    idx_df = pd.read_csv(INDEX_FILE)
    idx_df['trade_date'] = idx_df['trade_date'].astype(str)
    idx_df = idx_df.sort_values('trade_date').reset_index(drop=True)
    idx_df['ma20'] = idx_df['close'].rolling(20).mean()
    idx_df['downtrend'] = idx_df['close'] < idx_df['ma20']
    idx_df['index_ratio'] = idx_df['close'] / idx_df['ma20']
    
    ratio_map = idx_df.set_index('trade_date')['index_ratio'].to_dict()
    df['index_ratio'] = df['trade_date'].map(ratio_map).fillna(1.0)
    
    df = df.sort_values(['trade_date', 'ts_code']).reset_index(drop=True)
    
    trade_dates = sorted(df['trade_date'].unique())
    df_by_date = {dt: g for dt, g in df.groupby('trade_date')}
    
    holding_periods = [20, 10, 5]
    full_metrics = []
    yearly_navs = {}
    
    for h in holding_periods:
        name = f"Holding {h} Days"
        print(f"Running backtest for: {name}...", flush=True)
        nav_df = simulate_strategy_holding(df_by_date, trade_dates, h)
        
        nav = nav_df['nav']
        pnl = nav.pct_change().fillna(0)
        nyrs = len(pnl)/252
        cagr = (nav.iloc[-1]/INITIAL_CAPITAL)**(1/nyrs) - 1
        vol = pnl.std() * np.sqrt(252)
        sharpe = pnl.mean() / pnl.std() * np.sqrt(252) if pnl.std() > 1e-9 else 0
        mdd = calc_max_dd(nav)
        
        full_metrics.append({
            'Holding Period': f"{h} Trading Days",
            'Total Return': f"{nav.iloc[-1]/INITIAL_CAPITAL-1:.2%}",
            'CAGR': f"{cagr:.2%}",
            'Volatility': f"{vol:.2%}",
            'Sharpe Ratio': f"{sharpe:.2f}",
            'Max Drawdown': f"{mdd:.2%}"
        })
        
        nav_df['year'] = nav_df.index.strftime('%Y')
        yearly_results = []
        for year, group in nav_df.groupby('year'):
            year_indices = nav_df[nav_df['year'] == year].index
            start_idx = year_indices[0]
            end_idx = year_indices[-1]
            
            base_nav = nav_df.loc[start_idx, 'nav']
            all_indices = nav_df.index
            idx_pos = all_indices.get_loc(start_idx)
            if idx_pos > 0:
                base_nav = nav_df.loc[all_indices[idx_pos - 1], 'nav']
                
            ret = nav_df.loc[end_idx, 'nav'] / base_nav - 1
            if idx_pos == 0:
                ret = nav_df.loc[end_idx, 'nav'] / INITIAL_CAPITAL - 1
                
            mdd_y = calc_max_dd(group['nav'])
            yearly_results.append({
                'Year': year,
                'Return': ret,
                'MaxDD': mdd_y
            })
        yearly_navs[name] = pd.DataFrame(yearly_results)
        
    print("\n==========================================================================")
    print("【HOLDING PERIOD SENSITIVITY SUMMARY (TOP-30, 2021-2026)】")
    print("==========================================================================")
    print(pd.DataFrame(full_metrics).to_markdown(index=False))
    print("\n")
    
    print("==========================================================================")
    print("【YEAR-BY-YEAR SIDE-BY-SIDE PERFORMANCE AND DRAWDOWN (HOLDING PERIODS)】")
    print("==========================================================================")
    years = sorted(df['trade_date'].str[:4].unique())
    
    table_rows = []
    for i, year in enumerate(years):
        row = {'Year': year}
        for h in holding_periods:
            name = f"Holding {h} Days"
            r = yearly_navs[name].iloc[i]
            row[f"Hold_{h}d"] = f"{r['Return']*100:.1f}% ({r['MaxDD']*100:.1f}%)"
        table_rows.append(row)
        
    print(pd.DataFrame(table_rows).to_markdown(index=False))

if __name__ == '__main__':
    run_holding_analysis()
