"""An optional save policy uses the existing name-aware reference traversal."""
from hermes_cli.config import _preserve_env_ref_templates


def test_string_policy_follows_named_items_after_rotation_and_reordering():
    raw = {'providers': [{'name': 'a', 'token': '${A}'}, {'name': 'b', 'token': '${B}'}]}
    current = {'providers': [{'name': 'b', 'token': 'synthetic-old-b'}, {'name': 'a', 'token': 'synthetic-old-a'}]}
    def policy(current, raw, field):
        return raw if field == 'token' else None
    saved = _preserve_env_ref_templates(current, raw, string_policy=policy)
    assert saved == {'providers': [raw['providers'][1], raw['providers'][0]]}


def test_no_policy_retains_existing_edit_semantics():
    assert _preserve_env_ref_templates('edited', '${MISSING}') == 'edited'



def test_policy_refuses_ambiguous_named_items():
    import pytest
    raw = [{"name": "a", "api_key": "${A}"}, {"name": "a", "api_key": "${B}"}]
    with pytest.raises(ValueError, match="ambiguous named"):
        _preserve_env_ref_templates(raw, raw, string_policy=lambda *args: None)


def test_policy_refuses_partial_named_items():
    import pytest
    raw = [{"name": "a", "api_key": "${A}"}, {"api_key": "${B}"}]
    with pytest.raises(ValueError, match="ambiguous named"):
        _preserve_env_ref_templates(raw, raw, string_policy=lambda *args: None)
