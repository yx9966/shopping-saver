"""Contracts for provider failure handling and unverified price evidence."""
import importlib.util
import json
from pathlib import Path

import pytest


SPEC = importlib.util.spec_from_file_location(
    "shopping_maishou", Path(__file__).resolve().parents[1] / "scripts/maishou.py")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_prices_and_conflicting_coupon_evidence_are_preserved():
    item = {"goodsId": "opaque-id", "actualPrice": "416.1", "couponPrice": "20",
            "couponConditions": "0.00", "tagList": ["满21减20", "88VIP专享95折"],
            "commission": "16.86", "couponEndTime": "2026-10-31"}
    assert MODULE.extract_data({"code": 200, "data": [item]}, "search") == [item]
    assert MODULE.extract_data({"code": 200, "data": []}, "search") == []


@pytest.mark.parametrize("response", [
    {"code": 401, "message": "未登录", "data": []},
    {"code": 200, "status": "error", "data": []},
    {"code": 200, "data": {}},
    {"code": 200, "data": [{}]},
])
def test_failures_are_not_empty_success(response):
    with pytest.raises(MODULE.ProviderError):
        MODULE.extract_data(response, "search")


def test_detail_does_not_automatically_create_promotion_link(monkeypatch, capsys):
    calls = []

    def post(operation, payload, headers, timeout):
        calls.append((operation, payload))
        return {"goodsId": "latest-id", "actualPrice": "416.1"}

    monkeypatch.setattr(MODULE, "post", post)
    monkeypatch.setenv("MAISHOU_INVITE_CODE", "private-test-value")
    assert MODULE.main(["detail", "--source", "1", "--id", "search-id"]) == 0
    output = capsys.readouterr().out
    result = json.loads(output)
    assert [call[0] for call in calls] == ["detail"]
    assert result["checkout_verified"] is False
    assert result["requested_goods_id"] == "search-id"
    assert result["data"]["goodsId"] == "latest-id"
    assert result["referral_config"] == "custom"
    assert "private-test-value" not in output


def test_cli_provider_failure_returns_nonzero_without_success_output(monkeypatch, capsys):
    def fail(*args):
        raise MODULE.ProviderError("Provider error 401: 未登录")

    monkeypatch.setattr(MODULE, "post", fail)
    assert MODULE.main(["search", "--source", "2", "--keyword", "猫粮"]) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert json.loads(captured.err)["status"] == "error"
