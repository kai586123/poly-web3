from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime, timezone

from .models import (
    ActivityRecord,
    MarketReport,
    PolymarketMarket,
    SessionAnalyticsDiagnostics,
    TokenReport,
    TradeSession,
    WarningItem,
)
from .models import TradeRecord


@dataclass
class PnlDelta:
    timestamp: int
    market_slug: str
    token_id: str
    delta_pnl_usdc: float


@dataclass
class _Lot:
    qty: float
    cost_per_qty: float


@dataclass
class _TokenState:
    token_id: str
    outcome: str
    lots: deque[_Lot]
    realized_pnl_usdc: float = 0.0
    taker_fee_usdc: float = 0.0
    maker_reward_usdc: float = 0.0
    buy_qty: float = 0.0
    sell_qty: float = 0.0
    split_qty: float = 0.0
    redeem_qty: float = 0.0
    trade_count: int = 0

    @property
    def position_qty(self) -> float:
        return sum(lot.qty for lot in self.lots)


@dataclass
class _Event:
    timestamp: int
    tx: str
    kind: str
    token_id: str | None = None
    side: str | None = None
    size: float = 0.0
    price: float = 0.0
    usdc_size: float = 0.0
    is_taker: bool = False


@dataclass
class _SessionAccumulator:
    market_slug: str
    start_timestamp: int
    open_timestamp: int | None = None
    open_notional_usdc: float = 0.0
    open_qty: float = 0.0
    close_notional_usdc: float = 0.0
    close_qty: float = 0.0
    peak_position_notional_usdc: float = 0.0
    realized_pnl_usdc: float = 0.0
    event_count: int = 0
    warning_codes: set[str] = field(default_factory=set)


@dataclass
class MarketReplayResult:
    report: MarketReport
    deltas: list[PnlDelta]
    warnings: list[WarningItem]
    trade_sessions: list[TradeSession]
    session_diagnostics: SessionAnalyticsDiagnostics


SESSION_EXCLUSION_WARNING_CODES = {
    "REDEEM_SKIP_UNKNOWN_WINNER",
    "SELL_OVERSELL_ZERO_COST",
    "REDEEM_OVERSELL_ZERO_COST",
    "CLOSED_MARKET_UNKNOWN_OUTCOME",
    "CLOSED_MARKET_SETTLEMENT_ZERO_COST",
}


