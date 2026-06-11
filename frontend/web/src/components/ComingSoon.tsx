import { useLocation } from "react-router-dom";
import { Construction } from "lucide-react";
import { MENU } from "./Sidebar";

export default function ComingSoon() {
  const loc = useLocation();
  const item = MENU.find((m) => m.to === loc.pathname);
  const label = item?.label ?? loc.pathname;
  return (
    <div className="flex h-[70vh] items-center justify-center">
      <div className="text-center">
        <Construction className="mx-auto h-10 w-10 text-slate-400" />
        <h2 className="mt-3 text-xl font-semibold text-ink">{label}</h2>
        <p className="mt-1 text-sm text-muted">Coming soon — this page will arrive in a later phase.</p>
      </div>
    </div>
  );
}
