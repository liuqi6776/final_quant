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

# 策略参数
PORTFOLIO_SIZE = 100
HOLDING_DAYS = 20
MAX_WEIGHT_PER_INDUSTRY = 0.20
INITIAL_CAPITAL = 1000000.0
BUY_COST_RATE = 0.002
SELL_COST_RATE = 0.003

def is_limit_up(open_price, prev_close, code):
    limit = 0.198 if (code.startswith('30') or code.startswith('68')) else 0.098
    return open_price >= prev_close * (1 + limit)

def is_limit_down(open_price, prev_close, code):
    limit = 0.198 if (code.startswith('30') or code.startswith('68')) else 0.098
    return open_price <= prev_close * (1 - limit)

def simulate_strategy_custom(df_by_date, trade_dates, rebalance_dates, 
                             filter_type='none', qvix_th=1.5, pcr_th=0.95):
    """
    Simulates portfolio strategy with custom risk control.
    filter_type: 
      - 'none': Pure stock selection
      - 'ma20_only': Cash if close < MA20
      - 'ma20_and_qvix': Cash if close < MA20 AND qvix_z > qvix_th
      - 'ma20_and_options': Cash if close < MA20 AND (qvix_z > qvix_th OR pcr > pcr_th)
    """
    current_holdings = {}  # {ts_code: {'val': val, 'buy_price': buy_price, 'is_first_day': bool, 'shares': shares}}
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
                    # Halt
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
        
        # 2. Risk control check
        is_panic = False
        if len(day_data) > 0:
            is_downtrend = day_data['downtrend'].iloc[0]
            qvix_z = day_data['opt_qvix_zscore'].iloc[0]
            pcr = day_data['opt_pcr_vol_50'].iloc[0]
            
            if filter_type == 'ma20_only':
                is_panic = is_downtrend
            elif filter_type == 'ma20_and_qvix':
                is_panic = is_downtrend and (qvix_z > qvix_th)
            elif filter_type == 'ma20_and_options':
                is_panic = is_downtrend and ((qvix_z > qvix_th) or (pcr > pcr_th))
                
        # 3. Rebalancing
        if dt in rebalance_dates:
            if idx + 1 >= len(trade_dates): continue
            next_dt = trade_dates[idx+1]
            if next_dt not in df_by_date: continue
            
            next_day_prices = df_by_date[next_dt].set_index('ts_code').to_dict(orient='index')
            
            # Sell execution (check limit down / halt)
            sell_candidates = []
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
                    sell_candidates.append(code)
                    
            if is_panic:
                # Liquidate all sell candidates and hold cash
                for code in sell_candidates:
                    shares = current_holdings[code].get('shares', 0)
                    sell_price = next_day_prices[code]['open']
                    sell_val = shares * sell_price
                    cost = sell_val * SELL_COST_RATE
                    cash += (sell_val - cost)
                current_holdings = forced_holdings
                continue
                
            # Normal rebalance: sell candidates
            for code in sell_candidates:
                shares = current_holdings[code].get('shares', 0)
                sell_price = next_day_prices[code]['open']
                sell_val = shares * sell_price
                cost = sell_val * SELL_COST_RATE
                cash += (sell_val - cost)
                
            # Buy execution
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
                    
            total_target_stocks = len(selected_codes) + len(forced_holdings)
            if total_target_stocks > 0:
                new_holdings = {code: item for code, item in forced_holdings.items()}
                if len(selected_codes) > 0:
                    buy_value_per_stock = cash / len(selected_codes)
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
                current_holdings = {code: item for code, item in forced_holdings.items()}
                
    nav_df = pd.DataFrame(daily_navs)
    nav_df['trade_date'] = pd.to_datetime(nav_df['trade_date'])
    nav_df = nav_df.set_index('trade_date')
    return nav_df

def calc_max_dd(nav_series):
    peak = nav_series.cummax()
    dd = (nav_series - peak) / peak
    return dd.min()

