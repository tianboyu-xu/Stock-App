# -*- coding: utf-8 -*-
"""
===================================
股票数据相关模型
===================================

职责：
1. 定义股票实时行情模型
2. 定义历史 K 线数据模型
"""

from typing import Any, Dict, Optional, List

from pydantic import BaseModel, ConfigDict, Field


class StockQuote(BaseModel):
    """股票实时行情"""
    
    stock_code: str = Field(..., description="股票代码")
    stock_name: Optional[str] = Field(None, description="股票名称")
    current_price: float = Field(..., description="当前价格")
    change: Optional[float] = Field(None, description="涨跌额")
    change_percent: Optional[float] = Field(None, description="涨跌幅 (%)")
    open: Optional[float] = Field(None, description="开盘价")
    high: Optional[float] = Field(None, description="最高价")
    low: Optional[float] = Field(None, description="最低价")
    prev_close: Optional[float] = Field(None, description="昨收价")
    volume: Optional[float] = Field(None, description="成交量（股）")
    amount: Optional[float] = Field(None, description="成交额（元）")
    update_time: Optional[str] = Field(None, description="更新时间")
    
    model_config = ConfigDict(json_schema_extra={
        "example": {
            "stock_code": "600519",
            "stock_name": "贵州茅台",
            "current_price": 1800.00,
            "change": 15.00,
            "change_percent": 0.84,
            "open": 1785.00,
            "high": 1810.00,
            "low": 1780.00,
            "prev_close": 1785.00,
            "volume": 10000000,
            "amount": 18000000000,
            "update_time": "2024-01-01T15:00:00"
        }
    })


class KLineData(BaseModel):
    """K 线数据点"""
    
    date: str = Field(..., description="日期")
    open: float = Field(..., description="开盘价")
    high: float = Field(..., description="最高价")
    low: float = Field(..., description="最低价")
    close: float = Field(..., description="收盘价")
    volume: Optional[float] = Field(None, description="成交量")
    amount: Optional[float] = Field(None, description="成交额")
    change_percent: Optional[float] = Field(None, description="涨跌幅 (%)")
    
    model_config = ConfigDict(json_schema_extra={
        "example": {
            "date": "2024-01-01",
            "open": 1785.00,
            "high": 1810.00,
            "low": 1780.00,
            "close": 1800.00,
            "volume": 10000000,
            "amount": 18000000000,
            "change_percent": 0.84
        }
    })


class ExtractItem(BaseModel):
    """单条提取结果（代码、名称、置信度）"""

    code: Optional[str] = Field(None, description="股票代码，None 表示解析失败")
    name: Optional[str] = Field(None, description="股票名称（如有）")
    confidence: str = Field("medium", description="置信度：high/medium/low")


class ExtractFromImageResponse(BaseModel):
    """图片股票代码提取响应"""

    codes: List[str] = Field(..., description="提取的股票代码（已去重，向后兼容）")
    items: List[ExtractItem] = Field(default_factory=list, description="提取结果明细（代码+名称+置信度）")
    raw_text: Optional[str] = Field(None, description="原始 LLM 响应（调试用）")


class StockHistoryResponse(BaseModel):
    """股票历史行情响应"""

    stock_code: str = Field(..., description="股票代码")
    stock_name: Optional[str] = Field(None, description="股票名称")
    period: str = Field(..., description="K 线周期")
    data: List[KLineData] = Field(default_factory=list, description="K 线数据列表")

    model_config = ConfigDict(json_schema_extra={
        "example": {
            "stock_code": "600519",
            "stock_name": "贵州茅台",
            "period": "daily",
            "data": []
        }
    })


class IndicatorTriggers(BaseModel):
    """买卖触发器序列（收盘价或 null）"""

    macd_buy: List[Optional[float]] = Field(default_factory=list)
    macd_sell: List[Optional[float]] = Field(default_factory=list)
    kdj_buy: List[Optional[float]] = Field(default_factory=list)
    kdj_sell: List[Optional[float]] = Field(default_factory=list)
    rsi_buy: List[Optional[float]] = Field(default_factory=list)
    rsi_sell: List[Optional[float]] = Field(default_factory=list)
    obv_buy: List[Optional[float]] = Field(default_factory=list)
    obv_sell: List[Optional[float]] = Field(default_factory=list)
    boll_buy: List[Optional[float]] = Field(default_factory=list)
    boll_sell: List[Optional[float]] = Field(default_factory=list)
    cci_buy: List[Optional[float]] = Field(default_factory=list)
    cci_sell: List[Optional[float]] = Field(default_factory=list)
    dmi_buy: List[Optional[float]] = Field(default_factory=list)
    dmi_sell: List[Optional[float]] = Field(default_factory=list)
    mfi_buy: List[Optional[float]] = Field(default_factory=list)
    mfi_sell: List[Optional[float]] = Field(default_factory=list)


