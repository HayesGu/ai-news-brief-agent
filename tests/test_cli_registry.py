import pytest

from ai_research_agent.__main__ import main


def test_bootstrap_reset_requires_confirm(capsys) -> None:
    with pytest.raises(SystemExit) as exc_info:
        main(["registry", "bootstrap-reset"])

    captured = capsys.readouterr()

    assert exc_info.value.code == 1
    assert "bootstrap-reset requires --confirm" in captured.err