class ProfitEngine:
    def __init__(
        self,
        fee_rate_bps: float,
        maker_reward_ratio: float,
        missing_cost_warn_qty: float,
        charge_taker_fee: bool = True,
    ):
        self._fee_rate_bps = fee_rate_bps
        self._maker_reward_ratio = maker_reward_ratio
        self._missing_cost_warn_qty = missing_cost_warn_qty
        self._charge_taker_fee = charge_taker_fee

    def process_market(
        self,
        market: PolymarketMarket,
        taker_trades: list[TradeRecord],
        all_trades: list[TradeRecord],
        split_activities: list[ActivityRecord],
        redeem_activities: list[ActivityRecord],
    ) -> tuple[MarketReport, list[PnlDelta], list[WarningItem]]:
        result = self.analyze_market(
            market=market,
            taker_trades=taker_trades,
            all_trades=all_trades,
            split_activities=split_activities,
            redeem_activities=redeem_activities,
        )
        return result.report, result.deltas, result.warnings

    def analyze_market(
        self,
        market: PolymarketMarket,
        taker_trades: list[TradeRecord],
        all_trades: list[TradeRecord],
        split_activities: list[ActivityRecord],
        redeem_activities: list[ActivityRecord],
    ) -> MarketReplayResult:
        warnings: list[WarningItem] = []
        token_states: dict[str, _TokenState] = {
            market.up_token_id: _TokenState(token_id=market.up_token_id, outcome="Up", lots=deque()),
            market.down_token_id: _TokenState(token_id=market.down_token_id, outcome="Down", lots=deque()),
        }

        events, build_warnings, maker_reward_enabled, has_maker_trade = self._build_market_events(
            market=market,
            taker_trades=taker_trades,
            all_trades=all_trades,
            split_activities=split_activities,
            redeem_activities=redeem_activities,
        )
        warnings.extend(build_warnings)

        events.sort(key=lambda e: (e.timestamp, e.tx, _event_priority(e.kind)))

        pnl_deltas: list[PnlDelta] = []
        trade_sessions: list[TradeSession] = []
        session_diagnostics = SessionAnalyticsDiagnostics()
        active_session: _SessionAccumulator | None = None
        for event in events:
            was_flat = _is_market_flat(token_states)
            event_deltas: list[PnlDelta] = []
            event_warnings: list[WarningItem] = []
            if event.kind == "TRADE" and event.token_id in token_states:
                token_state = token_states[event.token_id]
                token_state.trade_count += 1
                event_deltas, event_warnings = self._apply_trade(
                    market_slug=market.slug,
                    token_state=token_state,
                    event=event,
                    maker_reward_enabled=maker_reward_enabled,
                )
            elif event.kind == "SPLIT":
                up_state = token_states[market.up_token_id]
                down_state = token_states[market.down_token_id]

                qty_each = event.size / 2.0
                usdc_each = event.usdc_size / 2.0
                if qty_each > 0:
                    up_state.lots.append(_Lot(qty=qty_each, cost_per_qty=usdc_each / qty_each))
                    down_state.lots.append(_Lot(qty=qty_each, cost_per_qty=usdc_each / qty_each))
                up_state.split_qty += qty_each
                down_state.split_qty += qty_each
            elif event.kind == "REDEEM" and event.token_id in token_states:
                token_state = token_states[event.token_id]
                event_deltas, event_warnings = self._close_position(
                    market_slug=market.slug,
                    token_state=token_state,
                    timestamp=event.timestamp,
                    quantity=event.size,
                    proceeds=event.usdc_size,
                    missing_cost_warn_code="REDEEM_OVERSELL_ZERO_COST",
                )
                token_state.redeem_qty += event.size
            pnl_deltas.extend(event_deltas)
            warnings.extend(event_warnings)

            is_flat = _is_market_flat(token_states)
            if was_flat and not is_flat and active_session is None:
                active_session = _SessionAccumulator(market_slug=market.slug, start_timestamp=event.timestamp)
            active_session = _record_session_event(active_session, event, event_deltas, event_warnings)
            if active_session is not None:
                inv = _inventory_cost_basis_usdc(token_states)
                if inv > active_session.peak_position_notional_usdc:
                    active_session.peak_position_notional_usdc = inv
            if active_session is not None and is_flat:
                session = _finalize_session(active_session, end_timestamp=event.timestamp)
                trade_sessions.append(session)
                session_diagnostics.total_detected_sessions += 1
                session_diagnostics.closed_sessions += 1
                _apply_session_diagnostic(session_diagnostics, session)
                active_session = None

        settlement_event, settlement_deltas, settlement_warnings = self._settle_closed_market_positions(
            market=market,
            token_states=token_states,
            events=events,
        )
        pnl_deltas.extend(settlement_deltas)
        warnings.extend(settlement_warnings)
        if settlement_event is not None:
            active_session = _record_session_event(active_session, settlement_event, settlement_deltas, settlement_warnings)
            if active_session is not None:
                inv = _inventory_cost_basis_usdc(token_states)
                if inv > active_session.peak_position_notional_usdc:
                    active_session.peak_position_notional_usdc = inv
            if active_session is not None and _is_market_flat(token_states):
                session = _finalize_session(active_session, end_timestamp=settlement_event.timestamp)
                trade_sessions.append(session)
                session_diagnostics.total_detected_sessions += 1
                session_diagnostics.closed_sessions += 1
                _apply_session_diagnostic(session_diagnostics, session)
                active_session = None

        if active_session is not None:
            session_diagnostics.total_detected_sessions += 1
            session_diagnostics.excluded_open_session_count += 1

        if not maker_reward_enabled and has_maker_trade:
            warnings.append(
                WarningItem(
                    market_slug=market.slug,
                    code="MAKER_REWARD_DEFERRED_TODAY",
                    message=(
                        "maker reward for markets on/after current UTC day 00:00 is excluded "
                        "because Polymarket settles maker rewards once per day"
                    ),
                )
            )

        token_reports: list[TokenReport] = []
        for token_state in token_states.values():
            token_reports.append(
                TokenReport(
                    token_id=token_state.token_id,
                    outcome=token_state.outcome,
                    realized_pnl_usdc=round(token_state.realized_pnl_usdc, 10),
                    taker_fee_usdc=round(token_state.taker_fee_usdc, 10),
                    maker_reward_usdc=round(token_state.maker_reward_usdc, 10),
                    buy_qty=round(token_state.buy_qty, 10),
                    sell_qty=round(token_state.sell_qty, 10),
                    split_qty=round(token_state.split_qty, 10),
                    redeem_qty=round(token_state.redeem_qty, 10),
                    ending_position_qty=round(token_state.position_qty, 10),
                    trade_count=token_state.trade_count,
                )
            )

        market_report = MarketReport(
            market_slug=market.slug,
            condition_id=market.condition_id,
            up_token_id=market.up_token_id,
            down_token_id=market.down_token_id,
            realized_pnl_usdc=round(sum(t.realized_pnl_usdc for t in token_reports), 10),
            taker_fee_usdc=round(sum(t.taker_fee_usdc for t in token_reports), 10),
            maker_reward_usdc=round(sum(t.maker_reward_usdc for t in token_reports), 10),
            ending_position_up=round(token_states[market.up_token_id].position_qty, 10),
            ending_position_down=round(token_states[market.down_token_id].position_qty, 10),
            tokens=sorted(token_reports, key=lambda x: x.token_id),
        )

        return MarketReplayResult(
            report=market_report,
            deltas=pnl_deltas,
            warnings=warnings,
            trade_sessions=trade_sessions,
            session_diagnostics=session_diagnostics,
        )

    def _build_market_events(
        self,
        market: PolymarketMarket,
        taker_trades: list[TradeRecord],
        all_trades: list[TradeRecord],
        split_activities: list[ActivityRecord],
        redeem_activities: list[ActivityRecord],
    ) -> tuple[list[_Event], list[WarningItem], bool, bool]:
        warnings: list[WarningItem] = []
        taker_keys = {_trade_key(t) for t in taker_trades}
        events: list[_Event] = []
        maker_reward_enabled = _is_maker_reward_enabled_for_market(market.slug)
        has_maker_trade = False

        for trade in all_trades:
            is_taker = _trade_key(trade) in taker_keys
            if not is_taker:
                has_maker_trade = True
            events.append(
                _Event(
                    timestamp=trade.timestamp,
                    tx=trade.transaction_hash,
                    kind="TRADE",
                    token_id=trade.asset,
                    side=trade.side,
                    size=float(trade.size),
                    price=float(trade.price),
                    is_taker=is_taker,
                )
            )

        for split in split_activities:
            events.append(
                _Event(
                    timestamp=split.timestamp,
                    tx=split.transaction_hash,
                    kind="SPLIT",
                    size=float(split.size),
                    usdc_size=float(split.usdc_size),
                )
            )

        for redeem in redeem_activities:
            winner_token = _resolve_winner_token(market)
            if not winner_token:
                warnings.append(
                    WarningItem(
                        timestamp=redeem.timestamp,
                        market_slug=market.slug,
                        code="REDEEM_SKIP_UNKNOWN_WINNER",
                        message="skip redeem because winner outcome cannot be uniquely inferred",
                    )
                )
                continue

            events.append(
                _Event(
                    timestamp=redeem.timestamp,
                    tx=redeem.transaction_hash,
                    kind="REDEEM",
                    token_id=winner_token,
                    size=float(redeem.size),
                    usdc_size=float(redeem.usdc_size),
                )
            )

        return events, warnings, maker_reward_enabled, has_maker_trade

    def _apply_trade(
        self,
        market_slug: str,
        token_state: _TokenState,
        event: _Event,
        maker_reward_enabled: bool,
    ) -> tuple[list[PnlDelta], list[WarningItem]]:
        deltas: list[PnlDelta] = []
        warnings: list[WarningItem] = []

        adjusted_size, _, fee_usdc = _fee_adjust(event.size, event.price, self._fee_rate_bps)

        if event.side == "BUY":
            qty_add = event.size
            if event.is_taker and self._charge_taker_fee:
                qty_add = adjusted_size
            total_cost = event.size * event.price
            if qty_add > 0:
                token_state.lots.append(_Lot(qty=qty_add, cost_per_qty=total_cost / qty_add))
            token_state.buy_qty += qty_add
            if event.is_taker and self._charge_taker_fee:
                token_state.taker_fee_usdc += fee_usdc
        elif event.side == "SELL":
            token_state.sell_qty += event.size
            proceeds = event.size * event.price
            if event.is_taker and self._charge_taker_fee:
                proceeds = adjusted_size * event.price
            close_deltas, close_warnings = self._close_position(
                market_slug=market_slug,
                token_state=token_state,
                timestamp=event.timestamp,
                quantity=event.size,
                proceeds=proceeds,
                missing_cost_warn_code="SELL_OVERSELL_ZERO_COST",
            )
            deltas.extend(close_deltas)
            warnings.extend(close_warnings)
            if event.is_taker and self._charge_taker_fee:
                token_state.taker_fee_usdc += fee_usdc

        if not event.is_taker and maker_reward_enabled:
            maker_reward = fee_usdc * self._maker_reward_ratio
            token_state.realized_pnl_usdc += maker_reward
            token_state.maker_reward_usdc += maker_reward
            deltas.append(
                PnlDelta(
                    timestamp=event.timestamp,
                    market_slug=market_slug,
                    token_id=token_state.token_id,
                    delta_pnl_usdc=maker_reward,
                )
            )

        return deltas, warnings

    def _settle_closed_market_positions(
        self,
        market: PolymarketMarket,
        token_states: dict[str, _TokenState],
        events: list[_Event],
    ) -> tuple[_Event | None, list[PnlDelta], list[WarningItem]]:
        if not market.closed:
            return None, [], []

        unsettled_states = [state for state in token_states.values() if state.position_qty > 1e-12]
        if not unsettled_states:
            return None, [], []

        winner_token = _resolve_winner_token(market)
        settlement_ts = _settlement_timestamp(market, events)
        if not winner_token:
            return _Event(timestamp=settlement_ts, tx="settlement", kind="SETTLEMENT"), [], [
                WarningItem(
                    timestamp=settlement_ts,
                    market_slug=market.slug,
                    code="CLOSED_MARKET_UNKNOWN_OUTCOME",
                    message="market is closed but winner outcome cannot be uniquely inferred",
                )
            ]

        deltas: list[PnlDelta] = []
        warnings: list[WarningItem] = []
        settled_qty = 0.0
        settled_proceeds = 0.0
        for token_state in unsettled_states:
            quantity = token_state.position_qty
            proceeds = quantity if token_state.token_id == winner_token else 0.0
            settled_qty += quantity
            settled_proceeds += proceeds
            close_deltas, close_warnings = self._close_position(
                market_slug=market.slug,
                token_state=token_state,
                timestamp=settlement_ts,
                quantity=quantity,
                proceeds=proceeds,
                missing_cost_warn_code="CLOSED_MARKET_SETTLEMENT_ZERO_COST",
            )
            deltas.extend(close_deltas)
            warnings.extend(close_warnings)

        return (
            _Event(
                timestamp=settlement_ts,
                tx="settlement",
                kind="SETTLEMENT",
                size=settled_qty,
                usdc_size=settled_proceeds,
            ),
            deltas,
            warnings,
        )

    def _close_position(
        self,
        market_slug: str,
        token_state: _TokenState,
        timestamp: int,
        quantity: float,
        proceeds: float,
        missing_cost_warn_code: str,
    ) -> tuple[list[PnlDelta], list[WarningItem]]:
        warnings: list[WarningItem] = []
        quantity = max(0.0, quantity)
        if quantity == 0:
            return [], warnings

        remaining = quantity
        realized_cost = 0.0
        while remaining > 1e-12 and token_state.lots:
            lot = token_state.lots[0]
            take = min(lot.qty, remaining)
            realized_cost += take * lot.cost_per_qty
            lot.qty -= take
            remaining -= take
            if lot.qty <= 1e-12:
                token_state.lots.popleft()

        if remaining > self._missing_cost_warn_qty:
            warnings.append(
                WarningItem(
                    timestamp=timestamp,
                    market_slug=market_slug,
                    token_id=token_state.token_id,
                    code=missing_cost_warn_code,
                    message=(
                        "position shortfall consumed at zero cost basis, "
                        f"missing_qty={remaining:.6f}"
                    ),
                )
            )

        realized = proceeds - realized_cost
        token_state.realized_pnl_usdc += realized

        return [
            PnlDelta(
                timestamp=timestamp,
                market_slug=market_slug,
                token_id=token_state.token_id,
                delta_pnl_usdc=realized,
            )
        ], warnings



