from app.safety import assess


def test_ssn_detected():
    assert "ssn-pattern" in assess("my number is 123-45-6789").reasons


def test_invalid_ssn_ignored():
    assert not assess("order 000-12-3456 shipped").sensitive


def test_card_requires_luhn():
    assert "card-number" in assess("card 4111 1111 1111 1111").reasons
    assert not assess("tracking 1234 5678 9012 3456").sensitive


def test_financial_sender_and_gov():
    assert assess("hello", "chase.com").sensitive
    assert assess("hello", "irs.gov").sensitive
    assert assess("hello", "city.ny.gov").sensitive


def test_keywords():
    assert assess("Your bank statement is ready").sensitive
    assert not assess("Big summer sale").sensitive
