"""Durable-write evidence must not disappear after an unrelated image result."""
import json
import pytest
from tools import write_approval as wa


def test_preflight_deferral_is_returned_to_the_calling_model(tmp_path, monkeypatch):
    from tools.memory_tool import MemoryStore, memory_tool
    monkeypatch.setenv('HERMES_HOME', str(tmp_path))
    (tmp_path / 'config.yaml').write_text('durable_write_review:\n  enabled: true\n')
    with wa.review_evidence([]):
        result = json.loads(memory_tool(action='add', target='user', content='Prefers HTTPS links.', store=MemoryStore()))
    assert result['review_state'] == 'defer'
    assert result['saved'] is False
    assert result['success'] is False
    assert 'missing' in result['message'].lower()
    assert 'Continue the task' not in result['message']
    assert not (tmp_path / 'memories/USER.md').exists()



@pytest.mark.parametrize('decision', ['accept', 'reject', 'defer', 'error'])
def test_tool_returns_completed_review_not_a_promise(tmp_path, monkeypatch, decision):
    from tools.memory_tool import MemoryStore, memory_tool
    monkeypatch.setenv('HERMES_HOME', str(tmp_path))
    (tmp_path / 'config.yaml').write_text('durable_write_review:\n  enabled: true\n')
    def review(*args):
        if decision == 'error':
            raise RuntimeError('provider unavailable')
        return {'decision': decision, 'reason': 'Test decision',
                'evidence': ['source:0'] if decision == 'accept' else []}, {}
    monkeypatch.setattr(wa, '_review_call', review)
    with wa.review_evidence([{'role': 'user', 'content': 'I prefer HTTPS links.'}]):
        result = json.loads(memory_tool(action='add', target='user', content='Prefers HTTPS links.', store=MemoryStore()))
    expected = {'accept': 'applied', 'error': 'defer'}.get(decision, decision)
    assert result['review_state'] == expected
    assert result['saved'] is (decision == 'accept')
    assert result['success'] is (decision == 'accept')
    assert (tmp_path / 'memories/USER.md').exists() is (decision == 'accept')
    assert 'Continue the task' not in result['message']
    if decision == 'accept':
        from agent.memory_manager import MemoryManager
        from unittest.mock import Mock
        manager = MemoryManager.__new__(MemoryManager)
        manager.on_memory_write = Mock()
        manager.notify_memory_tool_write(result, {'action': 'add', 'target': 'user', 'content': 'Prefers HTTPS links.'})
        manager.on_memory_write.assert_not_called()


@pytest.mark.parametrize('failure', ['storage', 'busy', 'malformed', 'manual_gate'])
def test_failure_and_manual_paths_are_explicit(tmp_path, monkeypatch, failure):
    from tools.memory_tool import MemoryStore, memory_tool
    monkeypatch.setenv('HERMES_HOME', str(tmp_path))
    cfg = 'durable_write_review:\n  enabled: true\n'
    if failure == 'manual_gate':
        cfg += 'memory:\n  write_approval: true\n'
    (tmp_path / 'config.yaml').write_text(cfg)
    def decide(*args):
        if failure == 'malformed':
            return {'unexpected': 'shape'}, {}
        return {'decision': 'accept', 'reason': 'Explicit preference', 'evidence': ['source:0']}, {}
    monkeypatch.setattr(wa, '_review_call', decide)
    if failure == 'storage':
        def fail(*args):
            raise OSError('disk unavailable')
        monkeypatch.setattr(wa, 'atomic_json_write', fail)
    if failure == 'busy':
        monkeypatch.setattr(wa, '_start_review', lambda callback: False)
    with wa.review_evidence([{'role': 'user', 'content': 'I prefer HTTPS links.'}]):
        result = json.loads(memory_tool(action='add', target='user', content='Prefers HTTPS links.', store=MemoryStore()))
    assert result['saved'] is False
    assert not (tmp_path / 'memories/USER.md').exists()
    assert result['review_state'] == {'storage': 'storage_error', 'manual_gate': 'accepted'}.get(failure, 'defer')
    assert 'Not saved' in result['message']


