// Tiny typed fetch wrapper for the FastAPI backend. Same-origin in prod
// (FastAPI serves dist/), proxied via Vite in dev.

// eslint-disable-next-line @typescript-eslint/no-explicit-any
export type ConfigData = Record<string, any>;

export type PutConfigResult = {
  ok: boolean;
  updated: boolean;
  restart_required: string[];
  message: string;
};

export type ConditionFlag = { name: string; passed: boolean };

export type RecentAlert = {
  time: string | null;
  timestamp_ist: string | null;
  symbol: string | null;
  strike: number | null;
  option_type: string | null;
  relation: string | null;
  conditions: ConditionFlag[];
  conditions_passed_count: number;
  conditions_total: number;
  status: string | null;
  risk: number | null;
  entry: number | null;
  lots: number | null;
  notes: string | null;
};

export type PnlDay = { date: string; realized_pnl: number; is_profit: boolean };
export type CumulativePoint = { date: string; net: number };
export type PnlTotals = {
  total_pnl: number;
  realized_pnl: number;
  unrealized_pnl: number;
  max_daily_profit: number;
  max_daily_loss: number;
};
export type PnlSeries = {
  window_days: number;
  days: PnlDay[];
  cumulative: CumulativePoint[];
  totals: PnlTotals;
};

export type OpenPosition = {
  symbol: string | null;
  option_type: string | null;
  strike: number | null;
  relation: string | null;
  status: string | null;
  entry_time: string | null;
  qty_lots: number | null;
  buy_price: number | null;
  ltp: number | null;
  sl: number | null;
  tp1: number | null;
  tp2: number | null;
  pnl: number | null;
  price_series: Array<{ t: string; price: number }>;
};

export type ConditionBucket = { label: string; count: number; pct: number };
export type ConditionSummary = { total_scans: number; buckets: ConditionBucket[] };

export type TradePlan = {
  max_trades_per_day: number;
  trades_taken: number;
  trades_remaining: number;
  daily_sl_hit: number;
  max_sl_per_day: number;
  cooldown_active: boolean;
  same_strike_sl_count: number;
};

export type ReentryStatus = {
  cooldown_minutes: number;
  minutes_since_last_sl: number | null;
  same_strike_kill_enabled: boolean;
  strikes_locked_today: number[];
};

export type Overview = {
  feed: { active_feed: string; status: "RUNNING" | "STOPPED" };
  modes: { alert_mode: boolean; order_place_mode: boolean; paper_trade_mode: boolean };
  instruments: {
    nifty_enabled: boolean;
    banknifty_enabled: boolean;
    nifty_lot_size: number | null;
    banknifty_lot_size: number | null;
  };
  position: {
    nifty_max_lots: number | null;
    banknifty_max_lots: number | null;
    lot_cap_enabled: boolean;
  };
  today: {
    date_ist: string;
    market_status: "OPEN" | "CLOSED";
    current_time_ist: string;
    gap_day: boolean;
    signals_today: number;
    positions_open: number;
    sl_hit_today: number;
    paper_pnl_today: number;
    paper_pnl_pct_today: number;
    open_positions_count: number;
  };
  circuit_breakers: {
    sl_count: number;
    max_sl_per_day: number;
    daily_loss: number;
    max_loss_per_day: number;
    status: "OK" | "WARN" | "TRIPPED";
  };
  next_events: {
    last_entry_time: string | null;
    soft_squareoff_time: string | null;
    hard_squareoff_time: string | null;
    eod_summary_time: string | null;
    dashboard_sync_time: string | null;
  };
  recent_alerts: RecentAlert[];
  pnl_series: PnlSeries;
  open_position: OpenPosition | null;
  condition_summary: ConditionSummary;
  trade_plan: TradePlan;
  reentry_status: ReentryStatus;
  bot: BotStatus;
  last_synced_ist: string;
  date_ist: string;
};

export type BotStatus = {
  status: "RUNNING" | "STOPPED";
  last_activity_ist: string | null;
  uptime_seconds: number | null;
  next_health_check_ist: string | null;
  last_config_reload_ist: string | null;
};

async function getJSON<T>(path: string): Promise<T> {
  const r = await fetch(path, { headers: { Accept: "application/json" } });
  if (!r.ok) throw new Error(`${r.status} ${r.statusText} on ${path}`);
  return (await r.json()) as T;
}

