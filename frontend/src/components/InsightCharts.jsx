import { useEffect, useMemo, useState } from "react";
import * as echarts from "echarts";
import ReactECharts from "echarts-for-react";
import { Card, Col, Divider, Row, Select, Typography } from "antd";

const { Text, Title } = Typography;

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

const PEAK_DISPLAY_BIN_COUNT = 20;

function sessionWinScore(s) {
  const ret = s.return_on_open_notional_pct;
  if (ret != null && Number(ret) > 1e-9) {
    return 1;
  }
  if (
    s.open_avg_price != null &&
    s.close_avg_price != null &&
    Math.abs(Number(s.close_avg_price) - Number(s.open_avg_price)) <= 1e-9
  ) {
    return 0.5;
  }
  if (ret != null && Number(ret) < -1e-9) {
    return 0;
  }
  return 0.5;
}

const SESSION_PRICE_BIN_WIDTH = 0.01;
const SESSION_PRICE_BIN_COUNT = 100;

function marketOrderKey(slug) {
  try {
    const parts = String(slug || "").split("-");
    const last = parts[parts.length - 1];
    const n = parseInt(last, 10);
    if (Number.isFinite(n)) {
      return n;
    }
  } catch {
    /* ignore */
  }
  return 1e18;
}

function sortTradeSessions(sessions) {
  return [...sessions].sort((a, b) => {
    const mk = marketOrderKey(a.market_slug) - marketOrderKey(b.market_slug);
    if (mk !== 0) {
      return mk;
    }
    const st = Number(a.start_timestamp || 0) - Number(b.start_timestamp || 0);
    if (st !== 0) {
      return st;
    }
    return Number(a.end_timestamp || 0) - Number(b.end_timestamp || 0);
  });
}

function priceBucketIndex(price) {
  const clamped = Math.max(0, Math.min(Number(price), 1));
  if (clamped >= 1) {
    return SESSION_PRICE_BIN_COUNT - 1;
  }
  return Math.min(
    SESSION_PRICE_BIN_COUNT - 1,
    Math.max(0, Math.floor(clamped / SESSION_PRICE_BIN_WIDTH)),
  );
}

function buildDiagnosticsFromSessions(sessions) {
  const d = {
    total_detected_sessions: sessions.length,
    closed_sessions: sessions.length,
    chart_eligible_sessions: 0,
    excluded_open_session_count: 0,
    excluded_no_trade_entry_count: 0,
    excluded_zero_open_notional_count: 0,
    excluded_warning_session_count: 0,
  };
  for (const s of sessions) {
    if (s.is_chart_eligible) {
      d.chart_eligible_sessions += 1;
    } else if (s.exclusion_reason === "no_trade_entry") {
      d.excluded_no_trade_entry_count += 1;
    } else if (s.exclusion_reason === "zero_open_notional") {
      d.excluded_zero_open_notional_count += 1;
    } else {
      d.excluded_warning_session_count += 1;
    }
  }
  return d;
}

