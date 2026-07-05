"""
数据清洗模块

提供 ST股过滤、股票代码筛选、标准化等功能
"""

import warnings
from typing import List, Optional

import numpy as np
import pandas as pd
from tqdm import tqdm


def remove_st_stocks(df: pd.DataFrame, stock_basic_df: Optional[pd.DataFrame] = None) -> pd.DataFrame:
    """
    剔除 ST 股票
    
    避免引入不可控的波动风险
    
    Args:
        df: 股票数据 DataFrame
        stock_basic_df: 股票基础信息表（需包含 ts_code, name）
    
    Returns:
        过滤后的 DataFrame
    """
    print("正在执行 ST 股票过滤...")
    
    if 'name' not in df.columns and stock_basic_df is None:
        warnings.warn("无法过滤 ST 股票：DataFrame 中缺少 'name' 列且未提供基础信息表")
        return df
    
    target_df = df.copy()
    
    if 'name' not in df.columns:
        # 合并股票名称
        target_df = pd.merge(df, stock_basic_df[['ts_code', 'name']], on='ts_code', how='left')
    
    # 过滤包含 ST, *ST 的股票
    condition = ~target_df['name'].str.contains('ST', na=False)
    filtered_df = target_df[condition]
    
    if 'name' not in df.columns:
        filtered_df = filtered_df.drop(columns=['name'])
    
    removed_count = len(target_df['ts_code'].unique()) - len(filtered_df['ts_code'].unique())
    print(f"ST 过滤完成，移除股票数量: {removed_count}")
    
    return filtered_df


def filter_stock_codes(df: pd.DataFrame, patterns: List[str] = ['^60', '^00']) -> pd.DataFrame:
    """
    根据股票代码前缀筛选
    
    Args:
        df: 股票数据 DataFrame
        patterns: 保留的股票代码前缀模式列表
    
    Returns:
        过滤后的 DataFrame
    """
    if 'ts_code' not in df.columns:
        warnings.warn("DataFrame 中缺少 'ts_code' 列，无法筛选股票代码")
        return df
    
    # 构建正则模式
    pattern = '|'.join([f'({p})' for p in patterns])
    
    return df[df['ts_code'].str.match(pattern)]


def apply_expanding_standardization(
    df: pd.DataFrame,
    cols_to_standardize: List[str],
    group_col: str = 'trade_date',
    min_periods: int = 60,
    suffix: str = '_norm'
) -> pd.DataFrame:
    """
    使用日频截面进行标准化，消除前视偏差与时序混淆偏误。
    将原时序扩展标准化改为日频截面标准化：
    z = (x - mean_cs) / (std_cs + 1e-8)
    
    Args:
        df: 数据 DataFrame
        cols_to_standardize: 需要标准化的列名列表
        group_col: 分组列名，默认按 'trade_date' 进行截面标准化
        min_periods: 最小计算周期 (为了保持参数兼容性保留，但在截面标准化中不使用)
        suffix: 标准化列名后缀
    
    Returns:
        添加标准化列的 DataFrame
    """
    print("正在应用截面标准化(消除前视偏差与时序错误)...")
    
    df = df.copy()
    
    # 仅对存在的列进行标准化
    valid_cols = [c for c in cols_to_standardize if c in df.columns]
    
    if not valid_cols:
        warnings.warn("没有找到需要标准化的列")
        return df
    
    grouped = df.groupby(group_col)
    
    for col in tqdm(valid_cols, desc="标准化特征"):
        df[f'{col}{suffix}'] = grouped[col].transform(
            lambda x: (x - x.mean()) / (x.std() + 1e-8)
        )
        
        # 缺失值填充
        df[f'{col}{suffix}'] = df[f'{col}{suffix}'].fillna(0)
    
    return df


def remove_outliers_mad(
    df: pd.DataFrame,
    cols: List[str],
    n: float = 3.0,
    group_col: str = 'trade_date'
) -> pd.DataFrame:
    """
    按交易日截面使用 MAD (Median Absolute Deviation) 进行去极值处理。
    
    Args:
        df: 数据 DataFrame
        cols: 需要去极值的列名列表
        n: 偏离度阈值倍数
        group_col: 按此列进行截面分组，默认 'trade_date'
        
    Returns:
        去极值后的 DataFrame
    """
    df = df.copy()
    valid_cols = [c for c in cols if c in df.columns]
    
    for col in valid_cols:
        # 计算中位数
        median = df.groupby(group_col)[col].transform('median')
        # 计算 |x - median|
        abs_dev = (df[col] - median).abs()
        # 计算 MAD = median(|x - median|)
        mad = abs_dev.groupby(df[group_col]).transform('median')
        
        # 边界 = median +/- n * 1.4826 * mad
        threshold = n * 1.4826 * mad
        lower_bound = median - threshold
        upper_bound = median + threshold
        
        df[col] = np.clip(df[col], lower_bound, upper_bound)
        
    return df


