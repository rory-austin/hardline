import pytest


@pytest.fixture(autouse=True)
def isolated_runtime_settings(monkeypatch):
    """Tests must never read the operator's private settings."""
    from hardline import runtime

    monkeypatch.setattr(
        runtime, "settings", lambda: {"rooms": [], "management_agents": []}
    )
