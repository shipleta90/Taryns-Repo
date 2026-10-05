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


def test_health_and_legal_are_sensitive():
    assert assess("You have a new shared document", "simplepractice.com").sensitive
    assert assess("Sign in to your Client Portal app").sensitive
    assert assess("Re: EPGGB Payment Plan Reminder 2115.002 IRMO Cardona V. Lockhart Post-Judgment").sensitive
    assert assess("Your attorney sent a document").sensitive


def test_ordinary_mail_not_flagged_by_new_rules():
    assert not assess("11u games Sunday").sensitive
    assert not assess("Middle School Mariner Memo: Week of October 5 - 9").sensitive
    assert not assess("Axios Pro Rata: Rigor reminder").sensitive
