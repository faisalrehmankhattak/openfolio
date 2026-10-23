from openfolio_worker.cards import card_for


def test_common_questions_select_local_cards():
    assert card_for('Tell me about your projects') == 'projects'
    assert card_for('What are your skills?') == 'skills'
    assert card_for('How do I contact you?') == 'contact'
    assert card_for('What is your work experience?') == 'experience'
    assert card_for('Hello, how are you?') is None
