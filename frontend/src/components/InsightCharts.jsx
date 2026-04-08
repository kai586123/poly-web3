import { useMemo } from "react";
import * as echarts from "echarts";
import ReactECharts from "echarts-for-react";
import { Card, Col, Row, Typography } from "antd";

const { Text } = Typography;

function barGradient(positive) {
  if (positive) {
    return new echarts.graphic.LinearGradient(0, 0, 0, 1, [
      { offset: 0, color: "#5eead4" },
      { offset: 1, color: "#2ca7b4" },
    ]);
  }
  return new echarts.graphic.LinearGradient(0, 0, 0, 1, [
    { offset: 0, color: "#fdba74" },
    { offset: 1, color: "#ea580c" },
  ]);
}

const neutralGrad = new echarts.graphic.LinearGradient(0, 0, 0, 1, [
  { offset: 0, color: "#cbd5e1" },
  { offset: 1, color: "#94a3b8" },
]);

function formatUsd(value) {
  const amount = Number(value || 0);
  const sign = amount < 0 ? "−" : "";
  return `${sign}$${Math.abs(amount).toFixed(4)}`;
}

function formatBucketLabel(row) {
  const start = Number(row?.bin_start_price || 0);
  const end = Number(row?.bin_end_price || 0);
  const close = end >= 1 ? "]" : ")";
  return `[${start.toFixed(2)}, ${end.toFixed(2)}${close}`;
}

function formatTooltipDetails(title, row) {
  return [
    `<b>${title}</b>`,
    `Weighted return: <b>${Number(row?.weighted_return_on_open_notional_pct || 0).toFixed(2)}%</b>`,
    `Win rate: <b>${Number(row?.win_rate_pct || 0).toFixed(2)}%</b>`,
    `Unweighted mean: <b>${Number(row?.average_return_on_open_notional_pct || 0).toFixed(2)}%</b>`,
    `Closed sessions: <b>${Number(row?.session_count || 0)}</b>`,
    `Open notional: <b>${formatUsd(row?.sum_open_notional_usdc)}</b>`,
    `Realized PnL: <b>${formatUsd(row?.sum_realized_pnl_usdc)}</b>`,
  ].join("<br/>");
}

function buildPriceAxisRange(rows) {
  if (!Array.isArray(rows) || rows.length <= 0) {
    return { min: 0, max: 1, scale: false };
  }

  const minStart = Math.min(...rows.map((row) => Number(row?.bin_start_price || 0)));
  const maxEnd = Math.max(...rows.map((row) => Number(row?.bin_end_price || 0)));
  const paddedMin = Math.max(0, Math.floor((minStart - 0.01) * 100) / 100);
  const paddedMax = Math.min(1, Math.ceil((maxEnd + 0.01) * 100) / 100);
  const hasRoom = paddedMax - paddedMin > 0.03;

  return {
    min: hasRoom ? paddedMin : Math.max(0, minStart - 0.01),
    max: hasRoom ? paddedMax : Math.min(1, maxEnd + 0.01),
    scale: true,
  };
}

