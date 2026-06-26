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
  untracked_count: number;
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
  sell_price_leg1: number | null;
  sell_price_leg2: number | null;
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

// ---- Dashboard & Reports F7b: Conditions + Risk ----

export type ConditionPassRate = {
  condition: string;
  label: string;
  status: "active" | "shadow" | "off";
  scans: number;
  passes: number;
  pass_rate: number;
};

export type FunnelBucket = { bucket: string; count: number };

export type BottleneckItem = { condition: string; blocked_count: number };

export type C5ShadowStats = {
  n: number;
  win_rate: number;
  avg_r: number;
};

export type C5ShadowReport = {
  alerts_total: number;
  c5_passed: number;
  c5_failed: number;
  c5_pass_rate: number;
  when_c5_passed: C5ShadowStats;
  when_c5_failed: C5ShadowStats;
  join_note?: string;
};

export type DIAlignment = {
  spot_aligned_pct: number;
  option_aligned_pct: number;
  note: string;
};

export type AdxBucket = {
  label: string;
  n: number;
  winners: number;
  losers: number;
  win_rate_pct: number | null;
};

export type AdxProfile = {
  n: number;
  avg_adx: number | null;
  median_adx: number | null;
  pct_rising: number | null;
  avg_spot_di_plus: number | null;
  avg_spot_di_minus: number | null;
  pct_spot_aligned: number | null;
  avg_opt_di_plus: number | null;
  avg_opt_di_minus: number | null;
  pct_opt_aligned: number | null;
  pct_c5_passed: number | null;
};

export type AdxConfigSnapshot = {
  adx_min: number;
  require_rising: boolean;
  use_di_alignment: boolean;
  gating: boolean;
  period: number;
};

export type AdxDeepDive = {
  config: AdxConfigSnapshot;
  join_coverage: { matched: number; total: number; pct: number; note: string | null };
  buckets: AdxBucket[];
  winner_profile: AdxProfile;
  loser_profile: AdxProfile;
};

export type ConditionsReport = {
  pass_rates: ConditionPassRate[];
  funnel: FunnelBucket[];
  bottleneck: BottleneckItem[];
  c5_shadow: C5ShadowReport;
  adx_deep_dive: AdxDeepDive | null;
  di_alignment?: DIAlignment;
};

export type RBucket = { r_bucket: string; count: number };
export type EquityCurvePoint = { date: string; equity: number; drawdown: number };
export type MaxDrawdown = { rupees: number; r: number };
export type Streaks = { current: number; max_win: number; max_loss: number };
export type MfeMAE = { avg_mfe_r: number; avg_mae_r: number };
export type RiskBucket = { risk_bucket: string; count: number };
export type RiskAdherence = {
  target: number;
  range_min: number;
  range_max: number;
  within_range_pct: number;
  distribution: RiskBucket[];
};
export type Payoff = { avg_win_r: number; avg_loss_r: number; ratio: number | null };

export type RiskReport = {
  r_distribution: RBucket[];
  equity_curve: EquityCurvePoint[];
  max_drawdown: MaxDrawdown;
  streaks: Streaks;
  mfe_mae?: MfeMAE;
  risk_adherence: RiskAdherence;
  payoff: Payoff;
};

// ---- Dashboard & Reports F7c: Insights + Monthly Summary + System Health ----

export type InsightsBreakdownRow = {
  key: string;
  n: number;
  win_rate: number;
  avg_r: number;
  total_pnl: number;
};

export type InsightsBreakdowns = {
  by_time_of_day: InsightsBreakdownRow[];
  by_weekday: InsightsBreakdownRow[];
  by_symbol: InsightsBreakdownRow[];
  by_relation: InsightsBreakdownRow[];
  by_option_type: InsightsBreakdownRow[];
  by_day_type?: InsightsBreakdownRow[];
  by_gap_type?: InsightsBreakdownRow[];
};

export type InsightsReport = {
  breakdowns: InsightsBreakdowns;
  key_insights: string[];
  total_n: number;
  min_sample: number;
  note: string | null;
  meta: { date_from: string; date_to: string };
};

export type MonthlyBestDay = { date: string | null; pnl: number };

export type MonthlyDetailRow = {
  month: string;
  month_key: string;
  total_trades: number;
  win_rate: number;
  total_pnl: number;
  realized_pnl: number;
  unrealized_pnl: number;
  profit_factor: number | null;
  max_profit: number;
  max_loss: number;
  best_day: MonthlyBestDay | null;
  worst_day: MonthlyBestDay | null;
};

export type CalendarDay = { date: string; pnl: number; trades: number };

