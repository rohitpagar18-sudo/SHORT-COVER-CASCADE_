import { useEffect, useMemo, useState } from "react";
import { useConfig } from "../../../context/ConfigContext";
import { useToast } from "../../../context/ToastContext";
import { SectionShell, Toggle, NumberField } from "../index";

type RiskReward = {
  target_risk_per_trade: number;
  risk_range_min: number;
  risk_range_max: number;
  normal_day_tp1_r: number;
  normal_day_tp2_r: number;
  expiry_day_tp1_r: number;
  expiry_day_tp2_r: number;
  move_sl_to_breakeven_after_tp1: boolean;
  trail_sl_after_tp1: boolean;
};

type PositionSizing = {
  lot_cap_enabled: boolean;
  nifty_max_lots: number;
  banknifty_max_lots: number;
};

type CircuitBreakers = {
  daily_sl_count_breaker: boolean;
  max_sl_per_day: number;
  daily_loss_breaker: boolean;
  max_loss_per_day_rupees: number;
};

type RiskMoneyLocal = {
  risk_reward: RiskReward;
  position_sizing: PositionSizing;
  circuit_breakers: CircuitBreakers;
};

function fromConfig(config: Record<string, unknown> | null): RiskMoneyLocal {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const c: any = (config ?? {}) as any;
  const r = c.risk_reward ?? {};
  const p = c.position_sizing ?? {};
  const cb = c.circuit_breakers ?? {};
  return {
    risk_reward: {
      target_risk_per_trade: r.target_risk_per_trade ?? 3000,
      risk_range_min: r.risk_range_min ?? 2500,
      risk_range_max: r.risk_range_max ?? 3500,
      normal_day_tp1_r: r.normal_day_tp1_r ?? 1.5,
      normal_day_tp2_r: r.normal_day_tp2_r ?? 2.5,
      expiry_day_tp1_r: r.expiry_day_tp1_r ?? 2.0,
      expiry_day_tp2_r: r.expiry_day_tp2_r ?? 3.0,
      move_sl_to_breakeven_after_tp1: r.move_sl_to_breakeven_after_tp1 ?? true,
      trail_sl_after_tp1: r.trail_sl_after_tp1 ?? false,
    },
    position_sizing: {
      lot_cap_enabled: p.lot_cap_enabled ?? true,
      nifty_max_lots: p.nifty_max_lots ?? 5,
      banknifty_max_lots: p.banknifty_max_lots ?? 5,
    },
    circuit_breakers: {
      daily_sl_count_breaker: cb.daily_sl_count_breaker ?? true,
      max_sl_per_day: cb.max_sl_per_day ?? 3,
      daily_loss_breaker: cb.daily_loss_breaker ?? true,
      max_loss_per_day_rupees: cb.max_loss_per_day_rupees ?? 6000,
    },
  };
}

function CardHeader({ title, subtitle }: { title: string; subtitle?: string }) {
  return (
    <div className="border-b border-slate-200 px-4 py-3">
      <div className="text-sm font-semibold text-ink">{title}</div>
      {subtitle && <div className="mt-0.5 text-xs text-muted">{subtitle}</div>}
    </div>
  );
}

