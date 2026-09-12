import type { RequestStatus } from "./types";

export function statusPillClass(status: RequestStatus): string {
  switch (status) {
    case "running":
      return "pill run";
    case "complete":
      return "pill done";
    case "failed":
      return "pill fail";
    case "partial":
    case "stopped":
    case "stopped-budget":
      return "pill warn";
    default:
      return "pill";
  }
}
