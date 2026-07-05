import os
import sys
import pandas as pd
import numpy as np
import warnings
from tqdm import tqdm

warnings.filterwarnings('ignore')

# 保证能导入 processing.cleaner
REPO_ROOT = r"C:\Users\liuqi\.gemini\antigravity\worktrees\quant_system_v2\factor-neutralization-alpha-research"
sys.path.append(REPO_ROOT)

from processing.cleaner import remove_outliers_mad, neutralize_factors, calculate_rolling_beta

FEATURES_FILE = os.path.join(REPO_ROOT, "smart-beta-research", "data", "features_longterm.parquet")

def calc_tma_cost_optimized(df):
    print("正在计算换手加权持仓成本线 (TMA Cost)...", flush=True)
    df = df.sort_values(['ts_code', 'trade_date']).reset_index(drop=True)
    close = df['close'].values
    turnover = df['turnover_rate'].fillna(0.0).values / 100.0
    
    # 提取个股的分界索引以避免 groupby.apply 的巨大开销
    codes = df['ts_code'].values
    unique_codes, start_indices = np.unique(codes, return_index=True)
    boundaries = list(start_indices) + [len(df)]
    
    cost = np.zeros(len(df))
    for i in range(len(boundaries) - 1):
        start = boundaries[i]
        end = boundaries[i+1]
        
        close_slice = close[start:end]
        tr_slice = turnover[start:end]
        cost_slice = np.zeros(end - start)
        
        cost_slice[0] = close_slice[0]
        for j in range(1, len(close_slice)):
            tr = tr_slice[j]
            if tr < 0.0:
                tr = 0.0
            elif tr > 1.0:
                tr = 1.0
            cost_slice[j] = cost_slice[j-1] * (1.0 - tr) + close_slice[j] * tr
            
        cost[start:end] = cost_slice
        
    df['chip_cost_tma'] = cost
    return df

