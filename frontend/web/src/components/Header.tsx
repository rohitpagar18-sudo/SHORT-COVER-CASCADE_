import { RefreshCw } from "lucide-react";

type Props = {
  title: string;
  lastSynced?: string | null;
};

export default function Header({ title, lastSynced }: Props) {
  return (
    <header className="flex items-center justify-between border-b border-slate-200 bg-white px-6 py-3">
      <div>
        <h1 className="text-lg font-semibold text-ink">{title}</h1>
        <div className="text-xs text-muted">Auto-Reload: ON · polls every 15s</div>
      </div>
      <div className="flex items-center gap-2 text-xs text-muted">
        <RefreshCw className="h-3.5 w-3.5" />
        <span>Last synced: {lastSynced ? new Date(lastSynced).toLocaleTimeString("en-IN") : "—"}</span>
      </div>
    </header>
  );
}
