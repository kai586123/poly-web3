import { useMemo } from "react";
import { Card, Col, Empty, Row, Statistic } from "antd";
import ReactECharts from "echarts-for-react";
import dayjs from "dayjs";
import { formatPct, formatUsd } from "../utils/format";

const EPS = 1e-12;

function mean(values) {
  if (!values.length) return 0;
  return values.reduce((acc, v) => acc + v, 0) / values.length;
}

function stddev(values) {
  if (!values.length) return 0;
  const m = mean(values);
  const variance = values.reduce((acc, v) => acc + (v - m) ** 2, 0) / values.length;
  return Math.sqrt(variance);
}

function buildStepDeltas(series) {
  const sorted = [...(series || [])].sort((a, b) => Number(a.ts) - Number(b.ts));
  return sorted.map((point, idx) => {
    const prev = idx === 0 ? 0 : Number(sorted[idx - 1].value || 0);
    const curr = Number(point.value || 0);
    return { ts: Number(point.ts), delta: curr - prev, cumulative: curr };
  });
}

function quantMetrics(totalSeries, totalSeriesNoFee, markets) {
  const deltas = buildStepDeltas(totalSeries);
  const deltaVals = deltas.map((d) => d.delta);
  const nonZero = deltaVals.filter((v) => Math.abs(v) > EPS);
  const wins = nonZero.filter((v) => v > 0);
  const losses = nonZero.filter((v) => v < 0);

  const grossProfit = wins.reduce((acc, v) => acc + v, 0);
  const grossLossAbs = Math.abs(losses.reduce((acc, v) => acc + v, 0));
  const profitFactor = grossLossAbs > EPS ? grossProfit / grossLossAbs : null;

  const avgDelta = mean(deltaVals);
  const vol = stddev(deltaVals);
  const downside = stddev(deltaVals.map((v) => (v < 0 ? v : 0)));
  const sharpe = vol > EPS ? (avgDelta / vol) * Math.sqrt(Math.max(deltaVals.length, 1)) : null;
  const sortino = downside > EPS ? (avgDelta / downside) * Math.sqrt(Math.max(deltaVals.length, 1)) : null;

  let peak = Number.NEGATIVE_INFINITY;
  let maxDrawdown = 0;
  const drawdownSeries = deltas.map((point) => {
    peak = Math.max(peak, point.cumulative);
    const dd = peak - point.cumulative;
    if (dd > maxDrawdown) maxDrawdown = dd;
    return { ts: point.ts, value: -dd };
  });

  const finalPnl = totalSeries.length ? Number(totalSeries[totalSeries.length - 1].value || 0) : 0;
  const finalNoFee = totalSeriesNoFee.length ? Number(totalSeriesNoFee[totalSeriesNoFee.length - 1].value || 0) : 0;
  const feeImpact = finalNoFee - finalPnl;

  const totalTrades = (markets || []).reduce(
    (acc, market) => acc + (market.tokens || []).reduce((tokenAcc, token) => tokenAcc + Number(token.trade_count || 0), 0),
    0,
  );

  const winRate = nonZero.length ? wins.length / nonZero.length : 0;
  const recovery = maxDrawdown > EPS ? finalPnl / maxDrawdown : null;

  return {
    finalPnl,
    feeImpact,
    maxDrawdown,
    profitFactor,
    winRate,
    sharpe,
    sortino,
    vol,
    recovery,
    totalTrades,
    deltas,
    deltaVals,
    drawdownSeries,
  };
}

function rollingSharpePoints(deltas, windowSize = 30) {
  if (deltas.length < windowSize) return [];
  const points = [];
  for (let i = windowSize - 1; i < deltas.length; i += 1) {
    const slice = deltas.slice(i - windowSize + 1, i + 1).map((x) => x.delta);
    const m = mean(slice);
    const s = stddev(slice);
    const value = s > EPS ? (m / s) * Math.sqrt(windowSize) : 0;
    points.push({ ts: deltas[i].ts, value });
  }
  return points;
}

