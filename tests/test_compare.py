"""Behavior contracts for candidate pricing and complete shopping plans."""
import importlib.util
import itertools
import json
from pathlib import Path
import random
import subprocess
import sys

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "compare.py"
SPEC = importlib.util.spec_from_file_location("shopping_compare", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)
NOW = "2026-10-13T12:00:00+08:00"


def order(name, prices, **kwargs):
    return {
        "id": name, "platform": "synthetic",
        "lines": [{"item": item, "quantity": 1, "unit_cents": price, "url": "https://example.invalid/item"} for item, price in prices.items()],
        "discounts": [], "shipping_cents": 0, "resources": [],
        "evidence": {"source": "https://example.invalid/synthetic", "observed_at": NOW},
        "valid_until": "2026-10-14T00:00:00+08:00", **kwargs,
    }


def rule(items, threshold, off, **kwargs):
    return {"id": "coupon", "items": items, "basis": "original", "threshold_cents": threshold, "off_cents": off, "repeat": False, **kwargs}


def run(orders, needs=None, cap=0):
    return MODULE.compare({"needs": needs or {"a": 1, "b": 1}, "max_filler_cents": cap, "orders": orders}, NOW)


def test_filler_total_shipping_and_fewest_orders():
    separate = [order("a", {"a": 18000}), order("b", {"b": 8500}, shipping_cents=500)]
    filled = order("filled", {"a": 19900, "b": 9900, "tissue": 500},
                   discounts=[rule(["a", "b", "tissue"], 30000, 5000)], resources=["one-coupon"])
    plans = run(separate + [filled], cap=500)
    assert plans["plans"]["lowest_total"]["total_cents"] == 25300
    assert plans["plans"]["without_filler"]["total_cents"] == 27000
    assert plans["saving_vs_without_filler_cents"] == 1700
    assert run(separate + [filled], cap=499)["plans"]["lowest_total"]["total_cents"] == 27000
    expensive = order("combined", {"a": 19000, "b": 9000})
    result = run(separate + [expensive])["plans"]
    assert result["lowest_total"]["order_count"] == 2
    assert result["fewest_orders"]["total_cents"] == 28000


def test_once_only_resources_and_exact_quantities():
    offers = [order("a", {"a": 100}, resources=["shared"]), order("b", {"b": 100}, resources=["shared"])]
    assert run(offers)["status"] == "no_complete_plan"
    offers.append(order("b-normal", {"b": 200}))
    assert run(offers)["plans"]["lowest_total"]["total_cents"] == 300
    assert run([offers[0]], {"a": 2})["status"] == "no_complete_plan"
    offers[0]["lines"][0]["quantity"] = 2
    assert run([offers[0]], {"a": 2})["plans"]["lowest_total"]["total_cents"] == 200


def test_scoped_discount_repeat_and_remaining_threshold():
    offer = order("all", {"a": 60000, "b": 10000}, shipping_cents=500,
                  discounts=[rule(["a"], 30000, 5000, repeat=True),
                             rule(["a"], 50000, 1000, id="second", basis="remaining")])
    result = run([offer])["plans"]["lowest_total"]
    assert result["total_cents"] == 59500
    offer["discounts"][1]["threshold_cents"] = 50001
    with pytest.raises(ValueError, match="threshold not met"):
        run([offer])


def test_allocation_conserves_cents_and_caps_discount():
    remaining = {"a": 1, "b": 2, "c": 2}
    MODULE.allocate(3, set(remaining), remaining)
    assert sum(remaining.values()) == 2
    assert min(remaining.values()) >= 0
    result = run([order("a", {"a": 100}, shipping_cents=50, discounts=[rule(["a"], 0, 500)])], {"a": 1})
    assert result["plans"]["lowest_total"]["total_cents"] == 50


def test_zero_budget_does_not_authorize_extra_goods_even_if_free():
    offer = order("with-extra", {"a": 100, "extra": 0})
    assert run([offer], {"a": 1})["status"] == "no_complete_plan"
    assert run([offer], {"a": 1}, cap=1)["plans"]["without_filler"] is None


def test_expiry_start_and_checkout_evidence():
    expired = order("expired", {"a": 1}, valid_until=NOW, valid_from="2026-10-12T00:00:00+08:00")
    future = order("future", {"a": 1}, valid_from="2026-10-13T13:00:00+08:00")
    current = order("current", {"a": 200}, checkout_total_cents=200)
    result = run([expired, future, current], {"a": 1})
    assert result["inactive_orders"] == ["expired", "future"]
    assert result["plans"]["lowest_total"]["verification"] == "checkout_observed"
    assert run([current, order("b", {"b": 200})])["plans"]["lowest_total"]["verification"] == "estimated"
    current["checkout_total_cents"] = 199
    with pytest.raises(ValueError, match="does not match"):
        run([current], {"a": 1})


