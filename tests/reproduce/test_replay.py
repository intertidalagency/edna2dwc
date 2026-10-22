from __future__ import annotations

from dataclasses import dataclass

import pytest



@dataclass
class _FakeCompletedProcess:
    returncode: int
    stdout: str = ""
    stderr: str = ""


        python="3.12.4",
        pyproj_version="3.6.1",
        proj_data_version="9.4.0",
        dependencies={"openpyxl": "3.1.2", "h5py": "3.11.0"},
    )


    return [
    ]




    captured = {}

    def fake_run(args, **kwargs):
        captured["args"] = args
        return _FakeCompletedProcess(returncode=0)



    def fake_run(args, **kwargs):



    captured = {}

    def fake_run(args, **kwargs):
        captured["args"] = args
        return _FakeCompletedProcess(returncode=0)

    assert captured["args"][0] == "sh"


    assert "--unpin" in message


    ]


    (tmp_path / "scripts").mkdir()


    bundle_dir = tmp_path / "bundle"
    bundle_dir.mkdir()




def test_default_archive_path_raises_without_a_recorded_out_dir(tmp_path):
