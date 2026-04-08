import { useMemo, useState } from "react";
import ReactECharts from "echarts-for-react";
import dayjs from "dayjs";
import { Button, Card, Col, Row, Segmented, Space } from "antd";
import { symbolColor } from "../utils/format";

function axisTimeLabel(value) {
  return dayjs(Number(value) * 1000).format("MM/DD HH:mm");
}

function tooltipTimeLabel(value) {
  return dayjs(Number(value) * 1000).format("YYYY-MM-DD HH:mm:ss");
}

function formatLossUsdc(value) {
  const loss = Number(value || 0);
  return `${loss < 0 ? "-" : ""}$${Math.abs(loss).toFixed(4)}`;
}

function drawdownDetailLines(marker, index) {
  const ts = Number(marker?.ts || 0);
  return [
    `${index + 1}. ${marker?.slug || "-"}`,
    `Loss: ${formatLossUsdc(marker?.drawdown)}`,
    `TS: ${ts || "-"}`,
    `Local: ${tooltipTimeLabel(ts)}`,
  ];
}

function tooltipFormatter(params, drawdownByTs) {
  const rows = Array.isArray(params) ? params : [params];
  if (!rows.length) {
    return "";
  }
  const ts = Number(rows[0].axisValue);
  const lines = [`Time: ${tooltipTimeLabel(ts)}`];
  for (const row of rows) {
    const marker = row.marker || "";
    const seriesName = row.seriesName || "-";
    const value = Array.isArray(row.value) ? row.value[1] : row.value;
    const display = value == null ? "-" : Number(value).toFixed(4);
    lines.push(`${marker} ${seriesName}: ${display}`);
  }
  if (drawdownByTs?.has(ts)) {
    const markers = drawdownByTs.get(ts) || [];
    if (markers.length) {
      lines.push("---");
      lines.push("Drawdown Events:");
      markers.forEach((marker, index) => {
        lines.push(...drawdownDetailLines(marker, index));
      });
    }
  }
  return lines.join("<br/>");
}

function seriesMap(points) {
  const map = new Map();
  (points || []).forEach((point) => {
    map.set(Number(point.ts), Number(point.value || 0));
  });
  return map;
}

function alignedSeriesData(map, xData) {
  let started = false;
  let lastValue = null;
  return xData.map((ts) => {
    if (map.has(ts)) {
      started = true;
      lastValue = map.get(ts);
    }
    if (!started) {
      return null;
    }
    return lastValue;
  });
}

function unionSortedTimestamps(...maps) {
  const all = new Set();
  maps.forEach((map) => {
    map.forEach((_value, ts) => all.add(Number(ts)));
  });
  return [...all].sort((a, b) => a - b);
}

function hexToRgba(hex, alpha) {
  const value = String(hex || "").replace("#", "");
  if (value.length !== 6) {
    return `rgba(47,167,182,${alpha})`;
  }
  const r = Number.parseInt(value.slice(0, 2), 16);
  const g = Number.parseInt(value.slice(2, 4), 16);
  const b = Number.parseInt(value.slice(4, 6), 16);
  return `rgba(${r},${g},${b},${alpha})`;
}

function compactSlug(slug, maxLen = 22) {
  const text = String(slug || "");
  if (text.length <= maxLen) {
    return text;
  }
  return `${text.slice(0, maxLen - 1)}…`;
}

function marketPrefixColor(prefix) {
  const key = String(prefix || "").toLowerCase();
  if (key === "btc-5") {
    return "#4f7cff";
  }
  if (key === "btc-15") {
    return "#29a36a";
  }
  return symbolColor(key);
}

