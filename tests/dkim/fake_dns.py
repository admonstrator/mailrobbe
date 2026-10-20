"""A DNS server stand-in for the resolver tests: dnspython's UDP transport answered from a dict.

dnspython's resolver logic (rcodes, retries, lifetime, nameserver selection) runs unchanged;
only dns.query.udp is replaced, so no query ever leaves the process. block_network makes every
other dnspython transport fail the test: pytest.fail raises a BaseException, which neither
dnspython's retry loop nor the resolver's catch-all can swallow.
"""

from dataclasses import dataclass, field

import dns.message
import dns.query
import dns.rcode
import dns.rdata
import dns.rdataclass
import dns.rdatatype
import pytest
from dns.rdtypes.ANY.TXT import TXT

# A zone entry: TXT records (each a tuple of character strings), an rcode without answer, or an
# exception (class or instance) the transport raises: dns.exception.Timeout, OSError.
Reply = list[tuple[bytes, ...]] | dns.rcode.Rcode | Exception | type[Exception]

ROOT_SERVER = dns.rdata.from_text(dns.rdataclass.IN, dns.rdatatype.NS, "a.root-servers.net.")


@dataclass(frozen=True, slots=True)
class Query:
    name: str  # absolute, with the trailing dot
    rdtype: str
    where: str  # nameserver address
    timeout: float | None
    edns: int
    payload: int


@dataclass
class FakeDns:
    """Answers TXT queries from zone, else with default; the root "." answers NS queries (the
    resolver's reachability probe) unless it has a zone entry of its own, such as a timeout."""

    zone: dict[str, Reply] = field(default_factory=dict)  # absolute name -> reply
    default: Reply = dns.rcode.NXDOMAIN  # for names not in the zone
    queries: list[Query] = field(default_factory=list)

    def down(self, reply: Reply = dns.rcode.REFUSED) -> None:
        """DNS unreachable: every name, the root included, gets reply."""
        self.default = self.zone["."] = reply

    def up(self) -> None:
        self.default = dns.rcode.NXDOMAIN
        self.zone.pop(".", None)

    def udp(
        self,
        request: dns.message.Message,
        where: str,
        timeout: float | None = None,
        **_: object,
    ) -> dns.message.Message:
        question = request.question[0]
        name = question.name.to_text()
        rdtype = dns.rdatatype.to_text(question.rdtype)
        self.queries.append(Query(name, rdtype, where, timeout, request.edns, request.payload))
        response = dns.message.make_response(request)
        if name == "." and name not in self.zone:
            rrset = response.find_rrset(
                response.answer, question.name, dns.rdataclass.IN, dns.rdatatype.NS, create=True
            )
            rrset.add(ROOT_SERVER, ttl=518400)
            return response
        reply = self.zone.get(name, self.default)
        if isinstance(reply, Exception | type):
            raise reply
        if isinstance(reply, dns.rcode.Rcode):
            response.set_rcode(reply)
            return response
        rrset = response.find_rrset(
            response.answer, question.name, dns.rdataclass.IN, dns.rdatatype.TXT, create=True
        )
        for strings in reply:
            rrset.add(TXT(dns.rdataclass.IN, dns.rdatatype.TXT, strings), ttl=300)
        return response


def txt(record: str) -> list[tuple[bytes, ...]]:
    """One TXT record as published: character strings of at most 255 bytes."""
    data = record.encode("latin-1")
    return [tuple(data[start : start + 255] for start in range(0, len(data), 255))]


def block_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def refuse(*args: object, **kwargs: object) -> None:
        pytest.fail("a test tried to send a DNS query")

    for transport in ("udp", "tcp", "https", "tls", "quic"):
        monkeypatch.setattr(dns.query, transport, refuse)


def install(monkeypatch: pytest.MonkeyPatch, zone: dict[str, Reply] | None = None) -> FakeDns:
    fake = FakeDns(dict(zone or {}))
    monkeypatch.setattr(dns.query, "udp", fake.udp)
    return fake
