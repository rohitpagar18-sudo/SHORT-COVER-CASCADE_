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
  };
  circuit_breakers: {
    sl_count: number;
    max_sl_per_day: number;
    daily_loss: number;
    max_loss_per_day: number;
  };
  next_events: {
    last_entry_time: string | null;
    soft_squareoff_time: string | null;
    hard_squareoff_time: string | null;
    eod_summary_time: string | null;
    dashboard_sync_time: string | null;
  };
  recent_alerts: Array<{
    time: string | null;
    timestamp_ist: string | null;
    symbol: string | null;
    strike: number | null;
    option_type: string | null;
    relation: string | null;
    conditions_passed: string[];
    status: string | null;
    risk: number | null;
    entry: number | null;
    lots: number | null;
  }>;
  bot: { status: "RUNNING" | "STOPPED"; last_activity_ist: string | null };
  last_synced_ist: string;
};

export type BotStatus = {
  status: "RUNNING" | "STOPPED";
  last_activity_ist: string | null;
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
    // FastAPI validation errors come back as { detail: { errors: [...] } }
    const payload = await r.json().catch(() => null);
    const msgs: string[] | undefined = payload?.detail?.errors;
    const str: string | undefined =
      typeof payload?.detail === "string" ? payload.detail : undefined;
    throw new Error(msgs?.join("; ") ?? str ?? `${r.status} ${r.statusText}`);
  }
  return (await r.json()) as T;
}

export const api = {
  overview: () => getJSON<Overview>("/api/overview"),
  botStatus: () => getJSON<BotStatus>("/api/bot/status"),
  getConfig: () => getJSON<ConfigData>("/api/config"),
  putConfig: (changes: Record<string, unknown>) =>
    putJSON<PutConfigResult>("/api/config", changes),
};