export default function PnlCharts({ totalSeries, totalSeriesNoFee, symbolSeries, symbolSeriesNoFee, drawdownMarkers }) {
  const [viewMode, setViewMode] = useState("net");
  const [showDrawdownMarks, setShowDrawdownMarks] = useState(false);

  const showNet = viewMode === "net" || viewMode === "compare";
  const showNoFee = viewMode === "no_fee" || viewMode === "compare";

  const totalOption = useMemo(() => {
    const netMap = seriesMap(totalSeries);
    const noFeeMap = seriesMap(totalSeriesNoFee);
    const xData = unionSortedTimestamps(showNet ? netMap : new Map(), showNoFee ? noFeeMap : new Map());

    const series = [];
    const drawdownByTs = new Map();
    if (showNet) {
      const netSeries = {
        name: "Net PnL",
        type: "line",
        color: "#2ca7b4",
        smooth: 0.32,
        smoothMonotone: "x",
        showSymbol: false,
        connectNulls: true,
        lineStyle: {
          width: 3,
          color: "#2ca7b4",
          cap: "round",
          join: "round",
        },
        data: alignedSeriesData(netMap, xData),
      };

      if (showDrawdownMarks) {
        const markerData = (drawdownMarkers || [])
          .map((marker) => {
            if (!netMap.has(marker.ts)) {
              return null;
            }
            const tsIndex = xData.indexOf(marker.ts);
            if (tsIndex < 0) {
              return null;
            }
            return {
              coord: [tsIndex, netMap.get(marker.ts)],
              ts: marker.ts,
              slug: marker.marketSlug,
              drawdown: marker.delta,
            };
          })
          .filter(Boolean);
        markerData.forEach((marker) => {
          if (!drawdownByTs.has(marker.ts)) {
            drawdownByTs.set(marker.ts, []);
          }
          drawdownByTs.get(marker.ts).push(marker);
        });

        if (markerData.length) {
          netSeries.markPoint = {
            symbol: "circle",
            symbolSize: 11,
            itemStyle: {
              color: "#ef4444",
              borderColor: "#ffffff",
              borderWidth: 1.5,
            },
            label: {
              show: true,
              position: "top",
              distance: 6,
              color: "#7f1d1d",
              fontSize: 10,
              backgroundColor: "rgba(255,255,255,0.9)",
              borderColor: "rgba(239,68,68,0.35)",
              borderWidth: 1,
              borderRadius: 4,
              padding: [2, 4],
              formatter: (params) => compactSlug(params?.data?.slug),
            },
            data: markerData,
            tooltip: {
              trigger: "item",
              formatter: (params) => {
                const data = params?.data || {};
                return drawdownDetailLines(data, 0).join("<br/>");
              },
            },
          };
        }
      }

      series.push(netSeries);
    }

    if (showNoFee) {
      series.push({
        name: "No-Fee PnL",
        type: "line",
        color: "#f59e0b",
        smooth: 0.32,
        smoothMonotone: "x",
        showSymbol: false,
        connectNulls: true,
        lineStyle: {
          width: 2.8,
          color: "#f59e0b",
          type: showNet ? "dashed" : "solid",
          cap: "round",
          join: "round",
        },
        data: alignedSeriesData(noFeeMap, xData),
      });
    }

    return {
      animation: false,
      title: {
        text: "Total PnL Curve",
        left: 14,
        top: 8,
        textStyle: {
          color: "#213047",
          fontWeight: 700,
          fontSize: 18,
        },
      },
      tooltip: {
        trigger: "axis",
        formatter: (params) => tooltipFormatter(params, showDrawdownMarks ? drawdownByTs : null),
      },
      legend: {
        top: 8,
        right: 18,
        icon: "rect",
        itemWidth: 12,
        itemHeight: 8,
      },
      grid: {
        left: 78,
        right: 30,
        top: 84,
        bottom: 44,
        containLabel: true,
      },
      xAxis: {
        type: "category",
        position: "bottom",
        boundaryGap: false,
        data: xData,
        axisLine: {
          onZero: false,
        },
        axisLabel: {
          color: "#617089",
          hideOverlap: true,
          formatter: axisTimeLabel,
        },
      },
      yAxis: {
        type: "value",
        axisLabel: {
          color: "#617089",
          formatter: (value) => Number(value).toFixed(2),
          margin: 12,
        },
        splitLine: {
          lineStyle: {
            color: "rgba(146,160,181,0.2)",
          },
        },
      },
      series,
    };
  }, [totalSeries, totalSeriesNoFee, showNet, showNoFee, showDrawdownMarks, drawdownMarkers]);

  const symbolOption = useMemo(() => {
    const symbolSet = new Set();
    if (showNet) {
      Object.keys(symbolSeries || {}).forEach((symbol) => symbolSet.add(symbol));
    }
    if (showNoFee) {
      Object.keys(symbolSeriesNoFee || {}).forEach((symbol) => symbolSet.add(symbol));
    }
    const symbols = [...symbolSet].sort();

    const mapsBySymbolNet = {};
    const mapsBySymbolNoFee = {};
    symbols.forEach((symbol) => {
      mapsBySymbolNet[symbol] = seriesMap((symbolSeries || {})[symbol] || []);
      mapsBySymbolNoFee[symbol] = seriesMap((symbolSeriesNoFee || {})[symbol] || []);
    });

    const allTsSet = new Set();
    symbols.forEach((symbol) => {
      const netMap = mapsBySymbolNet[symbol];
      const noFeeMap = mapsBySymbolNoFee[symbol];
      if (showNet) {
        netMap.forEach((_value, ts) => allTsSet.add(ts));
      }
      if (showNoFee) {
        noFeeMap.forEach((_value, ts) => allTsSet.add(ts));
      }
    });
    const xData = [...allTsSet].sort((a, b) => a - b);

    const series = [];
    const drawdownByTs = new Map();
    symbols.forEach((symbol) => {
      const baseColor = marketPrefixColor(symbol);

      if (showNet) {
        const netSeries = {
          name: symbol,
          type: "line",
          color: baseColor,
          smooth: 0.24,
          smoothMonotone: "x",
          showSymbol: false,
          connectNulls: true,
          lineStyle: {
            width: 2.6,
            color: baseColor,
            cap: "round",
            join: "round",
          },
          data: alignedSeriesData(mapsBySymbolNet[symbol], xData),
        };

        if (showDrawdownMarks) {
          const markerData = (drawdownMarkers || [])
            .filter((marker) => marker.marketPrefix === symbol)
            .map((marker) => {
              if (!mapsBySymbolNet[symbol].has(marker.ts)) {
                return null;
              }
              const tsIndex = xData.indexOf(marker.ts);
              if (tsIndex < 0) {
                return null;
              }
              return {
                coord: [tsIndex, mapsBySymbolNet[symbol].get(marker.ts)],
                ts: marker.ts,
                slug: marker.marketSlug,
                drawdown: marker.delta,
              };
            })
            .filter(Boolean);
          markerData.forEach((marker) => {
            if (!drawdownByTs.has(marker.ts)) {
              drawdownByTs.set(marker.ts, []);
            }
            drawdownByTs.get(marker.ts).push(marker);
          });

          if (markerData.length) {
            netSeries.markPoint = {
              symbol: "circle",
              symbolSize: 11,
              itemStyle: {
                color: "#ef4444",
                borderColor: "#ffffff",
                borderWidth: 1.5,
              },
              label: {
                show: true,
                position: "top",
                distance: 6,
                color: "#7f1d1d",
                fontSize: 10,
                backgroundColor: "rgba(255,255,255,0.9)",
                borderColor: "rgba(239,68,68,0.35)",
                borderWidth: 1,
                borderRadius: 4,
                padding: [2, 4],
                formatter: (params) => compactSlug(params?.data?.slug),
              },
              data: markerData,
              tooltip: {
                trigger: "item",
                formatter: (params) => {
                  const data = params?.data || {};
                  return drawdownDetailLines(data, 0).join("<br/>");
                },
              },
            };
          }
        }

        series.push(netSeries);
      }

      if (showNoFee) {
        series.push({
          name: showNet ? `${symbol} (No Fee)` : symbol,
          type: "line",
          color: showNet ? hexToRgba(baseColor, 0.8) : baseColor,
          smooth: 0.24,
          smoothMonotone: "x",
          showSymbol: false,
          connectNulls: true,
          lineStyle: {
            width: 2.4,
            color: showNet ? hexToRgba(baseColor, 0.8) : baseColor,
            type: showNet ? "dashed" : "solid",
            cap: "round",
            join: "round",
          },
          data: alignedSeriesData(mapsBySymbolNoFee[symbol], xData),
        });
      }
    });

    return {
      animation: false,
      title: {
        text: "Market Prefix PnL Curve",
        left: 14,
        top: 8,
        textStyle: {
          color: "#213047",
          fontWeight: 700,
          fontSize: 18,
        },
      },
      tooltip: {
        trigger: "axis",
        formatter: (params) => tooltipFormatter(params, showDrawdownMarks ? drawdownByTs : null),
      },
      legend: {
        type: "scroll",
        top: 38,
        left: 14,
        right: 16,
        icon: "rect",
        itemWidth: 12,
        itemHeight: 8,
      },
      grid: {
        left: 78,
        right: 30,
        top: 122,
        bottom: 44,
        containLabel: true,
      },
      xAxis: {
        type: "category",
        position: "bottom",
        boundaryGap: false,
        data: xData,
        axisLine: {
          onZero: false,
        },
        axisLabel: {
          color: "#617089",
          hideOverlap: true,
          formatter: axisTimeLabel,
        },
      },
      yAxis: {
        type: "value",
        axisLabel: {
          color: "#617089",
          formatter: (value) => Number(value).toFixed(2),
          margin: 12,
        },
        splitLine: {
          lineStyle: {
            color: "rgba(146,160,181,0.2)",
          },
        },
      },
      series,
    };
  }, [symbolSeries, symbolSeriesNoFee, showNet, showNoFee, showDrawdownMarks, drawdownMarkers]);

  return (
    <Card
      className="chart-card"
      bodyStyle={{ padding: 12 }}
      extra={
        <Space size={8}>
          <Button size="small" type={showDrawdownMarks ? "primary" : "default"} onClick={() => setShowDrawdownMarks((v) => !v)}>
            {showDrawdownMarks ? "Hide Drawdown Slug" : "Show Drawdown Slug"}
          </Button>
          <Segmented
            value={viewMode}
            onChange={setViewMode}
            options={[
              { label: "Net", value: "net" },
              { label: "No Fee", value: "no_fee" },
              { label: "Compare", value: "compare" },
            ]}
          />
        </Space>
      }
    >
      <Row gutter={[12, 12]}>
        <Col xs={24} lg={12}>
          <div className="chart-wrap">
            <ReactECharts option={totalOption} notMerge lazyUpdate style={{ height: "100%", width: "100%" }} />
          </div>
        </Col>
        <Col xs={24} lg={12}>
          <div className="chart-wrap">
            <ReactECharts option={symbolOption} notMerge lazyUpdate style={{ height: "100%", width: "100%" }} />
          </div>
        </Col>
      </Row>
    </Card>
  );
}
