import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Activity, AlertTriangle, Pause, Play, RefreshCw, Search, ScrollText } from "lucide-react";
import { Card, CardTitle, Skeleton } from "../components/Card";
import {
  api,
  type LogFileInfo,
  type LogTailJsonl,
  type LogTailResponse,
  type LogTailText,
  type LogTextRow,
} from "../lib/api";
import { timeAgoIST } from "../lib/format";
import { usePollIntervalMs } from "../context/SettingsContext";

const FILE_OPTIONS: { name: string; label: string }[] = [
  { name: "bot.log", label: "bot.log (text)" },
  { name: "signals.jsonl", label: "signals.jsonl" },
  { name: "alerts.jsonl", label: "alerts.jsonl" },
  { name: "paper_trades.jsonl", label: "paper_trades.jsonl" },
  { name: "state.json", label: "state.json" },
];

const LINE_OPTIONS = [100, 200, 500];
const LEVEL_OPTIONS = ["All", "DEBUG", "INFO", "WARNING", "ERROR"] as const;

function isTextTail(t: LogTailResponse | null): t is LogTailText {
  return !!t && t.type === "text";
}

function isJsonlTail(t: LogTailResponse | null): t is LogTailJsonl {
  return !!t && (t.type === "jsonl" || t.type === "json");
}