class CompositeBreakdown(BaseModel):
    """复合评分分解（各因子得分）"""

    macd: int = Field(0, description="MACD 因子得分")
    kdj: int = Field(0, description="KDJ 因子得分")
    rsi: int = Field(0, description="RSI 因子得分")
    regime: int = Field(0, description="长期趋势 regime 因子得分")
    momentum: int = Field(0, description="价格动量因子得分")
    boll: int = Field(0, description="BOLL %B 因子得分")
    cci: int = Field(0, description="CCI 因子得分")
    dmi: int = Field(0, description="DMI/ADX 因子得分")
    mfi: int = Field(0, description="MFI 因子得分")
    volume: int = Field(0, description="成交量确认因子得分")
    range52: int = Field(0, description="52 周位置因子得分")


class CompositeSignals(BaseModel):
    """复合 BUY/SELL 评分与信号"""

    buy_score: List[int] = Field(default_factory=list, description="BUY 评分序列（满分 = 经典 10 分 + 启用扩展因子权重和）")
    sell_score: List[int] = Field(default_factory=list, description="SELL 评分序列（满分 = 经典 10 分 + 启用扩展因子权重和）")
    buy_signal: List[Optional[float]] = Field(default_factory=list, description="BUY 信号（收盘价或 null，仅在评分进入阈值区间时触发）")
    sell_signal: List[Optional[float]] = Field(default_factory=list, description="SELL 信号（收盘价或 null，仅在评分进入阈值区间时触发）")
    buy_breakdown: List[CompositeBreakdown] = Field(default_factory=list, description="BUY 评分分解")
    sell_breakdown: List[CompositeBreakdown] = Field(default_factory=list, description="SELL 评分分解")
    max_buy_score: int = Field(10, description="BUY 评分满分（默认扩展因子权重为 0 时为 10）")
    max_sell_score: int = Field(10, description="SELL 评分满分（默认扩展因子权重为 0 时为 10）")


class StockIndicatorsResponse(BaseModel):
    """股票技术指标响应（Excel "300 Plot" 逻辑）"""

    stock_code: str = Field(..., description="股票代码")
    stock_name: Optional[str] = Field(None, description="股票名称")
    period: str = Field(..., description="K 线周期")
    dates: List[str] = Field(default_factory=list, description="日期序列")
    close: List[float] = Field(default_factory=list, description="收盘价序列")
    sma: Dict[str, List[Optional[float]]] = Field(default_factory=dict, description="SMA 序列")
    ema: Dict[str, List[Optional[float]]] = Field(default_factory=dict, description="EMA 序列")
    macd: List[Optional[float]] = Field(default_factory=list, description="MACD")
    macd_signal: List[Optional[float]] = Field(default_factory=list, description="MACD Signal")
    k: List[Optional[float]] = Field(default_factory=list, description="KDJ K")
    d: List[Optional[float]] = Field(default_factory=list, description="KDJ D")
    j: List[Optional[float]] = Field(default_factory=list, description="KDJ J")
    rsi: List[Optional[float]] = Field(default_factory=list, description="RSI(30~70)")
    rsi6: List[Optional[float]] = Field(default_factory=list, description="RSI 6 日均")
    rsi14: List[Optional[float]] = Field(default_factory=list, description="RSI 14 日均")
    bolu: List[Optional[float]] = Field(default_factory=list, description="布林上轨")
    bold: List[Optional[float]] = Field(default_factory=list, description="布林下轨")
    cci: List[Optional[float]] = Field(default_factory=list, description="CCI")
    obv: List[Optional[float]] = Field(default_factory=list, description="OBV")
    obv_ma: Dict[str, List[Optional[float]]] = Field(default_factory=dict, description="OBV 均值")
    triggers: IndicatorTriggers = Field(default_factory=IndicatorTriggers, description="买卖触发器")
    composite: Optional[CompositeSignals] = Field(None, description="复合 BUY/SELL 评分与信号")
    thresholds: Dict[str, float] = Field(default_factory=dict, description="使用的阈值")
    benefit_series_by_trigger: Dict[str, List[Optional[float]]] = Field(default_factory=dict, description="各触发器累计收益率序列")
    benefit_by_trigger: Dict[str, float] = Field(default_factory=dict, description="各触发器累计收益率")