def test_origin_is_isolated_and_retained_in_receipt(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from tools.memory_tool import MemoryStore, memory_tool
    monkeypatch.setenv('HERMES_HOME', str(tmp_path))
    (tmp_path / 'config.yaml').write_text('durable_write_review:\n  enabled: true\n')
    monkeypatch.setattr(wa, '_review_call', lambda *args: ({'decision': 'accept', 'reason': 'Explicit preference', 'evidence': ['source:0']}, {}))
    @wa.capture_review_evidence
    def invoke(agent, messages):
        return json.loads(memory_tool(action='add', target='user', content='Prefers HTTPS links.', store=MemoryStore()))
    result = invoke(SimpleNamespace(session_id='origin-test', platform='webui'), [{'role': 'user', 'content': 'I prefer HTTPS links.'}])
    receipt = json.loads((tmp_path / 'pending/memory/receipts' / (result['pending_id'] + '.json')).read_text())
    assert receipt['source_origin'] == {'session_id': 'origin-test', 'platform': 'webui'}
    assert wa._review_origin.get() is None


@pytest.mark.parametrize('enabled', [False, True])
def test_review_config_uses_utf8_on_non_utf8_hosts(tmp_path, monkeypatch, enabled):
    from pathlib import Path

    monkeypatch.setenv('HERMES_HOME', str(tmp_path))
    config = tmp_path / 'config.yaml'
    config.write_text('# 日本語\ndurable_write_review:\n  enabled: ' + str(enabled).lower() + '\n', encoding='utf-8')
    path_open = Path.open

    def non_utf8_default(path, mode='r', buffering=-1, encoding=None, errors=None, newline=None):
        if 'b' not in mode and encoding is None:
            encoding = 'ascii'
        return path_open(path, mode, buffering, encoding, errors, newline)

    monkeypatch.setattr(Path, 'open', non_utf8_default)
    result = wa.review_config()
    assert (result is not None) is enabled


def test_completed_receipt_uses_utf8_on_non_utf8_hosts(tmp_path, monkeypatch):
    from pathlib import Path

    monkeypatch.setenv('HERMES_HOME', str(tmp_path))
    record = {'id': 'utf8test', 'review': {'state': 'ready'}}
    monkeypatch.setattr(wa, '_stage_write', lambda *a, **kw: record)
    monkeypatch.setattr(wa, 'get_pending', lambda *a: None)
    receipt = tmp_path / 'pending/memory/receipts/utf8test.json'
    receipt.parent.mkdir(parents=True)
    receipt.write_text(json.dumps({'id': 'utf8test', 'summary': '日本語',
                                  'review': {'state': 'applied'}}, ensure_ascii=False), encoding='utf-8')
    monkeypatch.setattr(wa, '_start_review', lambda callback: True)
    read_text = Path.read_text

    def non_utf8_default(path, encoding=None, errors=None, **kwargs):
        return read_text(path, encoding=encoding or 'ascii', errors=errors, **kwargs)

    monkeypatch.setattr(Path, 'read_text', non_utf8_default)
    result = wa.stage_write('memory', {}, summary='日本語', origin='foreground')
    assert result['review']['state'] == 'applied'
    assert result['summary'] == '日本語'


@pytest.mark.parametrize('receipt_text', ['sensitive-receipt-sentinel', '[]', '"sensitive-receipt-sentinel"'])
def test_bad_receipt_readback_reports_unknown_without_leaking_bytes(tmp_path, monkeypatch, caplog, receipt_text):
    monkeypatch.setenv('HERMES_HOME', str(tmp_path))
    record = {'id': 'badjson', 'review': {'state': 'ready'}}
    monkeypatch.setattr(wa, '_stage_write', lambda *a, **kw: record)
    monkeypatch.setattr(wa, 'get_pending', lambda *a: None)
    receipt = tmp_path / 'pending/memory/receipts/badjson.json'
    receipt.parent.mkdir(parents=True)
    receipt.write_text(receipt_text, encoding='utf-8')
    monkeypatch.setattr(wa, '_start_review', lambda callback: True)
    result = wa.stage_write('memory', {}, summary='test', origin='foreground')
    assert result['review']['state'] == 'unknown'
    assert 'Durable-write outcome readback unavailable: memory/badjson' in caplog.text
    assert 'sensitive-receipt-sentinel' not in caplog.text


def test_uncertain_application_is_not_reported_as_unsaved(tmp_path, monkeypatch):
    from tools import memory_tool as mt
    monkeypatch.setenv('HERMES_HOME', str(tmp_path))
    (tmp_path / 'config.yaml').write_text('durable_write_review:\n  enabled: true\n')
    monkeypatch.setattr(wa, '_review_call', lambda *args: ({'decision': 'accept', 'reason': 'Explicit preference', 'evidence': ['source:0']}, {}))
    apply = mt.apply_memory_pending
    def uncertain(payload, store):
        result = apply(payload, store)
        assert result['success']
        raise OSError('post-write failure')
    monkeypatch.setattr(mt, 'apply_memory_pending', uncertain)
    with wa.review_evidence([{'role': 'user', 'content': 'I prefer HTTPS links.'}]):
        result = json.loads(mt.memory_tool(action='add', target='user', content='Prefers HTTPS links.', store=mt.MemoryStore()))
    assert result['review_state'] == 'applying'
    assert result['saved'] is None
    assert result['success'] is False
    assert 'uncertain' in result['message']
    assert (tmp_path / 'memories/USER.md').exists()


@pytest.mark.parametrize('batch', [False, True])
def test_skill_review_releases_outer_lock(tmp_path, monkeypatch, batch):
    import threading
    from tools import skill_manager_tool as sm
    from tools.memory_tool import MemoryStore
    monkeypatch.setenv('HERMES_HOME', str(tmp_path))
    (tmp_path / 'config.yaml').write_text('durable_write_review:\n  enabled: true\n')
    entered, release, written = threading.Event(), threading.Event(), threading.Event()
    result = []
    def decide(*args):
        entered.set()
        assert release.wait(5)
        return {'decision': 'reject', 'reason': 'Test rejection', 'evidence': []}, {}
    monkeypatch.setattr(wa, '_review_call', decide)
    def call():
        with wa.review_evidence([{'role': 'user', 'content': 'Please add a tested reusable procedure.'}]):
            op = {'action': 'create', 'name': 'probe', 'content': '---\nname: probe\ndescription: Test procedure.\n---\nTest.'}
            result.append(json.loads(sm.skill_manage(action=None, name=None, operations=[op]) if batch else sm.skill_manage(**op)))
    caller = threading.Thread(target=call)
    writer = threading.Thread(target=lambda: (MemoryStore().add('user', 'Concurrent entry'), written.set()))
    caller.start()
    try:
        assert entered.wait(5)
        writer.start()
        assert written.wait(2), 'Reviewer holds shared lock'
        assert caller.is_alive()
    finally:
        release.set()
        caller.join(5)
        if writer.ident:
            writer.join(5)
    assert result[0]['review_state'] == 'reject'


def test_multimodal_user_text_is_preserved_with_omission():
    with wa.review_evidence([{'role': 'user', 'content': [
        {'type': 'text', 'text': 'I prefer HTTPS links.'},
        {'type': 'image_url', 'image_url': {'url': 'data:image/png;base64,AA=='}}]}]):
        source = wa._evidence.get()
        assert source[0]['text'] == 'I prefer HTTPS links.'
        assert source[0]['omitted_nontext_parts'] == 1


@pytest.mark.parametrize('decision', ['accept', 'reject', 'defer'])
def test_background_destructive_proposal_keeps_human_gate(tmp_path, monkeypatch, decision):
    from tools import skill_provenance
    from tools.memory_tool import MemoryStore, memory_tool
    from agent.background_review import summarize_background_review_actions
    monkeypatch.setenv('HERMES_HOME', str(tmp_path))
    (tmp_path / 'config.yaml').write_text('durable_write_review:\n  enabled: true\n')
    store = MemoryStore()
    assert store.add('user', 'Prefers concise replies.')['success']
    monkeypatch.setattr(skill_provenance, 'is_unattended_review', lambda: True)
    monkeypatch.setattr(wa, '_review_call', lambda *args: ({'decision': decision, 'reason': 'Test decision', 'evidence': ['source:0'] if decision == 'accept' else []}, {}))
    with wa.review_evidence([{'role': 'user', 'content': 'Keep this existing preference.'}]):
        raw = memory_tool(action='remove', target='user', old_text='Prefers concise', store=store)
    result = json.loads(raw)
    assert result['review_state'] == ('accepted' if decision == 'accept' else decision)
    assert result['saved'] is False
    assert 'Prefers concise replies.' in (tmp_path / 'memories/USER.md').read_text()
    messages = [
        {'role': 'assistant', 'tool_calls': [{'id': 'persist', 'function': {'name': 'memory', 'arguments': '{"action":"remove","target":"user"}'}}]},
        {'role': 'tool', 'tool_call_id': 'persist', 'content': raw},
    ]
    notices = summarize_background_review_actions(messages, [])
    assert len(notices) == 1
    assert result['review_state'] in notices[0]
    assert 'updated' not in notices[0]
    if result['staged']:
        assert '/memory pending' in notices[0]


def test_pending_list_exposes_review_state_and_reason(tmp_path, monkeypatch):
    from hermes_cli.write_approval_commands import _fmt_pending_list
    monkeypatch.setenv('HERMES_HOME', str(tmp_path))
    (tmp_path / 'config.yaml').write_text('durable_write_review:\n  enabled: true\n')
    with wa.review_evidence([]):
        wa.stage_write('memory', {'action': 'add', 'content': 'A preference'}, summary='Test', origin='foreground')
    output = _fmt_pending_list('memory')
    assert 'Review: defer' in output
    assert 'Original source evidence missing' in output


def test_capacity_outcome_lock_failure_still_returns_state(tmp_path, monkeypatch):
    from contextlib import contextmanager
    from tools.memory_tool import MemoryStore, memory_tool
    monkeypatch.setenv('HERMES_HOME', str(tmp_path))
    (tmp_path / 'config.yaml').write_text('durable_write_review:\n  enabled: true\n')
    real_lock = wa.durable_write_lock
    calls = []
    @contextmanager
    def lock():
        calls.append(1)
        if len(calls) == 2:
            raise OSError('lock unavailable')
        with real_lock():
            yield
    monkeypatch.setattr(wa, 'durable_write_lock', lock)
    monkeypatch.setattr(wa, '_start_review', lambda callback: False)
    with wa.review_evidence([{'role': 'user', 'content': 'I prefer HTTPS links.'}]):
        result = json.loads(memory_tool(action='add', target='user', content='Prefers HTTPS links.', store=MemoryStore()))
    assert result['review_state'] == 'ready'
    assert result['success'] is False
    assert result['saved'] is False


def test_image_tool_result_preserves_human_text_and_declares_omission():
    preference = 'Use HTTPS links in the hosted WebUI; local links are unusable.'
    messages = [
        {'role': 'user', 'content': preference},
        {'role': 'assistant', 'tool_calls': [{'id': 'vision', 'function': {
            'name': 'vision_analyze', 'arguments': '{"image_url":"screenshot.png"}'}}]},
        {'role': 'tool', 'tool_call_id': 'vision', 'content': [
            {'type': 'text', 'text': 'Image loaded into your context.'},
            {'type': 'image_url', 'image_url': {'url': 'data:image/png;base64,AA=='}}]},
    ]
    with wa.review_evidence(messages):
        source = wa._evidence.get()
        assert [s['text'] for s in source if s['role'] == 'user'] == [preference]
        assert source[0]['omitted_tool_results'] == 1
        assert all(s['role'] != 'tool' for s in source)
