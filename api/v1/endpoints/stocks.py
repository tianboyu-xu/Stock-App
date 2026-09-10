# -*- coding: utf-8 -*-
"""
===================================
股票数据接口
===================================

职责：
1. POST /api/v1/stocks/extract-from-image 从图片提取股票代码
2. POST /api/v1/stocks/parse-import 解析 CSV/Excel/剪贴板
3. GET /api/v1/stocks/{code}/quote 实时行情接口
4. GET /api/v1/stocks/{code}/history 历史行情接口
"""

import logging
import json
from typing import Optional
import re

from fastapi import APIRouter, File, HTTPException, Query, Request, UploadFile, Depends

from api.deps import get_system_config_service

from api.v1.schemas.stocks import (
    AutoTuneResponse,
    CompositeSignals,
    ExtractFromImageResponse,
    ExtractItem,
    IndicatorTriggers,
    KLineData,
    StockHistoryResponse,
    StockIndicatorsResponse,
    StockQuote,
)
from api.v1.schemas.history import WatchlistReorderRequest, WatchlistRequest, WatchlistResponse
from api.v1.schemas.common import ErrorResponse
from src.services.image_stock_extractor import (
    ALLOWED_MIME,
    MAX_SIZE_BYTES,
    extract_stock_codes_from_image,
)
from src.services.import_parser import (
    MAX_FILE_BYTES,
    parse_import_from_bytes,
    parse_import_from_text,
)
from src.services.stock_service import StockService
from src.services.stock_list_parser import split_stock_list
from src.services.system_config_service import SystemConfigService
from data_provider.base import normalize_stock_code

logger = logging.getLogger(__name__)

router = APIRouter()

# 须在 /{stock_code} 路由之前定义
ALLOWED_MIME_STR = ", ".join(ALLOWED_MIME)


def _read_watchlist_codes(service: SystemConfigService) -> list:
    """Read STOCK_LIST codes as-is (no normalization)."""
    config_data = service.get_config(include_schema=False)
    stock_list_str = ""
    for item in config_data.get("items", []):
        if item.get("key") == "STOCK_LIST":
            stock_list_str = str(item.get("value", ""))
            break
    return split_stock_list(stock_list_str)


def _write_watchlist_codes(service: SystemConfigService, codes: list) -> None:
    """Persist stock codes to STOCK_LIST as-is (no normalization)."""
    config_data = service.get_config(include_schema=False)
    config_version = config_data.get("config_version", "")
    service.update(
        config_version=config_version,
        items=[{"key": "STOCK_LIST", "value": ",".join(codes)}],
        mask_token="******",
        reload_now=True,
    )


# Stock code validation patterns (aligned with frontend validateStockCode)
_STOCK_CODE_RE = re.compile(
    r"^(?:\d{6}"                              # A-share 6-digit
    r"|(?:SH|SZ|BJ)\d{6}"                     # exchange-prefixed A-share
    r"|\d{6}\.(?:SH|SZ|SS|BJ)"                # exchange-suffixed A-share
    r"|\d{1,5}\.HK"                           # HK suffix format
    r"|HK\d{1,5}"                             # HK prefix format
    r"|\d{5}"                                 # bare 5-digit HK code
    r"|[A-Z]{1,5}(?:\.(?:US|[A-Z]))?"         # US ticker
    r")$",
    re.IGNORECASE,
)


def _validate_and_normalize_stock_code(code: str) -> str:
    """Validate stock code format and return canonical form.

    Raises HTTPException(400) if the code does not match supported formats.
    """
    stripped = code.strip()
    if not stripped:
        raise HTTPException(
            status_code=400,
            detail={"error": "invalid_stock_code", "message": "股票代码不能为空"},
        )
    if not _STOCK_CODE_RE.match(stripped):
        raise HTTPException(
            status_code=400,
            detail={
                "error": "invalid_stock_code",
                "message": f"'{stripped}' 不是合法的股票代码格式",
            },
        )
    return normalize_stock_code(stripped)


def _watchlist_match_key(code: str) -> str:
    """Return the equivalence key used for watchlist add/remove matching."""
    normalized = normalize_stock_code(code.strip())
    if re.fullmatch(r"\d{5}", normalized):
        return f"HK{normalized}"
    return normalized.upper()


