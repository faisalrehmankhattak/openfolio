from dataclasses import replace

from fastapi.testclient import TestClient

from openfolio_worker.config import Limits
from openfolio_worker.server import create_app
from openfolio_worker.usage import TODAY_FULL, VISITOR_FULL

from conftest import ORIGIN

OFFER = {"sdp": "v=0", "type": "offer"}


def client_with(settings, **limits):
    return TestClient(create_app(replace(settings, limits=Limits(**limits))))


def test_new_calls_are_refused_once_the_daily_budget_is_spent(settings):
    client = client_with(settings, daily_budget_usd=1.0, price_llm_output_per_mtok=10.0)
    assert client.get("/v1/personas/demo/ice-servers", headers=ORIGIN).status_code == 200
    client.app.state.usage.add_llm("demo", None, 0, 100_000)  # $1.00
    for r in (
        client.get("/v1/personas/demo/ice-servers", headers=ORIGIN),
        client.post("/v1/personas/demo/offer", json=OFFER, headers=ORIGIN),
    ):
        assert r.status_code == 503
        assert r.json()["detail"] == TODAY_FULL


def test_one_visitor_is_held_to_the_daily_call_cap(settings):
    client = client_with(settings, visitor_calls_per_day=2)
    usage = client.app.state.usage
    me = usage.visitor_key("testclient")  # the address TestClient reports
    usage.add_call("demo", me)
    assert client.get("/v1/personas/demo/ice-servers", headers=ORIGIN).status_code == 200
    usage.add_call("demo", me)
    r = client.get("/v1/personas/demo/ice-servers", headers=ORIGIN)
    assert r.status_code == 429
    assert r.json()["detail"] == VISITOR_FULL
    usage.add_call("demo", usage.visitor_key("198.51.100.7"))
    assert usage.refusal("demo", usage.visitor_key("198.51.100.7")) is None


def test_healthz_says_when_calls_are_being_refused(settings):
    client = client_with(settings, daily_max_minutes=1)
    assert client.get("/healthz").json()["usage_limit"] is None
    client.app.state.usage.add_seconds("demo", None, 60)
    assert client.get("/healthz").json()["usage_limit"] == TODAY_FULL


def test_totals_survive_a_restart(settings):
    first = client_with(settings, daily_max_minutes=1)
    first.app.state.usage.add_seconds("demo", None, 60)
    again = client_with(settings, daily_max_minutes=1)
    assert again.get("/v1/personas/demo/ice-servers", headers=ORIGIN).json()["detail"] == TODAY_FULL
