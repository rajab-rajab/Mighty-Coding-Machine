from backend.evals import run_routing_regression_suite


def test_offline_routing_regression_suite_passes():
    report = run_routing_regression_suite()

    assert report["success"] is True
    assert report["passed"] == report["total"]

