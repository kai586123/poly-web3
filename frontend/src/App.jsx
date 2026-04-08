import { Layout, message } from "antd";
import { useEffect, useMemo, useRef, useState } from "react";
import AdvancedModal from "./components/AdvancedModal";
import ConfigPanel from "./components/ConfigPanel";
import MarketTable from "./components/MarketTable";
import InsightCharts from "./components/InsightCharts";
import PnlCharts from "./components/PnlCharts";
import QuantMetricsPanel from "./components/QuantMetricsPanel";
import StatusCard from "./components/StatusCard";
import { buildDefaultForm, EMPTY_SUMMARY } from "./constants";
import { createRun, fetchRunResult, stopRun } from "./services/api";
import { parseDateTimeTextToUnixSeconds, toDateTimeText } from "./utils/dateTime";

const IDLE_WARNING = "No warnings. Strategy is running with live market aggregation.";
const MAX_DRAWDOWN_MARKERS = 8;
const MIN_DRAWDOWN_DELTA_USDC = 0.5;

function extractMarketPrefix(marketSlug) {
  const raw = String(marketSlug || "").trim().toLowerCase();
  if (!raw) {
    return "unknown";
  }

  const parts = raw.split("-").filter(Boolean);
  if (parts.length >= 3) {
    const interval = parts[2].endsWith("m") ? parts[2].slice(0, -1) : parts[2];
    if (parts[1] === "updown") {
      return `${parts[0]}-${interval}`;
    }
    return `${parts[0]}-${parts[1]}-${interval}`;
  }

  return parts[0] || "unknown";
}

function reduceCurveDelta(points) {
  const byTs = new Map();
  for (const point of points || []) {
    const ts = Number(point.timestamp || 0);
    const delta = Number(point.delta_realized_pnl_usdc || 0);
    byTs.set(ts, (byTs.get(ts) || 0) + delta);
  }
  return byTs;
}

function buildDrawdownMarkers(marketCurves) {
  const worstDropBySlug = new Map();

  Object.entries(marketCurves || {}).forEach(([marketSlug, points]) => {
    const byTs = reduceCurveDelta(points);
    const timestamps = [...byTs.keys()].sort((a, b) => a - b);
    if (!timestamps.length) {
      return;
    }

    let worst = null;
    timestamps.forEach((ts) => {
      const delta = Number(byTs.get(ts) || 0);
      if (delta >= -MIN_DRAWDOWN_DELTA_USDC) {
        return;
      }
      if (!worst || delta < worst.delta) {
        worst = {
          ts,
          delta,
          marketSlug,
          marketPrefix: extractMarketPrefix(marketSlug),
        };
      }
    });

    if (worst) {
      worstDropBySlug.set(marketSlug, worst);
    }
  });

  return [...worstDropBySlug.values()]
    .sort((a, b) => a.delta - b.delta)
    .slice(0, MAX_DRAWDOWN_MARKERS);
}

function hasTradeActivity(market) {
  const tokens = Array.isArray(market?.tokens) ? market.tokens : [];
  return tokens.some((token) => Number(token.trade_count || 0) > 0);
}

function isTruthyQueryFlag(value) {
  const normalized = String(value || "")
    .trim()
    .toLowerCase();
  return normalized === "1" || normalized === "true" || normalized === "yes" || normalized === "on";
}

function parseBootstrapFromQuery(searchText) {
  const params = new URLSearchParams(searchText || "");
  const patch = {};

  const fieldMap = {
    address: "address",
    symbols: "symbols",
    intervals: "intervals",
    start_time: "startTime",
    end_time: "endTime",
    fee_rate_bps: "feeRateBps",
    missing_cost_warn_qty: "missingCostWarnQty",
    maker_reward_ratio: "makerRewardRatio",
    concurrency: "concurrency",
    page_limit: "pageLimit",
  };

  Object.entries(fieldMap).forEach(([queryKey, formKey]) => {
    const value = params.get(queryKey);
    if (value !== null && String(value).trim() !== "") {
      patch[formKey] = value;
    }
  });

  if (!patch.startTime) {
    const startTs = Number(params.get("start_ts"));
    if (Number.isFinite(startTs) && startTs > 0) {
      patch.startTime = toDateTimeText(new Date(startTs * 1000));
    }
  }

  if (!patch.endTime) {
    const endTs = Number(params.get("end_ts"));
    if (Number.isFinite(endTs) && endTs > 0) {
      patch.endTime = toDateTimeText(new Date(endTs * 1000));
    }
  }

  const autoStart = isTruthyQueryFlag(params.get("auto_start"));
  return { patch, autoStart };
}