async function putJSON<T>(path: string, body: unknown): Promise<T> {
  const r = await fetch(path, {
    method: "PUT",
    headers: { Accept: "application/json", "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!r.ok) {
    const payload = await r.json().catch(() => null);
    const msgs: string[] | undefined = payload?.detail?.errors;
    const str: string | undefined =
      typeof payload?.detail === "string" ? payload.detail : undefined;
    throw new Error(msgs?.join("; ") ?? str ?? `${r.status} ${r.statusText}`);
  }
  return (await r.json()) as T;
}

// ---- Trades & Performance + live open-position tracker (Phase F6) ----

export type LivePosition = {
  episode_id: string | null;
  alert_id: string | null;
  symbol: string | null;
  option_type: string | null;
  strike: number | null;
  relation: string | null;
  expiry: string | null;
  entry_time: string | null;
  qty_lots: number | null;
  lot_size: number | null;
  buy_price: number | null;
  sl: number | null;
  tp1: number | null;
  tp2: number | null;
  last_ltp: number | null;
  last_ltp_time: string | null;
  running_pnl: number | null;
  running_pnl_r: number | null;
  status: string | null;
  price_series: Array<{ time: string; price: number }>;
  bot_remark: string | null;
};

export type OpenPositionsResponse = {
  as_of: string | null;
  positions: LivePosition[];
};

export type TradeRow = {
  alert_id: string | null;
  episode_id: string | null;
  date: string | null;
  time: string | null;
  candle_timestamp: string | null;
  symbol: string | null;
  option_type: string | null;
  strike: number | null;
  relation: string | null;
  expiry: string | null;
  qty_lots: number | null;
  lot_size: number | null;
  buy_price: number | null;
  sell_price: number | null;
  sl: number | null;
  tp1: number | null;
  tp2: number | null;
  pnl: number | null;
  realized_R: number | null;
  status: string | null;
  outcome: string | null;
  exit_time: string | null;
  exit_reason: string | null;
  bot_remark: string | null;
};

export type TradesKpis = {
  total_trades: number;
  winning_trades: number;
  winning_pct: number;
  losing_trades: number;
  losing_pct: number;
  total_pnl: number;
  realized_pnl: number;
  unrealized_pnl: number;
  max_daily_profit: number;
  max_daily_loss: number;
};

export type DailySeriesPoint = {
  date: string;
  realized_pnl: number;
  is_profit: boolean;
  net: number;
};

export type TradeFilters = {
  date_from: string | null;
  date_to: string | null;
  symbol: string | null;
  option_type: string | null;
  status: string | null;
  outcome: string | null;
};

export type TradesResponse = {
  filters: TradeFilters;
  kpis: TradesKpis;
  trades: TradeRow[];
  daily_series: DailySeriesPoint[];
};

export type HistoryGroup = {
  period_label: string;
  period_start: string;
  total_trades: number;
  win_rate: number;
  total_pnl: number;
  realized_pnl: number;
  unrealized_pnl: number;
  max_profit: number;
  max_loss: number;
  trades: TradeRow[];
};

export type TradesHistoryResponse = {
  group_by: "day" | "week" | "month";
  filters: TradeFilters;
  groups: HistoryGroup[];
};

// ---- Paper Trading (F7) ----

export type PaperSelectionStatus = {
  max_trades_per_day: number;
  trades_taken: number;
  trades_remaining: number;
  daily_sl_hit: number;
  max_sl_per_day: number;
  cooldown_active: boolean;
  same_strike_sl_count: number;
};

export type PaperReentryStatus = {
  cooldown_minutes: number;
  minutes_since_last_sl: number | null;
  same_strike_kill_enabled: boolean;
  strikes_locked_today: number[];
};

export type PaperTodayResponse = {
  selection: PaperSelectionStatus;
  reentry: PaperReentryStatus;
};

export type EchoItem = {
  time: string | null;
  relation: string | null;
  price: number | null;
};

export type PaperEpisode = {
  episode_id: string | null;
  date: string | null;
  time: string | null;
  symbol: string | null;
  option_type: string | null;
  strike: number | null;
  relation: string | null;
  selection: "TAKEN" | "SKIPPED" | null;
  skip_reason: string | null;
  entry_price: number | null;
  sl: number | null;
  tp1: number | null;
  tp2: number | null;
  qty_lots: number | null;
  outcome: string | null;
  r_multiple: number | null;
  paper_pnl: number | null;
  mfe_r: number | null;
  mae_r: number | null;
  max_drawdown_r: number | null;
  echo_count: number;
  echoes: EchoItem[];
  is_overridden: boolean;
};

export type PaperEpisodesResponse = { episodes: PaperEpisode[] };

export type PaperOverridesResponse = {
  rows: Record<string, string>[];
  columns: string[];
};

// ---- Dashboard & Reports (F7a) ----

export type ReportKpi = {
  value: number | null;
  prev_value: number | null;
  delta_pct: number | null;
  spark: number[];
};

export type ReportKpis = {
  total_pnl: ReportKpi;
  total_trades: ReportKpi;
  win_rate: ReportKpi;
  profit_factor: ReportKpi;
  avg_win: ReportKpi;
  avg_loss: ReportKpi;
  expectancy: ReportKpi;
};

export type ReportCumulativePoint = { period: string; daily_pnl: number; cumulative_pnl: number };
export type ReportUnderlying = { symbol: string; pnl: number; pct: number };
export type ReportWeekday = { weekday: string; pnl: number };
export type ReportTopTrade = {
  date: string;
  time: string;
  symbol: string;
  option_type: string;
  strike: number | null;
  relation: string;
  pnl: number;
  outcome: string;
};
export type ReportOutcome = { outcome: string; count: number; pct: number };
export type ReportDuration = { bucket: string; trades: number; win_rate: number };
export type ReportMonthly = {
  month: string;
  total_trades: number;
  win_rate: number;
  total_pnl: number;
  realized_pnl: number;
  unrealized_pnl: number;
  profit_factor: number | null;
  max_profit: number;
  max_loss: number;
};

export type PerformanceReport = {
  kpis: ReportKpis;
  cumulative: ReportCumulativePoint[];
  pnl_by_underlying: ReportUnderlying[];
  pnl_by_weekday: ReportWeekday[];
  top_winners: ReportTopTrade[];
  top_losers: ReportTopTrade[];
  outcome_distribution: ReportOutcome[];
  trade_duration: ReportDuration[] | null;
  monthly: ReportMonthly[];
  meta: {
    date_from: string;
    date_to: string;
    prev_from: string | null;
    prev_to: string | null;
    agg: string;
  };
};

function buildQuery(params: Record<string, string | undefined | null>): string {
  const usp = new URLSearchParams();
  Object.entries(params).forEach(([k, v]) => {
    if (v != null && v !== "") usp.set(k, v);
  });
  const s = usp.toString();
  return s ? `?${s}` : "";
}

export const api = {
  overview: (date?: string) =>
    getJSON<Overview>(`/api/overview${date ? `?date=${encodeURIComponent(date)}` : ""}`),
  botStatus: () => getJSON<BotStatus>("/api/bot/status"),
  getConfig: () => getJSON<ConfigData>("/api/config"),
  putConfig: (changes: Record<string, unknown>) =>
    putJSON<PutConfigResult>("/api/config", changes),
  openPositions: () => getJSON<OpenPositionsResponse>("/api/positions/open"),
  trades: (params: Partial<TradeFilters> = {}) =>
    getJSON<TradesResponse>(`/api/trades${buildQuery(params as Record<string, string | undefined | null>)}`),
  tradesHistory: (
    params: Partial<TradeFilters> & { group_by?: "day" | "week" | "month" } = {},
  ) =>
    getJSON<TradesHistoryResponse>(
      `/api/trades/history${buildQuery(params as Record<string, string | undefined | null>)}`,
    ),
  paperToday: () => getJSON<PaperTodayResponse>("/api/paper/today"),
  paperEpisodes: (params: {
    date_from?: string;
    date_to?: string;
    status?: string;
    symbol?: string;
    option_type?: string;
  } = {}) => getJSON<PaperEpisodesResponse>(`/api/paper/episodes${buildQuery(params as Record<string, string | undefined | null>)}`),
  paperOverrides: () => getJSON<PaperOverridesResponse>("/api/paper/overrides"),
  reportsPerformance: (params: { date_from?: string; date_to?: string; agg?: string } = {}) =>
    getJSON<PerformanceReport>(`/api/reports/performance${buildQuery(params as Record<string, string | undefined | null>)}`),
};
