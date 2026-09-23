import io
import json
from unittest.mock import Mock
from urllib.error import URLError

import pytest

from backend import run


@pytest.mark.parametrize("ours,code", [(True, 0), (False, 1)])
def test_occupied_port(monkeypatch, capsys, ours, code):
    listener = Mock()
    listener.bind.side_effect = OSError("occupied")
    context = Mock()
    context.__enter__ = Mock(return_value=listener)
    context.__exit__ = Mock(return_value=False)
    monkeypatch.setattr(run.socket, "socket", Mock(return_value=context))
    monkeypatch.setattr(run, "is_our_server", lambda port: ours)
    assert run.serve(8000) == code
    assert ("already running" if ours else "Another service") in capsys.readouterr().out
    listener.listen.assert_not_called()


@pytest.mark.parametrize("title,expected", [("HACKALEM procurement", True), ("Another API", False)])
def test_server_identity(monkeypatch, title, expected):
    opener = Mock()
    opener.open.side_effect = [
        io.BytesIO(json.dumps({"status": "ok"}).encode()),
        io.BytesIO(json.dumps({"info": {"title": title}}).encode()),
    ]
    monkeypatch.setattr(run, "build_opener", lambda *args: opener)
    assert run.is_our_server(8000) is expected


def test_unresponsive_port(monkeypatch):
    opener = Mock()
    opener.open.side_effect = URLError("timeout")
    monkeypatch.setattr(run, "build_opener", lambda *args: opener)
    assert not run.is_our_server(8000)