export type MonthlyReport = {
  months: MonthlyDetailRow[];
  calendar: CalendarDay[];
  meta: { date_from: string; date_to: string };
};

export type SystemHealthFile = {
  name: string;
  last_modified_ist: string | null;
  size_kb: number | null;
  fresh: boolean;
};

export type ScanGap = { from: string; to: string; gap_min: number };

export type ScanCadence = {
  expected_interval_min: number;
  recent_gaps: ScanGap[];
  healthy: boolean;
  note: string;
};

export type DataIssue = { time: string | null; issue_type: string; detail: string };

export type SystemHealth = {
  feed: { active_feed: string; status: string };
  bot: { status: string; last_activity_ist: string | null; uptime_seconds: number | null };
  scan_cadence: ScanCadence;
  files: SystemHealthFile[];
  data_issues: { count: number; recent: DataIssue[] };
  last_config_reload_ist: string | null;
  last_dashboard_sync_ist: string | null;
};

// ---- F8: Logs Viewer ----

export type LogFileInfo = {
  name: string;
  path_label: string;
  size_kb: number | null;
  last_modified_ist: string | null;
};

export type LogTextRow = {
  raw: string;
  time: string | null;
  level: string | null;
  message: string;
};

export type LogTailText = {
  file: string;
  type: "text";
  rows: LogTextRow[];
  filtered_count: number;
  total_read: number;
};

export type LogTailJsonl = {
  file: string;
  type: "jsonl" | "json";
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  rows: Array<Record<string, any>>;
  filtered_count: number;
  total_read: number;
  skipped_malformed?: number;
};

export type LogTailResponse = LogTailText | LogTailJsonl;

// ---- Shadow Stop-Loss Lab ----

export type ShadowSlMethodSummary = {
  method: string;
  trades: number;
  win_rate: number;
  total_r: number;
  avg_r: number;
  capture_efficiency: number | null;
  time_stop_exits: number;
};

export type ShadowSlPerMethod = {
  exit_price: number | null;
  exit_time: string | null;
  exit_reason: string | null;
  r_multiple: number | null;
  max_unrealized_r: number | null;
  gave_back_r: number | null;
  initial_sl: number | null;
  tp1: number | null;
  tp2: number | null;
  entry: number | null;
  outcome_bucket: string | null;
  win: boolean;
};

export type ShadowSlTrade = {
  entry_time: string | null;
  symbol: string | null;
  strike: number | null;
  option_type: string | null;
  relation: string | null;
  is_expiry: boolean;
  per_method: Record<string, ShadowSlPerMethod>;
};

export type ShadowSlDay = {
  date: string;
  trades: ShadowSlTrade[];
};

export type ShadowSlResponse = {
  date_from: string | null;
  date_to: string | null;
  methods: ShadowSlMethodSummary[];
  days: ShadowSlDay[];
};


// ---- F8: Health / Liveness ----

export type ApiHealth = {
  ok: boolean;
  now_ist: string | null;
  project_root: string | null;
  config_present: boolean;
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
  reportsConditions: (params: { date_from?: string; date_to?: string } = {}) =>
    getJSON<ConditionsReport>(`/api/reports/conditions${buildQuery(params as Record<string, string | undefined | null>)}`),
  reportsRisk: (params: { date_from?: string; date_to?: string } = {}) =>
    getJSON<RiskReport>(`/api/reports/risk${buildQuery(params as Record<string, string | undefined | null>)}`),
  reportsInsights: (params: { date_from?: string; date_to?: string } = {}) =>
    getJSON<InsightsReport>(`/api/reports/insights${buildQuery(params as Record<string, string | undefined | null>)}`),
  reportsMonthly: (params: { date_from?: string; date_to?: string } = {}) =>
    getJSON<MonthlyReport>(`/api/reports/monthly${buildQuery(params as Record<string, string | undefined | null>)}`),
  systemHealth: () => getJSON<SystemHealth>("/api/system/health"),
  apiHealth: () => getJSON<ApiHealth>("/api/health"),
  logFiles: () => getJSON<{ files: LogFileInfo[] }>("/api/logs/files"),
  logTail: (params: { file: string; lines?: number; level?: string; search?: string }) =>
    getJSON<LogTailResponse>(
      `/api/logs/tail${buildQuery({
        file: params.file,
        lines: params.lines != null ? String(params.lines) : undefined,
        level: params.level,
        search: params.search,
      })}`,
    ),
  shadowSl: (params: { date_from?: string; date_to?: string } = {}) =>
    getJSON<ShadowSlResponse>(
      `/api/shadow-sl${buildQuery(params as Record<string, string | undefined | null>)}`,
    ),
};
