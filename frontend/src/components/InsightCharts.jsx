import { useMemo } from "react";
import * as echarts from "echarts";
import ReactECharts from "echarts-for-react";
import { Card, Col, Row, Typography } from "antd";

const { Text } = Typography;

function compactSlug(slug, maxLen = 30) {
  const text = String(slug || "");
  if (text.length <= maxLen) {
    return text;
  }
  return `${text.slice(0, maxLen - 1)}…`;
}

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

export default function InsightCharts({ hourlyPnl, scatterPoints }) {
  const hourlyOption = useMemo(() => {
    const buckets = hourlyPnl?.length === 24 ? hourlyPnl : Array(24).fill(0);
    const categories = Array.from({ length: 24 }, (_, i) => `${String(i).padStart(2, "0")}:00`);

    const data = buckets.map((raw) => {
      const val = Number(raw || 0);
      let color = neutralGrad;
      if (val > 0) {
        color = barGradient(true);
      } else if (val < 0) {
        color = barGradient(false);
      }
      return {
        value: val,
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
        text: "Realized PnL by UTC hour",
        subtext: "24 bars — sum of incremental PnL when events occur in each clock hour (UTC)",
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
          const row = Array.isArray(params) ? params[0] : params;
          const idx = row?.dataIndex ?? 0;
          const v = Number(buckets[idx] || 0);
          const sign = v < 0 ? "−" : "";
          return `${categories[idx]} UTC<br/><b>${sign}$${Math.abs(v).toFixed(4)}</b> <span style="color:#617089">USDC</span>`;
        },
      },
      xAxis: {
        type: "category",
        data: categories,
        axisLabel: { color: "#617089", fontSize: 11, interval: 1, rotate: 0 },
        axisTick: { alignWithLabel: true },
        axisLine: { lineStyle: { color: "rgba(146,160,181,0.35)" } },
      },
      yAxis: {
        type: "value",
        axisLabel: {
          color: "#617089",
          formatter: (value) => Number(value).toFixed(2),
        },
        splitLine: { lineStyle: { color: "rgba(146,160,181,0.2)" } },
      },
      series: [
        {
          name: "Δ PnL",
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
  }, [hourlyPnl]);

  const scatterOption = useMemo(() => {
    const rows = Array.isArray(scatterPoints) ? scatterPoints : [];
    const data = rows.map((p) => {
      const x = Number(p.avg_entry_price ?? 0);
      const y = Number(p.return_on_cost_pct ?? 0);
      const pnl = Number(p.realized_pnl_usdc ?? 0);
      const notional = Number(p.buy_notional_usdc ?? 0);
      const sz = Math.max(10, Math.min(40, 10 + Math.sqrt(Math.max(notional, 0)) * 2.2));
      const win = pnl >= 0;
      return {
        value: [x, y],
        name: p.market_slug,
        symbolSize: sz,
        itemStyle: {
          color: win
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
        text: "Entry vs return",
        subtext: "Each point is one market: VWAP of BUY fills (token price) vs return on buy notional",
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
          const v = param?.data?.value || [];
          const x = Number(v[0] ?? 0);
          const y = Number(v[1] ?? 0);
          const name = param?.data?.name || param?.name || "";
          const row = rows.find((r) => r.market_slug === name) || {};
          const pnl = Number(row.realized_pnl_usdc ?? 0);
          const notional = Number(row.buy_notional_usdc ?? 0);
          return [
            `<b>${compactSlug(name, 42)}</b>`,
            `Avg entry: <b>${x.toFixed(4)}</b>`,
            `Return on cost: <b>${y.toFixed(2)}%</b>`,
            `Realized PnL: <b>$${pnl.toFixed(4)}</b>`,
            `Buy notional: <b>$${notional.toFixed(2)}</b>`,
          ].join("<br/>");
        },
      },
      xAxis: {
        type: "value",
        name: "Avg entry (USDC / share)",
        nameLocation: "middle",
        nameGap: 28,
        nameTextStyle: { color: "#617089", fontSize: 11 },
        axisLabel: { color: "#617089", formatter: (v) => Number(v).toFixed(2) },
        splitLine: { lineStyle: { color: "rgba(146,160,181,0.18)" } },
      },
      yAxis: {
        type: "value",
        name: "Return on cost %",
        nameTextStyle: { color: "#617089", fontSize: 11 },
        axisLabel: { color: "#617089", formatter: (v) => `${Number(v).toFixed(1)}%` },
        splitLine: { lineStyle: { color: "rgba(146,160,181,0.18)" } },
      },
      series: [
        {
          name: "Markets",
          type: "scatter",
          data,
          symbol: "circle",
          large: rows.length > 120,
          largeThreshold: 120,
          emphasis: {
            scale: 1.08,
            itemStyle: { shadowBlur: 14, shadowColor: "rgba(44,167,180,0.25)" },
          },
        },
      ],
    };
  }, [scatterPoints]);

  const emptyScatter = !(scatterPoints && scatterPoints.length);

  return (
    <Card className="chart-card insight-charts-card" bodyStyle={{ padding: 12 }}>
      <Row gutter={[12, 12]} align="stretch">
        <Col xs={24} lg={12}>
          <div className="chart-wrap chart-wrap-insights">
            <ReactECharts option={hourlyOption} notMerge lazyUpdate style={{ height: "100%", width: "100%" }} />
          </div>
        </Col>
        <Col xs={24} lg={12}>
          <div className="chart-wrap chart-wrap-insights chart-wrap-scatter">
            {emptyScatter ? (
              <div className="insight-empty-hint">
                <Text type="secondary">Scatter appears after a full run (per-market VWAP & return).</Text>
              </div>
            ) : (
              <ReactECharts option={scatterOption} notMerge lazyUpdate style={{ height: "100%", width: "100%" }} />
            )}
          </div>
        </Col>
      </Row>
    </Card>
  );
}
