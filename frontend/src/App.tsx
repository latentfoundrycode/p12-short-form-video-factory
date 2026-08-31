import { useState } from "react";
import { PlaceholderView } from "./components/PlaceholderView";
import { RunView } from "./components/RunView";
import { Shell } from "./components/Shell";
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

  return (
    <Shell tab={tab} onTab={setTab} workflowCount={workflowCount}>
      {activeRun ? (
        <RunView
          workflowId={activeRun.workflowId}
          runId={activeRun.runId}
          onClose={() => {
            setActiveRun(null);
          }}
        />
      ) : tab === "workflows" ? (
        <WorkflowGrid
          onCount={setWorkflowCount}
          onStarted={(workflowId, runId) => {
            setActiveRun({ workflowId, runId });
          }}
        />
      ) : (
        <PlaceholderView tab={tab} />
      )}
    </Shell>
  );
}

export default App;