def _fee_adjust(size: float, price: float, fee_rate_bps: float) -> tuple[float, float, float]:
    fee_multiplier = fee_rate_bps / 1000 if fee_rate_bps else 0.0
    fee = 0.25 * (price * (1 - price)) ** 2 * fee_multiplier
    adjusted_size = (1 - fee) * size
    fee_token = size - adjusted_size
    fee_usdc = fee_token * price
    return adjusted_size, fee_token, fee_usdc



def _event_priority(kind: str) -> int:
    if kind == "SPLIT":
        return 0
    if kind == "TRADE":
        return 1
    if kind == "REDEEM":
        return 2
    return 9



def _trade_key(trade: TradeRecord) -> tuple[str, str, str, float, float, int]:
    return (
        trade.transaction_hash,
        trade.asset,
        trade.side,
        float(trade.price),
        float(trade.size),
        int(trade.timestamp),
    )



def _resolve_winner_token(market: PolymarketMarket) -> str | None:
    if len(market.outcome_prices) < 2:
        return None
    up_price = market.outcome_prices[0]
    down_price = market.outcome_prices[1]
    if up_price == 1 and down_price == 0:
        return market.up_token_id
    if up_price == 0 and down_price == 1:
        return market.down_token_id
    return None


def _market_ts_from_slug(market_slug: str) -> int | None:
    try:
        return int(str(market_slug).rsplit("-", 1)[-1])
    except Exception:  # noqa: BLE001
        return None


