## Summary
What does this PR do?

## Sovereign checks
- [ ] No `/mnt` paths introduced
- [ ] `processing/{inbox,active,done,failed}/` layout respected
- [ ] Settings exposed in `settings.json` if user-configurable
- [ ] Tests added or updated (`tests/test_e2e.py`)
- [ ] `pytest tests/` passes locally

## Test plan
- [ ] `python -m compileall src/ada_splitter web`
- [ ] `pytest tests/ -v`
- [ ] `python boundless.py` — manual smoke (browser auto-opens)
