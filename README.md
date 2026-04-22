# FinancialManager - 短线预测统计

根据你的需求，这个工具用于统计每天推荐股票的开盘/收盘收益，并输出按题材的趋势表现。

## 功能

- 读取每日推荐股票列表（CSV）。
- 自动查询每只股票当日开盘价和收盘价。
- 计算每只股票收益率（默认每只买入一手=100股）。
- 统计每天5只（或更多）股票的平均收益。
- 按题材汇总平均收益和总收益。
- 自动生成多维度图表（日期趋势、题材对比、个股 Top/Bottom）。

## 环境准备

```bash
pip install -r requirements.txt
```

## 输入格式

支持两种输入：

- `CSV`：必须包含以下列：
  - `date`：日期，格式如 `2026-04-13`
  - `code`：股票代码，支持 `000001`、`sz000001`、`sh600519` 等形式
- `TXT`：可直接粘贴推荐原文，脚本会自动解析
  - 日期行示例：`今天是2026年4月21日`
  - 股票行示例：`【飞龙股份 002536】`
  - 会自动提取关键信息：`date`、`code`、`company_name`、`theme`
  - 会自动从文件名提取推荐人（如 `张少辉.txt` -> `recommender=张少辉`）
  - 会自动提取 6 位股票代码并绑定到最近一次出现的日期

示例见 `sample_input.csv` 与 `sample_data.txt`。

## 运行方式

```bash
python financial_manager.py --input sample_input.csv --output-dir output
```

## 增量更新命令（不重启整套流程）

当看板已经在运行时，可单独执行下面命令追加新数据到缓存：

```bash
python append_data.py --input 张少辉.txt --output-dir output
```

该命令只更新：

- `output/recommendation_cache.csv`
- `output/quote_cache.csv`

不会重新跑整套统计导出流程，适合日常快速追加。
每次执行会自动检查 `recommendation_cache.csv` 与 `quote_cache.csv` 的键覆盖关系，
将 `quote_cache` 中缺失的推荐记录自动补齐（按 `date+code` 对齐）。

## 看板功能（功能二）

生成缓存数据后，可以启动可视化看板：

```bash
streamlit run dashboard.py
```

看板支持：

- 按推荐人筛选。
- 菜单切换日期，查看“当日推荐股票涨跌幅”柱状图。
- 选择统计区间（最近7天、最近30天、自定义），查看区间平均涨跌幅和每日平均明细。

## 输出文件

运行后会在 `output` 目录生成：

- `recommendation_cache.csv`：历史推荐缓存（按 `date+code` 去重，长期累积），由源文本自动解析写入。
- `quote_cache.csv`：核心历史数据表（按 `date+code` 去重），整合推荐信息与行情信息，包含 `recommender`、`theme`、开收盘、收益率、持仓收益等字段。

并在 `output/charts` 目录生成图表：

- `daily_avg_return_trend.png`：每日平均收益率趋势图。
- `theme_avg_return_top10.png`：题材平均收益率 Top10 柱状图。
- `stock_avg_return_top_bottom.png`：个股平均收益率 Top/Bottom 对比图。

## 说明

- 若某天停牌/非交易日，脚本会在 `error` 列记录原因。
- 题材来自源推荐文本，缺失时会记为 `未知题材`。
- 先查 `quote_cache.csv`，只有缓存不存在时才会请求后台行情接口。