export default function LogsPage() {
  const [files, setFiles] = useState<LogFileInfo[]>([]);
  const [file, setFile] = useState<string>("bot.log");
  const [lines, setLines] = useState<number>(200);
  const [level, setLevel] = useState<(typeof LEVEL_OPTIONS)[number]>("All");
  const [search, setSearch] = useState<string>("");
  const [autoRefresh, setAutoRefresh] = useState<boolean>(true);
  const [tail, setTail] = useState<LogTailResponse | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const pollMs = usePollIntervalMs();

  const logBodyRef = useRef<HTMLDivElement>(null);
  const stickToBottomRef = useRef<boolean>(true);

  const fetchTail = useCallback(async () => {
    try {
      const r = await api.logTail({ file, lines, level, search });
      setTail(r);
      setErr(null);
    } catch (e) {
      setErr((e as Error)?.message ?? "failed to load");
    } finally {
      setLoading(false);
    }
  }, [file, lines, level, search]);

  const fetchFiles = useCallback(async () => {
    try {
      const r = await api.logFiles();
      setFiles(r.files);
    } catch {
      // ignore — list_files can be reloaded later
    }
  }, []);

  useEffect(() => {
    fetchFiles();
  }, [fetchFiles]);

  useEffect(() => {
    let alive = true;
    let timer: number | undefined;
    setLoading(true);
    const tick = async () => {
      if (!alive) return;
      await fetchTail();
      if (alive && autoRefresh) {
        timer = window.setTimeout(tick, Math.max(pollMs, 5_000));
      }
    };
    tick();
    return () => {
      alive = false;
      if (timer) window.clearTimeout(timer);
    };
  }, [fetchTail, autoRefresh, pollMs]);

  // Auto-scroll bot.log to the bottom when at-bottom and new rows arrive.
  useEffect(() => {
    if (!isTextTail(tail)) return;
    const el = logBodyRef.current;
    if (!el) return;
    if (stickToBottomRef.current) {
      el.scrollTop = el.scrollHeight;
    }
  }, [tail]);

  const onScroll = () => {
    const el = logBodyRef.current;
    if (!el) return;
    const distFromBottom = el.scrollHeight - el.clientHeight - el.scrollTop;
    stickToBottomRef.current = distFromBottom < 24;
  };

  const fileInfo = useMemo(
    () => files.find((f) => f.name === file) ?? null,
    [files, file],
  );

  return (
    <div className="space-y-4">
      <Card>
        <CardTitle
          right={
            <span className="flex items-center gap-2 text-xs text-muted">
              {fileInfo?.last_modified_ist ? (
                <>
                  <span>{fileInfo.path_label}</span>
                  <span>·</span>
                  <span>{(fileInfo.size_kb ?? 0).toLocaleString()} KB</span>
                  <span>·</span>
                  <span>updated {timeAgoIST(fileInfo.last_modified_ist)}</span>
                </>
              ) : (
                <span className="text-muted">file not present yet</span>
              )}
            </span>
          }
        >
          <span className="flex items-center gap-2">
            <ScrollText className="h-4 w-4 text-sky-500" />
            Logs Viewer
          </span>
        </CardTitle>

        <div className="grid grid-cols-1 gap-3 md:grid-cols-[1fr_1fr_1fr_auto_auto]">
          <Field label="File">
            <select
              value={file}
              onChange={(e) => setFile(e.target.value)}
              className="w-full rounded-md border border-line bg-card px-2 py-1.5 text-sm"
            >
              {FILE_OPTIONS.map((opt) => (
                <option key={opt.name} value={opt.name}>
                  {opt.label}
                </option>
              ))}
            </select>
          </Field>

          <Field label="Lines">
            <select
              value={lines}
              onChange={(e) => setLines(Number(e.target.value))}
              className="w-full rounded-md border border-line bg-card px-2 py-1.5 text-sm"
            >
              {LINE_OPTIONS.map((n) => (
                <option key={n} value={n}>
                  Last {n}
                </option>
              ))}
            </select>
          </Field>

          {file === "bot.log" ? (
            <Field label="Level">
              <select
                value={level}
                onChange={(e) => setLevel(e.target.value as (typeof LEVEL_OPTIONS)[number])}
                className="w-full rounded-md border border-line bg-card px-2 py-1.5 text-sm"
              >
                {LEVEL_OPTIONS.map((l) => (
                  <option key={l} value={l}>
                    {l}
                  </option>
                ))}
              </select>
            </Field>
          ) : (
            <div className="hidden md:block" />
          )}

          <Field label="Auto-refresh">
            <button
              type="button"
              onClick={() => setAutoRefresh((v) => !v)}
              className={[
                "flex h-8 items-center justify-center gap-1 rounded-md border px-2 text-xs",
                autoRefresh
                  ? "border-emerald-300 bg-emerald-50 text-emerald-700 dark:border-emerald-900 dark:bg-emerald-950/40 dark:text-emerald-300"
                  : "border-line bg-card text-muted",
              ].join(" ")}
            >
              {autoRefresh ? <Pause className="h-3 w-3" /> : <Play className="h-3 w-3" />}
              {autoRefresh ? "ON" : "OFF"}
            </button>
          </Field>

          <Field label="&nbsp;">
            <button
              type="button"
              onClick={fetchTail}
              className="flex h-8 items-center gap-1 rounded-md border border-line bg-card px-2 text-xs hover:bg-line2"
            >
              <RefreshCw className="h-3 w-3" />
              Refresh
            </button>
          </Field>
        </div>

        <div className="mt-3 flex items-center gap-2">
          <Search className="h-4 w-4 text-muted" />
          <input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search (case-insensitive)…"
            className="w-full rounded-md border border-line bg-card px-2 py-1.5 text-sm"
          />
        </div>
      </Card>

      {err && !tail && (
        <Card>
          <div className="flex items-center gap-2 text-sm text-rose-600 dark:text-rose-400">
            <AlertTriangle className="h-4 w-4" />
            Failed to load: {err}
          </div>
        </Card>
      )}

      {loading && !tail ? (
        <Card>
          <Skeleton className="h-[420px] w-full" />
        </Card>
      ) : isTextTail(tail) ? (
        <Card>
          <CardTitle
            right={
              <span className="text-xs text-muted">
                {tail.filtered_count.toLocaleString()} of {tail.total_read.toLocaleString()} lines
              </span>
            }
          >
            <span className="flex items-center gap-2">
              <Activity className="h-4 w-4 text-emerald-500" />
              {tail.file}
            </span>
          </CardTitle>
          <BotLogView rows={tail.rows} bodyRef={logBodyRef} onScroll={onScroll} />
        </Card>
      ) : isJsonlTail(tail) ? (
        <Card>
          <CardTitle
            right={
              <span className="text-xs text-muted">
                {tail.filtered_count.toLocaleString()} of {tail.total_read.toLocaleString()} rows
                {tail.skipped_malformed ? ` · ${tail.skipped_malformed} skipped` : ""}
              </span>
            }
          >
            <span className="flex items-center gap-2">
              <Activity className="h-4 w-4 text-emerald-500" />
              {tail.file}
            </span>
          </CardTitle>
          <JsonTable rows={tail.rows} />
        </Card>
      ) : null}

      <p className="text-xs text-muted">
        Read-only view over <code className="font-mono">logs/</code>. The dashboard does not edit or
        rotate these files.
      </p>
    </div>
  );
}

