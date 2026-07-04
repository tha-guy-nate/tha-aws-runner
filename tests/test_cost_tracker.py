from unittest.mock import MagicMock, patch

from tha_aws_runner.cost_tracker import DdbCostTracker
from tha_aws_runner.ddb_pricing import rcu_price, wcu_price
from tha_aws_runner.dynamodb import ThaDdb
from tha_aws_runner.gsi import ThaGsi

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_ddb() -> ThaDdb:
    ddb = ThaDdb(region="us-east-1")
    return ddb


def make_tracker(ddb: ThaDdb | None = None, region: str = "us-east-1") -> DdbCostTracker:
    if ddb is None:
        ddb = make_ddb()
    return DdbCostTracker(ddb, region=region)


# ---------------------------------------------------------------------------
# ddb_pricing
# ---------------------------------------------------------------------------


def test_rcu_price_known_region() -> None:
    assert rcu_price("us-east-1") == 0.25 / 1_000_000


def test_wcu_price_known_region() -> None:
    assert wcu_price("us-east-1") == 1.25 / 1_000_000


def test_rcu_price_unknown_region_falls_back() -> None:
    assert rcu_price("xx-fake-1") == rcu_price("us-east-1")


def test_wcu_price_unknown_region_falls_back() -> None:
    assert wcu_price("xx-fake-1") == wcu_price("us-east-1")


def test_rcu_price_regional_premium() -> None:
    assert rcu_price("sa-east-1") > rcu_price("us-east-1")


# ---------------------------------------------------------------------------
# _inject
# ---------------------------------------------------------------------------


def test_inject_adds_key() -> None:
    tracker = make_tracker()
    params: dict = {}
    tracker._inject(params)
    assert params["ReturnConsumedCapacity"] == "INDEXES"


def test_inject_does_not_override_existing() -> None:
    tracker = make_tracker()
    params: dict = {"ReturnConsumedCapacity": "NONE"}
    tracker._inject(params)
    assert params["ReturnConsumedCapacity"] == "NONE"


def test_inject_does_not_override_indexes() -> None:
    tracker = make_tracker()
    params: dict = {"ReturnConsumedCapacity": "INDEXES"}
    tracker._inject(params)
    assert params["ReturnConsumedCapacity"] == "INDEXES"


# ---------------------------------------------------------------------------
# _capture
# ---------------------------------------------------------------------------


def test_capture_single_table() -> None:
    tracker = make_tracker()
    tracker._capture(
        {
            "ConsumedCapacity": {
                "TableName": "my_table",
                "ReadCapacityUnits": 10.0,
                "WriteCapacityUnits": 2.0,
            }
        }
    )
    assert tracker._rcu == 10.0
    assert tracker._wcu == 2.0
    assert tracker._tables["my_table"]["rcu"] == 10.0
    assert tracker._tables["my_table"]["wcu"] == 2.0
    assert tracker._tables["my_table"]["indexes"] == {}


def test_capture_accumulates_across_calls() -> None:
    tracker = make_tracker()
    tracker._capture(
        {
            "ConsumedCapacity": {
                "TableName": "t1",
                "ReadCapacityUnits": 5.0,
                "WriteCapacityUnits": 1.0,
            }
        }
    )
    tracker._capture(
        {
            "ConsumedCapacity": {
                "TableName": "t1",
                "ReadCapacityUnits": 3.0,
                "WriteCapacityUnits": 0.0,
            }
        }
    )
    assert tracker._rcu == 8.0
    assert tracker._wcu == 1.0
    assert tracker._tables["t1"]["rcu"] == 8.0
    assert tracker._tables["t1"]["wcu"] == 1.0


def test_capture_batch_list_response() -> None:
    tracker = make_tracker()
    tracker._capture(
        {
            "ConsumedCapacity": [
                {"TableName": "t1", "ReadCapacityUnits": 4.0, "WriteCapacityUnits": 0.0},
                {"TableName": "t2", "ReadCapacityUnits": 0.0, "WriteCapacityUnits": 6.0},
            ]
        }
    )
    assert tracker._rcu == 4.0
    assert tracker._wcu == 6.0
    assert tracker._tables["t1"]["rcu"] == 4.0
    assert tracker._tables["t2"]["wcu"] == 6.0


def test_capture_multiple_tables_tracked_separately() -> None:
    tracker = make_tracker()
    tracker._capture(
        {
            "ConsumedCapacity": [
                {"TableName": "a", "ReadCapacityUnits": 1.0, "WriteCapacityUnits": 0.0},
                {"TableName": "b", "ReadCapacityUnits": 2.0, "WriteCapacityUnits": 0.0},
            ]
        }
    )
    assert tracker._tables["a"]["rcu"] == 1.0
    assert tracker._tables["b"]["rcu"] == 2.0


