"""Learning and skill routing should reward useful context, not write volume."""
from agent import prompt_builder, background_review


def test_skill_prompt_selects_governing_procedure(tmp_path, monkeypatch):
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    assert Path(prompt_builder.__file__).resolve() == root / 'agent' / 'prompt_builder.py'
    monkeypatch.setenv('HERMES_HOME', str(tmp_path / 'home'))
    skill = tmp_path / 'testing' / 'sample'
    skill.mkdir(parents=True)
    (skill / 'SKILL.md').write_text('---\nname: sample\ndescription: Use for sample tasks.\n---\n# Sample\n')
    monkeypatch.setattr(prompt_builder, 'get_disabled_skill_names', lambda *_: set())
    prompt_builder.clear_skills_system_prompt_cache(clear_snapshot=True)
    text = prompt_builder._build_skills_system_prompt_inner(tmp_path, [], None, None, None)
    assert 'governing skill' in text
    assert 'security' in text
    assert 'even partially relevant' not in text


def test_background_learning_accepts_no_write():
    for text in (background_review._SKILL_REVIEW_PROMPT, background_review._COMBINED_REVIEW_PROMPT):
        assert 'missed learning opportunity' not in text
        assert 'no-write' in text
        assert 'existing owner' in text
