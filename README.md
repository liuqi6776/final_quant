# Final Quant - Style-Neutralized Smart-Beta Strategy / 风格中性化量化策略系统

This repository contains the complete standalone implementation, factor research reports, walkthroughs, and demo data for our style-neutralized index-enhancement strategy.
本仓库包含经过风格中性化重构后的指数增强策略的完整独立实现、微观结构因子研究报告、执行总结说明（Walkthrough）与演示数据集。

---

## Directory Structure / 目录结构
- `processing/`: Core data cleaner (winsorization, standardization, and regression-based industry+size+beta neutralization).
  核心数据清洗清洗器（去极值、标准化、及基于回归的行业/市值/Beta中性化模块）。
- `scripts/`: Logical pipeline and research scripts.
  策略逻辑流水线与因子研究脚本。
  - `test_microstructure_factors.py`: Empirical Rank IC check for Moneyflow, Chips, and News factors.
    资金流、筹码及新闻因子的日度中性化 Rank IC 体检与校验脚本。
  - `step3_train_ranking_model.py`: Walk-forward Ridge regression monthly rolling train/predict.
    月度滚动走势外插训练与预测。
  - `step4_portfolio_backtest.py`: Portfolio simulation with limit price check and 100-shares lot size constraint.
    包含涨跌停价判定与100股整手交易约束的组合回测引擎。
  - `step5_style_attribution.py`: Fama-French-Carhart style loading attribution (Market, Size, Value, Momentum) and industry exposure checks.
    Fama-French-Carhart 风格归因与多重共线性修复。
- `data/`: Sliced demo dataset (`features_longterm.parquet` containing 120 stocks from 2024 to 2026, ~45 MB) and CSI 1000 trend index.
  切片后的演示数据集（包含120只股票的2024至2026年数据，约45 MB）及中证1000趋势指数。
- `microstructure_factor_report.md`: Detailed research report documenting the Rank IC statistics of Moneyflow & Chips.
  多因子研究报告（详细记录资金流与筹码因子的 Rank IC 与量化机理）。
- `walkthrough.md`: Overall walkthrough summary explaining changes, results, and improvements.
  整体执行报告（详细说明统计偏误修正、因子组合剪枝、端到端回测提升与验证结论）。

---

## How to Run / 如何运行

Execute the scripts sequentially from the repository root:
在仓库根目录下按顺序执行以下命令：

1. **Microstructure Factor Health Check (Optional) / 资金流与筹码因子体检 (可选)**
   ```bash
   python scripts/test_microstructure_factors.py
   ```
   *Runs daily cross-sectional neutralization and prints the Rank IC metrics.*
   *运行因子的日度截面中性化并输出其 Rank IC 检验指标。*

2. **Model Training & Prediction / 模型训练与预测**
   ```bash
   python scripts/step3_train_ranking_model.py
   ```
   *Trains the rolling model on 2024 data and outputs walk-forward predictions for 2025-2026 to `predictions/predictions_longterm.parquet`.*
   *在2024年数据上进行滚动训练，并将2025-2026年的预测结果输出至 `predictions/predictions_longterm.parquet`。*

3. **Portfolio Backtest / 组合回测**
   ```bash
   python scripts/step4_portfolio_backtest.py
   ```
   *Simulates the trading strategy under 100-shares constraint and saves navigation curves to `results/portfolio_backtest_nav.png`.*
   *模拟100股整手约束下的策略交易，并将净值曲线保存至 `results/portfolio_backtest_nav.png`。*

4. **Style Attribution Analysis / 风格归因分析**
   ```bash
   python scripts/step5_style_attribution.py
   ```
   *Performs regression to output the Fama-French-Carhart style exposure loading report under `results/style_attribution_report.txt`.*
   *进行风格归因回归分析，输出风格暴露报告至 `results/style_attribution_report.txt`。*