@pytest.mark.parametrize("bad", [-1, 1.5, True, "100"])
def test_reject_invalid_money(bad):
    with pytest.raises(ValueError, match="integer"):
        run([order("a", {"a": bad})], {"a": 1})


def test_incomplete_plan_and_unknown_rules():
    result = run([order("a", {"a": 100})])
    assert result["status"] == "no_complete_plan"
    assert result["uncovered_items"] == ["b"]
    assert result["plans"]["lowest_total"] is None
    offer = order("a", {"a": 100})
    offer["discount_percent"] = 10
    with pytest.raises(ValueError, match="Unknown fields"):
        run([offer], {"a": 1})


def test_solver_matches_exhaustive_subsets():
    rng = random.Random(241)
    for _ in range(30):
        offers = []
        for index in range(8):
            items = rng.sample(["a", "b", "c"], rng.randint(1, 3))
            offers.append(order(str(index), {item: rng.randint(1, 500) for item in items},
                                resources=["shared"] if rng.random() < 0.4 else []))
        feasible = []
        for size in range(1, 4):
            for subset in itertools.combinations(offers, size):
                items = [line["item"] for candidate in subset for line in candidate["lines"]]
                resources = [resource for candidate in subset for resource in candidate["resources"]]
                if sorted(items) == ["a", "b", "c"] and len(resources) == len(set(resources)):
                    feasible.append((sum(line["unit_cents"] for candidate in subset for line in candidate["lines"]), size))
        result = run(offers, {"a": 1, "b": 1, "c": 1})["plans"]
        if not feasible:
            assert result["lowest_total"] is None
        else:
            assert (result["lowest_total"]["total_cents"], result["lowest_total"]["order_count"]) == min(feasible)
            assert (result["fewest_orders"]["order_count"], result["fewest_orders"]["total_cents"]) == min((count, cost) for cost, count in feasible)


def test_cli_roundtrip_and_error_exit_codes(tmp_path):
    data = {"needs": {"a": 1}, "orders": [order("a", {"a": 99})], "max_filler_cents": 0}
    source, target = tmp_path / "input.json", tmp_path / "result.json"
    source.write_text(json.dumps(data), encoding="utf-8")
    command = [sys.executable, str(SCRIPT), str(source), "--at", NOW]
    result = subprocess.run(command + ["--output", str(target)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert json.loads(target.read_text())["plans"]["lowest_total"]["total_cents"] == 99
    data["needs"]["b"] = 1
    source.write_text(json.dumps(data), encoding="utf-8")
    assert subprocess.run(command, capture_output=True).returncode == 1
    source.write_text("{", encoding="utf-8")
    assert subprocess.run(command, capture_output=True).returncode == 2


def test_lowest_total_includes_mandatory_fees():
    low_sticker = order("low-sticker", {"a": 40000}, shipping_cents=1000, other_fees_cents=2500)
    all_in = order("all-in", {"a": 42000}, checkout_total_cents=42000)
    result = run([low_sticker, all_in], {"a": 1})["plans"]
    assert result["lowest_total"]["orders"][0]["id"] == "all-in"
    assert result["lowest_total"]["total_cents"] == 42000
    low_sticker["checkout_total_cents"] = 43500
    priced = run([low_sticker], {"a": 1})["plans"]["lowest_total"]
    assert priced["orders"][0]["other_fees_cents"] == 2500
    low_sticker["other_fees_cents"] = -1
    with pytest.raises(ValueError, match="integer"):
        run([low_sticker], {"a": 1})


def test_verified_minimum_requires_every_order_to_be_observed():
    offers = [order("cheap-a", {"a": 100}),
              order("verified-a", {"a": 120}, checkout_total_cents=120),
              order("verified-b", {"b": 200}, checkout_total_cents=200),
              order("verified-combined", {"a": 200, "b": 200}, checkout_total_cents=400)]
    plans = run(offers)["plans"]
    assert plans["lowest_total"]["total_cents"] == 300
    assert plans["lowest_total"]["verification"] == "estimated"
    assert plans["lowest_verified"]["total_cents"] == 320
    assert plans["lowest_verified"]["verification"] == "checkout_observed"
    assert run([offers[0], offers[2]])["plans"]["lowest_verified"] is None
