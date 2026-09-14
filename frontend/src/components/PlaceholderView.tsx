import type { TabId } from "../tabs";

type PlaceholderTab = Extract<TabId, "settings">;

const LINES: Record<PlaceholderTab, string> = {
  settings: "Arrives in a later stage",
};

const TITLES: Record<PlaceholderTab, string> = {
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
