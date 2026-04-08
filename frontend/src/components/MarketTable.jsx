import { useMemo } from "react";
import { Card, Col, Divider, Row, Table } from "antd";
import dayjs from "dayjs";
import ReactECharts from "echarts-for-react";
import { formatPct, formatUsd } from "../utils/format";

function marketTs(slug) {
  const ts = Number(String(slug || "").split("-").pop());
  if (!Number.isFinite(ts) || ts <= 0) {
    return null;
  }
  return ts;
}

function marketLocalTime(slug) {
  const ts = marketTs(slug);
  if (!ts) {
    return "-";
  }
  return dayjs(ts * 1000).format("YYYY-MM-DD HH:mm:ss");
}

function marketPrefix(slug) {
  const raw = String(slug || "").trim().toLowerCase();
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

function buildHistogram(values, bins = 12) {
  if (!values.length) {
    return { labels: [], counts: [] };
  }
  const min = Math.min(...values);
  const max = Math.max(...values);
  if (Math.abs(max - min) < 1e-12) {
    return { labels: [min.toFixed(2)], counts: [values.length] };
  }
  const step = (max - min) / bins;
  const counts = new Array(bins).fill(0);
  values.forEach((value) => {
    const idx = Math.min(bins - 1, Math.max(0, Math.floor((value - min) / step)));
    counts[idx] += 1;
  });
  const labels = counts.map((_item, idx) => {
    const start = min + idx * step;
    const end = start + step;
    return `${start.toFixed(1)}~${end.toFixed(1)}`;
  });
  return { labels, counts };
}

const columns = [
  {
    title: "Market",
    dataIndex: "market_slug",
    key: "market_slug",
    ellipsis: true,
    width: 280,
    sorter: (a, b) => String(a.market_slug || "").localeCompare(String(b.market_slug || "")),
  },
  {
    title: "Trade Time",
    key: "trade_time",
    width: 180,
    render: (_value, record) => marketLocalTime(record.market_slug),
    sorter: (a, b) => Number(marketTs(a.market_slug) || 0) - Number(marketTs(b.market_slug) || 0),
  },
  {
    title: "Realized PnL",
    dataIndex: "realized_pnl_usdc",
    key: "realized_pnl_usdc",
    render: (value) => formatUsd(value),
    sorter: (a, b) => Number(a.realized_pnl_usdc || 0) - Number(b.realized_pnl_usdc || 0),
  },
  {
    title: "Taker Fee",
    dataIndex: "taker_fee_usdc",
    key: "taker_fee_usdc",
    render: (value) => formatUsd(value),
    sorter: (a, b) => Number(a.taker_fee_usdc || 0) - Number(b.taker_fee_usdc || 0),
  },
  {
    title: "Maker Reward",
    dataIndex: "maker_reward_usdc",
    key: "maker_reward_usdc",
    render: (value) => formatUsd(value),
    sorter: (a, b) => Number(a.maker_reward_usdc || 0) - Number(b.maker_reward_usdc || 0),
  },
  {
    title: "End Pos Up",
    dataIndex: "ending_position_up",
    key: "ending_position_up",
    render: (value) => Number(value || 0).toFixed(4),
    sorter: (a, b) => Number(a.ending_position_up || 0) - Number(b.ending_position_up || 0),
  },
  {
    title: "End Pos Down",
    dataIndex: "ending_position_down",
    key: "ending_position_down",
    render: (value) => Number(value || 0).toFixed(4),
    sorter: (a, b) => Number(a.ending_position_down || 0) - Number(b.ending_position_down || 0),
  },
];

export default function MarketTable({ markets }) {
  const pivotRows = useMemo(() => {
    const agg = new Map();
    (markets || []).forEach((market) => {
      const prefix = marketPrefix(market.market_slug);
      if (!agg.has(prefix)) {
        agg.set(prefix, {
          market_prefix: prefix,
          markets_count: 0,
          win_count: 0,
          pnl_sum: 0,
          taker_fee_sum: 0,
          maker_reward_sum: 0,
        });
      }
      const row = agg.get(prefix);
      const pnl = Number(market.realized_pnl_usdc || 0);
      row.markets_count += 1;
      if (pnl > 0) {
        row.win_count += 1;
      }
      row.pnl_sum += pnl;
      row.taker_fee_sum += Number(market.taker_fee_usdc || 0);
      row.maker_reward_sum += Number(market.maker_reward_usdc || 0);
    });

    return [...agg.values()]
      .map((row) => {
        const count = Number(row.markets_count || 0);
        return {
          ...row,
          avg_pnl: count > 0 ? row.pnl_sum / count : 0,
          win_rate: count > 0 ? (row.win_count / count) * 100 : 0,
          fee_net: Number(row.maker_reward_sum || 0) - Number(row.taker_fee_sum || 0),
        };
      })
      .sort((a, b) => Number(b.pnl_sum || 0) - Number(a.pnl_sum || 0));
  }, [markets]);

  const pivotColumns = [
    {
      title: "Market Prefix",
      dataIndex: "market_prefix",
      key: "market_prefix",
      width: 160,
      sorter: (a, b) => String(a.market_prefix || "").localeCompare(String(b.market_prefix || "")),
    },
    {
      title: "Markets",
      dataIndex: "markets_count",
      key: "markets_count",
      width: 100,
      sorter: (a, b) => Number(a.markets_count || 0) - Number(b.markets_count || 0),
    },
    {
      title: "Win Rate",
      dataIndex: "win_rate",
      key: "win_rate",
      width: 120,
      render: (value) => formatPct(value),
      sorter: (a, b) => Number(a.win_rate || 0) - Number(b.win_rate || 0),
    },
    {
      title: "PnL Sum",
      dataIndex: "pnl_sum",
      key: "pnl_sum",
      width: 130,
      render: (value) => formatUsd(value),
      sorter: (a, b) => Number(a.pnl_sum || 0) - Number(b.pnl_sum || 0),
    },
    {
      title: "Avg PnL",
      dataIndex: "avg_pnl",
      key: "avg_pnl",
      width: 130,
      render: (value) => formatUsd(value),
      sorter: (a, b) => Number(a.avg_pnl || 0) - Number(b.avg_pnl || 0),
    },
    {
      title: "Taker Fee",
      dataIndex: "taker_fee_sum",
      key: "taker_fee_sum",
      width: 130,
      render: (value) => formatUsd(value),
      sorter: (a, b) => Number(a.taker_fee_sum || 0) - Number(b.taker_fee_sum || 0),
    },
    {
      title: "Maker Reward",
      dataIndex: "maker_reward_sum",
      key: "maker_reward_sum",
      width: 140,
      render: (value) => formatUsd(value),
      sorter: (a, b) => Number(a.maker_reward_sum || 0) - Number(b.maker_reward_sum || 0),
    },
    {
      title: "Fee Net",
      dataIndex: "fee_net",
      key: "fee_net",
      width: 130,
      render: (value) => formatUsd(value),
      sorter: (a, b) => Number(a.fee_net || 0) - Number(b.fee_net || 0),
    },
  ];

  const pnlByPrefixOption = useMemo(() => {
    const xData = pivotRows.map((row) => row.market_prefix);
    const yData = pivotRows.map((row) => Number(row.pnl_sum || 0));
    return {
      animation: false,
      title: {
        text: "PnL by Prefix",
        left: 12,
        top: 8,
        textStyle: { fontSize: 14, fontWeight: 700, color: "#2b3950" },
      },
      grid: { left: 52, right: 16, top: 44, bottom: 42, containLabel: true },
      tooltip: { trigger: "axis" },
      xAxis: { type: "category", data: xData, axisLabel: { color: "#607089" } },
      yAxis: {
        type: "value",
        axisLabel: { color: "#607089", formatter: (value) => Number(value).toFixed(2) },
        splitLine: { lineStyle: { color: "rgba(146,160,181,0.2)" } },
      },
      series: [
        {
          type: "bar",
          data: yData,
          itemStyle: {
            color: (params) => (Number(params.value || 0) >= 0 ? "#2ca7b4" : "#e05757"),
            borderRadius: [4, 4, 0, 0],
          },
          barMaxWidth: 28,
        },
      ],
    };
  }, [pivotRows]);

  const winRateOption = useMemo(() => {
    const xData = pivotRows.map((row) => row.market_prefix);
    const yData = pivotRows.map((row) => Number(row.win_rate || 0));
    return {
      animation: false,
      title: {
        text: "Win Rate by Prefix",
        left: 12,
        top: 8,
        textStyle: { fontSize: 14, fontWeight: 700, color: "#2b3950" },
      },
      grid: { left: 50, right: 16, top: 44, bottom: 42, containLabel: true },
      tooltip: { trigger: "axis", formatter: (params) => `${params?.[0]?.axisValue}: ${Number(params?.[0]?.value || 0).toFixed(1)}%` },
      xAxis: { type: "category", data: xData, axisLabel: { color: "#607089" } },
      yAxis: {
        type: "value",
        min: 0,
        max: 100,
        axisLabel: { color: "#607089", formatter: (value) => `${Number(value).toFixed(0)}%` },
        splitLine: { lineStyle: { color: "rgba(146,160,181,0.2)" } },
      },
      series: [
        {
          type: "bar",
          data: yData,
          itemStyle: { color: "#6f5ef9", borderRadius: [4, 4, 0, 0] },
          barMaxWidth: 28,
        },
      ],
    };
  }, [pivotRows]);

  const pnlDistOption = useMemo(() => {
    const values = (markets || []).map((item) => Number(item.realized_pnl_usdc || 0));
    const histogram = buildHistogram(values, 12);
    return {
      animation: false,
      title: {
        text: "PnL Distribution",
        left: 12,
        top: 8,
        textStyle: { fontSize: 14, fontWeight: 700, color: "#2b3950" },
      },
      grid: { left: 50, right: 16, top: 44, bottom: 58, containLabel: true },
      tooltip: { trigger: "axis" },
      xAxis: {
        type: "category",
        data: histogram.labels,
        axisLabel: { color: "#607089", rotate: 30, fontSize: 11 },
      },
      yAxis: {
        type: "value",
        axisLabel: { color: "#607089" },
        splitLine: { lineStyle: { color: "rgba(146,160,181,0.2)" } },
      },
      series: [
        {
          type: "bar",
          data: histogram.counts,
          itemStyle: { color: "#4f7cff", borderRadius: [4, 4, 0, 0] },
          barMaxWidth: 20,
        },
      ],
    };
  }, [markets]);

  return (
    <Card className="market-card" title="Market Summary" bodyStyle={{ padding: 0 }}>
      <div className="market-section">
        <Table
          size="small"
          rowKey="market_slug"
          columns={columns}
          dataSource={markets}
          pagination={{ pageSize: 8 }}
          scroll={{ x: 1160 }}
          sortDirections={["descend", "ascend"]}
        />
      </div>

      <Divider orientation="left" style={{ margin: "8px 0 12px" }}>
        Pivot Summary
      </Divider>

      <div className="market-section">
        <Table
          size="small"
          rowKey="market_prefix"
          columns={pivotColumns}
          dataSource={pivotRows}
          pagination={false}
          scroll={{ x: 980 }}
          sortDirections={["descend", "ascend"]}
        />
      </div>

      <Divider orientation="left" style={{ margin: "8px 0 12px" }}>
        Statistics
      </Divider>

      <div className="market-section">
        <Row gutter={[12, 12]}>
          <Col xs={24} xl={8}>
            <div className="market-chart-wrap">
              <ReactECharts option={pnlByPrefixOption} notMerge lazyUpdate style={{ height: "100%", width: "100%" }} />
            </div>
          </Col>
          <Col xs={24} xl={8}>
            <div className="market-chart-wrap">
              <ReactECharts option={winRateOption} notMerge lazyUpdate style={{ height: "100%", width: "100%" }} />
            </div>
          </Col>
          <Col xs={24} xl={8}>
            <div className="market-chart-wrap">
              <ReactECharts option={pnlDistOption} notMerge lazyUpdate style={{ height: "100%", width: "100%" }} />
            </div>
          </Col>
        </Row>
      </div>
    </Card>
  );
}