@router.post(
    "/extract-from-image",
    response_model=ExtractFromImageResponse,
    responses={
        200: {"description": "提取的股票代码"},
        400: {"description": "图片无效", "model": ErrorResponse},
        500: {"description": "服务器错误", "model": ErrorResponse},
    },
    summary="从图片提取股票代码",
    description="上传截图/图片，通过 Vision LLM 提取股票代码。支持 JPEG、PNG、WebP、GIF，最大 5MB。",
)
def extract_from_image(
    file: Optional[UploadFile] = File(None, description="图片文件（表单字段名 file）"),
    include_raw: bool = Query(False, description="是否在结果中包含原始 LLM 响应"),
) -> ExtractFromImageResponse:
    """
    从上传的图片中提取股票代码（使用 Vision LLM）。

    表单字段请使用 file 上传图片。优先级：Gemini / Anthropic / OpenAI（首个可用）。
    """
    if not file or not file.filename:
        raise HTTPException(
            status_code=400,
            detail={"error": "bad_request", "message": "未提供文件，请使用表单字段 file 上传图片"},
        )

    content_type = (file.content_type or "").split(";")[0].strip().lower()
    if content_type not in ALLOWED_MIME:
        raise HTTPException(
            status_code=400,
            detail={
                "error": "unsupported_type",
                "message": f"不支持的类型: {content_type}。允许: {ALLOWED_MIME_STR}",
            },
        )

    try:
        # 先读取限定大小，再检查是否还有剩余（语义清晰：超出则拒绝）
        data = file.file.read(MAX_SIZE_BYTES)
        if file.file.read(1):
            raise HTTPException(
                status_code=400,
                detail={
                    "error": "file_too_large",
                    "message": f"图片超过 {MAX_SIZE_BYTES // (1024 * 1024)}MB 限制",
                },
            )
    except HTTPException:
        raise
    except Exception as e:
        logger.warning(f"读取上传文件失败: {e}")
        raise HTTPException(
            status_code=400,
            detail={"error": "read_failed", "message": "读取上传文件失败"},
        )

    try:
        items, raw_text = extract_stock_codes_from_image(data, content_type)
        extract_items = [
            ExtractItem(code=code, name=name, confidence=conf) for code, name, conf in items
        ]
        codes = [i.code for i in extract_items]
        return ExtractFromImageResponse(
            codes=codes,
            items=extract_items,
            raw_text=raw_text if include_raw else None,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail={"error": "extract_failed", "message": str(e)})
    except Exception as e:
        logger.error(f"图片提取失败: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail={"error": "internal_error", "message": "图片提取失败"},
        )


@router.post(
    "/parse-import",
    response_model=ExtractFromImageResponse,
    responses={
        200: {"description": "解析结果"},
        400: {"description": "未提供数据或解析失败", "model": ErrorResponse},
        500: {"description": "服务器错误", "model": ErrorResponse},
    },
    summary="解析 CSV/Excel/剪贴板",
    description="上传 CSV/Excel 文件或粘贴文本，自动解析股票代码。文件上限 2MB，文本上限 100KB。",
)
async def parse_import(request: Request) -> ExtractFromImageResponse:
    """
    解析 CSV/Excel 文件或剪贴板文本。

    - multipart/form-data + file: 上传文件
    - application/json + {"text": "..."}: 粘贴文本
    - 优先使用 file，若同时提供则忽略 text
    """
    content_type = (request.headers.get("content-type") or "").lower()

    if "application/json" in content_type:
        try:
            body = await request.json()
        except Exception as e:
            logger.warning("[parse_import] JSON parse failed: %s", e)
            raise HTTPException(
                status_code=400,
                detail={"error": "invalid_json", "message": f"JSON 解析失败: {e}"},
            )
        text = body.get("text") if isinstance(body, dict) else None
        if not text or not isinstance(text, str):
            raise HTTPException(
                status_code=400,
                detail={"error": "bad_request", "message": "未提供 text，请使用 {\"text\": \"...\"}"},
            )
        try:
            items = parse_import_from_text(text)
        except ValueError as e:
            text_bytes = len(text.encode("utf-8"))
            logger.warning(
                "[parse_import] parse_import_from_text failed: text_bytes=%d, error=%s",
                text_bytes,
                e,
            )
            raise HTTPException(status_code=400, detail={"error": "parse_failed", "message": str(e)})
    elif "multipart" in content_type:
        form = await request.form()
        file = form.get("file")
        if not file or not hasattr(file, "read"):
            raise HTTPException(
                status_code=400,
                detail={"error": "bad_request", "message": "未提供文件，请使用表单字段 file"},
            )
        file_size = getattr(file, "size", None)
        if isinstance(file_size, int) and file_size > MAX_FILE_BYTES:
            raise HTTPException(
                status_code=400,
                detail={
                    "error": "file_too_large",
                    "message": f"文件超过 {MAX_FILE_BYTES // (1024 * 1024)}MB 限制",
                },
            )
        try:
            data = file.file.read(MAX_FILE_BYTES)
            if file.file.read(1):
                raise HTTPException(
                    status_code=400,
                    detail={
                        "error": "file_too_large",
                        "message": f"文件超过 {MAX_FILE_BYTES // (1024 * 1024)}MB 限制",
                    },
                )
        except HTTPException:
            raise
        except Exception as e:
            filename = getattr(file, "filename", None) or ""
            size = getattr(file, "size", None)
            logger.warning(
                "[parse_import] file read failed: filename=%r, size=%s, error=%s",
                filename,
                size,
                e,
            )
            raise HTTPException(
                status_code=400,
                detail={"error": "read_failed", "message": "读取文件失败"},
            )
        filename = getattr(file, "filename", None) or ""
        try:
            items = parse_import_from_bytes(data, filename=filename)
        except ValueError as e:
            ext = "." + filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
            logger.warning(
                "[parse_import] parse_import_from_bytes failed: filename=%r, ext=%r, bytes=%d, error=%s",
                filename,
                ext,
                len(data),
                e,
            )
            raise HTTPException(status_code=400, detail={"error": "parse_failed", "message": str(e)})
    else:
        raise HTTPException(
            status_code=400,
            detail={
                "error": "bad_request",
                "message": "请使用 multipart/form-data 上传文件，或 application/json 提交 {\"text\": \"...\"}",
            },
        )

    extract_items = [
        ExtractItem(code=code, name=name, confidence=conf)
        for code, name, conf in items
    ]
    codes = list(dict.fromkeys(i.code for i in extract_items if i.code))
    return ExtractFromImageResponse(codes=codes, items=extract_items, raw_text=None)


