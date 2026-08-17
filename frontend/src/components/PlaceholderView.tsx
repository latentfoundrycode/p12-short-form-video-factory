import type { TabId } from "../tabs";

const LINES: Record<Exclude<TabId, "workflows">, string> = {
  schedule: "Arrives in a later stage",
  learning: "Arrives in a later stage",
  statistics: "Arrives in a later stage",
  settings: "Arrives in a later stage",
};

const TITLES: Record<Exclude<TabId, "workflows">, string> = {
  schedule: "Schedule",
  learning: "Learning",
  statistics: "Statistics",
  settings: "Settings",
};

export function PlaceholderView({ tab }: { tab: Exclude<TabId, "workflows"> }) {
  return (
    <section className="view on">
      <div className="page-head">
        <div>
          <div className="page-title">{TITLES[tab]}</div>
          <div className="page-note">{LINES[tab]}</div>
        </div>
      </div>
    </section>
  );
}