/** Rebuild hour/price buckets from trade sessions (matches backend session analytics logic). */
function rebuildSessionAnalyticsFromTradeSessions(sessions) {
  const ordered = sortTradeSessions(sessions);
  const diagnostics = buildDiagnosticsFromSessions(ordered);

  const hourAcc = {};
  for (let hour = 0; hour < 24; hour += 1) {
    hourAcc[hour] = { count: 0, sumPnl: 0, sumNotional: 0, sumReturn: 0, sumWinScore: 0 };
  }

  const priceAcc = new Map();

  for (const session of ordered) {
    if (
      !session.is_chart_eligible ||
      session.open_hour_utc == null ||
      session.open_avg_price == null ||
      session.return_on_open_notional_pct == null
    ) {
      continue;
    }
    const h = Number(session.open_hour_utc);
    const hourStats = hourAcc[h];
    hourStats.count += 1;
    hourStats.sumPnl += Number(session.realized_pnl_usdc || 0);
    hourStats.sumNotional += Number(session.open_notional_usdc || 0);
    hourStats.sumReturn += Number(session.return_on_open_notional_pct || 0);
    hourStats.sumWinScore += sessionWinScore(session);

    const pIdx = priceBucketIndex(session.open_avg_price);
    if (!priceAcc.has(pIdx)) {
      priceAcc.set(pIdx, { count: 0, sumPnl: 0, sumNotional: 0, sumReturn: 0, sumWinScore: 0 });
    }
    const pStats = priceAcc.get(pIdx);
    pStats.count += 1;
    pStats.sumPnl += Number(session.realized_pnl_usdc || 0);
    pStats.sumNotional += Number(session.open_notional_usdc || 0);
    pStats.sumReturn += Number(session.return_on_open_notional_pct || 0);
    pStats.sumWinScore += sessionWinScore(session);
  }

  const openHourBuckets = Array.from({ length: 24 }, (_, hour) => {
    const stats = hourAcc[hour];
    const cnt = stats.count;
    const sumNotional = stats.sumNotional;
    const wr = sumNotional > 1e-12 ? (stats.sumPnl / sumNotional) * 100 : 0;
    const ar = cnt ? stats.sumReturn / cnt : 0;
    const winr = cnt ? (stats.sumWinScore / cnt) * 100 : 0;
    return {
      hour_utc: hour,
      session_count: cnt,
      weighted_return_on_open_notional_pct: Math.round(wr * 1e6) / 1e6,
      average_return_on_open_notional_pct: Math.round(ar * 1e6) / 1e6,
      win_rate_pct: Math.round(winr * 1e6) / 1e6,
      sum_realized_pnl_usdc: Math.round(stats.sumPnl * 1e10) / 1e10,
      sum_open_notional_usdc: Math.round(stats.sumNotional * 1e10) / 1e10,
    };
  });

  const openPriceBuckets = [...priceAcc.keys()]
    .sort((a, b) => a - b)
    .map((idx) => {
      const stats = priceAcc.get(idx);
      const cnt = stats.count;
      const sumNotional = stats.sumNotional;
      const wr = sumNotional > 1e-12 ? (stats.sumPnl / sumNotional) * 100 : 0;
      const ar = cnt ? stats.sumReturn / cnt : 0;
      const winr = cnt ? (stats.sumWinScore / cnt) * 100 : 0;
      return {
        bin_index: idx,
        bin_start_price: Math.round(idx * SESSION_PRICE_BIN_WIDTH * 100) / 100,
        bin_end_price: Math.round(Math.min(1, (idx + 1) * SESSION_PRICE_BIN_WIDTH) * 100) / 100,
        session_count: cnt,
        weighted_return_on_open_notional_pct: Math.round(wr * 1e6) / 1e6,
        average_return_on_open_notional_pct: Math.round(ar * 1e6) / 1e6,
        win_rate_pct: Math.round(winr * 1e6) / 1e6,
        sum_realized_pnl_usdc: Math.round(stats.sumPnl * 1e10) / 1e10,
        sum_open_notional_usdc: Math.round(stats.sumNotional * 1e10) / 1e10,
      };
    });

  return {
    diagnostics,
    trade_sessions: ordered,
    open_hour_buckets: openHourBuckets,
    open_price_buckets: openPriceBuckets,
    open_peak_notional_buckets: [],
  };
}

