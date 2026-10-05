from app.triage import Action, EngagedSet, Message, decide
from tests.fakes import promo


def test_unengaged_promo_is_trashed():
    d = decide(promo(1), EngagedSet())
    assert d.action is Action.TRASH


def test_engaged_domain_promo_is_kept():
    d = decide(promo(1), EngagedSet(domains={"example.com"}))
    assert d.action is Action.LABEL


def test_engaged_address_is_kept():
    d = decide(promo(1), EngagedSet(addresses={"news@shop.example.com"}))
    assert d.action is Action.LABEL


def test_sensitive_never_trashed():
    d = decide(promo(1, subject="Your bank statement is ready"), EngagedSet())
    assert d.action is Action.SKIP and "sensitive" in d.reason
    d = decide(promo(2, sender="alerts@chase.com"), EngagedSet())
    assert d.action is Action.SKIP


def test_protected_labels_never_trashed():
    m = Message("1", "t", "x@y.com", "hi", labels=frozenset({"CATEGORY_PROMOTIONS", "STARRED"}))
    assert decide(m, EngagedSet()).action is Action.SKIP


def test_thread_you_replied_in_is_skipped():
    assert decide(promo(1, thread_has_user_reply=True), EngagedSet()).action is Action.SKIP


def test_non_promo_from_stranger_is_labelled_not_trashed():
    m = Message("1", "t", "Pat <pat@gmail.com>", "Quick question", labels=frozenset({"INBOX", "CATEGORY_PERSONAL"}))
    assert decide(m, EngagedSet()).action is Action.LABEL


def test_unsubscribe_header_alone_counts_as_promo_but_updates_do_not():
    m = Message("1", "t", "a@bulk.com", "Weekly", labels=frozenset({"INBOX"}), has_list_unsubscribe=True)
    assert decide(m, EngagedSet()).action is Action.TRASH
    m = Message("1", "t", "a@bulk.com", "Receipt", labels=frozenset({"INBOX", "CATEGORY_UPDATES"}), has_list_unsubscribe=True)
    assert decide(m, EngagedSet()).action is Action.LABEL


def test_unparseable_sender_skipped():
    assert decide(Message("1", "t", "garbage", "x"), EngagedSet()).action is Action.SKIP


def test_freemail_domain_engagement_is_per_address():
    engaged = EngagedSet(domains={"gmail.com"}, addresses={"pat@gmail.com"})
    spam = Message("1", "t", "deals@gmail.com", "50% off", labels=frozenset({"CATEGORY_PROMOTIONS"}))
    assert decide(spam, engaged).action is Action.TRASH
    friend = Message("2", "t", "pat@gmail.com", "50% off", labels=frozenset({"CATEGORY_PROMOTIONS"}))
    assert decide(friend, engaged).action is Action.LABEL
