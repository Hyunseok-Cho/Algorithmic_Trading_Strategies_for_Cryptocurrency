"""Readable report names distinguish actual RSI v2+ experiment parameters."""

from decimal import Decimal

import pytest

from tests.test_services_reporting_cli import fixture_result
from trading_lab.application.report_service import ReportService, parameter_label, report_name


def named_result(version="v2", *, stop="2", target=None, parameters=None, quality=None):
    result, _ = fixture_result()
    return result.model_copy(update={
        "request": result.request.model_copy(update={
            "strategy_id": "rsi", "strategy_version": version,
            "stop_loss_pct": Decimal(stop),
            "take_profit_pct": Decimal(target) if target is not None else None,
            "strategy_parameters": parameters or {"period": 14, "lower": "38", "upper": "70"},
        }),
        "data_quality": quality or {},
    })


def test_v1_name_unchanged():
    assert report_name(named_result("v1")) == (
        "2021-01-01T00-00-00Z - 2021-01-01T04-00-00Z"
    )


@pytest.mark.parametrize("version", ["v2", "v3", "v4"])
def test_v2_plus_names(version):
    result = named_result(version)
    assert report_name(result) == (
        "2021-01-01T0000Z-2021-01-01T0400Z-SL2-TPnone-P14-L38-U70"
    )


def test_actual_parameters_and_decimal_labels():
    result = named_result("v3", stop="1.50", target="3.00", quality={
        "strategy_effective_parameters": {"period": 21, "lower": "37.5", "upper": "72"},
    })
    assert report_name(result).endswith("-SL1.5-TP3-P21-L37.5-U72")
    assert parameter_label(Decimal("0")) == "0"
    assert parameter_label(None) == "none"


def test_names_do_not_guess_missing_historical_parameters():
    result = named_result()
    result = result.model_copy(update={
        "request": result.request.model_copy(update={"strategy_parameters": {}}),
    })
    assert report_name(result).endswith("-Punknown-Lunknown-Uunknown")


def test_parameter_sets_and_repeated_exports_are_preserved(tmp_path):
    service = ReportService(tmp_path)
    result = named_result()
    first = service.export(result)
    repeated = service.export(result)
    changed = service.export(named_result(stop="3"))
    assert first.name == report_name(result)
    assert repeated.name.startswith(first.name + "__")
    assert changed != first and "-SL3-" in changed.name
    for folder in (first, repeated, changed):
        assert (folder / "result.json").exists()