def _utc_day_start_ts(now: datetime | None = None) -> int:
    dt = now or datetime.now(timezone.utc)
    start = datetime(dt.year, dt.month, dt.day, tzinfo=timezone.utc)
    return int(start.timestamp())


def _is_maker_reward_enabled_for_market(market_slug: str) -> bool:
    market_ts = _market_ts_from_slug(market_slug)
    if market_ts is None:
        return True
    return market_ts < _utc_day_start_ts()


def _settlement_timestamp(market: PolymarketMarket, events: list[_Event]) -> int:
    event_ts = max((event.timestamp for event in events), default=0)
    market_ts = _market_ts_from_slug(market.slug) or 0
    return max(event_ts, market_ts)



def _is_market_flat(token_states: dict[str, _TokenState], epsilon: float = 1e-12) -> bool:
    return all(state.position_qty <= epsilon for state in token_states.values())


def _inventory_cost_basis_usdc(token_states: dict[str, _TokenState]) -> float:
    """Σ (shares × lot cost / 成交价) for all open lots — peak inventory notional in USDC."""
    total = 0.0
    for state in token_states.values():
        for lot in state.lots:
            total += float(lot.qty) * float(lot.cost_per_qty)
    return total


def _record_session_event(
    active_session: _SessionAccumulator | None,
    event: _Event,
    event_deltas: list[PnlDelta],
    event_warnings: list[WarningItem],
) -> _SessionAccumulator | None:
    if active_session is None:
        return None

    active_session.event_count += 1
    active_session.realized_pnl_usdc += sum(delta.delta_pnl_usdc for delta in event_deltas)
    for warning in event_warnings:
        active_session.warning_codes.add(warning.code)

    if event.kind == "TRADE" and event.side == "BUY" and event.size > 0:
        active_session.open_notional_usdc += float(event.size) * float(event.price)
        active_session.open_qty += float(event.size)
        if active_session.open_timestamp is None:
            active_session.open_timestamp = int(event.timestamp)
    elif event.kind == "TRADE" and event.side == "SELL" and event.size > 0:
        active_session.close_notional_usdc += float(event.size) * float(event.price)
        active_session.close_qty += float(event.size)
    elif event.kind in {"REDEEM", "SETTLEMENT"} and event.size > 0:
        active_session.close_notional_usdc += float(event.usdc_size)
        active_session.close_qty += float(event.size)

    return active_session


