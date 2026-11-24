import json

from sidereal.cli import main


def test_init_twice_then_openapi(settings, capsys):
    assert main(["init"]) == 0
    assert "sources added: 21" in capsys.readouterr().out
    assert main(["init"]) == 0
    assert "sources added: 0" in capsys.readouterr().out
    assert main(["openapi"]) == 0
    assert "/api/health" in json.loads(capsys.readouterr().out)["paths"]


def test_planned_command_exits_2(settings, capsys):
    assert main(["run", "--no-gate"]) == 2
    assert "not implemented yet (M13)" in capsys.readouterr().err


def test_config_error_exits_2(config_file, capsys):
    config_file.write_text("[web]\nport = 'x'\n")
    assert main(["init"]) == 2
    assert "error:" in capsys.readouterr().err


def test_serve_refuses_nonloopback(settings, capsys):
    assert main(["serve", "--host", "0.0.0.0"]) == 2
    assert "refusing to bind" in capsys.readouterr().err
