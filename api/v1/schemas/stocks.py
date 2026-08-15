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
    thresholds: Dict[str, float] = Field(default_factory=dict, description="使用的阈值")
    benefit_series: List[Optional[float]] = Field(default_factory=list, description="累计收益率序列")
    benefit_series_by_trigger: Dict[str, List[Optional[float]]] = Field(default_factory=dict, description="各触发器累计收益率序列")
    benefit_by_trigger: Dict[str, float] = Field(default_factory=dict, description="各触发器累计收益率")
    optimization: Optional[Dict[str, Any]] = Field(None, description="阈值调优结果")