@router.get(
    "/watchlist",
    response_model=WatchlistResponse,
    responses={
        200: {"description": "当前自选队列"},
        500: {"description": "服务器错误", "model": ErrorResponse},
    },
    summary="获取自选队列",
    description="返回当前 STOCK_LIST 配置中的所有股票代码。",
)
def get_watchlist(
    service: SystemConfigService = Depends(get_system_config_service),
) -> WatchlistResponse:
    try:
        codes = _read_watchlist_codes(service)
        return WatchlistResponse(stock_codes=codes, message=f"当前自选 {len(codes)} 只股票")
    except Exception as e:
        logger.error(f"获取自选队列失败: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail={"error": "internal_error", "message": f"获取自选队列失败: {str(e)}"},
        )


@router.post(
    "/watchlist/add",
    response_model=WatchlistResponse,
    responses={
        200: {"description": "已加入自选"},
        400: {"description": "参数错误", "model": ErrorResponse},
        500: {"description": "服务器错误", "model": ErrorResponse},
    },
    summary="加入自选队列",
    description="将指定股票代码加入 STOCK_LIST。",
)
def add_to_watchlist(
    request: WatchlistRequest,
    service: SystemConfigService = Depends(get_system_config_service),
) -> WatchlistResponse:
    try:
        validated = _validate_and_normalize_stock_code(request.stock_code)
        codes = _read_watchlist_codes(service)
        existing_keys = [_watchlist_match_key(c) for c in codes]
        if _watchlist_match_key(validated) not in existing_keys:
            codes.append(request.stock_code.strip())
            _write_watchlist_codes(service, codes)
        return WatchlistResponse(stock_codes=codes, message=f"已加入 {request.stock_code.strip()}")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"加入自选失败: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail={"error": "internal_error", "message": f"加入自选失败: {str(e)}"},
        )


@router.post(
    "/watchlist/remove",
    response_model=WatchlistResponse,
    responses={
        200: {"description": "已从自选删除"},
        400: {"description": "参数错误", "model": ErrorResponse},
        500: {"description": "服务器错误", "model": ErrorResponse},
    },
    summary="从自选队列删除",
    description="从 STOCK_LIST 中移除指定股票代码。",
)
def remove_from_watchlist(
    request: WatchlistRequest,
    service: SystemConfigService = Depends(get_system_config_service),
) -> WatchlistResponse:
    try:
        validated = _validate_and_normalize_stock_code(request.stock_code)
        codes = _read_watchlist_codes(service)
        existing_keys = [_watchlist_match_key(c) for c in codes]
        requested_key = _watchlist_match_key(validated)
        if requested_key in existing_keys:
            idx = existing_keys.index(requested_key)
            codes.pop(idx)
            _write_watchlist_codes(service, codes)
        return WatchlistResponse(stock_codes=codes, message=f"已移除 {request.stock_code.strip()}")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"从自选删除失败: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail={"error": "internal_error", "message": f"从自选删除失败: {str(e)}"},
        )


