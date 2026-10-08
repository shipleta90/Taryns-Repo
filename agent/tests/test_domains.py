from app.domains import domain_of_address, parse_addresses, registrable_domain


def test_registrable_domain():
    assert registrable_domain("mail.shop.example.com") == "example.com"
    assert registrable_domain("example.com") == "example.com"
    assert registrable_domain("news.brand.co.uk") == "brand.co.uk"
    assert registrable_domain("a.b.c.gov.au") == "c.gov.au"


def test_parse_addresses():
    assert parse_addresses('"Deals" <News@Shop.com>, bob@x.org') == ["news@shop.com", "bob@x.org"]
    assert parse_addresses("") == []
    assert domain_of_address("news@mail.shop.com") == "shop.com"