def calculate_rolling_beta(df: pd.DataFrame, window: int = 20) -> pd.DataFrame:
    """
    计算个股相对于全市场等权收益率的滚动 Beta (window个交易日)
    
    Args:
        df: 数据 DataFrame，必须包含 ts_code, trade_date, pct_chg
        window: 滚动窗口大小
        
    Returns:
        包含 'beta' 列的 DataFrame
    """
    df = df.sort_values(['ts_code', 'trade_date']).copy()
    
    # 计算每日市场等权收益率
    mkt_ret = df.groupby('trade_date')['pct_chg'].mean()
    df['mkt_pct_chg'] = df['trade_date'].map(mkt_ret)
    
    # 计算滚动 Covariance and Variance
    # Cov(R_i, R_m) = E[R_i * R_m] - E[R_i]*E[R_m]
    df['ret_prod'] = df['pct_chg'] * df['mkt_pct_chg']
    
    grouped = df.groupby('ts_code')
    mean_i = grouped['pct_chg'].transform(lambda x: x.rolling(window, min_periods=window//2).mean())
    mean_m = grouped['mkt_pct_chg'].transform(lambda x: x.rolling(window, min_periods=window//2).mean())
    mean_prod = grouped['ret_prod'].transform(lambda x: x.rolling(window, min_periods=window//2).mean())
    
    cov_im = mean_prod - mean_i * mean_m
    var_m = grouped['mkt_pct_chg'].transform(lambda x: x.rolling(window, min_periods=window//2).var())
    
    df['beta'] = cov_im / (var_m + 1e-8)
    df['beta'] = df['beta'].fillna(1.0)
    
    # 清理临时列
    df = df.drop(columns=['mkt_pct_chg', 'ret_prod'])
    return df


def neutralize_factors(
    df: pd.DataFrame,
    factor_cols: List[str],
    industry_col: str = 'industry',
    size_col: str = 'circ_mv',
    beta_col: str = 'beta'
) -> pd.DataFrame:
    """
    对每个交易日，将因子值对 [行业哑变量 + log(circ_mv) + Beta] 进行截面回归，并以残差作为中性化因子值。
    
    Args:
        df: 数据 DataFrame
        factor_cols: 需要中性化的因子列列表
        industry_col: 行业分类列名
        size_col: 流通市值列名
        beta_col: Beta 因子列名
        
    Returns:
        中性化残差填充后的 DataFrame
    """
    from sklearn.linear_model import LinearRegression
    df = df.copy()
    
    # 确保 log_circ_mv 存在
    if size_col in df.columns:
        df['log_circ_mv'] = np.log(df[size_col].clip(lower=1e-5))
    else:
        df['log_circ_mv'] = 0.0
        
    # 确保 beta 存在
    if beta_col not in df.columns:
        df = calculate_rolling_beta(df)
        
    valid_factor_cols = [c for c in factor_cols if c in df.columns]
    if not valid_factor_cols:
        return df
        
    # 提取行业哑变量 (使用 drop_first=True 消除完全共线性，指定 dtype=float 保证数值计算正确)
    if industry_col in df.columns and df[industry_col].nunique() > 1:
        df_ind_dummies = pd.get_dummies(df[industry_col], prefix='ind', drop_first=True, dtype=float)
    else:
        df_ind_dummies = pd.DataFrame(index=df.index)
        
    df_reg_base = pd.concat([df[['trade_date', 'log_circ_mv', beta_col]], df_ind_dummies], axis=1)
    
    neutralized_data = []
    
    for dt, group in df_reg_base.groupby('trade_date'):
        orig_group = df[df['trade_date'] == dt].copy()
        if len(orig_group) < 10:
            neutralized_data.append(orig_group)
            continue
            
        X_cols = ['log_circ_mv', beta_col] + list(df_ind_dummies.columns)
        X = group[X_cols].astype(float).values
        X_clean = np.nan_to_num(X, nan=0.0, posinf=0.0, neginf=0.0)
        
        for col in valid_factor_cols:
            y = pd.to_numeric(orig_group[col], errors='coerce').astype(float).values
            
            # 保证为 float 类型以避免 np.isnan 报错
            valid_mask = ~np.isnan(y) & ~np.isnan(X).any(axis=1)
            if valid_mask.sum() < 10:
                continue
                
            reg = LinearRegression()
            reg.fit(X_clean[valid_mask], y[valid_mask])
            y_pred = reg.predict(X_clean)
            orig_group[col] = y - y_pred
            
        neutralized_data.append(orig_group)
        
    df_neutralized = pd.concat(neutralized_data, ignore_index=True)
    return df_neutralized


def remove_outliers(
    df: pd.DataFrame,
    columns: List[str],
    method: str = 'zscore',
    threshold: float = 3.0
) -> pd.DataFrame:
    """
    移除异常值
    
    Args:
        df: 数据 DataFrame
        columns: 检查的列
        method: 方法 ('zscore' 或 'iqr')
        threshold: 阈值
    
    Returns:
        过滤后的 DataFrame
    """
    df = df.copy()
    
    for col in columns:
        if col not in df.columns:
            continue
        
        if method == 'zscore':
            z_scores = np.abs((df[col] - df[col].mean()) / df[col].std())
            df = df[z_scores < threshold]
        elif method == 'iqr':
            Q1 = df[col].quantile(0.25)
            Q3 = df[col].quantile(0.75)
            IQR = Q3 - Q1
            df = df[(df[col] >= Q1 - threshold * IQR) & (df[col] <= Q3 + threshold * IQR)]
    
    return df
