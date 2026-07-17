import pytest
from src.main import main


def test_main_without_args_prints_help(capsys):
    with pytest.raises(SystemExit) as exc_info:
        main([])
    assert exc_info.value.code == 1
    captured = capsys.readouterr()
    assert "usage" in captured.out