function buildPeakDisplayBuckets(tradeSessions, capInput) {
  const list = Array.isArray(tradeSessions) ? tradeSessions : [];
  const eligible = list.filter(
    (s) =>
      s.is_chart_eligible &&
      s.open_hour_utc != null &&
      s.open_avg_price != null &&
      s.return_on_open_notional_pct != null,
  );
  if (eligible.length === 0) {
    return { rows: [], axisUpper: 0, usedDataMax: 0, usedUserCap: null };
  }

  const peaks = eligible.map((s) => Math.max(0, Number(s.peak_position_notional_usdc || 0)));
  const dataMax = Math.max(...peaks, 1e-12);

  let userCap = null;
  if (capInput !== null && capInput !== undefined && capInput !== "") {
    const n = typeof capInput === "number" ? capInput : Number(String(capInput).trim());
    if (Number.isFinite(n) && n > 0) {
      userCap = n;
    }
  }

  const axisMax = userCap != null ? userCap : dataMax;
  const width = axisMax / PEAK_DISPLAY_BIN_COUNT;

  const acc = Array.from({ length: PEAK_DISPLAY_BIN_COUNT }, (_, i) => ({
    bin_index: i,
    bin_start_usdc: i * width,
    bin_end_usdc: (i + 1) * width,
    session_count: 0,
    sum_pnl: 0,
    sum_notional: 0,
    sum_return: 0,
    sum_win_score: 0,
    sum_peak: 0,
    last_bin_has_overflow: false,
  }));

  for (const s of eligible) {
    const peak = Math.max(0, Number(s.peak_position_notional_usdc || 0));
    let idx;
    if (userCap != null && peak > axisMax + 1e-9) {
      idx = PEAK_DISPLAY_BIN_COUNT - 1;
      acc[idx].last_bin_has_overflow = true;
    } else if (peak >= axisMax - 1e-12) {
      idx = PEAK_DISPLAY_BIN_COUNT - 1;
    } else {
      idx = Math.min(PEAK_DISPLAY_BIN_COUNT - 1, Math.floor(peak / width));
    }

    const b = acc[idx];
    b.session_count += 1;
    b.sum_pnl += Number(s.realized_pnl_usdc || 0);
    b.sum_notional += Number(s.open_notional_usdc || 0);
    b.sum_return += Number(s.return_on_open_notional_pct || 0);
    b.sum_win_score += sessionWinScore(s);
    b.sum_peak += peak;
  }

  const rows = acc
    .filter((b) => b.session_count > 0)
    .map((b) => {
      const wr = b.sum_notional > 1e-12 ? (b.sum_pnl / b.sum_notional) * 100 : 0;
      const ar = b.session_count ? b.sum_return / b.session_count : 0;
      const wrate = b.session_count ? (b.sum_win_score / b.session_count) * 100 : 0;
      return {
        bin_index: b.bin_index,
        bin_start_usdc: Math.round(b.bin_start_usdc * 10000) / 10000,
        bin_end_usdc: Math.round(b.bin_end_usdc * 10000) / 10000,
        bin_count: PEAK_DISPLAY_BIN_COUNT,
        session_count: b.session_count,
        weighted_return_on_open_notional_pct: Math.round(wr * 1e6) / 1e6,
        average_return_on_open_notional_pct: Math.round(ar * 1e6) / 1e6,
        win_rate_pct: Math.round(wrate * 1e6) / 1e6,
        sum_realized_pnl_usdc: b.sum_pnl,
        sum_open_notional_usdc: b.sum_notional,
        sum_peak_position_notional_usdc: b.sum_peak,
        last_bin_has_overflow: b.last_bin_has_overflow,
      };
    });

  return {
    rows,
    axisUpper: axisMax,
    usedDataMax: dataMax,
    usedUserCap: userCap,
  };
}

function formatNotionalBucketLabel(row) {
  const start = Number(row?.bin_start_usdc || 0);
  const end = Number(row?.bin_end_usdc || 0);
  const idx = Number(row?.bin_index ?? 0);
  const totalBins = Number(row?.bin_count ?? PEAK_DISPLAY_BIN_COUNT);
  if (idx >= totalBins - 1 && row?.last_bin_has_overflow) {
    return `[${start.toFixed(0)} USDC, +∞)`;
  }
  return `[${start.toFixed(0)}, ${end.toFixed(0)}) USDC`;
}

