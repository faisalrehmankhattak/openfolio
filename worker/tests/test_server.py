from dataclasses import replace

from fastapi.testclient import TestClient

from openfolio_worker.config import load_settings
from openfolio_worker.server import create_app


def client():
    return TestClient(create_app(load_settings()))


def test_public_profile():
    r = client().get("/v1/personas/faisal")
    assert r.status_code == 200 and r.json()["first_name"] == "Faisal"


def test_unknown_persona_404():
    assert client().get("/v1/personas/nobody").status_code == 404


def test_foreign_origin_blocked():
    r = client().post(
        "/v1/personas/faisal/offer",
        json={"sdp": "x", "type": "offer"},
        headers={"origin": "https://evil.example"},
    )
    assert r.status_code == 403


def test_unconfigured_server_refuses_calls():
    s = replace(load_settings(), deepgram_api_key=None, llm_api_key=None, llm_model="")
    c = TestClient(create_app(s))
    r = c.post("/v1/personas/faisal/offer", json={"sdp": "x", "type": "offer"},
               headers={"origin": "https://faisalrehmanktk.com"})
    assert r.status_code == 503