export default function InsightCharts({ sessionAnalytics }) {
  const diagnostics = sessionAnalytics?.diagnostics || {};
  const hourRows =
    Array.isArray(sessionAnalytics?.open_hour_buckets) && sessionAnalytics.open_hour_buckets.length === 24
      ? sessionAnalytics.open_hour_buckets
      : Array.from({ length: 24 }, (_, hour) => ({
          hour_utc: hour,
          session_count: 0,
          weighted_return_on_open_notional_pct: 0,
          average_return_on_open_notional_pct: 0,
          win_rate_pct: 0,
          sum_realized_pnl_usdc: 0,
          sum_open_notional_usdc: 0,
        }));
  const priceRows = Array.isArray(sessionAnalytics?.open_price_buckets) ? sessionAnalytics.open_price_buckets : [];
  const eligibleSessionCount = Number(diagnostics.chart_eligible_sessions || 0);

  const hourlyOption = useMemo(() => {
    const categories = hourRows.map((row) => `${String(Number(row.hour_utc || 0)).padStart(2, "0")}:00`);
    const data = hourRows.map((row) => {
      const val = Number(row.weighted_return_on_open_notional_pct || 0);
      let color = neutralGrad;
      if (val > 0) {
        color = barGradient(true);
      } else if (val < 0) {
        color = barGradient(false);
      }
      return {
        value: val,
        raw: row,
        itemStyle: {
          borderRadius: [6, 6, 2, 2],
          color,
          borderColor: "rgba(255,255,255,0.45)",
          borderWidth: 1,
        },
      };
    });

    return {
      animationDuration: 420,
      title: {
        text: "Average Return by Session Open Hour",
        subtext: "Closed flat-to-flat sessions, grouped by the UTC hour of the first BUY that opened the session",
        left: 14,
        top: 6,
        textStyle: { color: "#213047", fontWeight: 700, fontSize: 17 },
        subtextStyle: { color: "#617089", fontSize: 11, lineHeight: 14 },
      },
      grid: { left: 56, right: 18, top: 72, bottom: 36, containLabel: true },
      tooltip: {
        trigger: "axis",
        backgroundColor: "rgba(255,255,255,0.96)",
        borderColor: "#d5deec",
        borderWidth: 1,
        textStyle: { color: "#213047", fontSize: 12 },
        axisPointer: { type: "shadow", shadowStyle: { color: "rgba(44,167,180,0.08)" } },
        formatter: (params) => {
          const row = Array.isArray(params) ? params[0]?.data?.raw : params?.data?.raw;
          if (!row) {
            return "";
          }
          return formatTooltipDetails(`${categories[Number(row.hour_utc || 0)]} UTC`, row);
        },
      },
      xAxis: {
        type: "category",
        data: categories,
        axisLabel: { color: "#617089", fontSize: 11, interval: 1 },
        axisTick: { alignWithLabel: true },
        axisLine: { lineStyle: { color: "rgba(146,160,181,0.35)" } },
      },
      yAxis: {
        type: "value",
        axisLabel: {
          color: "#617089",
          formatter: (value) => `${Number(value).toFixed(1)}%`,
        },
        splitLine: { lineStyle: { color: "rgba(146,160,181,0.2)" } },
      },
      series: [
        {
          name: "Weighted return",
          type: "bar",
          barMaxWidth: 18,
          emphasis: {
            focus: "series",
            itemStyle: { shadowBlur: 12, shadowColor: "rgba(33,48,71,0.12)" },
          },
          data,
        },
      ],
    };
  }, [hourRows]);

  const hourlyWinRateOption = useMemo(() => {
    const categories = hourRows.map((row) => `${String(Number(row.hour_utc || 0)).padStart(2, "0")}:00`);
    const data = hourRows.map((row) => ({
      value: Number(row.win_rate_pct || 0),
      raw: row,
      itemStyle: {
        borderRadius: [6, 6, 2, 2],
        color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
          { offset: 0, color: "#93c5fd" },
          { offset: 1, color: "#2563eb" },
        ]),
        borderColor: "rgba(255,255,255,0.45)",
        borderWidth: 1,
      },
    }));

    return {
      animationDuration: 420,
      title: {
        text: "Win Rate by Session Open Hour",
        subtext: "Same flat-to-flat sessions, bucketed by the UTC hour of the opening BUY",
        left: 14,
        top: 6,
        textStyle: { color: "#213047", fontWeight: 700, fontSize: 17 },
        subtextStyle: { color: "#617089", fontSize: 11, lineHeight: 14 },
      },
      grid: { left: 56, right: 18, top: 72, bottom: 36, containLabel: true },
      tooltip: {
        trigger: "axis",
        backgroundColor: "rgba(255,255,255,0.96)",
        borderColor: "#d5deec",
        borderWidth: 1,
        textStyle: { color: "#213047", fontSize: 12 },
        axisPointer: { type: "shadow", shadowStyle: { color: "rgba(37,99,235,0.08)" } },
        formatter: (params) => {
          const row = Array.isArray(params) ? params[0]?.data?.raw : params?.data?.raw;
          if (!row) {
            return "";
          }
          return formatTooltipDetails(`${categories[Number(row.hour_utc || 0)]} UTC`, row);
        },
      },
      xAxis: {
        type: "category",
        data: categories,
        axisLabel: { color: "#617089", fontSize: 11, interval: 1 },
        axisTick: { alignWithLabel: true },
        axisLine: { lineStyle: { color: "rgba(146,160,181,0.35)" } },
      },
      yAxis: {
        type: "value",
        min: 0,
        max: 100,
        name: "Win rate %",
        nameTextStyle: { color: "#617089", fontSize: 11 },
        axisLabel: {
          color: "#617089",
          formatter: (value) => `${Number(value).toFixed(0)}%`,
        },
        splitLine: { lineStyle: { color: "rgba(146,160,181,0.2)" } },
      },
      series: [
        {
          name: "Win rate",
          type: "bar",
          barMaxWidth: 18,
          emphasis: {
            focus: "series",
            itemStyle: { shadowBlur: 12, shadowColor: "rgba(33,48,71,0.12)" },
          },
          data,
        },
      ],
    };
  }, [hourRows]);

  const priceAxisRange = useMemo(() => buildPriceAxisRange(priceRows), [priceRows]);

  const priceOption = useMemo(() => {
    const data = priceRows.map((row) => {
      const start = Number(row.bin_start_price || 0);
      const end = Number(row.bin_end_price || 0);
      const x = (start + end) / 2;
      const y = Number(row.weighted_return_on_open_notional_pct || 0);
      const sessions = Number(row.session_count || 0);
      return {
        value: [x, y],
        symbolSize: Math.max(10, Math.min(34, 10 + Math.sqrt(Math.max(sessions, 0)) * 3.5)),
        raw: row,
        itemStyle: {
          color:
            y >= 0
              ? new echarts.graphic.RadialGradient(0.35, 0.35, 0.9, [
                  { offset: 0, color: "#6ee7b7" },
                  { offset: 1, color: "#059669" },
                ])
              : new echarts.graphic.RadialGradient(0.35, 0.35, 0.9, [
                  { offset: 0, color: "#fdba74" },
                  { offset: 1, color: "#c2410c" },
                ]),
          borderColor: "rgba(255,255,255,0.85)",
          borderWidth: 1.5,
          shadowBlur: 6,
          shadowColor: "rgba(33,48,71,0.12)",
        },
      };
    });

    return {
      animationDuration: 480,
      title: {
        text: "Average Return by Session Open Price Bucket",
        subtext: "Cross-market 0.01 price buckets using the session's BUY VWAP as the opening price",
        left: 14,
        top: 6,
        textStyle: { color: "#213047", fontWeight: 700, fontSize: 17 },
        subtextStyle: { color: "#617089", fontSize: 11, lineHeight: 14 },
      },
      grid: { left: 56, right: 22, top: 72, bottom: 44, containLabel: true },
      tooltip: {
        trigger: "item",
        backgroundColor: "rgba(255,255,255,0.96)",
        borderColor: "#d5deec",
        borderWidth: 1,
        textStyle: { color: "#213047", fontSize: 12 },
        formatter: (param) => {
          const row = param?.data?.raw || {};
          return formatTooltipDetails(formatBucketLabel(row), row);
        },
      },
      xAxis: {
        type: "value",
        min: priceAxisRange.min,
        max: priceAxisRange.max,
        scale: priceAxisRange.scale,
        name: "Open price bucket center",
        nameLocation: "middle",
        nameGap: 28,
        nameTextStyle: { color: "#617089", fontSize: 11 },
        axisLabel: { color: "#617089", formatter: (v) => Number(v).toFixed(2) },
        splitLine: { lineStyle: { color: "rgba(146,160,181,0.18)" } },
      },
      yAxis: {
        type: "value",
        name: "Weighted return %",
        nameTextStyle: { color: "#617089", fontSize: 11 },
        axisLabel: { color: "#617089", formatter: (v) => `${Number(v).toFixed(1)}%` },
        splitLine: { lineStyle: { color: "rgba(146,160,181,0.18)" } },
      },
      series: [
        {
          name: "Price buckets",
          type: "scatter",
          data,
          symbol: "circle",
          large: data.length > 120,
          largeThreshold: 120,
          emphasis: {
            scale: 1.08,
            itemStyle: { shadowBlur: 14, shadowColor: "rgba(44,167,180,0.25)" },
          },
        },
      ],
    };
  }, [priceAxisRange.max, priceAxisRange.min, priceAxisRange.scale, priceRows]);

  const priceWinRateOption = useMemo(() => {
    const data = priceRows.map((row) => {
      const start = Number(row.bin_start_price || 0);
      const end = Number(row.bin_end_price || 0);
      const x = (start + end) / 2;
      const y = Number(row.win_rate_pct || 0);
      const sessions = Number(row.session_count || 0);
      return {
        value: [x, y],
        symbolSize: Math.max(10, Math.min(34, 10 + Math.sqrt(Math.max(sessions, 0)) * 3.5)),
        raw: row,
        itemStyle: {
          color: new echarts.graphic.RadialGradient(0.35, 0.35, 0.9, [
            { offset: 0, color: "#93c5fd" },
            { offset: 1, color: "#1d4ed8" },
          ]),
          borderColor: "rgba(255,255,255,0.85)",
          borderWidth: 1.5,
          shadowBlur: 6,
          shadowColor: "rgba(33,48,71,0.12)",
        },
      };
    });

    return {
      animationDuration: 480,
      title: {
        text: "Win Rate by Session Open Price Bucket",
        subtext: "Each bucket uses the same session sample as the return scatter and treats exact open=close as half-win",
        left: 14,
        top: 6,
        textStyle: { color: "#213047", fontWeight: 700, fontSize: 17 },
        subtextStyle: { color: "#617089", fontSize: 11, lineHeight: 14 },
      },
      grid: { left: 56, right: 22, top: 72, bottom: 44, containLabel: true },
      tooltip: {
        trigger: "item",
        backgroundColor: "rgba(255,255,255,0.96)",
        borderColor: "#d5deec",
        borderWidth: 1,
        textStyle: { color: "#213047", fontSize: 12 },
        formatter: (param) => {
          const row = param?.data?.raw || {};
          return formatTooltipDetails(formatBucketLabel(row), row);
        },
      },
      xAxis: {
        type: "value",
        min: priceAxisRange.min,
        max: priceAxisRange.max,
        scale: priceAxisRange.scale,
        name: "Open price bucket center",
        nameLocation: "middle",
        nameGap: 28,
        nameTextStyle: { color: "#617089", fontSize: 11 },
        axisLabel: { color: "#617089", formatter: (v) => Number(v).toFixed(2) },
        splitLine: { lineStyle: { color: "rgba(146,160,181,0.18)" } },
      },
      yAxis: {
        type: "value",
        min: 0,
        max: 100,
        name: "Win rate %",
        nameTextStyle: { color: "#617089", fontSize: 11 },
        axisLabel: { color: "#617089", formatter: (v) => `${Number(v).toFixed(0)}%` },
        splitLine: { lineStyle: { color: "rgba(146,160,181,0.18)" } },
      },
      series: [
        {
          name: "Price bucket win rate",
          type: "scatter",
          data,
          symbol: "circle",
          large: data.length > 120,
          largeThreshold: 120,
          emphasis: {
            scale: 1.08,
            itemStyle: { shadowBlur: 14, shadowColor: "rgba(37,99,235,0.25)" },
          },
        },
      ],
    };
  }, [priceAxisRange.max, priceAxisRange.min, priceAxisRange.scale, priceRows]);

  const diagnosticsText = [
    `Eligible sessions: ${eligibleSessionCount}`,
    `Closed: ${Number(diagnostics.closed_sessions || 0)}`,
    `Open at window end: ${Number(diagnostics.excluded_open_session_count || 0)}`,
    `No trade entry: ${Number(diagnostics.excluded_no_trade_entry_count || 0)}`,
    `Warning-filtered: ${Number(diagnostics.excluded_warning_session_count || 0)}`,
  ].join(" · ");

  return (
    <Card className="chart-card insight-charts-card" bodyStyle={{ padding: 12 }}>
      <Row gutter={[12, 12]} align="stretch">
        <Col xs={24} lg={12}>
          <div className="chart-wrap chart-wrap-insights">
            {eligibleSessionCount <= 0 ? (
              <div className="insight-empty-hint">
                <Text type="secondary">No closed trade sessions with a trade-based opening price were found.</Text>
              </div>
            ) : (
              <ReactECharts option={hourlyOption} notMerge lazyUpdate style={{ height: "100%", width: "100%" }} />
            )}
          </div>
        </Col>
        <Col xs={24} lg={12}>
          <div className="chart-wrap chart-wrap-insights chart-wrap-scatter">
            {priceRows.length <= 0 ? (
              <div className="insight-empty-hint">
                <Text type="secondary">Price buckets appear after closed sessions with BUY-led openings are detected.</Text>
              </div>
            ) : (
              <ReactECharts option={priceOption} notMerge lazyUpdate style={{ height: "100%", width: "100%" }} />
            )}
          </div>
        </Col>
        <Col xs={24} lg={12}>
          <div className="chart-wrap chart-wrap-insights">
            {eligibleSessionCount <= 0 ? (
              <div className="insight-empty-hint">
                <Text type="secondary">Win-rate buckets need at least one closed trade session.</Text>
              </div>
            ) : (
              <ReactECharts option={hourlyWinRateOption} notMerge lazyUpdate style={{ height: "100%", width: "100%" }} />
            )}
          </div>
        </Col>
        <Col xs={24} lg={12}>
          <div className="chart-wrap chart-wrap-insights chart-wrap-scatter">
            {priceRows.length <= 0 ? (
              <div className="insight-empty-hint">
                <Text type="secondary">Win-rate price buckets appear after closed sessions with BUY-led openings are detected.</Text>
              </div>
            ) : (
              <ReactECharts option={priceWinRateOption} notMerge lazyUpdate style={{ height: "100%", width: "100%" }} />
            )}
          </div>
        </Col>
      </Row>
      <div style={{ padding: "8px 6px 2px" }}>
        <Text type="secondary">{diagnosticsText}</Text>
      </div>
    </Card>
  );
}
