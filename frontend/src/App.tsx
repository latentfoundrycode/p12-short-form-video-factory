import { useState } from "react";
import { PlaceholderView } from "./components/PlaceholderView";
import { Shell } from "./components/Shell";
import { WorkflowGrid } from "./components/WorkflowGrid";
import type { TabId } from "./tabs";

function App() {
  const [tab, setTab] = useState<TabId>("workflows");
  const [workflowCount, setWorkflowCount] = useState<number | null>(null);

  return (
    <Shell tab={tab} onTab={setTab} workflowCount={workflowCount}>
      {tab === "workflows" ? (
        <WorkflowGrid onCount={setWorkflowCount} />
      ) : (
        <PlaceholderView tab={tab} />
      )}
    </Shell>
  );
}

export default App;