def test_capture_none_parsed_is_no_op() -> None:
    tracker = make_tracker()
    tracker._capture(None)
    assert tracker._rcu == 0.0
    assert tracker._wcu == 0.0


def test_capture_missing_consumed_capacity_is_no_op() -> None:
    tracker = make_tracker()
    tracker._capture({"Items": []})
    assert tracker._rcu == 0.0


def test_capture_missing_units_default_to_zero() -> None:
    tracker = make_tracker()
    tracker._capture({"ConsumedCapacity": {"TableName": "t"}})
    assert tracker._rcu == 0.0
    assert tracker._wcu == 0.0
    assert tracker._tables["t"]["rcu"] == 0.0
    assert tracker._tables["t"]["wcu"] == 0.0
    assert tracker._tables["t"]["indexes"] == {}


def test_capture_gsi_breakdown() -> None:
    tracker = make_tracker()
    tracker._capture(
        {
            "ConsumedCapacity": {
                "TableName": "my_table",
                "ReadCapacityUnits": 5.0,
                "WriteCapacityUnits": 0.0,
                "GlobalSecondaryIndexes": {
                    "my-gsi": {"ReadCapacityUnits": 5.0, "WriteCapacityUnits": 0.0}
                },
            }
        }
    )
    assert tracker._tables["my_table"]["indexes"]["my-gsi"]["rcu"] == 5.0
    assert tracker._tables["my_table"]["indexes"]["my-gsi"]["wcu"] == 0.0


def test_capture_gsi_accumulates() -> None:
    tracker = make_tracker()
    for _ in range(3):
        tracker._capture(
            {
                "ConsumedCapacity": {
                    "TableName": "t",
                    "ReadCapacityUnits": 2.0,
                    "WriteCapacityUnits": 0.0,
                    "GlobalSecondaryIndexes": {
                        "idx": {"ReadCapacityUnits": 2.0, "WriteCapacityUnits": 0.0}
                    },
                }
            }
        )
    assert tracker._tables["t"]["indexes"]["idx"]["rcu"] == 6.0


# ---------------------------------------------------------------------------
# summary()
# ---------------------------------------------------------------------------


def test_summary_usd_calculation() -> None:
    tracker = make_tracker(region="us-east-1")
    tracker._rcu = 1_000_000.0
    tracker._wcu = 1_000_000.0
    result = tracker.summary()
    expected = round(1_000_000 * rcu_price("us-east-1") + 1_000_000 * wcu_price("us-east-1"), 6)
    assert result["usd"] == expected
    assert result["rcu"] == 1_000_000.0
    assert result["wcu"] == 1_000_000.0
    assert result["region"] == "us-east-1"


def test_summary_per_table_usd() -> None:
    tracker = make_tracker(region="us-east-1")
    tracker._tables = {"t1": {"rcu": 500_000.0, "wcu": 100_000.0, "indexes": {}}}
    tracker._rcu = 500_000.0
    tracker._wcu = 100_000.0
    result = tracker.summary()
    t1 = result["tables"]["t1"]
    assert t1["rcu"] == 500_000.0
    assert t1["wcu"] == 100_000.0
    assert t1["usd"] == round(
        500_000 * rcu_price("us-east-1") + 100_000 * wcu_price("us-east-1"), 6
    )


def test_summary_includes_gsi_indexes() -> None:
    tracker = make_tracker(region="us-east-1")
    tracker._tables = {
        "t1": {
            "rcu": 10.0,
            "wcu": 0.0,
            "indexes": {"my-gsi": {"rcu": 10.0, "wcu": 0.0}},
        }
    }
    tracker._rcu = 10.0
    result = tracker.summary()
    idx = result["tables"]["t1"]["indexes"]["my-gsi"]
    assert idx["rcu"] == 10.0
    assert idx["wcu"] == 0.0
    assert idx["usd"] == round(10.0 * rcu_price("us-east-1"), 6)


def test_summary_no_indexes_key_when_no_gsi() -> None:
    tracker = make_tracker()
    tracker._tables = {"t1": {"rcu": 5.0, "wcu": 0.0, "indexes": {}}}
    tracker._rcu = 5.0
    result = tracker.summary()
    assert "indexes" not in result["tables"]["t1"]


