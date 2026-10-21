import re
from datetime import UTC, date, datetime

import pytest

from mailrobbe.config import Settings
from mailrobbe.enums import SignalKind
from mailrobbe.signals.model import (
    MAIL_KINDS,
    REPLY_PREFIXES,
    SignalFigures,
    SignalRules,
    address_class,
    domain_list,
    forward_pattern,
    forward_prefix,
    in_domains,
    rules,
    signal_group,
    signal_keys,
    signal_theme,
    silence,
    term_signal,
)
from mailrobbe.themes import load_signal_lists, load_themes

PREFIXES = ("Fwd", "Fw", "WG", "TR")


def _rules(**changes: object) -> SignalRules:
    values: dict[str, object] = {
        "internal_domains": ("nordwind.example",),
        "private_domains": ("webpost.example", "gmail.com"),
        "timezone": "Europe/Berlin",
        "night_from": 22,
        "night_to": 6,
        "many_recipients": 25,
        "forward_prefixes": PREFIXES,
        "themes": (("spenden", "Spendenaffären"), ("gewalt", "Gewalt")),
    }
    return SignalRules(**(values | changes))  # type: ignore[arg-type]


def test_rules_join_settings_file_and_themes() -> None:
    settings = Settings(
        internal_domains=" Nordwind.example, ", private_domains="Webpost.Example,gmail.com"
    )
    found = rules(settings)
    lists = load_signal_lists()
    assert found.internal_domains == ("nordwind.example",)
    assert found.private_domains[: len(lists.private_domains)] == lists.private_domains
    assert found.private_domains[-1] == "webpost.example"  # gmail.com is in the list already
    assert found.timezone == "Europe/Berlin"
    assert found.themes == tuple((theme.key, theme.name) for theme in load_themes())


def test_keys_groups_and_labels() -> None:
    found = _rules()
    assert found.keys == (*MAIL_KINDS, "term:spenden", "term:gewalt")
    assert SignalKind.SILENT not in found.keys
    assert found.knows("night") and found.knows("term:gewalt")
    assert not found.knows("silent") and not found.knows("term:rassismus")
    assert signal_group("bcc") == "recipients" and signal_group("term:spenden") == "wording"
    assert signal_theme("term:spenden") == "spenden" and signal_theme("night") is None
    assert term_signal("gewalt") == "term:gewalt"
    assert found.label("term:spenden") == "Wortfeld Spendenaffären"
    assert found.label("forward_out") == "Weiterleitung nach außen"
    assert found.theme_name("term:gewalt") == "Gewalt" and found.theme_name("bcc") is None


def test_internal_signals_need_internal_domains() -> None:
    assert _rules().available("private_alias")
    without = _rules(internal_domains=())
    assert not without.available("internal_to_private")
    assert not without.available("private_to_internal")
    assert not without.available("private_alias")
    assert without.available("private") and without.available("forward_out")
    assert not without.available("term:rassismus")


def test_night_hours_wrap_around_midnight() -> None:
    assert _rules().night_hours == (0, 1, 2, 3, 4, 5, 22, 23)
    assert _rules(night_from=1, night_to=5).night_hours == (1, 2, 3, 4)


def test_address_classes() -> None:
    found = _rules(private_domains=("webpost.example", "nordwind.example"))
    assert address_class("nordwind.example", found) == "internal"  # internal wins
    assert address_class("mail.Nordwind.example", found) == "internal"
    assert address_class("webpost.example", found) == "private"
    assert address_class("xwebpost.example", found) == "external"
    assert in_domains("A.Gmail.com", ["gmail.com"]) and not in_domains("gmail.co", ["gmail.com"])
    assert domain_list("a.example, B.example,,a.example") == ("a.example", "b.example")


@pytest.mark.parametrize(
    ("subject", "prefix"),
    [
        ("WG: Angebot", "WG"),
        ("wg:Angebot", "wg"),
        ("Fwd: Re: Angebot", "Fwd"),
        ("AW: WG: Angebot", "WG"),
        ("Re[2]: Fw[3]: Angebot", "Fw"),
        ("[Vorstand] AW: Fwd : Angebot", "Fwd"),
        ("  TR: Offre", "TR"),
        ("Re: Angebot", None),
        ("Wgebiet: Angebot", None),
        ("Angebot WG: neu", None),
        ("Info: WG: Angebot", None),  # "Info" is no prefix, so the forward is not at the start
        ("", None),
        (None, None),
    ],
)
def test_forward_prefixes(subject: str | None, prefix: str | None) -> None:
    assert forward_prefix(subject, PREFIXES) == prefix


def test_forward_pattern_takes_every_prefix() -> None:
    pattern = forward_pattern(PREFIXES)
    for reply in REPLY_PREFIXES:
        assert re.match(pattern, f"{reply}: WG: x", re.IGNORECASE)
        assert not re.match(pattern, f"{reply}: x", re.IGNORECASE)


def test_snapshot_round_trips_through_json() -> None:
    found = _rules()
    snapshot = found.snapshot()
    assert snapshot["themes"] == [["spenden", "Spendenaffären"], ["gewalt", "Gewalt"]]
    assert snapshot["private_domains"] == ["webpost.example", "gmail.com"]
    assert snapshot == _rules().snapshot() and snapshot != _rules(night_to=5).snapshot()
    figures = SignalFigures(
        computed_at=datetime(2026, 10, 21, 15, 0, tzinfo=UTC),
        rules=snapshot,
        mails=10,
        signals={"night": 2},
        persons={"night": 1},
    )
    assert SignalFigures.from_json(figures.to_json()) == figures


def test_signal_keys_follow_the_themes() -> None:
    keys = signal_keys()
    assert keys[: len(MAIL_KINDS)] == MAIL_KINDS
    assert keys[len(MAIL_KINDS) :] == tuple(f"term:{theme.key}" for theme in load_themes())


def _months(*counts: int) -> dict[date, int]:
    """Counts per month from January 2020 on."""
    return {date(2020 + index // 12, index % 12 + 1, 1): n for index, n in enumerate(counts)}


def test_silence_follows_the_timeline_rule() -> None:
    first, end = date(2020, 1, 1), date(2020, 12, 1)
    # Mails in every month up to June, then none up to the end: silent from July.
    assert silence(_months(2, 1, 3, 1, 1, 2), first, end) == (date(2020, 7, 1), 10)
    # Only two silent months before the end are not enough.
    assert silence(_months(*([1] * 10)), first, end) is None
    # Too few mails before.
    assert silence(_months(1, 0, 1, 0, 1), first, end) is None
    # A month after the end does not count.
    assert silence(_months(2, 2, 2, 2, 2, 2) | {date(2021, 6, 1): 4}, first, end) == (
        date(2020, 7, 1),
        12,
    )