class AutoTuneSegmentMetrics(BaseModel):
    """Auto Tune 单区间回测绩效"""

    total_return_pct: float = Field(0.0, description="区间总收益率 (%)")
    cagr_pct: float = Field(0.0, description="年化复合收益率 (%)")
    after_tax_total_return_pct: float = Field(
        0.0,
        description="税后区间总收益率 (%)，按美国资本利得税近似（短期/长期税率按持仓时长区分）",
    )
    after_tax_cagr_pct: float = Field(
        0.0,
        description="税后年化复合收益率 (%)，按美国资本利得税近似（短期/长期税率按持仓时长区分）",
    )
    max_drawdown_pct: float = Field(0.0, description="最大回撤 (%)，负值")
    sharpe: float = Field(0.0, description="年化 Sharpe 比率")
    sortino: float = Field(0.0, description="年化 Sortino 比率")
    profit_factor: Optional[float] = Field(None, description="盈亏比（无亏损交易时封顶 99）")
    trades: int = Field(0, description="交易次数（一买一卖记 1 次）")
    win_rate_pct: float = Field(0.0, description="胜率 (%)")
    avg_trade_pct: float = Field(0.0, description="平均单笔收益 (%)")
    avg_holding_days: float = Field(0.0, description="平均持仓交易日数")
    exposure_pct: float = Field(0.0, description="持仓时间占比 (%)")
    trades_per_year: float = Field(0.0, description="年均交易次数")


class AutoTuneParams(BaseModel):
    """Auto Tune 策略参数"""

    thresholds: Dict[str, Any] = Field(default_factory=dict, description="复合评分阈值参数")
    stop_multiple_atr: Optional[float] = Field(None, description="ATR 止损倍数（未启用为 null）")
    trail_multiple_atr: Optional[float] = Field(None, description="ATR 移动止盈倍数（未启用为 null）")


class AutoTuneEquitySeries(BaseModel):
    """测试段累计收益序列（相对初始资金，包含首日收益与交易成本）"""

    dates: List[str] = Field(default_factory=list, description="交易日日期 (YYYY-MM-DD)")
    values: List[float] = Field(default_factory=list, description="累计收益 (%)，与 dates 一一对应")


class AutoTuneStrategyResult(BaseModel):
    """单策略代际寻优结果"""

    key: str = Field(..., description="策略标识 (A/B/C/D/E/F)")
    name_zh: str = Field("", description="策略名称（中文）")
    name_en: str = Field("", description="策略名称（英文）")
    description_zh: str = Field("", description="策略说明（中文）")
    description_en: str = Field("", description="策略说明（英文）")
    tuned: bool = Field(False, description="是否参与参数寻优")
    params: AutoTuneParams = Field(default_factory=AutoTuneParams)
    metrics: Dict[str, AutoTuneSegmentMetrics] = Field(
        default_factory=dict,
        description="train/validation/test/train_validation 各区间绩效",
    )
    objectives: Dict[str, float] = Field(default_factory=dict, description="各区间目标函数得分")
    validation_score: Optional[float] = Field(None, description="验证折目标函数中位数减去标准差")
    validation_score_median: Optional[float] = Field(None, description="验证折目标函数中位数")
    validation_score_dispersion: Optional[float] = Field(None, description="验证折目标函数总体标准差")
    validation_positive_folds: Optional[int] = Field(None, description="CAGR 为正的验证折数")
    validation_worst_cagr_pct: Optional[float] = Field(None, description="验证折中最差 CAGR (%)")
    validation_eligible_folds: Optional[int] = Field(None, description="达到最少交易数要求的验证折数")
    validation_folds: List[Dict[str, Any]] = Field(
        default_factory=list, description="按时间推进的训练/验证区间及逐折绩效、目标函数"
    )
    test_confidence: Optional[Dict[str, Any]] = Field(
        None, description="固定策略测试收益的分块重采样 Sharpe 区间；不是未来盈利概率"
    )
    param_robustness: Optional[float] = Field(
        None, description="训练集最优邻域内候选的验证集达标比例（0~1）"
    )
    test_equity: Optional[AutoTuneEquitySeries] = Field(
        None, description="测试段累计收益序列，供前端绘制对比曲线"
    )


