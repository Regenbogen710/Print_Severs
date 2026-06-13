import ipaddress

from app.security import address_in_entries, parse_client_address


def test_parse_lan_address() -> None:
    client = parse_client_address("192.168.1.20")

    assert client.is_lan
    assert not client.is_local


def test_whitelist_accepts_cidr() -> None:
    address = ipaddress.ip_address("203.0.113.8")

    assert address_in_entries(address, ["203.0.113.0/24"])
    assert not address_in_entries(address, ["198.51.100.0/24"])
