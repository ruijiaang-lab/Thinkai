"""清单与技能结构校验：plugin.json / marketplace.json / .mcp.json / 三个 SKILL.md。

守住：版本号四处一致、skill 目录真实存在、frontmatter name 与目录名一致、
marketplace 正确列本插件、MCP 配置指向 mcp/server.py。
"""
import json

from conftest import ROOT

EXPECTED_VERSION = "2.0.0"
SKILL_DIRS = ["supply-chain-settlement", "scs-reconcile", "scs-ledger"]


def _read_json(relpath):
    return json.loads((ROOT / relpath).read_text(encoding="utf-8"))


def _frontmatter_name(skill_relpath):
    text = (ROOT / skill_relpath).read_text(encoding="utf-8")
    assert text.startswith("---"), f"{skill_relpath} 缺少 frontmatter"
    fm = text.split("---", 2)[1]
    for line in fm.splitlines():
        if line.startswith("name:"):
            return line.split(":", 1)[1].strip()
    return None


def test_codex_plugin_manifest():
    p = _read_json(".codex-plugin/plugin.json")
    assert p["name"] == "supply-chain-settlement"
    assert p["version"] == EXPECTED_VERSION
    assert len(p["skills"]) == 3
    for s in p["skills"]:
        assert (ROOT / s / "SKILL.md").is_file(), f"缺少 {s}/SKILL.md"
    assert p["mcpServers"]["scs"]["args"] == ["mcp/server.py"]


def test_claude_plugin_manifest():
    p = _read_json(".claude-plugin/plugin.json")
    assert p["name"] == "supply-chain-settlement"
    assert p["version"] == EXPECTED_VERSION


def test_marketplaces_list_plugin():
    for mf in (".claude-plugin/marketplace.json", ".codex-plugin/marketplace.json"):
        m = _read_json(mf)
        assert m["name"] == "thinkai-ops"
        plugin = m["plugins"][0]
        assert plugin["name"] == "supply-chain-settlement"
        assert plugin["source"] == "./"
        assert plugin["version"] == EXPECTED_VERSION


def test_mcp_config():
    m = _read_json(".mcp.json")
    srv = m["mcpServers"]["scs"]
    assert srv["command"] == "python3"
    assert srv["args"][0].endswith("mcp/server.py")
    assert (ROOT / "mcp" / "server.py").is_file()


def test_skill_frontmatter_names_match_dirs():
    for d in SKILL_DIRS:
        assert _frontmatter_name(f"skills/{d}/SKILL.md") == d, d


def test_master_skill_dispatches_to_subs():
    """总控 SKILL.md 必须显式引用两个子技能的路径。"""
    text = (ROOT / "skills/supply-chain-settlement/SKILL.md").read_text(encoding="utf-8")
    assert "../scs-reconcile/SKILL.md" in text
    assert "../scs-ledger/SKILL.md" in text


def test_versions_in_sync():
    assert f'version = "{EXPECTED_VERSION}"' in (ROOT / "pyproject.toml").read_text()
    init_text = (ROOT / "src/scs/__init__.py").read_text()
    assert f'__version__ = "{EXPECTED_VERSION}"' in init_text
    for mf in (".codex-plugin/plugin.json", ".claude-plugin/plugin.json",
               ".claude-plugin/marketplace.json", ".codex-plugin/marketplace.json"):
        data = _read_json(mf)
        version = data.get("version") or data["plugins"][0]["version"]
        assert version == EXPECTED_VERSION, mf