@router.post(
    "/watchlist/reorder",
    response_model=WatchlistResponse,
    responses={
        200: {"description": "已重排自选队列"},
        400: {"description": "参数错误", "model": ErrorResponse},
        500: {"description": "服务器错误", "model": ErrorResponse},
    },
    summary="重排自选队列",
    description="按请求顺序重排 STOCK_LIST；重复代码去重、未知代码忽略，未提及的现有代码追加到末尾。",
)
def reorder_watchlist(
    request: WatchlistReorderRequest,
    service: SystemConfigService = Depends(get_system_config_service),
) -> WatchlistResponse:
    try:
        existing = _read_watchlist_codes(service)
        existing_keys = [_watchlist_match_key(c) for c in existing]
        ordered: list = []
        seen_keys = set()
        for raw in request.stock_codes:
            stripped = raw.strip()
            if not stripped:
                continue
            key = _watchlist_match_key(stripped)
            if key in seen_keys:
                continue
            if key in existing_keys:
                ordered.append(existing[existing_keys.index(key)])
                seen_keys.add(key)
        for code in existing:
            key = _watchlist_match_key(code)
            if key not in seen_keys:
                ordered.append(code)
                seen_keys.add(key)
        _write_watchlist_codes(service, ordered)
        return WatchlistResponse(stock_codes=ordered, message="已重排自选队列")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"重排自选失败: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail={"error": "internal_error", "message": f"重排自选失败: {str(e)}"},
        )


@router.get(
    "/{stock_code}/quote",
    response_model=StockQuote,
    responses={
        200: {"description": "行情数据"},
        404: {"description": "股票不存在", "model": ErrorResponse},
        500: {"description": "服务器错误", "model": ErrorResponse},
    },
    summary="获取股票实时行情",
    description="获取指定股票的最新行情数据"
)
def get_stock_quote(stock_code: str) -> StockQuote:
    """
    获取股票实时行情
    
    获取指定股票的最新行情数据
    
    Args:
        stock_code: 股票代码（如 600519、00700、AAPL）
        
    Returns:
        StockQuote: 实时行情数据
        
    Raises:
        HTTPException: 404 - 股票不存在
    """
    try:
        service = StockService()
        
        # 使用 def 而非 async def，FastAPI 自动在线程池中执行
        result = service.get_realtime_quote(stock_code)
        
        if result is None:
            raise HTTPException(
                status_code=404,
                detail={
                    "error": "not_found",
                    "message": f"未找到股票 {stock_code} 的行情数据"
                }
            )
        
        return StockQuote(
            stock_code=result.get("stock_code", stock_code),
            stock_name=result.get("stock_name"),
            current_price=result.get("current_price", 0.0),
            change=result.get("change"),
            change_percent=result.get("change_percent"),
            open=result.get("open"),
            high=result.get("high"),
            low=result.get("low"),
            prev_close=result.get("prev_close"),
            volume=result.get("volume"),
            amount=result.get("amount"),
            update_time=result.get("update_time")
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取实时行情失败: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail={
                "error": "internal_error",
                "message": f"获取实时行情失败: {str(e)}"
            }
        )


