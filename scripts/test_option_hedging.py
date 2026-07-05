import os
import numpy as np
import pandas as pd
from scipy.stats import norm

NAV_FILE = r"C:\Users\liuqi\.gemini\antigravity\worktrees\quant_system_v2\factor-neutralization-alpha-research\smart-beta-research\results\portfolio_comparison_nav.csv"

# ── Black-Scholes Formula ─────────────────────────────────────────────
def bs_put_price(S, K, T, r, sigma):
    if T <= 0:
        return max(K - S, 0.0)
    if sigma <= 0:
        return max(K * np.exp(-r * T) - S, 0.0)
    d1 = (np.log(S / K) + (r + 0.5 * sigma**2) * T) / (sigma * np.sqrt(T))
    d2 = d1 - sigma * np.sqrt(T)
    price = K * np.exp(-r * T) * norm.cdf(-d2) - S * norm.cdf(-d1)
    return max(price, 0.0)

def calc_max_dd(nav_series):
    peak = nav_series.cummax()
    dd = (nav_series - peak) / peak
    return dd.min()

def run_option_backtest(df, structure='single_put', moneyness=0.05, iv_model='dynamic', iv_flat=0.25):
    """
    Backtests option hedging.
    structure: 'single_put' or 'put_spread'
    moneyness: 0.05 (-5%), 0.10 (-10%), 0.15 (-15%)
    iv_model: 'flat' or 'dynamic' (rolling 20d index volatility + 4% VRP)
    """
    # Create daily returns for CSI 1000 to compute realized volatility
    df = df.copy().sort_values('trade_date').reset_index(drop=True)
    df['csi_ret'] = df['Benchmark_CSI1000'].pct_change()
    df['rv_20d'] = df['csi_ret'].rolling(20).std() * np.sqrt(252)
    df['rv_20d'] = df['rv_20d'].fillna(0.20)  # Default fallback
    
    # Calculate daily IV
    if iv_model == 'flat':
        df['iv'] = iv_flat
    else:
        df['iv'] = df['rv_20d'] + 0.04  # 4% Volatility Risk Premium
        # Clamp between 15% and 50%
        df['iv'] = df['iv'].clip(0.15, 0.50)
        
    N = len(df)
    r = 0.02  # Risk-free rate
    roll_period = 21  # 21 trading days (1 month)
    
    hedged_nav = np.zeros(N)
    hedged_nav[0] = 1.0
    
    # We loop through monthly rolling periods
    i = 0
    while i < N - 1:
        start_idx = i
        end_idx = min(i + roll_period, N - 1)
        period_len = end_idx - start_idx
        
        # Spot, pure stock, and IV at the start of the month
        S0 = df.loc[start_idx, 'Benchmark_CSI1000']
        Pure0 = df.loc[start_idx, 'Strategy_Pure']
        IV0 = df.loc[start_idx, 'iv']
        NAV_start = hedged_nav[start_idx]
        
        # Strike prices
        if structure == 'single_put':
            K1 = (1.0 - moneyness) * S0
            # Calculate option premium cost ratio at t_start
            w = bs_put_price(S0, K1, period_len/252.0, r, IV0) / S0
        elif structure == 'put_spread':
            K1 = (1.0 - moneyness) * S0
            K2 = (1.0 - (moneyness + 0.10)) * S0  # Spread width is 10%
            opt1 = bs_put_price(S0, K1, period_len/252.0, r, IV0)
            opt2 = bs_put_price(S0, K2, period_len/252.0, r, IV0)
            w = (opt1 - opt2) / S0
            
        # Limit premium allocation to a max of 10% of portfolio
        w = min(max(w, 0.0), 0.10)
        
        # Daily simulation for this period
        for t in range(start_idx, end_idx + 1):
            if t == start_idx:
                continue
            
            days_passed = t - start_idx
            T_t = max(period_len - days_passed, 0) / 252.0
            
            S_t = df.loc[t, 'Benchmark_CSI1000']
            Pure_t = df.loc[t, 'Strategy_Pure']
            IV_t = df.loc[t, 'iv']
            
            # Calculate current option values
            if structure == 'single_put':
                p_t = bs_put_price(S_t, K1, T_t, r, IV_t)
                opt_payoff_ratio = p_t / S0
            elif structure == 'put_spread':
                p_t1 = bs_put_price(S_t, K1, T_t, r, IV_t)
                p_t2 = bs_put_price(S_t, K2, T_t, r, IV_t)
                opt_payoff_ratio = (p_t1 - p_t2) / S0
                
            # Compound daily NAV
            hedged_nav[t] = NAV_start * ((1.0 - w) * (Pure_t / Pure0) + opt_payoff_ratio)
            
        i = end_idx
        
    df['Hedged_NAV'] = hedged_nav
    return df

