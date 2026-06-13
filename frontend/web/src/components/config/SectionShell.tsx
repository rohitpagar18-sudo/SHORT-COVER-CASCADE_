import { useState, type ReactNode } from "react";
import { AlertTriangle, RefreshCw, Save } from "lucide-react";
import type { PutConfigResult } from "../../lib/api";

interface SectionShellProps {
  title: string;
  subtitle?: string;
  children: ReactNode;
  onSave: () => Promise<PutConfigResult>;
  isDirty: boolean;
  onReload: () => void;
  saveDisabled?: boolean;
  saveDisabledHint?: string;
}

export function SectionShell({
  title, subtitle, children, onSave, isDirty, onReload,
  saveDisabled = false, saveDisabledHint,
}: SectionShellProps) {
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [restartKeys, setRestartKeys] = useState<string[]>([]);

  const handleSave = async () => {
    setSaving(true);
    setSaveError(null);
    try {
      const result = await onSave();
      setRestartKeys(result.restart_required ?? []);
    } catch (e: unknown) {
      setSaveError(e instanceof Error ? e.message : "Save failed");
    } finally {
      setSaving(false);
    }
  };

  const handleReload = () => {
    setRestartKeys([]);
    setSaveError(null);
    onReload();
  };

  return (
    <div className="rounded-xl border border-slate-200 bg-white shadow-sm">
      {/* Header */}
      <div className="flex items-center justify-between gap-4 border-b border-slate-100 px-5 py-4">
        <div className="min-w-0">
          <h3 className="text-sm font-semibold text-ink">{title}</h3>
          {subtitle && <p className="mt-0.5 text-xs text-muted">{subtitle}</p>}
        </div>
        <div className="flex shrink-0 items-center gap-2">
          {isDirty && (
            <span className="text-xs font-medium text-amber-600">Unsaved changes</span>
          )}
          <button
            type="button"
            onClick={handleReload}
            disabled={saving}
            title="Discard local edits and reload from server"
            className="flex items-center gap-1.5 rounded-md border border-slate-200 px-2.5 py-1.5 text-xs text-muted hover:bg-slate-50 disabled:opacity-50"
          >
            <RefreshCw className="h-3 w-3" />
            Reload
          </button>
          <button
            type="button"
            onClick={handleSave}
            disabled={!isDirty || saving || saveDisabled}
            title={saveDisabled ? saveDisabledHint : undefined}
            className="flex items-center gap-1.5 rounded-md bg-emerald-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-emerald-700 disabled:cursor-not-allowed disabled:opacity-50"
          >
            <Save className="h-3 w-3" />
            {saving ? "Saving…" : "Save Changes"}
          </button>
        </div>
      </div>

      {/* Restart required banner */}
      {restartKeys.length > 0 && (
        <div className="flex items-start gap-2 border-b border-amber-100 bg-amber-50 px-5 py-3">
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-amber-500" />
          <div className="text-xs text-amber-800">
            <span className="font-semibold">Restart required</span> — changes to{" "}
            {restartKeys.map((k) => (
              <code key={k} className="mx-0.5 rounded bg-amber-100 px-1 font-mono">{k}</code>
            ))}{" "}
            will take effect after restarting{" "}
            <code className="rounded bg-amber-100 px-1 font-mono">run.bat</code>.
          </div>
        </div>
      )}

      {/* Save error banner */}
      {saveError && (
        <div className="border-b border-rose-100 bg-rose-50 px-5 py-3 text-xs text-rose-700">
          <span className="font-semibold">Save failed:</span> {saveError}
        </div>
      )}

      {/* Body — each child row has a bottom border from divide */}
      <div className="divide-y divide-slate-100 px-5">
        {children}
      </div>
    </div>
  );
}