@router.get(
    "/{stock_code}/history",
    response_model=StockHistoryResponse,
    responses={
        200: {"description": "历史行情数据"},
        422: {"description": "不支持的周期参数", "model": ErrorResponse},
        500: {"description": "服务器错误", "model": ErrorResponse},
    },
    summary="获取股票历史行情",
    description="获取指定股票的历史 K 线数据"
)
def get_stock_history(
    stock_code: str,
    period: str = Query("daily", description="K 线周期", pattern="^(daily|weekly|monthly)$"),
    days: int = Query(30, ge=1, le=365, description="获取天数")
) -> StockHistoryResponse:
    """
    获取股票历史行情
    
    获取指定股票的历史 K 线数据
    
    Args:
        stock_code: 股票代码
        period: K 线周期 (daily/weekly/monthly)
        days: 获取天数
        
    Returns:
        StockHistoryResponse: 历史行情数据
    """
    try:
        service = StockService()
        
        # 使用 def 而非 async def，FastAPI 自动在线程池中执行
        result = service.get_history_data(
            stock_code=stock_code,
            period=period,
            days=days
        )
        
        # 转换为响应模型
        data = [
            KLineData(
                date=item.get("date"),
                open=item.get("open"),
                high=item.get("high"),
                low=item.get("low"),
                close=item.get("close"),
                volume=item.get("volume"),
                amount=item.get("amount"),
                change_percent=item.get("change_percent")
            )
            for item in result.get("data", [])
        ]
        
        return StockHistoryResponse(
            stock_code=stock_code,
            stock_name=result.get("stock_name"),
            period=period,
            data=data
        )
    
    except ValueError as e:
        # period 参数不支持的错误（如 weekly/monthly）
        raise HTTPException(
            status_code=422,
            detail={
                "error": "unsupported_period",
                "message": str(e)
            }
        )
    except Exception as e:
        logger.error(f"获取历史行情失败: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail={
                "error": "internal_error",
                "message": f"获取历史行情失败: {str(e)}"
            }
        )


