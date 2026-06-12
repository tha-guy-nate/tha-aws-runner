from __future__ import annotations

import threading
import types
from typing import TYPE_CHECKING, Any

from tha_aws_runner.ddb_pricing import rcu_price, wcu_price

if TYPE_CHECKING:
    from tha_aws_runner.aws_base import AWSBase, AWSClients


class DdbCostTracker:
    """
    Context manager that tallies DynamoDB RCU/WCU consumed across a run and
    estimates USD cost. Accepts any AWSBase instance (ThaDdb, ThaGsi, etc.).

    Hooks boto3 session events on every session used by the instance — including
    per-thread sessions created by ThreadPoolExecutor workers — so threaded
    batch operations are counted correctly. Each instance tracks its own session;
    pass the same instance you are calling operations on.

    Usage::

        with DdbCostTracker(ddb) as cost:
            ddb.batch_update_by_pk(..., workers=8, commit=True)

        with DdbCostTracker(gsi) as cost:
            gsi.batch_query(...)

        print(cost.summary())
        # {"usd": 0.0042, "rcu": 1200.0, "wcu": 340.0, "region": "us-east-1", "tables": {...}}
    """

    def __init__(self, ddb: AWSBase, *, region: str | None = None) -> None:
        self._ddb = ddb
        self._region: str = region or ddb.clients.session.region_name or "us-east-1"
        self._lock = threading.Lock()
        self._rcu: float = 0.0
        self._wcu: float = 0.0
        self._tables: dict[str, dict[str, float]] = {}
        self._hooked: dict[int, Any] = {}  # id(boto3_session) -> session object

    # ------------------------------------------------------------------
    # boto3 event handlers
    # ------------------------------------------------------------------

    def _inject(self, params: dict[str, Any], **_: Any) -> None:
        """Inject ReturnConsumedCapacity=TOTAL so AWS returns usage data."""
        if "ReturnConsumedCapacity" not in params:
            params["ReturnConsumedCapacity"] = "TOTAL"

    def _capture(self, parsed: dict[str, Any] | None, **_: Any) -> None:
        """Accumulate ConsumedCapacity from a DynamoDB response."""
        if not parsed:
            return
        capacity = parsed.get("ConsumedCapacity")
        if capacity is None:
            return
        entries: list[dict[str, Any]] = capacity if isinstance(capacity, list) else [capacity]
        with self._lock:
            for entry in entries:
                table = entry.get("TableName", "unknown")
                rcu = float(entry.get("ReadCapacityUnits", 0))
                wcu = float(entry.get("WriteCapacityUnits", 0))
                self._rcu += rcu
                self._wcu += wcu
                row = self._tables.setdefault(table, {"rcu": 0.0, "wcu": 0.0})
                row["rcu"] += rcu
                row["wcu"] += wcu

    # ------------------------------------------------------------------
    # Session hook management
    # ------------------------------------------------------------------

    def _hook(self, session: Any) -> None:
        """Register event handlers on a boto3 session (idempotent)."""
        sid = id(session)
        with self._lock:
            if sid in self._hooked:
                return
            self._hooked[sid] = session
        uid = f"tha-cost-{id(self)}-{sid}"
        emitter = session._session.get_component("event_emitter")  # type: ignore[attr-defined]
        emitter.register(
            "before-parameter-build.dynamodb.*", self._inject, unique_id=f"{uid}-i"
        )
        emitter.register(
            "after-call.dynamodb.*", self._capture, unique_id=f"{uid}-c"
        )

    def _unhook_all(self) -> None:
        for sid, session in self._hooked.items():
            uid = f"tha-cost-{id(self)}-{sid}"
            emitter = session._session.get_component("event_emitter")  # type: ignore[attr-defined]
            emitter.unregister(
                "before-parameter-build.dynamodb.*", self._inject, unique_id=f"{uid}-i"
            )
            emitter.unregister(
                "after-call.dynamodb.*", self._capture, unique_id=f"{uid}-c"
            )
        self._hooked.clear()

    # ------------------------------------------------------------------
    # Context manager
    # ------------------------------------------------------------------

    def __enter__(self) -> DdbCostTracker:
        # Hook the main session used by single-threaded calls.
        self._hook(self._ddb.clients.session)

        # Wrap _thread_clients at the instance level so every new per-thread
        # session created during the run also gets hooked.
        tracker = self
        _orig: Any = type(self._ddb)._thread_clients

        def _wrapped(ddb_self: AWSBase) -> AWSClients:
            clients = _orig(ddb_self)
            tracker._hook(clients.session)
            return clients

        self._ddb._thread_clients = types.MethodType(_wrapped, self._ddb)  # type: ignore[method-assign]
        return self

    def __exit__(self, *_: Any) -> None:
        # Remove the instance-level override so the class method is restored.
        try:
            del self._ddb.__dict__["_thread_clients"]
        except KeyError:
            pass
        self._unhook_all()

    # ------------------------------------------------------------------
    # Results
    # ------------------------------------------------------------------

    def summary(self) -> dict[str, Any]:
        """Return total RCU, WCU, estimated USD, and a per-table breakdown."""
        r_price = rcu_price(self._region)
        w_price = wcu_price(self._region)
        with self._lock:
            rcu, wcu = self._rcu, self._wcu
            tables = {name: dict(stats) for name, stats in self._tables.items()}
        return {
            "usd": round(rcu * r_price + wcu * w_price, 6),
            "rcu": rcu,
            "wcu": wcu,
            "region": self._region,
            "tables": {
                name: {
                    "rcu": s["rcu"],
                    "wcu": s["wcu"],
                    "usd": round(s["rcu"] * r_price + s["wcu"] * w_price, 6),
                }
                for name, s in tables.items()
            },
        }
