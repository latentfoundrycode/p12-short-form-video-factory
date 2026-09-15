from __future__ import annotations

import math
import time
from collections.abc import Callable, Mapping
from typing import TYPE_CHECKING, Any

from sfvf._budget import BudgetError, BudgetGuard, Ceilings
from sfvf.context import BudgetConfig

from app.learning.optimizer import CompleteFn

if TYPE_CHECKING:
    import httpx2

LEARNING_METER = "learning"
_HTTP_TIMEOUT_S = 60.0
_RETRY_AFTER_DEFAULT_S = 1.0
_MAX_ATTEMPTS = 3


class CompletionError(Exception):
    """Raised when an OpenRouter completion fails outside budget enforcement."""


def _retry_after_s(header: str | None) -> float:
    if header is None:
        return _RETRY_AFTER_DEFAULT_S
    try:
        value = float(header)
    except (TypeError, ValueError):
        return _RETRY_AFTER_DEFAULT_S
    if not math.isfinite(value) or value < 0:
        return _RETRY_AFTER_DEFAULT_S
    return value


def _default_client_factory() -> httpx2.Client:
    try:
        import httpx2
    except ImportError as exc:
        raise RuntimeError(
            "learning completion requires the 'httpx2' package. Install the SDK "
            "'openrouter' extra: pip install 'sfvf[openrouter]'."
        ) from exc
    return httpx2.Client(
        base_url="https://openrouter.ai/api/v1",
        timeout=_HTTP_TIMEOUT_S,
    )


def _usage_cost(data: dict[str, Any]) -> float | None:
    usage = data.get("usage")
    if not isinstance(usage, dict):
        return None
    cost = usage.get("cost")
    if isinstance(cost, bool) or not isinstance(cost, int | float):
        return None
    try:
        amount = float(cost)
    except OverflowError:
        return None
    if not math.isfinite(amount) or amount < 0.0:
        return None
    return amount


def make_openrouter_completion(
    *,
    secrets: Mapping[str, str],
    budget: BudgetConfig | None,
    model: str,
    run_id: str,
    client_factory: Callable[[], httpx2.Client] = _default_client_factory,
    sleep: Callable[[float], None] = time.sleep,
) -> CompleteFn:
    def complete(messages: list[dict[str, str]]) -> str:
        key = secrets.get("OPENROUTER_API_KEY")
        if not key:
            raise CompletionError("OpenRouter API key is not configured")

        if budget is None:
            raise BudgetError(
                f"no budget configured; refusing paid call for meter {LEARNING_METER!r}"
            )
        estimate = budget.estimates.get(LEARNING_METER)
        if estimate is None or not (estimate > 0):
            raise BudgetError(
                f"no positive budget estimate configured for meter {LEARNING_METER!r}"
            )
        guard = BudgetGuard(
            budget.ledger_path,
            ceilings=Ceilings(per_run=budget.per_run, per_day=budget.per_day),
            kill_switch_path=budget.kill_switch_path,
        )
        token = guard.reserve(
            run_id=run_id,
            meter=LEARNING_METER,
            unit="usd",
            estimate=estimate,
        )

        unbilled = False
        try:
            with client_factory() as client:
                for attempt in range(_MAX_ATTEMPTS):
                    resp = client.post(
                        "/chat/completions",
                        headers={"Authorization": f"Bearer {key}"},
                        json={"model": model, "messages": messages},
                    )
                    if resp.status_code == 200:
                        break
                    if resp.status_code == 429:
                        if attempt < _MAX_ATTEMPTS - 1:
                            sleep(_retry_after_s(resp.headers.get("Retry-After")))
                        continue
                    unbilled = True
                    raise CompletionError(f"OpenRouter error {resp.status_code}")
                else:
                    unbilled = True
                    raise CompletionError("OpenRouter rate limited after retries (429)")

                try:
                    data = resp.json()
                except Exception as exc:
                    raise CompletionError("OpenRouter returned a malformed response body") from exc
                if not isinstance(data, dict):
                    raise CompletionError("OpenRouter response has the wrong shape")

            cost = _usage_cost(data)
            if cost is not None:
                guard.reconcile(token, actual=cost)

            try:
                content = data["choices"][0]["message"]["content"]
            except (KeyError, IndexError, TypeError) as exc:
                raise CompletionError("OpenRouter response is missing assistant content") from exc
            if not isinstance(content, str):
                raise CompletionError("OpenRouter response is missing assistant content")
            return content
        finally:
            if unbilled:
                guard.reconcile(token, actual=0.0)

    return complete