def _finalize_session(active_session: _SessionAccumulator, end_timestamp: int) -> TradeSession:
    warning_codes = sorted(active_session.warning_codes)
    open_timestamp = active_session.open_timestamp
    open_notional = float(active_session.open_notional_usdc)
    open_qty = float(active_session.open_qty)
    close_notional = float(active_session.close_notional_usdc)
    close_qty = float(active_session.close_qty)
    has_trade_entry = open_timestamp is not None and open_qty > 1e-12
    open_avg_price = (open_notional / open_qty) if open_qty > 1e-12 else None
    close_avg_price = (close_notional / close_qty) if close_qty > 1e-12 else None
    return_pct = (active_session.realized_pnl_usdc / open_notional) * 100.0 if open_notional > 1e-12 else None

    exclusion_reason = None
    if not has_trade_entry:
        exclusion_reason = "no_trade_entry"
    elif open_notional <= 1e-12:
        exclusion_reason = "zero_open_notional"
    elif any(code in SESSION_EXCLUSION_WARNING_CODES for code in warning_codes):
        exclusion_reason = "warning"

    return TradeSession(
        market_slug=active_session.market_slug,
        start_timestamp=int(active_session.start_timestamp),
        end_timestamp=int(end_timestamp),
        open_timestamp=int(open_timestamp) if open_timestamp is not None else None,
        open_hour_utc=(
            datetime.fromtimestamp(int(open_timestamp), tz=timezone.utc).hour
            if open_timestamp is not None
            else None
        ),
        open_avg_price=round(open_avg_price, 6) if open_avg_price is not None else None,
        open_notional_usdc=round(open_notional, 10),
        open_qty=round(open_qty, 10),
        close_avg_price=round(close_avg_price, 6) if close_avg_price is not None else None,
        close_notional_usdc=round(close_notional, 10),
        close_qty=round(close_qty, 10),
        peak_position_notional_usdc=round(float(active_session.peak_position_notional_usdc), 10),
        realized_pnl_usdc=round(active_session.realized_pnl_usdc, 10),
        return_on_open_notional_pct=round(return_pct, 6) if return_pct is not None else None,
        event_count=active_session.event_count,
        has_trade_entry=has_trade_entry,
        is_chart_eligible=exclusion_reason is None,
        exclusion_reason=exclusion_reason,
        warning_codes=warning_codes,
    )


def _apply_session_diagnostic(diagnostics: SessionAnalyticsDiagnostics, session: TradeSession) -> None:
    if session.is_chart_eligible:
        diagnostics.chart_eligible_sessions += 1
    elif session.exclusion_reason == "no_trade_entry":
        diagnostics.excluded_no_trade_entry_count += 1
    elif session.exclusion_reason == "zero_open_notional":
        diagnostics.excluded_zero_open_notional_count += 1
    else:
        diagnostics.excluded_warning_session_count += 1


def build_curve(deltas: list[PnlDelta]) -> list[tuple[int, float, float]]:
    by_ts: dict[int, float] = defaultdict(float)
    for delta in deltas:
        by_ts[delta.timestamp] += delta.delta_pnl_usdc

    cumulative = 0.0
    points: list[tuple[int, float, float]] = []
    for ts in sorted(by_ts.keys()):
        delta = by_ts[ts]
        cumulative += delta
        points.append((ts, delta, cumulative))
    return points
