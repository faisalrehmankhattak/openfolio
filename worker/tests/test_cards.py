import pytest

from openfolio_worker.cards import card_data, card_for


@pytest.mark.parametrize(
    ("text", "card"),
    [
        ("Tell me about your projects", "projects"),
        ("What are your skills?", "skills"),
        ("How do I contact you?", "contact"),
        ("Why should we hire you?", "contact"),
        ("What is your work experience?", "experience"),
        ("Hello, how are you?", None),
    ],
)
def test_question_selects_card(text, card):
    assert card_for(text) == card


def test_naming_a_project_shows_projects(persona):
    assert card_for("Tell me about Fieldnote", persona) == "projects"
    assert card_for("Tell me about Fieldnote") is None


def test_card_data_is_json_ready(persona):
    contact = card_data(persona, "contact")
    assert contact["email"] == persona.email
    assert all(isinstance(link["url"], str) for link in contact["links"])
    assert card_data(persona, "projects")["projects"][0]["name"] == persona.projects[0].name