def test_summary_zero_when_no_calls() -> None:
    tracker = make_tracker()
    result = tracker.summary()
    assert result["usd"] == 0.0
    assert result["rcu"] == 0.0
    assert result["wcu"] == 0.0
    assert result["tables"] == {}


def test_summary_does_not_mutate_internal_tables() -> None:
    tracker = make_tracker()
    tracker._tables = {"t": {"rcu": 10.0, "wcu": 0.0, "indexes": {}}}
    tracker._rcu = 10.0
    result = tracker.summary()
    result["tables"]["t"]["rcu"] = 999.0
    assert tracker._tables["t"]["rcu"] == 10.0


# ---------------------------------------------------------------------------
# Context manager — hook/unhook
# ---------------------------------------------------------------------------


def _mock_session() -> MagicMock:
    session = MagicMock()
    emitter = MagicMock()
    session._session.get_component.return_value = emitter
    session.region_name = "us-east-1"
    return session


def test_enter_hooks_main_session() -> None:
    ddb = make_ddb()
    mock_sess = _mock_session()
    ddb.clients.session = mock_sess

    tracker = DdbCostTracker(ddb)
    tracker.__enter__()

    emitter = mock_sess._session.get_component.return_value
    assert emitter.register.call_count == 2
    tracker.__exit__(None, None, None)


def test_exit_unhooks_main_session() -> None:
    ddb = make_ddb()
    mock_sess = _mock_session()
    ddb.clients.session = mock_sess

    tracker = DdbCostTracker(ddb)
    tracker.__enter__()
    tracker.__exit__(None, None, None)

    emitter = mock_sess._session.get_component.return_value
    assert emitter.unregister.call_count == 2


def test_exit_restores_thread_clients() -> None:
    ddb = make_ddb()
    mock_sess = _mock_session()
    ddb.clients.session = mock_sess

    tracker = DdbCostTracker(ddb)
    tracker.__enter__()
    assert "_thread_clients" in ddb.__dict__
    tracker.__exit__(None, None, None)
    assert "_thread_clients" not in ddb.__dict__


def test_exit_without_enter_is_a_noop() -> None:
    ddb = make_ddb()
    mock_sess = _mock_session()
    ddb.clients.session = mock_sess

    tracker = DdbCostTracker(ddb)
    tracker.__exit__(None, None, None)  # never entered — no _thread_clients override to remove
    assert "_thread_clients" not in ddb.__dict__


def test_hook_is_idempotent() -> None:
    ddb = make_ddb()
    mock_sess = _mock_session()
    ddb.clients.session = mock_sess

    tracker = DdbCostTracker(ddb)
    tracker.__enter__()

    emitter = mock_sess._session.get_component.return_value
    count_before = emitter.register.call_count
    tracker._hook(mock_sess)  # hook same session again
    assert emitter.register.call_count == count_before  # no extra registrations

    tracker.__exit__(None, None, None)


def test_thread_clients_wrapper_hooks_new_session() -> None:
    ddb = make_ddb()
    main_sess = _mock_session()
    thread_sess = _mock_session()
    ddb.clients.session = main_sess

    thread_clients_mock = MagicMock()
    thread_clients_mock.session = thread_sess

    tracker = DdbCostTracker(ddb)

    # Patch _thread_clients BEFORE __enter__ so the closure captures the mock as _orig.
    with patch.object(type(ddb), "_thread_clients", return_value=thread_clients_mock):
        tracker.__enter__()
        result = ddb._thread_clients()

    assert result is thread_clients_mock
    thread_emitter = thread_sess._session.get_component.return_value
    assert thread_emitter.register.call_count == 2

    tracker.__exit__(None, None, None)


def test_accepts_gsi_instance() -> None:
    gsi = ThaGsi(region="us-east-1")
    mock_sess = _mock_session()
    gsi.clients.session = mock_sess

    tracker = DdbCostTracker(gsi)
    tracker.__enter__()
    emitter = mock_sess._session.get_component.return_value
    assert emitter.register.call_count == 2
    tracker.__exit__(None, None, None)


def test_context_manager_via_with() -> None:
    ddb = make_ddb()
    mock_sess = _mock_session()
    ddb.clients.session = mock_sess

    with DdbCostTracker(ddb) as cost:
        cost._capture(
            {
                "ConsumedCapacity": {
                    "TableName": "t",
                    "ReadCapacityUnits": 1.0,
                    "WriteCapacityUnits": 1.0,
                }
            }
        )

    result = cost.summary()
    assert result["rcu"] == 1.0
    assert result["wcu"] == 1.0
    assert result["usd"] > 0