function buildEmptySessionAnalytics() {
  return {
    diagnostics: {
      total_detected_sessions: 0,
      closed_sessions: 0,
      chart_eligible_sessions: 0,
      excluded_open_session_count: 0,
      excluded_no_trade_entry_count: 0,
      excluded_zero_open_notional_count: 0,
      excluded_warning_session_count: 0,
    },
    trade_sessions: [],
    open_hour_buckets: Array.from({ length: 24 }, (_, hour) => ({
      hour_utc: hour,
      session_count: 0,
      weighted_return_on_open_notional_pct: 0,
      average_return_on_open_notional_pct: 0,
      win_rate_pct: 0,
      sum_realized_pnl_usdc: 0,
      sum_open_notional_usdc: 0,
    })),
    open_price_buckets: [],
    open_peak_notional_buckets: [],
  };
}

function normalizeSessionAnalytics(raw) {
  const empty = buildEmptySessionAnalytics();
  if (!raw || typeof raw !== "object") {
    return empty;
  }

  const diagnostics = { ...empty.diagnostics, ...(raw.diagnostics || {}) };
  const hourById = new Map(
    (Array.isArray(raw.open_hour_buckets) ? raw.open_hour_buckets : []).map((bucket) => [Number(bucket.hour_utc), bucket]),
  );
  const openHourBuckets = Array.from({ length: 24 }, (_, hour) => ({
    ...empty.open_hour_buckets[hour],
    ...(hourById.get(hour) || {}),
    hour_utc: hour,
  }));

  return {
    diagnostics,
    trade_sessions: Array.isArray(raw.trade_sessions) ? raw.trade_sessions : [],
    open_hour_buckets: openHourBuckets,
    open_price_buckets: Array.isArray(raw.open_price_buckets) ? raw.open_price_buckets : [],
    open_peak_notional_buckets: Array.isArray(raw.open_peak_notional_buckets) ? raw.open_peak_notional_buckets : [],
  };
}