class AutoTuneBenchmarkMetrics(BaseModel):
    """基准在单个窗口的绩效（不可用时为 null）"""

    train_validation: Optional[AutoTuneSegmentMetrics] = Field(
        None, description="训练+验证窗口绩效"
    )
    test: Optional[AutoTuneSegmentMetrics] = Field(None, description="测试窗口绩效")


class AutoTuneBenchmark(BaseModel):
    """Auto Tune 对比基准

    - stock_buy_hold：个股买入持有
    - sp500_buy_hold：标普500 买入持有
    - strategy_on_sp500：推荐策略买卖时点套用标普500 价格重放
    """

    key: str = Field(..., description="基准标识")
    name_zh: str = Field("", description="基准名称（中文）")
    name_en: str = Field("", description="基准名称（英文）")
    description_zh: str = Field("", description="基准说明（中文）")
    description_en: str = Field("", description="基准说明（英文）")
    available: bool = Field(False, description="基准数据是否可用")
    metrics: AutoTuneBenchmarkMetrics = Field(
        default_factory=AutoTuneBenchmarkMetrics,
        description="与策略同口径的 训练+验证 / 测试 窗口绩效",
    )
    test_equity: Optional[AutoTuneEquitySeries] = Field(
        None, description="测试段累计收益序列，供前端绘制对比曲线"
    )


class AutoTuneParamDisplay(BaseModel):
    """推荐参数展示项"""

    key: str = Field(..., description="参数键名")
    value: Any = Field(..., description="优化后取值")
    default: Any = Field(None, description="默认取值")


class AutoTuneRecommended(BaseModel):
    """Auto Tune 推荐结果"""

    strategy_key: str = Field(..., description="推荐策略标识")
    reason_code: str = Field(
        ...,
        description="选择原因：baseline_sufficient / best_validation / simplicity_preference",
    )
    eps: float = Field(..., description="简洁性容忍度 EPS_SIMPLICITY")
    thresholds: Dict[str, Any] = Field(default_factory=dict, description="可直接应用到图表的阈值参数")
    risk: Dict[str, Optional[Any]] = Field(
        default_factory=dict,
        description="风控开关与 ATR 倍数（use_trend_filter/use_volume_filter/stop_multiple_atr/trail_multiple_atr）",
    )
    params_display: List[AutoTuneParamDisplay] = Field(
        default_factory=list, description="按展示顺序排列的参数列表"
    )


class AutoTuneResponse(BaseModel):
    """Auto Tune 参数寻优响应

    方法：历史数据 → 训练集寻优 → 验证集选型 → 测试集仅报告，
    目标函数平衡限幅 Sharpe、归一化 CAGR 和最大回撤，跨验证折使用中位数减标准差。
    """

    methodology_version: Optional[int] = Field(
        None, description="寻优与回测口径版本；缺失或旧版本结果需重新运行后才能应用"
    )
    window_days: int = Field(..., description="两次买入之间的最小间隔天数")
    history: Dict[str, Any] = Field(..., description="实际使用的历史数据范围")
    split: Dict[str, Any] = Field(..., description="train/validation/test 区间划分")
    walk_forward: Optional[Dict[str, Any]] = Field(
        None, description="按时间推进的验证折、评分聚合方式及最终参数来源"
    )
    assumptions: Dict[str, Any] = Field(..., description="回测假设（执行价、成本、窗口等）")
    fixed_parameters: Dict[str, Any] = Field(
        ..., description="固定不参与寻优的指标周期参数及原因"
    )
    strategies: List[AutoTuneStrategyResult] = Field(
        default_factory=list, description="各代策略对比结果；测试绩效仅用于选型完成后的报告"
    )
    benchmarks: List[AutoTuneBenchmark] = Field(
        default_factory=list,
        description=(
            "对比基准（个股买入持有 / 标普500 买入持有 / 推荐策略时点套用标普500），"
            "税后口径与策略一致"
        ),
    )
    recommended: AutoTuneRecommended = Field(..., description="最终推荐参数")
    fine_tune: Optional[Dict[str, Any]] = Field(
        default=None,
        description=(
            "Fine Tune 滑动窗口扫描结果（未启用时为 None）；selection_basis=validation，"
            "sweep 使用 validation_* 指标及 validation_score，旧 test_* 字段为 null；"
            "final_test 单独报告最终选中策略的 strategy_key/position_index/metrics/equity"
        )
    )
