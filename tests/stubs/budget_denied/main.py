from sfvf._budget import BudgetExceededError


def run(ctx) -> None:
    # Stand in for a paid call the budget guard refused (a ceiling breach or the kill-switch). The
    # runner must report this as a budget denial so the supervisor labels the run stopped-budget.
    raise BudgetExceededError("per-day ceiling reached")