@router.get(
    "/{stock_code}/indicators",
    response_model=StockIndicatorsResponse,
    responses={
        200: {"description": "技术指标数据"},
        422: {"description": "不支持的周期参数", "model": ErrorResponse},
        500: {"description": "服务器错误", "model": ErrorResponse},
    },
    summary="获取股票技术指标",
    description="按 Excel \"300 Plot\" 逻辑计算 SMA/EMA/MACD/KDJ/RSI/BOLL/CCI/OBV 及买卖触发器",
)
def get_stock_indicators(
    stock_code: str,
    period: str = Query("daily", description="K 线周期", pattern="^(daily|weekly|monthly)$"),
    days: int = Query(365, ge=7, le=1825, description="获取天数（最多 5 年）"),
    bol_constant: Optional[float] = Query(None, description="BOL constant 阈值"),
    macd_buy: Optional[float] = Query(None, description="MACD Buy 阈值"),
    macd_sell: Optional[float] = Query(None, description="MACD Sell 阈值"),
    kdj_buy: Optional[float] = Query(None, description="KDJ Buy 阈值"),
    kdj_sell: Optional[float] = Query(None, description="KDJ Sell 阈值"),
    rsi_buy: Optional[float] = Query(None, description="RSI Buy 阈值"),
    rsi_sell: Optional[float] = Query(None, description="RSI Sell 阈值"),
    composite_buy_threshold: Optional[float] = Query(None, description="复合 BUY 评分触发阈值"),
    composite_sell_threshold: Optional[float] = Query(None, description="复合 SELL 评分触发阈值"),
    macd_lookback: Optional[float] = Query(None, description="MACD 百分位回看窗口"),
    macd_low_percentile: Optional[float] = Query(None, description="MACD 低位百分位阈值"),
    macd_high_percentile: Optional[float] = Query(None, description="MACD 高位百分位阈值"),
    rsi_low: Optional[float] = Query(None, description="RSI 超卖阈值"),
    rsi_high: Optional[float] = Query(None, description="RSI 超买阈值"),
    kdj_low: Optional[float] = Query(None, description="KDJ 超卖阈值（复合评分用）"),
    kdj_high: Optional[float] = Query(None, description="KDJ 超买阈值（复合评分用）"),
    trend_period: Optional[float] = Query(None, description="长期趋势均线周期"),
    boll_buy_level: Optional[float] = Query(None, description="BOLL %B 向上穿越的看多水平"),
    boll_sell_level: Optional[float] = Query(None, description="BOLL %B 向下穿越的看空水平"),
    boll_weight: Optional[float] = Query(None, description="BOLL %B 因子权重（0 为禁用）"),
    cci_buy_level: Optional[float] = Query(None, description="CCI 向上穿越的看多水平"),
    cci_sell_level: Optional[float] = Query(None, description="CCI 向下穿越的看空水平"),
    cci_weight: Optional[float] = Query(None, description="CCI 因子权重（0 为禁用）"),
    adx_min_level: Optional[float] = Query(None, description="DMI 触发要求的 ADX 趋势强度下限"),
    dmi_weight: Optional[float] = Query(None, description="DMI 因子权重（0 为禁用）"),
    mfi_buy_level: Optional[float] = Query(None, description="MFI 向上穿越的看多水平"),
    mfi_sell_level: Optional[float] = Query(None, description="MFI 向下穿越的看空水平"),
    mfi_weight: Optional[float] = Query(None, description="MFI 因子权重（0 为禁用）"),
    volume_confirm_level: Optional[float] = Query(None, description="量能确认：volume/SMA20(volume) 下限"),
    volume_weight: Optional[float] = Query(None, description="量能确认因子权重（0 为禁用）"),
    range52_high_level: Optional[float] = Query(None, description="52 周位置：close/252 日最高 的看多水平"),
    range52_low_level: Optional[float] = Query(None, description="52 周位置：close/252 日最低 的看空水平"),
    range52_weight: Optional[float] = Query(None, description="52 周位置因子权重（0 为禁用）"),
    transaction_window: int = Query(7, ge=1, le=365, description="交易窗口天数"),
) -> StockIndicatorsResponse:
    """
    获取股票技术指标

    获取指定股票的历史 K 线并按 Excel "300 Plot" 逻辑计算技术指标。

    Args:
        stock_code: 股票代码
        period: K 线周期 (daily/weekly/monthly)
        days: 获取天数（指标需要较长窗口，默认 365）
        其余: 可选阈值覆盖

    Returns:
        StockIndicatorsResponse: 技术指标数据
    """
    try:
        service = StockService()
        # Fetch extra history so long-window indicators (SMA200 needs 200 points)
        # are computed for the entire visible range, not just the tail.
        # Ensure we fetch at least 400 days (200 for SMA200 + 200 display buffer)
        # regardless of the requested display days.
        warmup_days = max(days + 200, 400)
        result = service.get_history_data(
            stock_code=stock_code,
            period=period,
            days=warmup_days,
        )

        from src.services.indicator_service import (
            DEFAULT_THRESHOLDS,
            compute_indicators,
        )

        overrides = {
            "bol_constant": bol_constant,
            "macd_buy": macd_buy,
            "macd_sell": macd_sell,
            "kdj_buy": kdj_buy,
            "kdj_sell": kdj_sell,
            "rsi_buy": rsi_buy,
            "rsi_sell": rsi_sell,
            "composite_buy_threshold": composite_buy_threshold,
            "composite_sell_threshold": composite_sell_threshold,
            "macd_lookback": macd_lookback,
            "macd_low_percentile": macd_low_percentile,
            "macd_high_percentile": macd_high_percentile,
            "rsi_low": rsi_low,
            "rsi_high": rsi_high,
            "kdj_low": kdj_low,
            "kdj_high": kdj_high,
            "trend_period": trend_period,
            "boll_buy_level": boll_buy_level,
            "boll_sell_level": boll_sell_level,
            "boll_weight": boll_weight,
            "cci_buy_level": cci_buy_level,
            "cci_sell_level": cci_sell_level,
            "cci_weight": cci_weight,
            "adx_min_level": adx_min_level,
            "dmi_weight": dmi_weight,
            "mfi_buy_level": mfi_buy_level,
            "mfi_sell_level": mfi_sell_level,
            "mfi_weight": mfi_weight,
            "volume_confirm_level": volume_confirm_level,
            "volume_weight": volume_weight,
            "range52_high_level": range52_high_level,
            "range52_low_level": range52_low_level,
            "range52_weight": range52_weight,
        }
        thresholds = dict(DEFAULT_THRESHOLDS)
        for key, value in overrides.items():
            if value is not None:
                thresholds[key] = float(value)

        bars = result.get("data", [])
        computed = compute_indicators(bars, thresholds)

        from src.services.indicator_optimizer import calculate_trigger_benefits
        trigger_benefits = calculate_trigger_benefits(computed, transaction_window)

        if len(computed["dates"]) > days:
            visible_start = len(computed["dates"]) - days
        else:
            visible_start = 0

        visible_start = max(0, len(computed["dates"]) - days)
        def trim_series(value):
            if isinstance(value, dict):
                return {key: trim_series(item) for key, item in value.items()}
            if isinstance(value, list):
                return value[visible_start:]
            return value

        return StockIndicatorsResponse(
            stock_code=stock_code,
            stock_name=result.get("stock_name"),
            period=period,
            dates=trim_series(computed["dates"]),
            close=trim_series(computed["close"]),
            sma=trim_series(computed["sma"]),
            ema=trim_series(computed["ema"]),
            macd=trim_series(computed["macd"]),
            macd_signal=trim_series(computed["macd_signal"]),
            k=trim_series(computed["k"]),
            d=trim_series(computed["d"]),
            j=trim_series(computed["j"]),
            rsi=trim_series(computed["rsi"]),
            rsi6=trim_series(computed["rsi6"]),
            rsi14=trim_series(computed["rsi14"]),
            bolu=trim_series(computed["bolu"]),
            bold=trim_series(computed["bold"]),
            cci=trim_series(computed["cci"]),
            obv=trim_series(computed["obv"]),
            obv_ma=trim_series(computed["obv_ma"]),
            triggers=IndicatorTriggers(**trim_series(computed["triggers"])),
            composite=CompositeSignals(**trim_series(computed["composite"])),
            thresholds=thresholds,
            benefit_series_by_trigger={
                key: value["benefit_series"][visible_start:]
                for key, value in trigger_benefits.items()
            },
            benefit_by_trigger={
                key: value["accumulated_benefit_pct"]
                for key, value in trigger_benefits.items()
            },
        )

    except ValueError as e:
        raise HTTPException(
            status_code=422,
            detail={
                "error": "unsupported_period",
                "message": str(e)
            }
        )
    except Exception as e:
        logger.error(f"获取技术指标失败: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail={
                "error": "internal_error",
                "message": f"获取技术指标失败: {str(e)}"
            }
        )