def run_sensitivity_analysis():
    df_raw = pd.read_csv(NAV_FILE)
    df_raw['trade_date'] = df_raw['trade_date'].astype(str)
    df_raw['year'] = df_raw['trade_date'].str[:4]
    
    # Configurations to test
    configs = [
        # (name, structure, moneyness, iv_model, iv_flat)
        ('Single Put -5% (Dynamic IV)', 'single_put', 0.05, 'dynamic', 0.0),
        ('Single Put -10% (Dynamic IV)', 'single_put', 0.10, 'dynamic', 0.0),
        ('Single Put -10% (IV = 20%)', 'single_put', 0.10, 'flat', 0.20),
        ('Single Put -10% (IV = 30%)', 'single_put', 0.10, 'flat', 0.30),
        ('Put Spread -5%/-15% (Dynamic IV)', 'put_spread', 0.05, 'dynamic', 0.0),
        ('Put Spread -10%/-20% (Dynamic IV)', 'put_spread', 0.10, 'dynamic', 0.0),
    ]
    
    # Run each config and collect full period metrics
    full_metrics = []
    yearly_results = {}
    
    for name, struct, money, iv_model, iv_flat in configs:
        res_df = run_option_backtest(df_raw, struct, money, iv_model, iv_flat)
        
        # Calculate full period metrics
        eq = res_df['Hedged_NAV']
        pnl = eq.pct_change().fillna(0)
        nyrs = len(pnl)/252
        cagr = (eq.iloc[-1]**(1/nyrs)-1) if nyrs>0 else 0
        vol = pnl.std() * np.sqrt(252)
        sharpe = pnl.mean() / pnl.std() * np.sqrt(252) if pnl.std() > 1e-9 else 0
        mdd = calc_max_dd(eq)
        
        full_metrics.append({
            'Strategy Configuration': name,
            'Total Return': f"{eq.iloc[-1]-1:.2%}",
            'CAGR': f"{cagr:.2%}",
            'Volatility': f"{vol:.2%}",
            'Sharpe Ratio': f"{sharpe:.2f}",
            'Max Drawdown': f"{mdd:.2%}"
        })
        
        # Calculate year-by-year returns and max drawdowns
        yearly_metrics = []
        for year, group in res_df.groupby('year'):
            group = group.sort_values('trade_date').reset_index(drop=True)
            year_indices = res_df[res_df['year'] == year].index
            start_idx = year_indices[0]
            end_idx = year_indices[-1]
            
            base_nav = res_df.loc[start_idx - 1, 'Hedged_NAV'] if start_idx > 0 else res_df.loc[0, 'Hedged_NAV']
            ret = res_df.loc[end_idx, 'Hedged_NAV'] / base_nav - 1
            if start_idx == 0:
                ret = res_df.loc[end_idx, 'Hedged_NAV'] / res_df.loc[0, 'Hedged_NAV'] - 1
                
            mdd_y = calc_max_dd(group['Hedged_NAV'])
            yearly_metrics.append({
                'Year': year,
                'Return': f"{ret*100:.2f}%",
                'MaxDD': f"{mdd_y*100:.2f}%"
            })
        yearly_results[name] = pd.DataFrame(yearly_metrics)
        
    print("==========================================================================")
    print("【OPTION HEDGING CONFIGURATIONS SENSITIVITY SUMMARY (2021-2026)】")
    print("==========================================================================")
    print(pd.DataFrame(full_metrics).to_markdown(index=False))
    print("\n")
    
    # Print yearly comparison for each strategy
    print("==========================================================================")
    print("【YEAR-BY-YEAR PERFORMANCE COMPARISON (Strategy Return / Max Drawdown)】")
    print("==========================================================================")
    
    # We want to print a table with columns: Year, Pure (Unhedged), Wind-down (Hedged), then each option strategy
    # Get the years
    years = sorted(df_raw['year'].unique())
    
    # Calculate baseline yearly metrics
    baseline_metrics = []
    for year, group in df_raw.groupby('year'):
        group = group.sort_values('trade_date').reset_index(drop=True)
        year_indices = df_raw[df_raw['year'] == year].index
        start_idx, end_idx = year_indices[0], year_indices[-1]
        
        base_nav_pure = df_raw.loc[start_idx - 1, 'Strategy_Pure'] if start_idx > 0 else df_raw.loc[0, 'Strategy_Pure']
        base_nav_hedged = df_raw.loc[start_idx - 1, 'Strategy_Hedged'] if start_idx > 0 else df_raw.loc[0, 'Strategy_Hedged']
        base_nav_csi = df_raw.loc[start_idx - 1, 'Benchmark_CSI1000'] if start_idx > 0 else df_raw.loc[0, 'Benchmark_CSI1000']
        
        ret_pure = df_raw.loc[end_idx, 'Strategy_Pure'] / base_nav_pure - 1
        ret_hedged = df_raw.loc[end_idx, 'Strategy_Hedged'] / base_nav_hedged - 1
        ret_csi = df_raw.loc[end_idx, 'Benchmark_CSI1000'] / base_nav_csi - 1
        if start_idx == 0:
            ret_pure = df_raw.loc[end_idx, 'Strategy_Pure'] / df_raw.loc[0, 'Strategy_Pure'] - 1
            ret_hedged = df_raw.loc[end_idx, 'Strategy_Hedged'] / df_raw.loc[0, 'Strategy_Hedged'] - 1
            ret_csi = df_raw.loc[end_idx, 'Benchmark_CSI1000'] / df_raw.loc[0, 'Benchmark_CSI1000'] - 1
            
        baseline_metrics.append({
            'Year': year,
            'Pure': f"{ret_pure*100:.1f}% ({calc_max_dd(group['Strategy_Pure'])*100:.1f}%)",
            'Wind-down': f"{ret_hedged*100:.1f}% ({calc_max_dd(group['Strategy_Hedged'])*100:.1f}%)",
            'CSI1000': f"{ret_csi*100:.1f}% ({calc_max_dd(group['Benchmark_CSI1000'])*100:.1f}%)"
        })
    comp_df = pd.DataFrame(baseline_metrics)
    
    # Merge option strategies
    for name in yearly_results:
        # Create column name like "Spread -5%/-15%"
        col_name = name.replace(" (Dynamic IV)", "").replace(" (IV = 20%)", " (IV20)").replace(" (IV = 30%)", " (IV30)")
        col_data = []
        for i, r in yearly_results[name].iterrows():
            col_data.append(f"{r['Return']} ({r['MaxDD']})")
        comp_df[col_name] = col_data
        
    print(comp_df.to_markdown(index=False))

if __name__ == '__main__':
    run_sensitivity_analysis()
