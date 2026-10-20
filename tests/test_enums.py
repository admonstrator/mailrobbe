from mailspider.enums import DkimStatus, best_dkim_status


def test_best_dkim_status_prefers_pass() -> None:
    statuses = [DkimStatus.FAIL, DkimStatus.PASS, DkimStatus.NO_KEY]
    assert best_dkim_status(statuses) is DkimStatus.PASS


def test_best_dkim_status_orders_failures() -> None:
    assert best_dkim_status([DkimStatus.FAIL, DkimStatus.NO_KEY]) is DkimStatus.NO_KEY
    assert best_dkim_status([DkimStatus.NO_KEY, DkimStatus.TEMP_ERROR]) is DkimStatus.TEMP_ERROR


def test_best_dkim_status_without_signatures_is_unsigned() -> None:
    assert best_dkim_status([]) is DkimStatus.UNSIGNED
