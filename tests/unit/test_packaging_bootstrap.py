"""Source packaging must not execute environment bootstrapping."""
import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_bootstrap_is_not_a_setuptools_setup_script():
    assert not (ROOT / "setup.py").exists()
    assert (ROOT / "bootstrap.py").is_file()


def test_bootstrap_import_has_no_top_level_setup_call():
    tree = ast.parse((ROOT / "bootstrap.py").read_text(encoding="utf-8"))
    guards = [node for node in tree.body if isinstance(node, ast.If)]
    assert len(guards) == 1
    assert ast.unparse(guards[0].test) == "__name__ == '__main__'"
    assert isinstance(guards[0].body[0], ast.Expr)
    assert ast.unparse(guards[0].body[0]) == "main()"


def test_documented_bootstrap_commands_use_the_explicit_filename():
    for relative in ("README.md", "docs/Guide.md", "scripts/windows/setup.bat",
                     "scripts/windows/run.bat"):
        text = (ROOT / relative).read_text(encoding="utf-8")
        assert "setup.py" not in text, relative
        assert "bootstrap.py" in text, relative
