import type { ReactNode } from "react";
import { TABS, type TabId } from "../tabs";

type ShellProps = {
  tab: TabId;
  onTab: (tab: TabId) => void;
  workflowCount: number | null;
  children: ReactNode;
};

function BrandMark() {
  return (
    <div className="brand-mark">
      <svg width="28" height="21" viewBox="0 0 581 442" fill="currentColor" aria-hidden="true">
        <path
          fillRule="evenodd"
          d="M51 35H196V34A34 34 0 0 1 230 0H350A34 34 0 0 1 384 34V35H530A51 51 0 0 1 581 86V391A51 51 0 0 1 530 442H51A51 51 0 0 1 0 391V86A51 51 0 0 1 51 35ZM143 237.5A147 147 0 1 0 437 237.5A147 147 0 1 0 143 237.5ZM179 237.5A111 111 0 1 0 401 237.5A111 111 0 1 0 179 237.5ZM470 114A28 28 0 1 0 526 114A28 28 0 1 0 470 114Z"
        />
      </svg>
    </div>
  );
}

function TabIcon({ tab }: { tab: TabId }) {
  switch (tab) {
    case "workflows":
      return (
        <svg
          width="13"
          height="13"
          viewBox="0 0 16 16"
          fill="none"
          stroke="currentColor"
          strokeWidth="1.4"
        >
          <rect x="1.5" y="1.5" width="5" height="5" />
          <rect x="9.5" y="1.5" width="5" height="5" />
          <rect x="1.5" y="9.5" width="5" height="5" />
          <rect x="9.5" y="9.5" width="5" height="5" />
        </svg>
      );
    case "schedule":
      return (
        <svg
          width="13"
          height="13"
          viewBox="0 0 16 16"
          fill="none"
          stroke="currentColor"
          strokeWidth="1.4"
        >
          <rect x="1.5" y="2.8" width="13" height="11.7" rx="1" />
          <path d="M1.5 6.2h13M5 1.5v2.6M11 1.5v2.6" />
        </svg>
      );
    case "learning":
      return (
        <svg
          width="13"
          height="13"
          viewBox="0 0 16 16"
          fill="none"
          stroke="currentColor"
          strokeWidth="1.4"
        >
          <path d="M8 1.6 14.4 5 8 8.4 1.6 5 8 1.6Z" />
          <path d="M3.6 6.6v3.9c0 1 2 2 4.4 2s4.4-1 4.4-2V6.6" />
        </svg>
      );
    case "statistics":
      return (
        <svg
          width="13"
          height="13"
          viewBox="0 0 16 16"
          fill="none"
          stroke="currentColor"
          strokeWidth="1.4"
        >
          <path d="M1.8 14.2h12.4" />
          <path d="M4 14V8.5M8 14V3.4M12 14v-7" />
        </svg>
      );
    case "settings":
      return (
        <svg
          width="13"
          height="13"
          viewBox="0 0 16 16"
          fill="none"
          stroke="currentColor"
          strokeWidth="1.4"
        >
          <circle cx="8" cy="8" r="2.4" />
          <path d="M8 1.4v1.9M8 12.7v1.9M14.6 8h-1.9M3.3 8H1.4M12.7 3.3l-1.3 1.3M4.6 11.4l-1.3 1.3M12.7 12.7l-1.3-1.3M4.6 4.6 3.3 3.3" />
        </svg>
      );
  }
}

export function Shell({ tab, onTab, workflowCount, children }: ShellProps) {
  return (
    <div className="app">
      <header className="topbar">
        <div className="brand">
          <BrandMark />
          <div>
            <div className="brand-name">Short-Form Video Factory</div>
          </div>
        </div>
        <nav className="tabs">
          {TABS.map((item) => (
            <button
              key={item.id}
              type="button"
              className={tab === item.id ? "tab on" : "tab"}
              aria-current={tab === item.id ? "page" : undefined}
              onClick={() => {
                onTab(item.id);
              }}
            >
              <span className="ico">
                <TabIcon tab={item.id} />
              </span>
              {item.label}
            </button>
          ))}
        </nav>
      </header>
      <main className="main">{children}</main>
      <footer className="statusbar">
        {workflowCount !== null ? (
          <div className="st">
            <b>{workflowCount}</b>
            {workflowCount === 1 ? " plug-in" : " plug-ins"}
          </div>
        ) : null}
      </footer>
    </div>
  );
}
