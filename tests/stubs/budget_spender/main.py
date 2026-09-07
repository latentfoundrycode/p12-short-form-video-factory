import json
from pathlib import Path

from sfvf._budget import BudgetGuard, Ceilings


def run(ctx) -> None:
    # A run that actually spends: reserve, then reconcile a real amount against the shared ledger,
    # exactly as the paid providers do, so the supervisor can surface the spend in request.budget.
    # The budget block is carried in context.json (video-dir cwd); absent it, this is a no-op spend.
    data = json.loads(Path("context.json").read_text(encoding="utf-8"))
    budget = data.get("budget")
    if budget:
        guard = BudgetGuard(
            Path(budget["ledger_path"]),
            ceilings=Ceilings(
                per_run=budget.get("per_run", {}),
                per_day=budget.get("per_day", {}),
            ),
            kill_switch_path=(
                Path(budget["kill_switch_path"]) if budget.get("kill_switch_path") else None
            ),
        )
        token = guard.reserve(run_id=ctx.run_id, meter="openrouter", unit="EUR", estimate=0.05)
        guard.reconcile(token, actual=0.02)
    ctx.emit({"t": "result", "video": "final.mp4", "caption": "spent"})