export default function App({ serverDefaults }) {
  const [formData, setFormData] = useState(() => buildDefaultForm(serverDefaults));
  const [runId, setRunId] = useState(null);
  const [runStatus, setRunStatus] = useState("IDLE");
  const [running, setRunning] = useState(false);
  const [advancedOpen, setAdvancedOpen] = useState(false);

  const [progress, setProgress] = useState({ current: 0, total: 0 });
  const [summary, setSummary] = useState(EMPTY_SUMMARY);
  const [markets, setMarkets] = useState([]);
  const [downloads, setDownloads] = useState(null);
  const [warnings, setWarnings] = useState([]);

  const [totalSeries, setTotalSeries] = useState([]);
  const [totalSeriesNoFee, setTotalSeriesNoFee] = useState([]);
  const [symbolSeries, setSymbolSeries] = useState({});
  const [symbolSeriesNoFee, setSymbolSeriesNoFee] = useState({});
  const [drawdownMarkers, setDrawdownMarkers] = useState([]);
  const [sessionAnalytics, setSessionAnalytics] = useState(buildEmptySessionAnalytics);

  const eventSourceRef = useRef(null);
  const bootstrapHandledRef = useRef(false);
  const totalByTsRef = useRef(new Map());
  const symbolByTsRef = useRef(new Map());
  const totalByTsNoFeeRef = useRef(new Map());
  const symbolByTsNoFeeRef = useRef(new Map());

  useEffect(() => {
    const end = new Date();
    end.setSeconds(0, 0);
    const start = new Date(end.getTime() - 24 * 60 * 60 * 1000);
    setFormData((prev) => ({
      ...prev,
      startTime: prev.startTime || toDateTimeText(start),
      endTime: prev.endTime || toDateTimeText(end),
    }));
  }, []);

  useEffect(
    () => () => {
      if (eventSourceRef.current) {
        eventSourceRef.current.close();
      }
    },
    [],
  );

  useEffect(() => {
    if (bootstrapHandledRef.current) {
      return;
    }
    bootstrapHandledRef.current = true;

    const { patch, autoStart } = parseBootstrapFromQuery(window.location.search);
    if (!Object.keys(patch).length) {
      return;
    }

    setFormData((prev) => {
      const merged = { ...prev, ...patch };
      if (autoStart) {
        setTimeout(() => {
          handleStart(merged);
        }, 0);
      }
      return merged;
    });
  }, []);

  const roi = useMemo(() => {
    const base =
      Math.max(1, Math.abs(Number(summary.total_taker_fee_usdc || 0)) + Math.abs(Number(summary.total_maker_reward_usdc || 0)));
    return (Number(summary.total_realized_pnl_usdc || 0) / base) * 100;
  }, [summary]);

  const winRate = useMemo(() => {
    if (!markets.length) {
      return 0;
    }
    const winCount = markets.filter((market) => Number(market.realized_pnl_usdc || 0) > 0).length;
    return (winCount / markets.length) * 100;
  }, [markets]);

  const progressPercent = progress.total > 0 ? Math.round((progress.current / progress.total) * 100) : 0;
  const latestWarning = warnings[0] || IDLE_WARNING;

  function updateField(key, value) {
    setFormData((prev) => ({ ...prev, [key]: value }));
  }

  function pushWarning(text) {
    if (!text) {
      return;
    }
    setWarnings((prev) => [text, ...prev].slice(0, 200));
  }

  function clearCurves() {
    totalByTsRef.current = new Map();
    symbolByTsRef.current = new Map();
    totalByTsNoFeeRef.current = new Map();
    symbolByTsNoFeeRef.current = new Map();
    setTotalSeries([]);
    setTotalSeriesNoFee([]);
    setSymbolSeries({});
    setSymbolSeriesNoFee({});
    setDrawdownMarkers([]);
    setSessionAnalytics(buildEmptySessionAnalytics());
  }

  function clearRunData() {
    clearCurves();
    setProgress({ current: 0, total: 0 });
    setSummary(EMPTY_SUMMARY);
    setMarkets([]);
    setDownloads(null);
    setWarnings([]);
  }

  function recomputeTotalSeries() {
    const byTs = totalByTsRef.current;
    const timestamps = [...byTs.keys()].sort((a, b) => a - b);
    let cumulative = 0;
    const points = timestamps.map((ts) => {
      cumulative += Number(byTs.get(ts) || 0);
      return { ts, value: cumulative };
    });
    setTotalSeries(points);
  }

  function recomputeSymbolSeries(symbol) {
    const map = symbolByTsRef.current.get(symbol);
    if (!map) {
      return;
    }
    const timestamps = [...map.keys()].sort((a, b) => a - b);
    let cumulative = 0;
    const points = timestamps.map((ts) => {
      cumulative += Number(map.get(ts) || 0);
      return { ts, value: cumulative };
    });

    setSymbolSeries((prev) => ({ ...prev, [symbol]: points }));
  }

  function recomputeAllSymbolSeries() {
    const next = {};
    for (const [symbol, byTs] of symbolByTsRef.current.entries()) {
      const timestamps = [...byTs.keys()].sort((a, b) => a - b);
      let cumulative = 0;
      next[symbol] = timestamps.map((ts) => {
        cumulative += Number(byTs.get(ts) || 0);
        return { ts, value: cumulative };
      });
    }
    setSymbolSeries(next);
  }

  function appendTotalDelta(timestamp, delta) {
    const ts = Number(timestamp);
    const d = Number(delta || 0);
    const byTs = totalByTsRef.current;
    byTs.set(ts, (byTs.get(ts) || 0) + d);
    recomputeTotalSeries();
  }

  function appendSymbolDelta(symbol, timestamp, delta) {
    const ts = Number(timestamp);
    if (!symbolByTsRef.current.has(symbol)) {
      symbolByTsRef.current.set(symbol, new Map());
    }
    const byTs = symbolByTsRef.current.get(symbol);
    byTs.set(ts, (byTs.get(ts) || 0) + Number(delta || 0));
    recomputeSymbolSeries(symbol);
  }

  function rebuildCurvesFromReport(report) {
    totalByTsRef.current = reduceCurveDelta(report.total_curve || []);

    symbolByTsRef.current = new Map();
    const marketCurves = report.market_curves || {};
    setDrawdownMarkers(buildDrawdownMarkers(marketCurves));
    Object.entries(marketCurves).forEach(([marketSlug, points]) => {
      const marketPrefix = extractMarketPrefix(marketSlug);
      if (!symbolByTsRef.current.has(marketPrefix)) {
        symbolByTsRef.current.set(marketPrefix, new Map());
      }
      const symbolMap = symbolByTsRef.current.get(marketPrefix);
      const reduced = reduceCurveDelta(points);
      reduced.forEach((delta, ts) => {
        symbolMap.set(ts, (symbolMap.get(ts) || 0) + delta);
      });
    });

    recomputeTotalSeries();
    recomputeAllSymbolSeries();

    totalByTsNoFeeRef.current = reduceCurveDelta(report.total_curve_no_fee || []);
    const noFeeTimestamps = [...totalByTsNoFeeRef.current.keys()].sort((a, b) => a - b);
    let noFeeCumulative = 0;
    setTotalSeriesNoFee(
      noFeeTimestamps.map((ts) => {
        noFeeCumulative += Number(totalByTsNoFeeRef.current.get(ts) || 0);
        return { ts, value: noFeeCumulative };
      }),
    );

    symbolByTsNoFeeRef.current = new Map();
    const marketNoFeeCurves = report.market_curves_no_fee || {};
    Object.entries(marketNoFeeCurves).forEach(([marketSlug, points]) => {
      const marketPrefix = extractMarketPrefix(marketSlug);
      if (!symbolByTsNoFeeRef.current.has(marketPrefix)) {
        symbolByTsNoFeeRef.current.set(marketPrefix, new Map());
      }
      const byTs = symbolByTsNoFeeRef.current.get(marketPrefix);
      const reduced = reduceCurveDelta(points);
      reduced.forEach((delta, ts) => {
        byTs.set(ts, (byTs.get(ts) || 0) + delta);
      });
    });
    const nextNoFeeSymbolSeries = {};
    for (const [symbol, byTs] of symbolByTsNoFeeRef.current.entries()) {
      const timestamps = [...byTs.keys()].sort((a, b) => a - b);
      let cumulative = 0;
      nextNoFeeSymbolSeries[symbol] = timestamps.map((ts) => {
        cumulative += Number(byTs.get(ts) || 0);
        return { ts, value: cumulative };
      });
    }
    setSymbolSeriesNoFee(nextNoFeeSymbolSeries);

    setSessionAnalytics(normalizeSessionAnalytics(report.session_analytics));
  }

  function recomputeTotalSeriesNoFee() {
    const byTs = totalByTsNoFeeRef.current;
    const timestamps = [...byTs.keys()].sort((a, b) => a - b);
    let cumulative = 0;
    setTotalSeriesNoFee(
      timestamps.map((ts) => {
        cumulative += Number(byTs.get(ts) || 0);
        return { ts, value: cumulative };
      }),
    );
  }

  function recomputeSymbolSeriesNoFee(symbol) {
    const byTs = symbolByTsNoFeeRef.current.get(symbol);
    if (!byTs) {
      return;
    }
    const timestamps = [...byTs.keys()].sort((a, b) => a - b);
    let cumulative = 0;
    setSymbolSeriesNoFee((prev) => ({
      ...prev,
      [symbol]: timestamps.map((ts) => {
        cumulative += Number(byTs.get(ts) || 0);
        return { ts, value: cumulative };
      }),
    }));
  }

  function appendTotalDeltaNoFee(timestamp, delta) {
    const ts = Number(timestamp);
    const byTs = totalByTsNoFeeRef.current;
    byTs.set(ts, (byTs.get(ts) || 0) + Number(delta || 0));
    recomputeTotalSeriesNoFee();
  }

  function appendSymbolDeltaNoFee(symbol, timestamp, delta) {
    const ts = Number(timestamp);
    if (!symbolByTsNoFeeRef.current.has(symbol)) {
      symbolByTsNoFeeRef.current.set(symbol, new Map());
    }
    const byTs = symbolByTsNoFeeRef.current.get(symbol);
    byTs.set(ts, (byTs.get(ts) || 0) + Number(delta || 0));
    recomputeSymbolSeriesNoFee(symbol);
  }

  async function loadResult(currentRunId) {
    const report = await fetchRunResult(currentRunId);
    if (!report) {
      return;
    }

    setMarkets((report.markets || []).filter(hasTradeActivity));
    setSummary(report.summary || EMPTY_SUMMARY);
    setDownloads(report.artifacts || null);
    if (Array.isArray(report.warnings)) {
      const warningTexts = report.warnings
        .map((warning) => `${warning.code}: ${warning.message}`)
        .reverse();
      setWarnings((prev) => [...warningTexts, ...prev].slice(0, 200));
    }

    rebuildCurvesFromReport(report);
  }

  function closeStream() {
    if (eventSourceRef.current) {
      eventSourceRef.current.close();
      eventSourceRef.current = null;
    }
  }

  function attachStream(currentRunId) {
    closeStream();
    const stream = new EventSource(`/api/runs/${currentRunId}/stream`);
    eventSourceRef.current = stream;

    stream.addEventListener("run_started", (event) => {
      const data = JSON.parse(event.data || "{}");
      setRunStatus("RUNNING");
      setProgress({ current: 0, total: Number(data.progress_total || 0) });
    });

    stream.addEventListener("progress", (event) => {
      const data = JSON.parse(event.data || "{}");
      if (data.current !== undefined && data.total !== undefined) {
        setProgress({ current: Number(data.current), total: Number(data.total) });
      }
    });

    stream.addEventListener("warning", (event) => {
      const data = JSON.parse(event.data || "{}");
      pushWarning(`${data.code}: ${data.message}`);
    });

    stream.addEventListener("point_total", (event) => {
      const data = JSON.parse(event.data || "{}");
      appendTotalDelta(data.timestamp, data.delta_realized_pnl_usdc);
    });

    stream.addEventListener("point_market", (event) => {
      const data = JSON.parse(event.data || "{}");
      appendSymbolDelta(extractMarketPrefix(data.market_slug), data.timestamp, data.delta_realized_pnl_usdc);
    });

    stream.addEventListener("point_total_no_fee", (event) => {
      const data = JSON.parse(event.data || "{}");
      appendTotalDeltaNoFee(data.timestamp, data.delta_realized_pnl_usdc);
    });

    stream.addEventListener("point_market_no_fee", (event) => {
      const data = JSON.parse(event.data || "{}");
      appendSymbolDeltaNoFee(extractMarketPrefix(data.market_slug), data.timestamp, data.delta_realized_pnl_usdc);
    });

    stream.addEventListener("completed", async () => {
      setRunStatus("COMPLETED");
      setRunning(false);
      await loadResult(currentRunId);
      closeStream();
    });

    stream.addEventListener("stopped", async () => {
      setRunStatus("STOPPED");
      setRunning(false);
      await loadResult(currentRunId);
      closeStream();
    });

    stream.addEventListener("run_error", (event) => {
      setRunStatus("FAILED");
      setRunning(false);

      try {
        const data = JSON.parse(event.data || "{}");
        pushWarning(`ERROR: ${data.message || "run failed"}`);
      } catch (_error) {
        pushWarning("ERROR: run failed");
      }

      closeStream();
    });

    stream.addEventListener("error", () => {
      if (stream.readyState !== EventSource.CLOSED) {
        pushWarning("SSE reconnecting...");
      }
    });
  }

  function buildPayload(sourceFormData = formData) {
    const startTs = parseDateTimeTextToUnixSeconds(sourceFormData.startTime);
    const endTs = parseDateTimeTextToUnixSeconds(sourceFormData.endTime);
    if (startTs >= endTs) {
      throw new Error("end time must be later than start time");
    }

    return {
      address: sourceFormData.address.trim(),
      start_ts: startTs,
      end_ts: endTs,
      symbols: sourceFormData.symbols
        .split(",")
        .map((item) => item.trim().toLowerCase())
        .filter(Boolean),
      intervals: sourceFormData.intervals
        .split(",")
        .map((item) => Number(item.trim()))
        .filter((value) => Number.isFinite(value) && value > 0),
      fee_rate_bps: Number(sourceFormData.feeRateBps),
      missing_cost_warn_qty: Number(sourceFormData.missingCostWarnQty),
      maker_reward_ratio: Number(sourceFormData.makerRewardRatio),
      concurrency: Number(sourceFormData.concurrency),
      page_limit: Number(sourceFormData.pageLimit),
      request_timeout_sec: 20,
    };
  }

  async function handleStart(overrideFormData = null) {
    try {
      clearRunData();
      const payload = buildPayload(overrideFormData || formData);
      const created = await createRun(payload);

      setRunId(created.run_id);
      setRunStatus("PENDING");
      setRunning(true);
      attachStream(created.run_id);
    } catch (error) {
      setRunStatus("FAILED");
      pushWarning(`start failed: ${error.message || String(error)}`);
      message.error("Start failed");
    }
  }

  async function handleStop() {
    if (!runId) {
      return;
    }
    try {
      await stopRun(runId);
      setRunStatus("STOPPING");
    } catch (error) {
      pushWarning(`stop failed: ${error.message || String(error)}`);
    }
  }

  async function handleToggleRun() {
    if (running) {
      await handleStop();
      return;
    }
    await handleStart();
  }

  function handleReset() {
    closeStream();
    setRunId(null);
    setRunStatus("IDLE");
    setRunning(false);
    clearRunData();
  }

  return (
    <Layout className="page-layout">
      <div className="container">
        <StatusCard
          runStatus={runStatus}
          latestWarning={latestWarning}
          summary={summary}
          roi={roi}
          winRate={winRate}
          progressPercent={progressPercent}
        />

        <ConfigPanel
          formData={formData}
          updateField={updateField}
          downloads={downloads}
          onOpenAdvanced={() => setAdvancedOpen(true)}
          onToggleRun={handleToggleRun}
          onReset={handleReset}
          running={running}
          runStatus={runStatus}
        />

        <PnlCharts
          totalSeries={totalSeries}
          totalSeriesNoFee={totalSeriesNoFee}
          symbolSeries={symbolSeries}
          symbolSeriesNoFee={symbolSeriesNoFee}
          drawdownMarkers={drawdownMarkers}
        />

        <QuantMetricsPanel totalSeries={totalSeries} totalSeriesNoFee={totalSeriesNoFee} markets={markets} />

        <InsightCharts sessionAnalytics={sessionAnalytics} peakNotionalCapUsdc={formData.peakNotionalCapUsdc} />

        <MarketTable markets={markets} />
      </div>

      <AdvancedModal open={advancedOpen} onClose={() => setAdvancedOpen(false)} formData={formData} updateField={updateField} />
    </Layout>
  );
}
