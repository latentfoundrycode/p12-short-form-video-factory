import type { TabId } from "../tabs";

type PlaceholderTab = Exclude<TabId, "workflows" | "statistics">;

const LINES: Record<PlaceholderTab, string> = {
  schedule: "Arrives in a later stage",
  learning: "Arrives in a later stage",
  settings: "Arrives in a later stage",
};

const TITLES: Record<PlaceholderTab, string> = {
  schedule: "Schedule",
  learning: "Learning",
  settings: "Settings",
};

export function PlaceholderView({ tab }: { tab: PlaceholderTab }) {
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
