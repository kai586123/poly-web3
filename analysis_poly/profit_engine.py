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
class TurnoverDelta:
    """Per TRADE fill: gross notional size * price (USDC) for analytics."""

    timestamp: int
    market_slug: str
    delta_turnover_usdc: float


@dataclass
class _Lot:
    qty: float
    cost_per_qty: float


@dataclass
class _TokenState:
    token_id: str
    side: str
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
    token_side: str | None = None
    token_outcome: str | None = None
    side: str | None = None
    size: float = 0.0
    price: float = 0.0
    usdc_size: float = 0.0
    is_taker: bool = False


@dataclass
class _PairLeg:
    timestamp: int
    tx: str
    qty: float
    price: float


@dataclass
class _SessionAccumulator:
    market_slug: str
    start_timestamp: int
    entry_side: str | None = None
    entry_outcome: str | None = None
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
    turnover_deltas: list[TurnoverDelta]
    warnings: list[WarningItem]
    trade_sessions: list[TradeSession]
    session_diagnostics: SessionAnalyticsDiagnostics
    side_trade_sessions: dict[str, list[TradeSession]]
    side_session_diagnostics: dict[str, SessionAnalyticsDiagnostics]


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
        apply_maker_reward: bool = False,
    ):
        self._fee_rate_bps = fee_rate_bps
        self._maker_reward_ratio = maker_reward_ratio
        self._missing_cost_warn_qty = missing_cost_warn_qty
        self._charge_taker_fee = charge_taker_fee
        self._apply_maker_reward = apply_maker_reward

    def process_market(
        self,
        market: PolymarketMarket,
        taker_trades: list[TradeRecord],
        all_trades: list[TradeRecord],
        split_activities: list[ActivityRecord],
        redeem_activities: list[ActivityRecord],
        fee_rate_bps_by_token: dict[str, float] | None = None,
        maker_reward_ratio_override: float | None = None,
    ) -> tuple[MarketReport, list[PnlDelta], list[WarningItem]]:
        result = self.analyze_market(
            market=market,
            taker_trades=taker_trades,
            all_trades=all_trades,
            split_activities=split_activities,
            redeem_activities=redeem_activities,
            fee_rate_bps_by_token=fee_rate_bps_by_token,
            maker_reward_ratio_override=maker_reward_ratio_override,
        )
        return result.report, result.deltas, result.warnings

    def analyze_market(
        self,
        market: PolymarketMarket,
        taker_trades: list[TradeRecord],
        all_trades: list[TradeRecord],
        split_activities: list[ActivityRecord],
        redeem_activities: list[ActivityRecord],
        fee_rate_bps_by_token: dict[str, float] | None = None,
        maker_reward_ratio_override: float | None = None,
    ) -> MarketReplayResult:
        warnings: list[WarningItem] = []
        token_states: dict[str, _TokenState] = {
            market.up_token_id: _TokenState(
                token_id=market.up_token_id,
                side="YES",
                outcome=_market_outcome_label(market, 0, fallback="Yes"),
                lots=deque(),
            ),
            market.down_token_id: _TokenState(
                token_id=market.down_token_id,
                side="NO",
                outcome=_market_outcome_label(market, 1, fallback="No"),
                lots=deque(),
            ),
        }

        events, build_warnings = self._build_market_events(
            market=market,
            taker_trades=taker_trades,
            all_trades=all_trades,
            split_activities=split_activities,
            redeem_activities=redeem_activities,
        )
        warnings.extend(build_warnings)
        effective_fee_rate_bps_by_token = fee_rate_bps_by_token or {}
        maker_reward_ratio = (
            float(maker_reward_ratio_override)
            if maker_reward_ratio_override is not None
            else float(self._maker_reward_ratio)
        )
        has_fee_enabled_token = any(
            float(effective_fee_rate_bps_by_token.get(token_id, self._fee_rate_bps)) > 0
            for token_id in (market.up_token_id, market.down_token_id)
        )
        # Category participates in maker rebates (see Polymarket maker-rebates docs); ratio is e.g. 0.20 / 0.25.
        maker_rebate_category_enabled = has_fee_enabled_token and maker_reward_ratio > 1e-12

        events.sort(key=lambda e: (e.timestamp, e.tx, _event_priority(e.kind)))

        pnl_deltas: list[PnlDelta] = []
        turnover_deltas: list[TurnoverDelta] = []
        for event in events:
            event_deltas: list[PnlDelta] = []
            event_warnings: list[WarningItem] = []
            if event.kind == "TRADE" and event.token_id in token_states:
                turnover_deltas.append(
                    TurnoverDelta(
                        timestamp=event.timestamp,
                        market_slug=market.slug,
                        delta_turnover_usdc=float(event.size) * float(event.price),
                    )
                )
                token_state = token_states[event.token_id]
                token_state.trade_count += 1
                event_deltas, event_warnings = self._apply_trade(
                    market_slug=market.slug,
                    token_state=token_state,
                    event=event,
                    fee_rate_bps=float(effective_fee_rate_bps_by_token.get(token_state.token_id, self._fee_rate_bps)),
                    maker_rebate_category_enabled=maker_rebate_category_enabled,
                    maker_reward_ratio=maker_reward_ratio,
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

        settlement_event, settlement_side_events, settlement_deltas, settlement_warnings = self._settle_closed_market_positions(
            market=market,
            token_states=token_states,
            events=events,
        )
        pnl_deltas.extend(settlement_deltas)
        warnings.extend(settlement_warnings)
        pair_events = sorted(
            [*events, *settlement_side_events],
            key=lambda e: (e.timestamp, e.tx, _event_priority(e.kind)),
        )
        trade_sessions, side_trade_sessions = _build_trade_pair_sessions(market, pair_events)
        session_diagnostics = _pair_session_diagnostics(trade_sessions)
        side_session_diagnostics = {
            side: _pair_session_diagnostics(side_trade_sessions.get(side, []))
            for side in ("YES", "NO")
        }

        token_reports: list[TokenReport] = []
        for token_state in token_states.values():
            token_reports.append(
                TokenReport(
                    token_id=token_state.token_id,
                    side=token_state.side,
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
            yes_outcome_label=_market_outcome_label(market, 0, fallback="Yes"),
            no_outcome_label=_market_outcome_label(market, 1, fallback="No"),
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
            turnover_deltas=turnover_deltas,
            warnings=warnings,
            trade_sessions=trade_sessions,
            session_diagnostics=session_diagnostics,
            side_trade_sessions=side_trade_sessions,
            side_session_diagnostics=side_session_diagnostics,
        )

    def _build_market_events(
        self,
        market: PolymarketMarket,
        taker_trades: list[TradeRecord],
        all_trades: list[TradeRecord],
        split_activities: list[ActivityRecord],
        redeem_activities: list[ActivityRecord],
    ) -> tuple[list[_Event], list[WarningItem]]:
        warnings: list[WarningItem] = []
        taker_trades = _dedupe_trades_preserve_order(taker_trades)
        all_trades = _dedupe_trades_preserve_order(all_trades)
        taker_keys = {_trade_key(t) for t in taker_trades}
        events: list[_Event] = []
        for trade in all_trades:
            is_taker = _trade_key(trade) in taker_keys
            events.append(
                _Event(
                    timestamp=trade.timestamp,
                    tx=trade.transaction_hash,
                    kind="TRADE",
                    token_id=trade.asset,
                    token_side=_token_side_for_asset(market, trade.asset),
                    token_outcome=_token_outcome_for_asset(market, trade.asset),
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

        return events, warnings

    def _apply_trade(
        self,
        market_slug: str,
        token_state: _TokenState,
        event: _Event,
        fee_rate_bps: float,
        maker_rebate_category_enabled: bool,
        maker_reward_ratio: float,
    ) -> tuple[list[PnlDelta], list[WarningItem]]:
        deltas: list[PnlDelta] = []
        warnings: list[WarningItem] = []

        adjusted_size, _, fee_usdc = _fee_adjust(event.size, event.price, fee_rate_bps)

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

        # Maker rebate is MODELED (Data API trades have no rebate field). We credit maker_reward_ratio ×
        # fee_equivalent per maker-classified fill at fill time (fee_equivalent uses the same C×rate×p×(1−p)
        # curve as taker fees). This can exceed wallet rebates if fills are misclassified as maker (see stable
        # _trade_key) or pool share is below the headline category %.
        if (
            not event.is_taker
            and maker_rebate_category_enabled
            and self._apply_maker_reward
        ):
            maker_reward = fee_usdc * maker_reward_ratio
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
    ) -> tuple[_Event | None, list[_Event], list[PnlDelta], list[WarningItem]]:
        if not market.closed:
            return None, [], [], []

        unsettled_states = [state for state in token_states.values() if state.position_qty > 1e-12]
        if not unsettled_states:
            return None, [], [], []

        winner_token = _resolve_winner_token(market)
        settlement_ts = _settlement_timestamp(market, events)
        if not winner_token:
            return _Event(timestamp=settlement_ts, tx="settlement", kind="SETTLEMENT"), [], [], [
                WarningItem(
                    timestamp=settlement_ts,
                    market_slug=market.slug,
                    code="CLOSED_MARKET_UNKNOWN_OUTCOME",
                    message="market is closed but winner outcome cannot be uniquely inferred",
                )
            ]

        deltas: list[PnlDelta] = []
        warnings: list[WarningItem] = []
        side_events: list[_Event] = []
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
            side_events.append(
                _Event(
                    timestamp=settlement_ts,
                    tx="settlement",
                    kind="SETTLEMENT",
                    token_id=token_state.token_id,
                    token_side=token_state.side,
                    token_outcome=token_state.outcome,
                    size=quantity,
                    usdc_size=proceeds,
                )
            )

        return (
            _Event(
                timestamp=settlement_ts,
                tx="settlement",
                kind="SETTLEMENT",
                size=settled_qty,
                usdc_size=settled_proceeds,
            ),
            side_events,
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
    """Taker fee in USDC and maker fee-equivalent (Polymarket): qty * (bps/1000) * p * (1-p)."""
    qty = max(0.0, float(size))
    px = max(0.0, min(1.0, float(price)))
    fee_rate = max(0.0, float(fee_rate_bps)) / 1000.0 if fee_rate_bps else 0.0
    fee_usdc = qty * fee_rate * px * (1.0 - px)
    fee_usdc = round(fee_usdc, 5)
    if fee_usdc < 0.00001:
        fee_usdc = 0.0
    fee_token = fee_usdc / px if px > 1e-12 else 0.0
    fee_token = min(qty, max(0.0, fee_token))
    adjusted_size = max(0.0, qty - fee_token)
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
    """Stable across /trades?takerOnly=true vs false — those are two HTTP calls and JSON floats can differ."""
    return (
        str(trade.transaction_hash),
        str(trade.asset),
        str(trade.side),
        round(float(trade.price), 10),
        round(float(trade.size), 10),
        int(trade.timestamp),
    )


def _dedupe_trades_preserve_order(trades: list[TradeRecord]) -> list[TradeRecord]:
    seen: set[tuple[str, str, str, float, float, int]] = set()
    out: list[TradeRecord] = []
    for t in trades:
        k = _trade_key(t)
        if k in seen:
            continue
        seen.add(k)
        out.append(t)
    return out



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


def _market_outcome_label(market: PolymarketMarket, index: int, fallback: str) -> str:
    if index < len(market.outcomes):
        label = str(market.outcomes[index]).strip()
        if label:
            return label
    return fallback


def _token_side_for_asset(market: PolymarketMarket, asset: str | None) -> str | None:
    if asset == market.up_token_id:
        return "YES"
    if asset == market.down_token_id:
        return "NO"
    return None


def _token_outcome_for_asset(market: PolymarketMarket, asset: str | None) -> str | None:
    side = _token_side_for_asset(market, asset)
    if side == "YES":
        return _market_outcome_label(market, 0, fallback="Yes")
    if side == "NO":
        return _market_outcome_label(market, 1, fallback="No")
    return None


def _enrich_event_with_side(event: _Event, market: PolymarketMarket, token_id: str | None) -> _Event:
    return _Event(
        timestamp=event.timestamp,
        tx=event.tx,
        kind=event.kind,
        token_id=token_id,
        token_side=_token_side_for_asset(market, token_id),
        token_outcome=_token_outcome_for_asset(market, token_id),
        side=event.side,
        size=event.size,
        price=event.price,
        usdc_size=event.usdc_size,
        is_taker=event.is_taker,
    )


def _side_event_from_split_or_settlement(
    base_event: _Event,
    market: PolymarketMarket,
    token_id: str,
    size: float,
    usdc_size: float,
) -> _Event:
    return _Event(
        timestamp=base_event.timestamp,
        tx=base_event.tx,
        kind=base_event.kind,
        token_id=token_id,
        token_side=_token_side_for_asset(market, token_id),
        token_outcome=_token_outcome_for_asset(market, token_id),
        side=base_event.side,
        size=size,
        price=base_event.price,
        usdc_size=usdc_size,
        is_taker=base_event.is_taker,
    )


def _build_trade_pair_sessions(
    market: PolymarketMarket,
    events: list[_Event],
) -> tuple[list[TradeSession], dict[str, list[TradeSession]]]:
    side_sessions = {
        "YES": _build_side_trade_pair_sessions(
            market_slug=market.slug,
            token_id=market.up_token_id,
            side="YES",
            outcome=_market_outcome_label(market, 0, fallback="Yes"),
            events=events,
        ),
        "NO": _build_side_trade_pair_sessions(
            market_slug=market.slug,
            token_id=market.down_token_id,
            side="NO",
            outcome=_market_outcome_label(market, 1, fallback="No"),
            events=events,
        ),
    }
    combined = sorted(
        [*side_sessions["YES"], *side_sessions["NO"]],
        key=lambda s: (s.start_timestamp, s.end_timestamp, s.entry_side or "", s.market_slug),
    )
    return combined, side_sessions


def _build_side_trade_pair_sessions(
    market_slug: str,
    token_id: str,
    side: str,
    outcome: str,
    events: list[_Event],
) -> list[TradeSession]:
    ordered_events = sorted(
        [event for event in events if event.token_id == token_id],
        key=lambda e: (e.timestamp, e.tx, _event_priority(e.kind)),
    )
    sessions: list[TradeSession] = []
    buy_block: list[_PairLeg] = []
    close_block: list[_PairLeg] = []
    phase = "idle"

    for event in ordered_events:
        leg = _pair_leg_from_event(event)
        if leg is None:
            continue
        if event.kind == "TRADE" and event.side == "BUY":
            if phase in {"idle", "buy"}:
                buy_block.append(leg)
                phase = "buy"
                continue
            sessions.extend(
                _emit_trade_pair_sessions(
                    market_slug=market_slug,
                    side=side,
                    outcome=outcome,
                    buy_block=buy_block,
                    close_block=close_block,
                    terminal=False,
                )
            )
            buy_block = [leg]
            close_block = []
            phase = "buy"
            continue

        if not buy_block:
            # Ignore sells/redeems/settlement before the first buy block on this side.
            continue

        close_block.append(leg)
        phase = "close"

    if buy_block:
        sessions.extend(
            _emit_trade_pair_sessions(
                market_slug=market_slug,
                side=side,
                outcome=outcome,
                buy_block=buy_block,
                close_block=close_block,
                terminal=True,
            )
        )

    return sessions


def _pair_leg_from_event(event: _Event) -> _PairLeg | None:
    if event.kind == "TRADE" and event.side in {"BUY", "SELL"} and event.size > 1e-12:
        return _PairLeg(
            timestamp=int(event.timestamp),
            tx=str(event.tx),
            qty=float(event.size),
            price=float(event.price),
        )
    if event.kind in {"REDEEM", "SETTLEMENT"} and event.size > 1e-12:
        price = float(event.usdc_size) / float(event.size) if float(event.size) > 1e-12 else 0.0
        return _PairLeg(
            timestamp=int(event.timestamp),
            tx=str(event.tx),
            qty=float(event.size),
            price=price,
        )
    return None


def _emit_trade_pair_sessions(
    market_slug: str,
    side: str,
    outcome: str,
    buy_block: list[_PairLeg],
    close_block: list[_PairLeg],
    terminal: bool,
) -> list[TradeSession]:
    total_buy_qty = _pair_leg_qty_sum(buy_block)
    total_close_qty = _pair_leg_qty_sum(close_block)
    matched_qty = min(total_buy_qty, total_close_qty)
    sessions: list[TradeSession] = []

    if matched_qty > 1e-12:
        entry_legs = _take_pair_legs_from_end(buy_block, matched_qty)
        exit_legs = _take_pair_legs_from_start(close_block, matched_qty)
        sessions.append(
            _build_trade_pair_session(
                market_slug=market_slug,
                side=side,
                outcome=outcome,
                entry_legs=entry_legs,
                exit_legs=exit_legs,
                synthetic_zero=False,
                synthetic_close_timestamp=None,
            )
        )

    if terminal:
        residual_qty = max(0.0, total_buy_qty - matched_qty)
        if residual_qty > 1e-12:
            residual_entry_legs = _take_pair_legs_from_start(buy_block, residual_qty)
            synthetic_close_ts = (
                close_block[-1].timestamp
                if close_block
                else (buy_block[-1].timestamp if buy_block else 0)
            )
            sessions.append(
                _build_trade_pair_session(
                    market_slug=market_slug,
                    side=side,
                    outcome=outcome,
                    entry_legs=residual_entry_legs,
                    exit_legs=[],
                    synthetic_zero=True,
                    synthetic_close_timestamp=synthetic_close_ts,
                )
            )

    return sessions


def _pair_leg_qty_sum(legs: list[_PairLeg]) -> float:
    return sum(float(leg.qty) for leg in legs)


def _take_pair_legs_from_start(legs: list[_PairLeg], target_qty: float) -> list[_PairLeg]:
    remaining = max(0.0, float(target_qty))
    out: list[_PairLeg] = []
    for leg in legs:
        if remaining <= 1e-12:
            break
        take = min(float(leg.qty), remaining)
        if take <= 1e-12:
            continue
        out.append(_PairLeg(timestamp=leg.timestamp, tx=leg.tx, qty=take, price=float(leg.price)))
        remaining -= take
    return out


def _take_pair_legs_from_end(legs: list[_PairLeg], target_qty: float) -> list[_PairLeg]:
    remaining = max(0.0, float(target_qty))
    rev_out: list[_PairLeg] = []
    for leg in reversed(legs):
        if remaining <= 1e-12:
            break
        take = min(float(leg.qty), remaining)
        if take <= 1e-12:
            continue
        rev_out.append(_PairLeg(timestamp=leg.timestamp, tx=leg.tx, qty=take, price=float(leg.price)))
        remaining -= take
    return list(reversed(rev_out))


def _pair_leg_notional_sum(legs: list[_PairLeg]) -> float:
    return sum(float(leg.qty) * float(leg.price) for leg in legs)


def _pair_leg_avg_price(legs: list[_PairLeg]) -> float | None:
    qty = _pair_leg_qty_sum(legs)
    if qty <= 1e-12:
        return None
    return _pair_leg_notional_sum(legs) / qty


def _build_trade_pair_session(
    market_slug: str,
    side: str,
    outcome: str,
    entry_legs: list[_PairLeg],
    exit_legs: list[_PairLeg],
    synthetic_zero: bool,
    synthetic_close_timestamp: int | None,
) -> TradeSession:
    open_qty = _pair_leg_qty_sum(entry_legs)
    open_notional = _pair_leg_notional_sum(entry_legs)
    close_qty = open_qty
    close_notional = 0.0 if synthetic_zero else _pair_leg_notional_sum(exit_legs)
    open_avg_price = _pair_leg_avg_price(entry_legs)
    close_avg_price = 0.0 if synthetic_zero else _pair_leg_avg_price(exit_legs)
    open_timestamp = entry_legs[0].timestamp if entry_legs else synthetic_close_timestamp or 0
    end_timestamp = (
        synthetic_close_timestamp
        if synthetic_zero
        else (exit_legs[-1].timestamp if exit_legs else open_timestamp)
    )
    realized = close_notional - open_notional
    return_pct = (realized / open_notional) * 100.0 if open_notional > 1e-12 else None
    exclusion_reason = None if open_notional > 1e-12 else "zero_open_notional"

    return TradeSession(
        market_slug=market_slug,
        start_timestamp=int(open_timestamp),
        end_timestamp=int(end_timestamp),
        entry_side=side,
        entry_outcome=outcome,
        open_timestamp=int(open_timestamp),
        open_hour_utc=datetime.fromtimestamp(int(open_timestamp), tz=timezone.utc).hour,
        open_avg_price=round(float(open_avg_price), 6) if open_avg_price is not None else None,
        open_notional_usdc=round(open_notional, 10),
        open_qty=round(open_qty, 10),
        close_avg_price=round(float(close_avg_price), 6) if close_avg_price is not None else None,
        close_notional_usdc=round(close_notional, 10),
        close_qty=round(close_qty, 10),
        peak_position_notional_usdc=round(open_notional, 10),
        realized_pnl_usdc=round(realized, 10),
        return_on_open_notional_pct=round(return_pct, 6) if return_pct is not None else None,
        event_count=len(entry_legs) + len(exit_legs) + (1 if synthetic_zero else 0),
        has_trade_entry=open_qty > 1e-12,
        is_chart_eligible=exclusion_reason is None,
        exclusion_reason=exclusion_reason,
        warning_codes=(["TERMINAL_FORCE_ZERO_CLOSE"] if synthetic_zero else []),
    )


def _pair_session_diagnostics(sessions: list[TradeSession]) -> SessionAnalyticsDiagnostics:
    diagnostics = SessionAnalyticsDiagnostics(
        total_detected_sessions=len(sessions),
        closed_sessions=len(sessions),
    )
    for session in sessions:
        if session.is_chart_eligible:
            diagnostics.chart_eligible_sessions += 1
        elif session.exclusion_reason == "no_trade_entry":
            diagnostics.excluded_no_trade_entry_count += 1
        elif session.exclusion_reason == "zero_open_notional":
            diagnostics.excluded_zero_open_notional_count += 1
        else:
            diagnostics.excluded_warning_session_count += 1
    return diagnostics


def _market_ts_from_slug(market_slug: str) -> int | None:
    try:
        return int(str(market_slug).rsplit("-", 1)[-1])
    except Exception:  # noqa: BLE001
        return None


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


def _token_inventory_cost_basis_usdc(token_state: _TokenState) -> float:
    total = 0.0
    for lot in token_state.lots:
        total += float(lot.qty) * float(lot.cost_per_qty)
    return total


def _advance_side_session(
    market_slug: str,
    token_state: _TokenState,
    active_session: _SessionAccumulator | None,
    event: _Event,
    event_deltas: list[PnlDelta],
    event_warnings: list[WarningItem],
    was_flat: bool,
    side_trade_sessions: dict[str, list[TradeSession]],
    side_session_diagnostics: dict[str, SessionAnalyticsDiagnostics],
) -> _SessionAccumulator | None:
    is_flat = token_state.position_qty <= 1e-12
    if was_flat and not is_flat and active_session is None:
        active_session = _SessionAccumulator(market_slug=market_slug, start_timestamp=event.timestamp)
    if active_session is None and (not was_flat or not is_flat):
        active_session = _SessionAccumulator(market_slug=market_slug, start_timestamp=event.timestamp)
    active_session = _record_session_event(active_session, event, event_deltas, event_warnings)
    if active_session is not None:
        inv = _token_inventory_cost_basis_usdc(token_state)
        if inv > active_session.peak_position_notional_usdc:
            active_session.peak_position_notional_usdc = inv
    if active_session is not None and is_flat:
        session = _finalize_session(active_session, end_timestamp=event.timestamp)
        side = token_state.side
        side_trade_sessions[side].append(session)
        side_session_diagnostics[side].total_detected_sessions += 1
        side_session_diagnostics[side].closed_sessions += 1
        _apply_session_diagnostic(side_session_diagnostics[side], session)
        return None
    return active_session


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
            active_session.entry_side = event.token_side
            active_session.entry_outcome = event.token_outcome
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
        entry_side=active_session.entry_side,
        entry_outcome=active_session.entry_outcome,
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


def build_turnover_curve(deltas: list[TurnoverDelta]) -> list[tuple[int, float, float]]:
    by_ts: dict[int, float] = defaultdict(float)
    for delta in deltas:
        by_ts[delta.timestamp] += delta.delta_turnover_usdc

    cumulative = 0.0
    points: list[tuple[int, float, float]] = []
    for ts in sorted(by_ts.keys()):
        delta = by_ts[ts]
        cumulative += delta
        points.append((ts, delta, cumulative))
    return points


def build_pnl_turnover_timeline(
    start_ts: int,
    total_deltas: list[PnlDelta],
    total_deltas_no_fee: list[PnlDelta],
    turnover_deltas: list[TurnoverDelta],
) -> list[tuple[int, float, float, float]]:
    """Return (timestamp, cum_turnover, cum_pnl_net, cum_pnl_no_fee), sorted by time."""
    pnl_by_ts: dict[int, float] = defaultdict(float)
    for d in total_deltas:
        pnl_by_ts[d.timestamp] += d.delta_pnl_usdc
    pnl_nf_by_ts: dict[int, float] = defaultdict(float)
    for d in total_deltas_no_fee:
        pnl_nf_by_ts[d.timestamp] += d.delta_pnl_usdc
    turn_by_ts: dict[int, float] = defaultdict(float)
    for d in turnover_deltas:
        turn_by_ts[d.timestamp] += d.delta_turnover_usdc

    all_ts = sorted(set(pnl_by_ts) | set(pnl_nf_by_ts) | set(turn_by_ts))
    out: list[tuple[int, float, float, float]] = []
    cum_turn = 0.0
    cum_pnl = 0.0
    cum_pnl_nf = 0.0

    if all_ts and int(all_ts[0]) > int(start_ts):
        out.append((int(start_ts), 0.0, 0.0, 0.0))

    for ts in all_ts:
        cum_turn += turn_by_ts.get(ts, 0.0)
        cum_pnl += pnl_by_ts.get(ts, 0.0)
        cum_pnl_nf += pnl_nf_by_ts.get(ts, 0.0)
        out.append((int(ts), cum_turn, cum_pnl, cum_pnl_nf))

    return out