function histogram(values, bins = 24) {
  if (!values.length) return { labels: [], counts: [] };
  const minVal = Math.min(...values);
  const maxVal = Math.max(...values);
  if (Math.abs(maxVal - minVal) < EPS) {
    return { labels: [minVal.toFixed(2)], counts: [values.length] };
  }

  const step = (maxVal - minVal) / bins;
  const counts = new Array(bins).fill(0);
  for (const value of values) {
    const idx = Math.min(bins - 1, Math.max(0, Math.floor((value - minVal) / step)));
    counts[idx] += 1;
  }

  const labels = counts.map((_, idx) => {
    const left = minVal + idx * step;
    const right = left + step;
    return `${left.toFixed(1)}~${right.toFixed(1)}`;
  });
  return { labels, counts };
}

function fmtTs(ts) {
  return dayjs(Number(ts) * 1000).format("MM/DD HH:mm");
}

function fmtStat(value, type = "number") {
  if (value == null || Number.isNaN(Number(value))) return "-";
  if (type === "usd") return formatUsd(value);
  if (type === "pct") return formatPct(Number(value) * 100);
  return Number(value).toFixed(3);
}

export default function QuantMetricsPanel({ totalSeries, totalSeriesNoFee, markets }) {
  const metrics = useMemo(() => quantMetrics(totalSeries, totalSeriesNoFee, markets), [totalSeries, totalSeriesNoFee, markets]);

  const rollSharpe = useMemo(() => rollingSharpePoints(metrics.deltas, 30), [metrics.deltas]);
  const hist = useMemo(() => histogram(metrics.deltaVals, 24), [metrics.deltaVals]);

  const drawdownOption = useMemo(
    () => ({
      animation: false,
      title: { text: "Drawdown Curve", left: 12, top: 6, textStyle: { fontSize: 15, fontWeight: 700, color: "#2b3950" } },
      grid: { left: 70, right: 18, top: 42, bottom: 32, containLabel: true },
      tooltip: {
        trigger: "axis",
        formatter: (params) => {
          const row = Array.isArray(params) ? params[0] : params;
          return `Time: ${dayjs(Number(row.axisValue) * 1000).format("YYYY-MM-DD HH:mm:ss")}<br/>Drawdown: ${Number(row.value).toFixed(4)}`;
        },
      },
      xAxis: {
        type: "category",
        boundaryGap: false,
        data: metrics.drawdownSeries.map((p) => p.ts),
        axisLabel: { color: "#607089", formatter: fmtTs, hideOverlap: true },
      },
      yAxis: {
        type: "value",
        axisLabel: { color: "#607089", formatter: (v) => Number(v).toFixed(2) },
        splitLine: { lineStyle: { color: "rgba(146,160,181,0.2)" } },
      },
      series: [
        {
          type: "line",
          name: "Drawdown",
          smooth: 0.2,
          showSymbol: false,
          lineStyle: { color: "#e05757", width: 2.2 },
          areaStyle: { color: "rgba(224,87,87,0.15)" },
          data: metrics.drawdownSeries.map((p) => p.value),
        },
      ],
    }),
    [metrics.drawdownSeries],
  );

  const histOption = useMemo(
    () => ({
      animation: false,
      title: { text: "PnL Increment Distribution", left: 12, top: 6, textStyle: { fontSize: 15, fontWeight: 700, color: "#2b3950" } },
      grid: { left: 58, right: 16, top: 42, bottom: 56, containLabel: true },
      tooltip: { trigger: "axis" },
      xAxis: {
        type: "category",
        data: hist.labels,
        axisLabel: { color: "#607089", rotate: 35, fontSize: 11 },
      },
      yAxis: {
        type: "value",
        axisLabel: { color: "#607089" },
        splitLine: { lineStyle: { color: "rgba(146,160,181,0.2)" } },
      },
      series: [
        {
          type: "bar",
          name: "Count",
          data: hist.counts,
          itemStyle: { color: "#4f7cff", borderRadius: [4, 4, 0, 0] },
          barMaxWidth: 18,
        },
      ],
    }),
    [hist],
  );

  const sharpeOption = useMemo(
    () => ({
      animation: false,
      title: { text: "Rolling Sharpe (Window=30)", left: 12, top: 6, textStyle: { fontSize: 15, fontWeight: 700, color: "#2b3950" } },
      grid: { left: 66, right: 16, top: 42, bottom: 34, containLabel: true },
      tooltip: {
        trigger: "axis",
        formatter: (params) => {
          const row = Array.isArray(params) ? params[0] : params;
          return `Time: ${dayjs(Number(row.axisValue) * 1000).format("YYYY-MM-DD HH:mm:ss")}<br/>Sharpe: ${Number(row.value).toFixed(4)}`;
        },
      },
      xAxis: {
        type: "category",
        boundaryGap: false,
        data: rollSharpe.map((p) => p.ts),
        axisLabel: { color: "#607089", formatter: fmtTs, hideOverlap: true },
      },
      yAxis: {
        type: "value",
        axisLabel: { color: "#607089", formatter: (v) => Number(v).toFixed(2) },
        splitLine: { lineStyle: { color: "rgba(146,160,181,0.2)" } },
      },
      series: [
        {
          type: "line",
          smooth: 0.2,
          showSymbol: false,
          lineStyle: { color: "#2ea66d", width: 2.3 },
          data: rollSharpe.map((p) => p.value),
        },
      ],
    }),
    [rollSharpe],
  );

  return (
    <Card className="quant-card" bodyStyle={{ padding: 12 }}>
      <Row gutter={[10, 10]}>
        <Col xs={12} md={8} lg={4}>
          <div className="metric-kpi"><Statistic title="Total PnL" value={fmtStat(metrics.finalPnl, "usd")} /></div>
        </Col>
        <Col xs={12} md={8} lg={4}>
          <div className="metric-kpi"><Statistic title="Fee Impact" value={fmtStat(metrics.feeImpact, "usd")} /></div>
        </Col>
        <Col xs={12} md={8} lg={4}>
          <div className="metric-kpi"><Statistic title="Max Drawdown" value={fmtStat(-metrics.maxDrawdown, "usd")} /></div>
        </Col>
        <Col xs={12} md={8} lg={4}>
          <div className="metric-kpi"><Statistic title="Profit Factor" value={fmtStat(metrics.profitFactor)} /></div>
        </Col>
        <Col xs={12} md={8} lg={4}>
          <div className="metric-kpi"><Statistic title="Win Rate" value={fmtStat(metrics.winRate, "pct")} /></div>
        </Col>
        <Col xs={12} md={8} lg={4}>
          <div className="metric-kpi"><Statistic title="Step Sharpe" value={fmtStat(metrics.sharpe)} /></div>
        </Col>
      </Row>

      {metrics.deltas.length < 2 ? (
        <div className="metrics-empty"><Empty description="Insufficient curve data" /></div>
      ) : (
        <Row gutter={[12, 12]} style={{ marginTop: 10 }}>
          <Col xs={24} xl={8}>
            <div className="metric-chart-wrap">
              <ReactECharts option={drawdownOption} notMerge lazyUpdate style={{ height: "100%", width: "100%" }} />
            </div>
          </Col>
          <Col xs={24} xl={8}>
            <div className="metric-chart-wrap">
              <ReactECharts option={histOption} notMerge lazyUpdate style={{ height: "100%", width: "100%" }} />
            </div>
          </Col>
          <Col xs={24} xl={8}>
            <div className="metric-chart-wrap">
              <ReactECharts option={sharpeOption} notMerge lazyUpdate style={{ height: "100%", width: "100%" }} />
            </div>
          </Col>
        </Row>
      )}
    </Card>
  );
}
