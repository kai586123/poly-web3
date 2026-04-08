import { COLOR_PALETTE } from "../constants";

export function formatUsd(value) {
  const v = Number(value || 0);
  return `${v < 0 ? "-" : ""}$${Math.abs(v).toLocaleString(undefined, {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })}`;
}

export function formatPct(value) {
  return `${Number(value || 0).toFixed(1)}%`;
}

export function symbolColor(symbol) {
  let hash = 0;
  const key = String(symbol || "unknown").toLowerCase();
  for (let i = 0; i < key.length; i += 1) {
    hash = (hash * 31 + key.charCodeAt(i)) >>> 0;
  }
  return COLOR_PALETTE[hash % COLOR_PALETTE.length];
}
