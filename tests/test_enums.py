from mailrobbe.enums import DkimStatus, KeyOrigin, best_dkim_status, origin_status, strongest_origin


def test_best_dkim_status_prefers_pass() -> None:
    statuses = [DkimStatus.FAIL, DkimStatus.PASS, DkimStatus.NO_KEY]
    assert best_dkim_status(statuses) is DkimStatus.PASS


def test_best_dkim_status_orders_failures() -> None:
    assert best_dkim_status([DkimStatus.FAIL, DkimStatus.NO_KEY]) is DkimStatus.NO_KEY
    assert best_dkim_status([DkimStatus.NO_KEY, DkimStatus.TEMP_ERROR]) is DkimStatus.TEMP_ERROR


def test_best_dkim_status_without_signatures_is_unsigned() -> None:
    assert best_dkim_status([]) is DkimStatus.UNSIGNED


def test_consistent_ranks_between_pass_and_temp_error() -> None:
    assert best_dkim_status([DkimStatus.CONSISTENT, DkimStatus.PASS]) is DkimStatus.PASS
    assert best_dkim_status([DkimStatus.TEMP_ERROR, DkimStatus.CONSISTENT]) is (
        DkimStatus.CONSISTENT
    )


def test_strongest_origin_and_its_status() -> None:
    origins = [KeyOrigin.RECONSTRUCTED, KeyOrigin.DOCUMENTED, KeyOrigin.OBSERVED]
    assert strongest_origin(origins) is KeyOrigin.OBSERVED
    assert strongest_origin([]) is None
    assert origin_status(KeyOrigin.DOCUMENTED) is DkimStatus.PASS
    assert origin_status(KeyOrigin.RECONSTRUCTED) is DkimStatus.CONSISTENT