def run_factor_health_check():
    print(">>> 启动资金流 + 筹码分布 + 重大利好新闻因子体检程序 <<<", flush=True)
    if not os.path.exists(FEATURES_FILE):
        print(f"Error: 找不到数据文件 {FEATURES_FILE}")
        return
        
    print(f"正在读取特征文件 {FEATURES_FILE} ...", flush=True)
    # 仅读取必要列以节省内存
    cols_to_load = [
        'trade_date', 'ts_code', 'close', 'high', 'low', 'pct_chg', 'turnover_rate', 'industry', 'circ_mv',
        'net_mf_amount', 'buy_lg_amount', 'buy_elg_amount', 'vol_amount', 'news_stock_impact', 'mkt_excess_ret_20d'
    ]
    df = pd.read_parquet(FEATURES_FILE, columns=cols_to_load)
    print(f"数据读取完毕，总行数: {len(df)}")
    
    # 1. 计算筹码持仓线
    df = calc_tma_cost_optimized(df)
    
    # 2. 构建待测因子
    print("正在构建量化因子...", flush=True)
    
    # A. 资金流因子
    df['moneyflow_large'] = (df['buy_lg_amount'] + df['buy_elg_amount']) / (df['vol_amount'] + 1e-8)
    df['moneyflow_net'] = df['net_mf_amount'] / (df['vol_amount'] + 1e-8)
    
    # B. 筹码集中度与获利偏离
    # 动态滚动最值 (按股票分组)
    grouped = df.groupby('ts_code')
    df['roll_high_60d'] = grouped['high'].transform(lambda x: x.rolling(60, min_periods=30).max())
    df['roll_low_60d'] = grouped['low'].transform(lambda x: x.rolling(60, min_periods=30).min())
    df['roll_high_120d'] = grouped['high'].transform(lambda x: x.rolling(120, min_periods=60).max())
    df['roll_low_120d'] = grouped['low'].transform(lambda x: x.rolling(120, min_periods=60).min())
    
    df['chip_concentr_60d'] = (df['roll_high_60d'] - df['roll_low_60d']) / (df['roll_high_60d'] + df['roll_low_60d'] + 1e-8)
    df['chip_concentr_120d'] = (df['roll_high_120d'] - df['roll_low_120d']) / (df['roll_high_120d'] + df['roll_low_120d'] + 1e-8)
    df['chip_profit_dev'] = (df['close'] - df['chip_cost_tma']) / (df['chip_cost_tma'] + 1e-8)
    
    # C. 新闻重大利好及情绪得分
    df['news_major_positive'] = (df['news_stock_impact'] >= 3.0).astype(float)
    df['news_sentiment'] = df['news_stock_impact']
    
    test_factors = [
        'moneyflow_large', 'moneyflow_net', 
        'chip_concentr_60d', 'chip_concentr_120d', 'chip_profit_dev',
        'news_major_positive', 'news_sentiment'
    ]
    
    # 清理临时列释放内存
    df = df.drop(columns=['roll_high_60d', 'roll_low_60d', 'roll_high_120d', 'roll_low_120d'])
    
    # 填充空值
    df[test_factors] = df[test_factors].fillna(0.0)
    
    # 3. 因子预处理：去极值与标准化
    print("正在进行横截面因子预处理 (MAD Winsorize & Z-score)...", flush=True)
    df = remove_outliers_mad(df, test_factors, n=3.0)
    
    for col in test_factors:
        date_means = df.groupby('trade_date')[col].transform('mean')
        date_stds = df.groupby('trade_date')[col].transform('std')
        date_stds = date_stds.replace(0, 1).fillna(1)
        df[col] = (df[col] - date_means) / (date_stds + 1e-8)
        
    # 4. 核心步骤：回归中性化
    print("正在计算滚动个股 Beta 并应用行业+市值+Beta中性化...", flush=True)
    df = calculate_rolling_beta(df)
    df = neutralize_factors(df, test_factors)
    
    # 5. 计算日度 Rank IC (因子值与未来20日超额收益的相关系数)
    print("正在计算各因子的日度 Rank IC...", flush=True)
    
    # 仅保留测试周期 (20220101 之后)
    df_test = df[df['trade_date'].astype(str) >= '20220101'].copy()
    
    ic_results = []
    
    for factor in test_factors:
        # 每日计算 Spearman 相关系数
        def calc_daily_ic(group):
            valid = group[[factor, 'mkt_excess_ret_20d']].dropna()
            if len(valid) < 10:
                return np.nan
            return valid[factor].corr(valid['mkt_excess_ret_20d'], method='spearman')
            
        daily_ics = df_test.groupby('trade_date').apply(calc_daily_ic)
        daily_ics = daily_ics.dropna()
        
        mean_ic = daily_ics.mean()
        std_ic = daily_ics.std()
        ic_ir = mean_ic / (std_ic + 1e-8)
        t_stat = ic_ir * np.sqrt(len(daily_ics))
        
        ic_results.append({
            'Factor': factor,
            'Mean Rank IC': mean_ic,
            'IC Std': std_ic,
            'IC IR (t-stat)': t_stat,
            'Trading Days': len(daily_ics)
        })
        print(f"因子 {factor:20s} | Mean IC: {mean_ic:+.4f} | t-stat: {t_stat:+.2f}", flush=True)
        
    # 输出最终 ASCII 报表
    print("\n" + "="*80)
    print("                       新引入因子中性化后 Rank IC 体检报告                  ")
    print("="*80)
    print(f"{'Factor Name':22s} | {'Mean IC':9s} | {'IC Std':8s} | {'t-stat (IR)':12s} | {'Days':5s}")
    print("-"*80)
    for r in ic_results:
        print(f"{r['Factor']:22s} | {r['Mean Rank IC']:+9.4f} | {r['IC Std']:8.4f} | {r['IC IR (t-stat)']:+12.4f} | {r['Trading Days']:5d}")
    print("="*80)
    
if __name__ == '__main__':
    run_factor_health_check()
