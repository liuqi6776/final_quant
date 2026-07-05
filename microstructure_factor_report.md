# Research Report: Moneyflow & Chip Distribution Factors / 多因子研究报告：资金流、筹码分布与新闻利好因子

This report presents the empirical Rank IC validation results for the newly constructed market microstructure factors: Moneyflow, Chip Distribution, and Event-driven News.
本报告展示了新构建的市场微观结构因子（资金流、筹码分布及事件驱动新闻）的 Rank IC 经验验证结果。

---

## 1. Factor Definitions & Formulas / 因子定义与计算公式

### 1.1 Moneyflow Factors / 资金流因子
- **Large Moneyflow Ratio (`moneyflow_large`) / 主力资金流占比**:
  $$moneyflow\_large = \frac{buy\_lg\_amount + buy\_elg\_amount}{vol\_amount}$$
  *Measures the proportion of daily transaction volume driven by large and extra-large institutional orders.*
  *衡量每日交易额中大单与特大单机构资金流的占比。*
  
- **Net Moneyflow Ratio (`moneyflow_net`) / 净资金流占比**:
  $$moneyflow\_net = \frac{net\_mf\_amount}{vol\_amount}$$
  *Measures the proportion of net capital inflow relative to total volume.*
  *衡量日度主力资金净流入占总交易额的比例。*

### 1.2 Chip Distribution Factors / 筹码分布因子
- **Chip Concentration (`chip_concentr_60d` / `chip_concentr_120d`) / 筹码集中度**:
  $$chip\_concentr = \frac{Price\_High - Price\_Low}{Price\_High + Price\_Low}$$
  *Where Price_High and Price_Low represent the rolling maximum high price and minimum low price over the lookback window (60 or 120 trading days). A smaller value indicates tighter consolidation (higher chip density).*
  *其中 Price_High 和 Price_Low 代表滚动窗口（60日或120日）内的最高价和最低价。数值越小表示股价区间越窄，筹码越密集。*

- **Chip Cost Profit/Loss Deviation (`chip_profit_dev`) / 筹码获利偏离度**:
  $$chip\_profit\_dev = \frac{Close - Cost}{Cost}$$
  *Where Cost is calculated recursively weighted by daily turnover rate:*
  *其中持仓均线成本 Cost 采用日度换手率作为权重递归计算：*
  $$Cost_t = Cost_{t-1} \times (1 - Turnover_t) + Close_t \times Turnover_t$$

### 1.3 News Event Factors / 新闻事件因子
- **News Major Positive Indicator (`news_major_positive`) / 重大利好新闻**:
  $$news\_major\_positive = I(\text{news\_stock\_impact} \ge 3.0)$$
  *Binary indicator representing whether a major positive news event has occurred.*
  *代表当日是否发生了个股重大利好新闻事件（得分大于等于3）的二值虚拟变量。*

---

## 2. Empirical Rank IC Results / Rank IC 验证结果

*Test Period: 2022-01-04 to 2026-03-11 (991 trading days, ~4.6 million stock-day observations).*
*All factors are cross-sectionally winsorized (MAD) and neutralized against [Industry + Size + Beta] daily.*
*测试区间：2022年01月04日至2026年03月11日（共991个交易日，约460万只股日样本）。*
*所有因子在计算日度 Rank IC 前，均已过截面 MAD 去极值、标准化，并对 [行业哑变量 + log(流通市值) + Beta] 进行了截面回归中性化剥离。*

| Factor Name / 因子名称 | Mean Rank IC / IC均值 | IC Std / IC标准差 | t-statistic (IR) / t值 | Validation Status / 体检结论 |
| :--- | :---: | :---: | :---: | :---: |
| **`chip_concentr_60d`** | **-0.0600** | 0.0996 | **-18.96** | **Passed / 通过 (做多主力因子)** |
| **`moneyflow_large`** | **-0.0459** | 0.0579 | **-24.92** | **Passed / 通过 (做多反转因子)** |
| **`chip_profit_dev`** | **-0.0424** | 0.0869 | **-15.35** | **Passed / 通过 (左侧支撑因子)** |
| **`chip_concentr_120d`** | **-0.0503** | 0.1028 | **-15.41** | **Passed / 通过 (辅助主力因子)** |
| **`moneyflow_net`** | **+0.0110** | 0.0546 | **+6.36** | **Passed / 通过 (正向偏置因子)** |
| `news_major_positive` | *NaN* | *NaN* | *NaN* | Sparse Event / 稀疏事件 (适合做子集过滤) |
| `news_sentiment` | *NaN* | *NaN* | *NaN* | Sparse Event / 稀疏事件 (适合做辅助过滤) |

---

## 3. Quantitative Insights / 量化逻辑解析

1. **Chip Concentration Alpha / 筹码集中度阿尔法**:
   - The Rank IC of `chip_concentr_60d` is strongly negative (**-0.0600, t-stat: -18.96**).
     `chip_concentr_60d` 的 Rank IC 为强负数（**-0.0600，t值: -18.96**）。
   - This validates the classic microstructure theory: a narrow price consolidation range (smaller concentration value) indicates that chips have clustered into a single peak (strong主力锁仓/吸筹). This leads to positive future returns when the price breaks out.
     这完美验证了筹码密集理论：价格区间极窄代表筹码向主力成本线靠拢，锁仓越充分，未来突破后的超额收益越显著。

2. **Moneyflow Reversal Effect / 主力资金流的反转效应**:
   - The Rank IC of `moneyflow_large` is strongly negative (**-0.0459, t-stat: -24.92**).
     `moneyflow_large` 的 Rank IC 为强负值（**-0.0459，t值: -24.92**）。
   - In A-shares, single-day massive institutional buying (large moneyflow spikes) attracts significant retail attention and creates short-term price overshooting. Over the 20-day horizon, these stocks experience a strong mean-reversion pull. Therefore, in our stock ranking system, we should **reverse its sign** (buy low large-inflows, sell/avoid high large-inflows).
     在 A 股市场，单日大单和特大单的暴涨极易吸引散户跟风导致股价短期超调，在中周期（20天）上会形成强烈的反转压力。因此在因子合成中应当**反向使用**该因子，进行逆向价值投资。

3. **News Sparsity / 新闻利好的稀疏性**:
   - Due to the extreme sparsity of major news events (averaging ~1.5 occurrences daily across 3,300 stocks), cross-sectional Spearman correlation results in daily NaN values (zero variance). We recommend using news indicators as **event-driven filters (White List triggers)** rather than continuous sorting features.
     由于重大利好新闻的发生极度稀疏（全市场日均约1.5只股票），日度截面计算表现为零方差（导致 IC 呈 NaN）。我们建议将其作为**事件过滤器（如选股白名单触发）**，而非截面排序因子。