function formatTooltipDetails(title, row) {
  const lines = [`<b>${title}</b>`];
  if (
    row?.sum_peak_position_notional_usdc != null &&
    Number(row?.session_count || 0) > 0
  ) {
    const avgPeak = Number(row.sum_peak_position_notional_usdc) / Number(row.session_count);
    lines.push(`Avg matched entry notional: <b>${formatUsd(avgPeak)}</b>`);
  }
  lines.push(
    `Weighted return: <b>${Number(row?.weighted_return_on_open_notional_pct || 0).toFixed(2)}%</b>`,
    `Win rate: <b>${Number(row?.win_rate_pct || 0).toFixed(2)}%</b>`,
    `Unweighted mean: <b>${Number(row?.average_return_on_open_notional_pct || 0).toFixed(2)}%</b>`,
    `Closed pairs: <b>${Number(row?.session_count || 0)}</b>`,
    `Entry notional: <b>${formatUsd(row?.sum_open_notional_usdc)}</b>`,
    `Realized PnL: <b>${formatUsd(row?.sum_realized_pnl_usdc)}</b>`,
  );
  return lines.join("<br/>");
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

function buildPeakChartAxisRange(axisUpper) {
  const u = Number(axisUpper || 0);
  if (!(u > 0)) {
    return { min: 0, max: 100, scale: false };
  }
  const pad = Math.max(u * 0.04, 1);
  return {
    min: 0,
    max: u + pad,
    scale: true,
  };
}

function parsePeakNotionalCap(value) {
  if (value === "" || value == null) {
    return undefined;
  }
  const n = Number(typeof value === "string" ? value.trim() : value);
  return Number.isFinite(n) && n > 0 ? n : undefined;
}

function SessionAnalyticsSection({ sectionLabel = "ALL", sessionAnalytics, peakNotionalCapUsdc = "" }) {
  const peakOrderCapUsdc = useMemo(() => parsePeakNotionalCap(peakNotionalCapUsdc), [peakNotionalCapUsdc]);

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
  const {
    rows: peakRows,
    axisUpper: peakAxisUpper,
    usedUserCap: peakUsedCap,
  } = useMemo(
    () => buildPeakDisplayBuckets(sessionAnalytics?.trade_sessions, peakOrderCapUsdc),
    [sessionAnalytics?.trade_sessions, peakOrderCapUsdc],
  );
  const peakAxisRange = useMemo(() => buildPeakChartAxisRange(peakAxisUpper), [peakAxisUpper]);
  const peakChartSubtext = useMemo(() => {
    if (!(peakAxisUpper > 0)) {
      return "";
    }
    if (peakUsedCap != null) {
      return `Matched entry notional = Σ(selected shares × entry price). X-axis 0–$${peakUsedCap.toFixed(0)} in ${PEAK_DISPLAY_BIN_COUNT} equal buckets (manual cap; larger pairs stack in last bucket).`;
    }
    return `Matched entry notional = Σ(selected shares × entry price). X-axis 0–$${peakAxisUpper.toFixed(0)} in ${PEAK_DISPLAY_BIN_COUNT} equal buckets (empty cap → use data max).`;
  }, [peakAxisUpper, peakUsedCap]);
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
        text: "Average Return by Pair Entry Hour",
        subtext: "BUY-block -> reduce-block pairs, grouped by the UTC hour of the matched entry BUY tail",
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
        text: "Win Rate by Pair Entry Hour",
        subtext: "Same pair sample, bucketed by the UTC hour of the matched entry BUY tail",
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
        text: "Average Return by Pair Entry Price Bucket",
        subtext: "Cross-market 0.01 price buckets using the matched BUY tail VWAP as the entry price",
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
        name: "Entry price bucket center",
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
        text: "Win Rate by Pair Entry Price Bucket",
        subtext: "Each bucket uses the same pair sample as the return scatter and treats exact entry=exit as half-win",
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
        name: "Entry price bucket center",
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

  const peakNotionalReturnOption = useMemo(() => {
    const data = peakRows.map((row) => {
      const start = Number(row.bin_start_usdc || 0);
      const end = Number(row.bin_end_usdc || 0);
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
                  { offset: 0, color: "#a7f3d0" },
                  { offset: 1, color: "#047857" },
                ])
              : new echarts.graphic.RadialGradient(0.35, 0.35, 0.9, [
                  { offset: 0, color: "#fde68a" },
                  { offset: 1, color: "#b45309" },
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
        text: "Average Return by Pair Entry Notional",
        subtext: peakChartSubtext || "Set max order size above, or leave empty to use data max; axis is split into 20 equal buckets.",
        left: 14,
        top: 6,
        textStyle: { color: "#213047", fontWeight: 700, fontSize: 17 },
        subtextStyle: { color: "#617089", fontSize: 11, lineHeight: 14 },
      },
      grid: { left: 56, right: 22, top: 80, bottom: 44, containLabel: true },
      tooltip: {
        trigger: "item",
        backgroundColor: "rgba(255,255,255,0.96)",
        borderColor: "#d5deec",
        borderWidth: 1,
        textStyle: { color: "#213047", fontSize: 12 },
        formatter: (param) => {
          const row = param?.data?.raw || {};
          return formatTooltipDetails(formatNotionalBucketLabel(row), row);
        },
      },
      xAxis: {
        type: "value",
        min: peakAxisRange.min,
        max: peakAxisRange.max,
        scale: peakAxisRange.scale,
        name: "Entry notional (USDC) bucket center",
        nameLocation: "middle",
        nameGap: 28,
        nameTextStyle: { color: "#617089", fontSize: 11 },
        axisLabel: { color: "#617089", formatter: (v) => `$${Number(v).toFixed(0)}` },
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
          name: "Peak notional buckets",
          type: "scatter",
          data,
          symbol: "circle",
          large: data.length > 120,
          largeThreshold: 120,
          emphasis: {
            scale: 1.08,
            itemStyle: { shadowBlur: 14, shadowColor: "rgba(4,120,87,0.25)" },
          },
        },
      ],
    };
  }, [peakAxisRange.max, peakAxisRange.min, peakAxisRange.scale, peakChartSubtext, peakRows]);

  const peakNotionalWinRateOption = useMemo(() => {
    const data = peakRows.map((row) => {
      const start = Number(row.bin_start_usdc || 0);
      const end = Number(row.bin_end_usdc || 0);
      const x = (start + end) / 2;
      const y = Number(row.win_rate_pct || 0);
      const sessions = Number(row.session_count || 0);
      return {
        value: [x, y],
        symbolSize: Math.max(10, Math.min(34, 10 + Math.sqrt(Math.max(sessions, 0)) * 3.5)),
        raw: row,
        itemStyle: {
          color: new echarts.graphic.RadialGradient(0.35, 0.35, 0.9, [
            { offset: 0, color: "#c4b5fd" },
            { offset: 1, color: "#5b21b6" },
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
        text: "Win Rate by Pair Entry Notional",
        subtext: peakChartSubtext
          ? `${peakChartSubtext} Win rate uses the same pair rules as other charts.`
          : "Same buckets as the return scatter; win rate uses the same pair rules as other charts.",
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
          return formatTooltipDetails(formatNotionalBucketLabel(row), row);
        },
      },
      xAxis: {
        type: "value",
        min: peakAxisRange.min,
        max: peakAxisRange.max,
        scale: peakAxisRange.scale,
        name: "Entry notional (USDC) bucket center",
        nameLocation: "middle",
        nameGap: 28,
        nameTextStyle: { color: "#617089", fontSize: 11 },
        axisLabel: { color: "#617089", formatter: (v) => `$${Number(v).toFixed(0)}` },
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
          name: "Peak notional win rate",
          type: "scatter",
          data,
          symbol: "circle",
          large: data.length > 120,
          largeThreshold: 120,
          emphasis: {
            scale: 1.08,
            itemStyle: { shadowBlur: 14, shadowColor: "rgba(91,33,182,0.25)" },
          },
        },
      ],
    };
  }, [peakAxisRange.max, peakAxisRange.min, peakAxisRange.scale, peakChartSubtext, peakRows]);

  const diagnosticsText = [
    `Eligible pairs: ${eligibleSessionCount}`,
    `Closed pairs: ${Number(diagnostics.closed_sessions || 0)}`,
    `No trade entry: ${Number(diagnostics.excluded_no_trade_entry_count || 0)}`,
    `Warning-filtered: ${Number(diagnostics.excluded_warning_session_count || 0)}`,
  ].join(" · ");

  return (
    <>
      <div style={{ padding: "4px 6px 10px" }}>
        <Title level={5} style={{ margin: 0 }}>
          {sectionLabel}
        </Title>
      </div>
      <Row gutter={[12, 12]} align="stretch">
        <Col xs={24} lg={12}>
          <div className="chart-wrap chart-wrap-insights">
            {eligibleSessionCount <= 0 ? (
              <div className="insight-empty-hint">
                <Text type="secondary">No BUY-block {"->"} reduce-block pairs with a trade-based entry price were found.</Text>
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
                <Text type="secondary">Price buckets appear after pair cycles with BUY-led entries are detected.</Text>
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
                <Text type="secondary">Win-rate buckets need at least one closed pair cycle.</Text>
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
                <Text type="secondary">Win-rate price buckets appear after pair cycles with BUY-led entries are detected.</Text>
              </div>
            ) : (
              <ReactECharts option={priceWinRateOption} notMerge lazyUpdate style={{ height: "100%", width: "100%" }} />
            )}
          </div>
        </Col>
        <Col xs={24} lg={12}>
          <div className="chart-wrap chart-wrap-insights chart-wrap-scatter">
            {eligibleSessionCount <= 0 || peakRows.length <= 0 ? (
              <div className="insight-empty-hint">
                <Text type="secondary">
                  Entry notional buckets appear after pair cycles; matched entry notional = Σ (selected shares × entry price).
                </Text>
              </div>
            ) : (
              <ReactECharts option={peakNotionalReturnOption} notMerge lazyUpdate style={{ height: "100%", width: "100%" }} />
            )}
          </div>
        </Col>
        <Col xs={24} lg={12}>
          <div className="chart-wrap chart-wrap-insights chart-wrap-scatter">
            {eligibleSessionCount <= 0 || peakRows.length <= 0 ? (
              <div className="insight-empty-hint">
                <Text type="secondary">Win rate by entry notional uses the same buckets as the return scatter.</Text>
              </div>
            ) : (
              <ReactECharts option={peakNotionalWinRateOption} notMerge lazyUpdate style={{ height: "100%", width: "100%" }} />
            )}
          </div>
        </Col>
      </Row>
      <div style={{ padding: "8px 6px 2px" }}>
        <Text type="secondary">{diagnosticsText}</Text>
      </div>
    </>
  );
}

export default function InsightCharts({
  sessionAnalytics,
  sessionAnalyticsBySide = {},
  peakNotionalCapUsdc = "",
  sourceAddresses: rawSourceAddresses = [],
}) {
  const sourceAddresses = Array.isArray(rawSourceAddresses) ? rawSourceAddresses : [];
  const [walletFilter, setWalletFilter] = useState("all");

  useEffect(() => {
    setWalletFilter("all");
  }, [sourceAddresses.join(",")]);

  const hasProvenance =
    sourceAddresses.length > 1 && (sessionAnalytics?.trade_sessions || []).some((s) => s.source_address);

  const filteredAll = useMemo(() => {
    const list = sessionAnalytics?.trade_sessions || [];
    if (!hasProvenance || walletFilter === "all") {
      return sessionAnalytics;
    }
    const filt = list.filter((s) => s.source_address === walletFilter);
    return rebuildSessionAnalyticsFromTradeSessions(filt);
  }, [hasProvenance, walletFilter, sessionAnalytics]);

  const filteredBySide = useMemo(() => {
    if (!hasProvenance || walletFilter === "all") {
      return sessionAnalyticsBySide;
    }
    const yesList = sessionAnalyticsBySide?.YES?.trade_sessions || [];
    const noList = sessionAnalyticsBySide?.NO?.trade_sessions || [];
    return {
      YES: rebuildSessionAnalyticsFromTradeSessions(yesList.filter((s) => s.source_address === walletFilter)),
      NO: rebuildSessionAnalyticsFromTradeSessions(noList.filter((s) => s.source_address === walletFilter)),
    };
  }, [hasProvenance, walletFilter, sessionAnalyticsBySide]);

  const cardTitle = (
    <div style={{ display: "flex", flexWrap: "wrap", gap: 10, alignItems: "center" }}>
      <span style={{ fontWeight: 600 }}>Pair-cycle analytics</span>
      {sourceAddresses.length > 1 ? (
        <Text type="secondary" style={{ fontSize: 12, maxWidth: 560 }}>
          Portfolio view stacks sessions from each wallet; multi-wallet runs also write per-wallet JSON next to the merged export.
        </Text>
      ) : null}
      {hasProvenance ? (
        <Select
          size="small"
          value={walletFilter}
          onChange={setWalletFilter}
          style={{ minWidth: 260 }}
          options={[
            { value: "all", label: "All wallets" },
            ...sourceAddresses.map((addr) => ({ value: addr, label: addr })),
          ]}
        />
      ) : null}
    </div>
  );

  return (
    <Card className="chart-card insight-charts-card" bodyStyle={{ padding: 12 }} title={cardTitle}>
      <SessionAnalyticsSection sectionLabel="ALL" sessionAnalytics={filteredAll} peakNotionalCapUsdc={peakNotionalCapUsdc} />
      <Divider style={{ margin: "18px 0" }} />
      <SessionAnalyticsSection
        sectionLabel="YES"
        sessionAnalytics={filteredBySide?.YES}
        peakNotionalCapUsdc={peakNotionalCapUsdc}
      />
      <Divider style={{ margin: "18px 0" }} />
      <SessionAnalyticsSection
        sectionLabel="NO"
        sessionAnalytics={filteredBySide?.NO}
        peakNotionalCapUsdc={peakNotionalCapUsdc}
      />
    </Card>
  );
}
