from mailrobbe.api.deps import EDITOR_LIMIT, editor_name


def test_editor_name_is_decoded_cleaned_and_cut() -> None:
    assert editor_name("Anna%20M%C3%BCller") == "Anna Müller"
    assert editor_name("  Eva \t Klein ") == "Eva Klein"
    assert editor_name("a%0Ab%00c") == "a b c"
    assert editor_name("%FF") == "�"
    assert editor_name("x" * 300) == "x" * EDITOR_LIMIT
    assert editor_name(None) is None
    assert editor_name("%20%0A") is None
