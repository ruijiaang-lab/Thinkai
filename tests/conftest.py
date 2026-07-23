import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "mcp"))


@pytest.fixture
def scs_bin():
    return ROOT / "bin" / "scs"


def run_scs(scs_bin, *args, workspace=None, expect_fail=False):
    """运行 bin/scs，返回 CompletedProcess；失败时抛出带输出的断言。"""
    cmd = [str(scs_bin)]
    if workspace:
        cmd += ["--workspace", str(workspace)]
    cmd += list(args)
    p = subprocess.run(cmd, capture_output=True, text=True)
    if not expect_fail and p.returncode != 0:
        raise AssertionError(
            f"scs 执行失败（rc={p.returncode}）\n命令: {' '.join(cmd)}\n"
            f"--- stdout ---\n{p.stdout}\n--- stderr ---\n{p.stderr}")
    if expect_fail and p.returncode == 0:
        raise AssertionError(
            f"预期失败但成功了\n命令: {' '.join(cmd)}\nstdout: {p.stdout}")
    return p