function Field({ label, children }: { label: React.ReactNode; children: React.ReactNode }) {
  return (
    <div>
      <div className="mb-1 text-[11px] uppercase tracking-wide text-muted">{label}</div>
      {children}
    </div>
  );
}

function levelTone(lvl: string | null | undefined): string {
  if (!lvl) return "text-muted";
  switch (lvl.toUpperCase()) {
    case "ERROR":
    case "CRITICAL":
      return "text-rose-500";
    case "WARNING":
      return "text-amber-500";
    case "INFO":
      return "text-emerald-500";
    case "DEBUG":
      return "text-sky-400";
    default:
      return "text-muted";
  }
}

function BotLogView({
  rows,
  bodyRef,
  onScroll,
}: {
  rows: LogTextRow[];
  bodyRef: React.RefObject<HTMLDivElement | null>;
  onScroll: () => void;
}) {
  if (rows.length === 0) {
    return (
      <div className="flex h-[200px] items-center justify-center text-sm text-muted">
        No log lines match the current filter.
      </div>
    );
  }
  return (
    <div
      ref={bodyRef}
      onScroll={onScroll}
      className="max-h-[520px] overflow-y-auto rounded-md border border-line2 bg-bg p-2 font-mono text-[11px] leading-snug"
    >
      {rows.map((r, i) => (
        <div key={i} className="flex items-start gap-2 whitespace-pre-wrap break-all py-0.5">
          <span className="shrink-0 text-muted">{r.time ?? "—"}</span>
          <span className={["shrink-0 font-semibold", levelTone(r.level)].join(" ")}>
            {(r.level ?? "—").padEnd(7, " ")}
          </span>
          <span className="text-ink">{r.message}</span>
        </div>
      ))}
    </div>
  );
}

function JsonTable({ rows }: { rows: Array<Record<string, unknown>> }) {
  if (rows.length === 0) {
    return (
      <div className="flex h-[200px] items-center justify-center text-sm text-muted">
        No rows in this file (or filter excluded everything).
      </div>
    );
  }

  // Pick the column set from the union of keys in the first few rows,
  // capped at a reasonable width.
  const sample = rows.slice(0, 12);
  const columns: string[] = [];
  const seen = new Set<string>();
  for (const r of sample) {
    for (const k of Object.keys(r)) {
      if (!seen.has(k)) {
        seen.add(k);
        columns.push(k);
      }
    }
  }
  const display = columns.slice(0, 14);
  const overflow = columns.length - display.length;

  return (
    <div className="overflow-auto rounded-md border border-line2">
      <table className="min-w-full text-[11px]">
        <thead className="sticky top-0 bg-line2 text-muted">
          <tr>
            {display.map((c) => (
              <th key={c} className="whitespace-nowrap px-2 py-1.5 text-left font-semibold">
                {c}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={i} className="border-t border-line2 align-top hover:bg-line2/50">
              {display.map((c) => (
                <td key={c} className="max-w-[240px] truncate px-2 py-1 font-mono">
                  {renderCell(r[c])}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
      {overflow > 0 && (
        <div className="border-t border-line2 bg-line2/50 px-2 py-1 text-[10px] text-muted">
          + {overflow} more field{overflow === 1 ? "" : "s"} per row (full row available in raw JSONL).
        </div>
      )}
    </div>
  );
}

function renderCell(v: unknown): string {
  if (v == null) return "—";
  if (typeof v === "string") return v;
  if (typeof v === "number") return String(v);
  if (typeof v === "boolean") return v ? "✓" : "✗";
  try {
    const s = JSON.stringify(v);
    return s.length > 80 ? s.slice(0, 77) + "…" : s;
  } catch {
    return String(v);
  }
}