export function RiskMoneySection() {
  const { config, save, reload } = useConfig();
  const toast = useToast();
  const [local, setLocal] = useState<RiskMoneyLocal>(() => fromConfig(config));

  useEffect(() => {
    setLocal(fromConfig(config));
  }, [config]);

  const remote = useMemo(() => fromConfig(config), [config]);
  const isDirty = JSON.stringify(local) !== JSON.stringify(remote);

  const setRR = (patch: Partial<RiskReward>) =>
    setLocal((prev) => ({ ...prev, risk_reward: { ...prev.risk_reward, ...patch } }));

  const setPS = (patch: Partial<PositionSizing>) =>
    setLocal((prev) => ({ ...prev, position_sizing: { ...prev.position_sizing, ...patch } }));

  const setCB = (patch: Partial<CircuitBreakers>) =>
    setLocal((prev) => ({ ...prev, circuit_breakers: { ...prev.circuit_breakers, ...patch } }));

  const handleSave = async () => {
    const result = await save({
      risk_reward: local.risk_reward,
      position_sizing: local.position_sizing,
      circuit_breakers: local.circuit_breakers,
    } as Record<string, unknown>);
    if (result.updated) {
      toast.push("Saved — applies on the bot's next scan.", "ok");
    }
    return result;
  };

  const handleReload = () => {
    setLocal(remote);
    reload();
  };

  return (
    <SectionShell
      title="Risk & Money"
      subtitle="Risk-per-trade, position sizing, and circuit breakers — the three layers that cap each day's downside."
      onSave={handleSave}
      isDirty={isDirty}
      onReload={handleReload}
    >
      {/* Risk / Reward */}
      <div className="py-3">
        <div className="rounded-lg border border-slate-200 bg-white">
          <CardHeader
            title="Risk / Reward"
            subtitle="₹ risked per trade and the R-multiples for exit targets."
          />
          <div className="divide-y divide-slate-100 px-4">
            <NumberField
              label="Target Risk per Trade"
              helper="Sweet spot ₹ risk per trade"
              value={local.risk_reward.target_risk_per_trade}
              min={0}
              step={100}
              prefix="₹"
              onChange={(v) => setRR({ target_risk_per_trade: v })}
            />
            <NumberField
              label="Risk Range Min"
              helper="Lower bound of acceptable ₹ risk"
              value={local.risk_reward.risk_range_min}
              min={0}
              step={100}
              prefix="₹"
              onChange={(v) => setRR({ risk_range_min: v })}
            />
            <NumberField
              label="Risk Range Max"
              helper="Upper bound of acceptable ₹ risk"
              value={local.risk_reward.risk_range_max}
              min={0}
              step={100}
              prefix="₹"
              onChange={(v) => setRR({ risk_range_max: v })}
            />
            <NumberField
              label="Normal Day TP1 (R)"
              helper="Non-expiry: first exit at this × R"
              value={local.risk_reward.normal_day_tp1_r}
              min={0}
              step={0.1}
              suffix="R"
              onChange={(v) => setRR({ normal_day_tp1_r: v })}
            />
            <NumberField
              label="Normal Day TP2 (R)"
              helper="Non-expiry: final exit at this × R"
              value={local.risk_reward.normal_day_tp2_r}
              min={0}
              step={0.1}
              suffix="R"
              onChange={(v) => setRR({ normal_day_tp2_r: v })}
            />
            <NumberField
              label="Expiry Day TP1 (R)"
              helper="Expiry: first exit at this × R (bigger targets)"
              value={local.risk_reward.expiry_day_tp1_r}
              min={0}
              step={0.1}
              suffix="R"
              onChange={(v) => setRR({ expiry_day_tp1_r: v })}
            />
            <NumberField
              label="Expiry Day TP2 (R)"
              helper="Expiry: final exit at this × R"
              value={local.risk_reward.expiry_day_tp2_r}
              min={0}
              step={0.1}
              suffix="R"
              onChange={(v) => setRR({ expiry_day_tp2_r: v })}
            />
            <Toggle
              label="Move SL to Breakeven after TP1"
              helper="After TP1, move remaining SL to entry price (Method 1/2; Method 3 ignores this)."
              value={local.risk_reward.move_sl_to_breakeven_after_tp1}
              onChange={(v) => setRR({ move_sl_to_breakeven_after_tp1: v })}
            />
            <Toggle
              label="Trail SL After TP1"
              helper="Legacy — for real trailing use Stop Loss Method 3."
              value={local.risk_reward.trail_sl_after_tp1}
              onChange={(v) => setRR({ trail_sl_after_tp1: v })}
            />
          </div>
        </div>
      </div>

      {/* Position Sizing */}
      <div className="py-3">
        <div className="rounded-lg border border-slate-200 bg-white">
          <CardHeader
            title="Position Sizing"
            subtitle="Hard lot caps applied after the ₹-risk formula."
          />
          <div className="divide-y divide-slate-100 px-4">
            <Toggle
              label="Lot Cap Enabled"
              helper="ON = enforce hard caps below. OFF = sizing only by ₹ risk (risky for cheap premiums)."
              value={local.position_sizing.lot_cap_enabled}
              onChange={(v) => setPS({ lot_cap_enabled: v })}
            />
            <NumberField
              label="NIFTY Max Lots"
              helper="Hard ceiling for NIFTY"
              value={local.position_sizing.nifty_max_lots}
              min={1}
              suffix="lots"
              onChange={(v) => setPS({ nifty_max_lots: v })}
            />
            <NumberField
              label="BankNifty Max Lots"
              helper="Hard ceiling for BankNifty"
              value={local.position_sizing.banknifty_max_lots}
              min={1}
              suffix="lots"
              onChange={(v) => setPS({ banknifty_max_lots: v })}
            />
          </div>
        </div>
      </div>

      {/* Circuit Breakers */}
      <div className="py-3">
        <div className="rounded-lg border border-slate-200 bg-white">
          <CardHeader
            title="Circuit Breakers"
            subtitle="Daily kill switches. First trigger wins — bot stops for the day."
          />
          <div className="divide-y divide-slate-100 px-4">
            <Toggle
              label="Daily SL Count Breaker"
              helper="ON = stop trading for the day after N stop-losses"
              value={local.circuit_breakers.daily_sl_count_breaker}
              onChange={(v) => setCB({ daily_sl_count_breaker: v })}
            />
            <NumberField
              label="Max SL per Day"
              helper="Stop the day after this many SL hits"
              value={local.circuit_breakers.max_sl_per_day}
              min={1}
              suffix="hits"
              onChange={(v) => setCB({ max_sl_per_day: v })}
            />
            <Toggle
              label="Daily Loss Breaker"
              helper="ON = stop trading for the day after ₹ cumulative loss"
              value={local.circuit_breakers.daily_loss_breaker}
              onChange={(v) => setCB({ daily_loss_breaker: v })}
            />
            <NumberField
              label="Max Loss per Day"
              helper="Stop the day once cumulative loss reaches this ₹ amount"
              value={local.circuit_breakers.max_loss_per_day_rupees}
              min={0}
              step={500}
              prefix="₹"
              onChange={(v) => setCB({ max_loss_per_day_rupees: v })}
            />
          </div>
        </div>
      </div>
    </SectionShell>
  );
}
