import { useState } from "react";
import { LearningView } from "./components/LearningView";
import { LibraryView } from "./components/LibraryView";
import { SettingsView } from "./components/SettingsView";
import { RunsListView } from "./components/RunsListView";
import { RunView } from "./components/RunView";
import { ScheduleView } from "./components/ScheduleView";
import { Shell } from "./components/Shell";
import { StatisticsView } from "./components/StatisticsView";
import { WorkflowGrid } from "./components/WorkflowGrid";
import type { TabId } from "./tabs";

type ActiveRun = {
  workflowId: string;
  runId: string;
};

function App() {
  const [tab, setTab] = useState<TabId>("workflows");
  const [workflowCount, setWorkflowCount] = useState<number | null>(null);
  const [activeRun, setActiveRun] = useState<ActiveRun | null>(null);
  const [browsing, setBrowsing] = useState<{ workflowId: string } | null>(null);
  const [openedRuns, setOpenedRuns] = useState<Set<string>>(() => new Set());

  return (
    <Shell tab={tab} onTab={setTab} workflowCount={workflowCount}>
      {activeRun ? (
        <RunView
          key={activeRun.runId}
          workflowId={activeRun.workflowId}
          runId={activeRun.runId}
          onClose={() => {
            setActiveRun(null);
          }}
          onReplay={(runId) => {
            setActiveRun({ workflowId: activeRun.workflowId, runId });
          }}
        />
      ) : tab === "workflows" && browsing ? (
        <RunsListView
          key={browsing.workflowId}
          workflowId={browsing.workflowId}
          onBack={() => {
            setBrowsing(null);
          }}
          onOpenRun={(runId) => {
            setActiveRun({ workflowId: browsing.workflowId, runId });
          }}
        />
      ) : tab === "workflows" ? (
        <WorkflowGrid
          onCount={setWorkflowCount}
          onStarted={(workflowId, runId) => {
            setActiveRun({ workflowId, runId });
          }}
          openedRuns={openedRuns}
          onViewRuns={(workflowId, runId) => {
            if (runId) {
              setOpenedRuns((prev) => new Set(prev).add(runId));
            }
            setBrowsing({ workflowId });
          }}
        />
      ) : tab === "schedule" ? (
        <ScheduleView />
      ) : tab === "library" ? (
        <LibraryView />
      ) : tab === "learning" ? (
        <LearningView />
      ) : tab === "statistics" ? (
        <StatisticsView />
      ) : (
        <SettingsView />
      )}
    </Shell>
  );
}

export default App;
