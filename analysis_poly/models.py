from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from .storage_paths import default_reports_dir


class RunStatus(str, Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    STOPPING = "STOPPING"
    COMPLETED = "COMPLETED"
    STOPPED = "STOPPED"
    FAILED = "FAILED"


class AnalysisRequest(BaseModel):
    address: str
    start_ts: int
    end_ts: int
    symbols: list[Literal["btc", "eth", "sol", "xrp"]]
    intervals: list[int]
    fee_rate_bps: float = 1000
    maker_reward_ratio: float = 0.0
    missing_cost_warn_qty: float = 0.5
    page_limit: int = 1000
    concurrency: int = 5
    request_timeout_sec: float = 20
    output_dir: str = Field(default_factory=lambda: str(default_reports_dir()))

    @field_validator("address")
    @classmethod
    def validate_address(cls, value: str) -> str:
        lowered = value.lower().strip()
        if not lowered.startswith("0x"):
            raise ValueError("address must start with 0x")
        return lowered

    @field_validator("symbols")
    @classmethod
    def validate_symbols(cls, value: list[str]) -> list[str]:
        if not value:
            raise ValueError("symbols cannot be empty")
        uniq = sorted(set(value))
        return uniq

    @field_validator("intervals")
    @classmethod
    def validate_intervals(cls, value: list[int]) -> list[int]:
        if not value:
            raise ValueError("intervals cannot be empty")
        if any(v <= 0 for v in value):
            raise ValueError("intervals must be > 0")
        return sorted(set(value))

    @model_validator(mode="after")
    def validate_time_range(self) -> "AnalysisRequest":
        if self.start_ts >= self.end_ts:
            raise ValueError("start_ts must be smaller than end_ts")
        return self


class RunCreated(BaseModel):
    run_id: str
    status: RunStatus


class RunStopAck(BaseModel):
    run_id: str
    status: RunStatus


class RunState(BaseModel):
    run_id: str
    status: RunStatus
    started_at: datetime | None = None
    ended_at: datetime | None = None
    progress_current: int = 0
    progress_total: int = 0
    message: str = ""


class WarningItem(BaseModel):
    timestamp: int | None = None
    market_slug: str | None = None
    token_id: str | None = None
    code: str
    message: str


class CurvePoint(BaseModel):
    timestamp: int
    delta_realized_pnl_usdc: float
    cumulative_realized_pnl_usdc: float


class PnlTurnoverPoint(BaseModel):
    timestamp: int
    cumulative_turnover_usdc: float
    cumulative_realized_pnl_usdc: float
    cumulative_realized_pnl_usdc_no_fee: float


class TokenReport(BaseModel):
    token_id: str
    side: Literal["YES", "NO"]
    outcome: str
    realized_pnl_usdc: float = 0
    taker_fee_usdc: float = 0
    maker_reward_usdc: float = 0
    buy_qty: float = 0
    sell_qty: float = 0
    split_qty: float = 0
    redeem_qty: float = 0
    ending_position_qty: float = 0
    trade_count: int = 0


class MarketReport(BaseModel):
    market_slug: str
    condition_id: str
    up_token_id: str
    down_token_id: str
    yes_outcome_label: str = "Yes"
    no_outcome_label: str = "No"
    realized_pnl_usdc: float = 0
    taker_fee_usdc: float = 0
    maker_reward_usdc: float = 0
    ending_position_up: float = 0
    ending_position_down: float = 0
    tokens: list[TokenReport] = Field(default_factory=list)


class SummaryStats(BaseModel):
    total_realized_pnl_usdc: float = 0
    total_taker_fee_usdc: float = 0
    total_maker_reward_usdc: float = 0
    markets_total: int = 0
    markets_processed: int = 0


class MarketScatterPoint(BaseModel):
    """Per-market avg buy (VWAP) vs realized return on buy notional."""

    market_slug: str
    avg_entry_price: float
    realized_pnl_usdc: float
    return_on_cost_pct: float
    buy_notional_usdc: float


class TradeSession(BaseModel):
    market_slug: str
    start_timestamp: int
    end_timestamp: int
    entry_side: Literal["YES", "NO"] | None = None
    entry_outcome: str | None = None
    open_timestamp: int | None = None
    open_hour_utc: int | None = None
    open_avg_price: float | None = None
    open_notional_usdc: float = 0
    open_qty: float = 0
    close_avg_price: float | None = None
    close_notional_usdc: float = 0
    close_qty: float = 0
    peak_position_notional_usdc: float = 0
    realized_pnl_usdc: float = 0
    return_on_open_notional_pct: float | None = None
    event_count: int = 0
    has_trade_entry: bool = False
    is_chart_eligible: bool = False
    exclusion_reason: str | None = None
    warning_codes: list[str] = Field(default_factory=list)


class SessionOpenHourBucket(BaseModel):
    hour_utc: int
    session_count: int = 0
    weighted_return_on_open_notional_pct: float = 0
    average_return_on_open_notional_pct: float = 0
    win_rate_pct: float = 0
    sum_realized_pnl_usdc: float = 0
    sum_open_notional_usdc: float = 0


class SessionOpenPriceBucket(BaseModel):
    bin_index: int
    bin_start_price: float
    bin_end_price: float
    session_count: int = 0
    weighted_return_on_open_notional_pct: float = 0
    average_return_on_open_notional_pct: float = 0
    win_rate_pct: float = 0
    sum_realized_pnl_usdc: float = 0
    sum_open_notional_usdc: float = 0


class SessionPeakNotionalBucket(BaseModel):
    bin_index: int
    bin_start_usdc: float
    bin_end_usdc: float
    session_count: int = 0
    weighted_return_on_open_notional_pct: float = 0
    average_return_on_open_notional_pct: float = 0
    win_rate_pct: float = 0
    sum_realized_pnl_usdc: float = 0
    sum_open_notional_usdc: float = 0
    sum_peak_position_notional_usdc: float = 0


class SessionAnalyticsDiagnostics(BaseModel):
    total_detected_sessions: int = 0
    closed_sessions: int = 0
    chart_eligible_sessions: int = 0
    excluded_open_session_count: int = 0
    excluded_no_trade_entry_count: int = 0
    excluded_zero_open_notional_count: int = 0
    excluded_warning_session_count: int = 0


class SessionAnalytics(BaseModel):
    diagnostics: SessionAnalyticsDiagnostics = Field(default_factory=SessionAnalyticsDiagnostics)
    trade_sessions: list[TradeSession] = Field(default_factory=list)
    open_hour_buckets: list[SessionOpenHourBucket] = Field(
        default_factory=lambda: [SessionOpenHourBucket(hour_utc=hour) for hour in range(24)]
    )
    open_price_buckets: list[SessionOpenPriceBucket] = Field(default_factory=list)
    open_peak_notional_buckets: list[SessionPeakNotionalBucket] = Field(default_factory=list)


class AnalysisReport(BaseModel):
    request: AnalysisRequest
    summary: SummaryStats
    markets: list[MarketReport]
    total_curve: list[CurvePoint]
    market_curves: dict[str, list[CurvePoint]]
    side_curves: dict[Literal["YES", "NO"], list[CurvePoint]] = Field(default_factory=dict)
    total_curve_no_fee: list[CurvePoint] = Field(default_factory=list)
    market_curves_no_fee: dict[str, list[CurvePoint]] = Field(default_factory=dict)
    side_curves_no_fee: dict[Literal["YES", "NO"], list[CurvePoint]] = Field(default_factory=dict)
    total_pnl_turnover_curve: list[PnlTurnoverPoint] = Field(default_factory=list)
    warnings: list[WarningItem]
    is_partial: bool = False
    artifacts: dict[str, str] = Field(default_factory=dict)
    hourly_realized_pnl_usdc: list[float] = Field(
        default_factory=lambda: [0.0] * 24,
        description="Sum of realized PnL deltas by UTC hour-of-day (0–23).",
    )
    market_scatter: list[MarketScatterPoint] = Field(default_factory=list)
    session_analytics: SessionAnalytics = Field(default_factory=SessionAnalytics)
    session_analytics_by_side: dict[Literal["YES", "NO"], SessionAnalytics] = Field(default_factory=dict)


class PolymarketMarket(BaseModel):
    slug: str
    condition_id: str
    up_token_id: str
    down_token_id: str
    outcomes: list[str]
    outcome_prices: list[float]
    closed: bool = False
    fees_enabled: bool | None = None
    category: str | None = None
    outcome: str | None = None


class TradeRecord(BaseModel):
    transaction_hash: str = Field(alias="transactionHash")
    timestamp: int
    side: Literal["BUY", "SELL"]
    asset: str
    condition_id: str = Field(alias="conditionId")
    size: float
    price: float
    outcome: str | None = None


class ActivityRecord(BaseModel):
    transaction_hash: str = Field(alias="transactionHash")
    timestamp: int
    type: str
    condition_id: str = Field(alias="conditionId")
    slug: str = ""
    size: float = 0
    usdc_size: float = Field(default=0, alias="usdcSize")


class StreamEvent(BaseModel):
    event: str
    data: dict


def utc_now() -> datetime:
    return datetime.now(timezone.utc)
