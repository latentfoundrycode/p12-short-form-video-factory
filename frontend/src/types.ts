export type Problem = {
  code: string;
  message: string;
  severity: "error" | "warning";
};

export type Workflow = {
  id: string;
  name: string | null;
  description: string | null;
  thumbnail_url: string | null;
  valid: boolean;
  problems: Problem[];
};

export type WorkflowList = {
  workflows: Workflow[];
};
