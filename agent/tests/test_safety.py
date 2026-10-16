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
    assert assess("Re: Payment Plan Reminder for matter 1234.001 IRMO Smith v. Jones Post-Judgment").sensitive
    assert assess("Your attorney sent a document").sensitive


def test_ordinary_mail_not_flagged_by_new_rules():
    assert not assess("11u games Sunday").sensitive
    assert not assess("Middle School Mariner Memo: Week of October 5 - 9").sensitive
    assert not assess("Axios Pro Rata: Rigor reminder").sensitive


# ---- privacy scrubbing (what the cloud model sees) --------------------------------------
from app import privacy  # noqa: E402


def test_redacts_ids_and_codes_but_keeps_ordinary_text():
    s = privacy.redact("SSN 123-45-6789, card 4111 1111 1111 1111, account ending in 4821, "
                       "routing number: 021000021, your verification code is 482913. Call 415-555-0134.")
    for secret in ("123-45-6789", "4111", "4821", "021000021", "482913"):
        assert secret not in s
    assert "415-555-0134" in s and "your verification code is [hidden code]" in s


def test_amounts_hidden_only_in_money_mail():
    bank = privacy.email_full({"id": "b", "from": "Alerts <alerts@chase.com>", "subject": "Balance",
                               "body": "Your balance is $12,345.67"})
    shop = privacy.email_full({"id": "s", "from": "Shop <hi@shop.com>", "subject": "Shipped",
                               "body": "Order total $45.10"})
    assert "12,345" not in bank["body"] and bank["redacted"] is True
    assert shop["body"] == "Order total $45.10" and "redacted" not in shop


def test_health_email_is_readable():
    m = privacy.email_full({"id": "h", "from": "Portal <noreply@simplepractice.com>",
                            "subject": "Appointment reminder", "body": "See you Tuesday at 3pm."})
    assert m["body"] == "See you Tuesday at 3pm."