@router.get(
    "/{stock_code}/auto-tune",
    response_model=AutoTuneResponse,
    responses={
        200: {"description": "Auto Tune 参数寻优结果"},
        422: {"description": "历史数据不足", "model": ErrorResponse},
        500: {"description": "服务器错误", "model": ErrorResponse},
    },
    summary="Auto Tune 参数寻优",
    description=(
        "基于最多 20 年日线历史，对复合评分阈值做多代际（A 基线 / B 趋势过滤 / "
        "C ATR 风控 / D 归一化评分 / E 多因子评分 / F 多因子+风控）训练/验证/测试寻优，"
        "测试段长度可选（1-5 年，默认 5 年），训练段范围可用日期裁剪，"
        "目标函数平衡收益、回撤、Sharpe、交易质量与信号频率，"
        "推荐参数可直接应用到图表指标。"
        "附三个同窗口基准（标普500 买入持有 / 个股买入持有 / "
        "推荐策略时点套用标普500）；税后指标按美国资本利得税近似，"
        "税率按持仓时长区分短期/长期（默认按家庭应税收入约 40 万美元档）。"
    ),
)
def auto_tune_stock(
    stock_code: str,
    window_days: int = Query(90, ge=10, le=365, description="两次买入之间的最小间隔天数"),
    years: float = Query(10.0, ge=3.0, le=20.0, description="回测历史年数"),
    test_years: float = Query(3.0, ge=1.0, le=5.0, description="样本外测试段年数（从历史尾部预留）"),
    train_start_date: Optional[str] = Query(None, pattern=r"^\d{4}-\d{2}-\d{2}$", description="训练段起始日期（可选裁剪）"),
    train_end_date: Optional[str] = Query(None, pattern=r"^\d{4}-\d{2}-\d{2}$", description="训练段结束日期（可选裁剪）"),
    fine_tune_window_days: Optional[int] = Query(None, ge=60, le=3000, description="Fine Tune 滑动训练窗口天数（可选）"),
    allocation_config: Optional[str] = Query(None, max_length=4096, description="资金配置设置 JSON，见 Auto Tune 文档"),
    aces_config: Optional[str] = Query(None, max_length=8192, description="Strategy G ACES versioned configuration JSON; omitted means disabled"),
) -> AutoTuneResponse:
    """
    Auto Tune 参数寻优

    流程：历史数据 -> 滚动训练/验证 -> 冻结普通与 Fine Tune 选择 -> 测试集仅报告，
    避免用测试期选择参数，也避免只按历史收益最大化选参。
    测试段长度由 test_years 指定（默认 3 年），训练/验证在剩余
    历史按 60:20 相对比例划分；train_start_date/train_end_date
    可选，用于把训练段裁剪到指定日期范围。
    附三个同窗口基准（标普500 买入持有 / 个股买入持有 /
    推荐策略时点套用标普500），税后指标按美国资本利得税近似
    （短期/长期税率按持仓时长区分）。

    Args:
        stock_code: 股票代码
        window_days: 两次买入之间的最小间隔天数（默认 90）
        years: 回测历史年数（默认 10 年，最多 20 年）
        test_years: 样本外测试段年数（默认 3 年）
        train_start_date: 训练段起始日期（可选）
        train_end_date: 训练段结束日期（可选）
        fine_tune_window_days: Fine Tune 滑动训练窗口天数（可选）

    Returns:
        AutoTuneResponse: 六代策略对比（A–F）、基准对比与推荐参数
    """
    try:
        from src.services.allocation.research import AllocationConfig
        from src.services.allocation.economic_reward import BenchmarkDataMissing
        config_values = json.loads(allocation_config) if allocation_config else {}
        if not isinstance(config_values, dict):
            raise ValueError("allocation_config must be a JSON object")
        AllocationConfig.from_dict(config_values)
    except (ValueError, TypeError) as error:
        raise HTTPException(status_code=422, detail={"error": "invalid_allocation_config", "message": str(error)})
    try:
        from src.services.aces.config import ACESConfig
        aces_values = json.loads(aces_config) if aces_config else None
        if aces_values is not None:
            ACESConfig.from_dict(aces_values)
    except (ValueError, TypeError) as error:
        raise HTTPException(status_code=422, detail={"error": "invalid_aces_config", "message": str(error)})
    try:
        service = StockService()
        # get_daily_data(days=N) 的 N 约为交易日数的一半（内部换算日历区间），
        # 因此取 years*365/2 + 30 以覆盖完整历史。
        fetch_days = int(years * 365 / 2) + 30
        result = service.get_history_data(
            stock_code=stock_code,
            period="daily",
            days=fetch_days,
        )

        bars = result.get("data", [])
        from src.services.allocation.economic_reward import BenchmarkSeries
        from data_provider.us_index_mapping import is_us_stock_code
        from src.config import get_config
        economic_values = config_values.setdefault("economic", {})
        economic_values.setdefault("allowed_max_drawdown", min(1., get_config().portfolio_risk_drawdown_alert_pct / 100))
        if aces_values is not None:
            aces_values.setdefault("allocation", {}).setdefault("economic", {}).setdefault(
                "allowed_max_drawdown", min(1., get_config().portfolio_risk_drawdown_alert_pct / 100))
        allocation_benchmark = None
        # Total-return economics require verified adjusted prices and matching US
        # session closes on both sides. Never substitute the ^GSPC price index.
        if is_us_stock_code(stock_code) and result.get("price_basis") == "ADJUSTED_TOTAL_RETURN":
            adjusted = service.get_history_data(stock_code="SPY", period="daily", days=fetch_days)
            if adjusted.get("price_basis") == "ADJUSTED_TOTAL_RETURN":
                allocation_benchmark = BenchmarkSeries(
                    {bar["date"]: bar["close"] for bar in adjusted.get("data", [])}, adjusted=True)
        from src.services.indicator_optimizer import (
            BENCHMARK_INDEX_CODE,
            run_auto_tune,
        )
        # 标普500 基准数据 best-effort 获取，缺失时对应基准标记为不可用
        try:
            bench_result = service.get_history_data(
                stock_code=BENCHMARK_INDEX_CODE,
                period="daily",
                days=fetch_days,
            )
            benchmark_bars = bench_result.get("data", [])
            if len(benchmark_bars) < 100:
                benchmark_bars = None
        except Exception as e:
            logger.warning(f"获取标普500 基准数据失败，跳过相关基准: {e}")
            benchmark_bars = None

        report = run_auto_tune(
            bars,
            window_days=window_days,
            history_years=years,
            benchmark_bars=benchmark_bars,
            test_years=test_years,
            train_start_date=train_start_date,
            train_end_date=train_end_date,
            fine_tune_window_days=fine_tune_window_days,
            allocation_config=config_values,
            allocation_benchmark=allocation_benchmark,
            aces_config=aces_values,
            aces_metadata={"ticker": stock_code, "provider": result.get("source"),
                           "adjustment_mode": result.get("price_basis")},
        )
        return AutoTuneResponse(**report)

    except BenchmarkDataMissing as e:
        raise HTTPException(status_code=422, detail={"error": "BENCHMARK_DATA_MISSING", "message": str(e)})
    except ValueError as e:
        raise HTTPException(
            status_code=422,
            detail={
                "error": "insufficient_history",
                "message": str(e)
            }
        )
    except Exception as e:
        logger.error(f"Auto Tune 失败: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail={
                "error": "internal_error",
                "message": f"Auto Tune 失败: {str(e)}"
            }
        )
