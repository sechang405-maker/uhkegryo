from types import SimpleNamespace
from backend.services.session_titles import title_terms


def test_saved_names_multiple_and_legacy_catalog_fallback():
    catalog = SimpleNamespace(get_active=lambda key: {'label_ko': '복원된 이름'} if key == 'old' else None)
    assert title_terms('[{"term_id":"a","label_ko":"저장된 이름"},{"term_id":"old"}]', catalog) == [
        {'term_id': 'a', 'label_ko': '저장된 이름'}, {'term_id': 'old', 'label_ko': '복원된 이름'}]


def test_malformed_records_do_not_expose_requests_or_raise():
    for value in (None, {}, 'bad json', 5):
        assert title_terms(value) == []
    assert title_terms([{}, {'term_id': 'x', 'request_text':'private'}, {'term_id':'x'}]) == [{'term_id':'x','label_ko':''}]
