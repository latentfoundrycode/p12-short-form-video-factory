export const TABS = [
  { id: "workflows", label: "Workflows" },
  { id: "schedule", label: "Schedule" },
  { id: "learning", label: "Learning" },
  { id: "statistics", label: "Statistics" },
  { id: "settings", label: "Settings" },
] as const;

export type TabId = (typeof TABS)[number]["id"];