def main():
    print("Loading data files...")
    pred_df = pd.read_parquet(PRED_FILE)
    pred_df = pred_df.drop_duplicates(subset=['trade_date', 'ts_code'])
    
    feat_df = pd.read_parquet(FEATURES_FILE, columns=['trade_date', 'ts_code', 'vol', 'opt_qvix_zscore', 'opt_pcr_vol_50'])
    feat_df = feat_df.drop_duplicates(subset=['trade_date', 'ts_code'])
    
    df = pred_df.merge(feat_df, on=['trade_date', 'ts_code'], how='left')
    df['vol'] = df['vol'].fillna(0)
    df['opt_qvix_zscore'] = df['opt_qvix_zscore'].fillna(0)
    df['opt_pcr_vol_50'] = df['opt_pcr_vol_50'].fillna(0)
    
    # Calculate index trend
    idx_df = pd.read_csv(INDEX_FILE)
    idx_df['trade_date'] = idx_df['trade_date'].astype(str)
    idx_df = idx_df.sort_values('trade_date').reset_index(drop=True)
    idx_df['ma20'] = idx_df['close'].rolling(20).mean()
    idx_df['downtrend'] = idx_df['close'] < idx_df['ma20']
    trend_map = idx_df.set_index('trade_date')['downtrend'].to_dict()
    df['downtrend'] = df['trade_date'].map(trend_map).fillna(False)
    
    df = df.sort_values(['trade_date', 'ts_code']).reset_index(drop=True)
    
    trade_dates = sorted(df['trade_date'].unique())
    rebalance_dates = set(trade_dates[::HOLDING_DAYS])
    df_by_date = {dt: g for dt, g in df.groupby('trade_date')}
    
    # Set of test configurations
    test_cases = [
        ('1. Pure Selection (No Wind-down)', 'none', 0.0, 0.0),
        ('2. MA20 Only (Hard Wind-down)', 'ma20_only', 0.0, 0.0),
        ('3. MA20 + QVIX Z>1.0 Confirm', 'ma20_and_qvix', 1.0, 0.0),
        ('4. MA20 + QVIX Z>1.5 Confirm', 'ma20_and_qvix', 1.5, 0.0),
        ('5. MA20 + (QVIX Z>1.2 OR PCR>0.95)', 'ma20_and_options', 1.2, 0.95),
        ('6. MA20 + (QVIX Z>1.5 OR PCR>0.95)', 'ma20_and_options', 1.5, 0.95),
        ('7. MA20 + (QVIX Z>1.5 OR PCR>1.00)', 'ma20_and_options', 1.5, 1.00),
    ]
    
    # Run backtests
    full_metrics = []
    yearly_navs = {}
    
    for name, f_type, qvix_th, pcr_th in test_cases:
        print(f"Running backtest for: {name}...", flush=True)
        nav_df = simulate_strategy_custom(df_by_date, trade_dates, rebalance_dates, f_type, qvix_th, pcr_th)
        
        # Calculate full metrics
        nav = nav_df['nav']
        pnl = nav.pct_change().fillna(0)
        nyrs = len(pnl)/252
        cagr = (nav.iloc[-1]/INITIAL_CAPITAL)**(1/nyrs) - 1
        vol = pnl.std() * np.sqrt(252)
        sharpe = pnl.mean() / pnl.std() * np.sqrt(252) if pnl.std() > 1e-9 else 0
        mdd = calc_max_dd(nav)
        
        full_metrics.append({
            'Configuration': name,
            'Total Return': f"{nav.iloc[-1]/INITIAL_CAPITAL-1:.2%}",
            'CAGR': f"{cagr:.2%}",
            'Volatility': f"{vol:.2%}",
            'Sharpe Ratio': f"{sharpe:.2f}",
            'Max Drawdown': f"{mdd:.2%}"
        })
        
        # Calculate yearly breakdown
        nav_df['year'] = nav_df.index.strftime('%Y')
        yearly_results = []
        for year, group in nav_df.groupby('year'):
            year_indices = nav_df[nav_df['year'] == year].index
            start_idx = year_indices[0]
            end_idx = year_indices[-1]
            
            # Find base NAV
            base_nav = nav_df.loc[start_idx, 'nav']
            # Find index position in index to get previous row
            all_indices = nav_df.index
            idx_pos = all_indices.get_loc(start_idx)
            if idx_pos > 0:
                base_nav = nav_df.loc[all_indices[idx_pos - 1], 'nav']
                
            ret = nav_df.loc[end_idx, 'nav'] / base_nav - 1
            # First year check
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
    print("【OPTION SENTIMENT MULTI-FACTOR TIMING STRATEGY SUMMARY (2021-2026)】")
    print("==========================================================================")
    print(pd.DataFrame(full_metrics).to_markdown(index=False))
    print("\n")
    
    # Side-by-side yearly returns and drawdowns comparison
    print("==========================================================================")
    print("【YEAR-BY-YEAR SIDE-BY-SIDE PERFORMANCE AND DRAWDOWN COMPARISON】")
    print("==========================================================================")
    years = sorted(df['trade_date'].str[:4].unique())
    
    # We will build a table
    table_rows = []
    for i, year in enumerate(years):
        row = {'Year': year}
        for name in yearly_navs:
            col_name = name.split(". ")[1].replace(" (No Wind-down)", "").replace(" (Hard Wind-down)", "").replace(" Confirm", "")
            r = yearly_navs[name].iloc[i]
            row[col_name] = f"{r['Return']*100:.1f}% ({r['MaxDD']*100:.1f}%)"
        table_rows.append(row)
        
    print(pd.DataFrame(table_rows).to_markdown(index=False))

if __name__ == '__main__':
    main()
