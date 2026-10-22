"""Tests for memanga.completion shell scripts (#248).

The bash tests source the generated script and call the completion
function with a synthetic COMP_WORDS, so they check what a user sees on
TAB, not just the script text. Only bash is supported. Source-name
suggestions for `search --source` are from #260.
"""

import argparse
import shutil
import subprocess
import sys

import pytest

from memanga import cli, completion
from memanga.scrapers import list_supported_sources
from memanga.scrapers.registry import TEMPLATE_SCRAPERS
from memanga.search import BROKEN_SEARCH_SOURCES, compute_search_sources

needs_bash = pytest.mark.skipif(
    sys.platform == "win32" or shutil.which("bash") is None,
    reason="needs bash",
)


@pytest.fixture
def parser(monkeypatch):
    monkeypatch.delenv("MEMANGA_CLI_ONLY", raising=False)
    return cli.build_parser()


def _complete(script, *words):
    """Return bash's COMPREPLY for the command line ``memanga *words``.

    The last word is the one being completed ("" for a fresh word).
    """
    line = ["memanga", *words]
    quoted = " ".join("'" + w.replace("'", "'\\''") + "'" for w in line)
    program = (
        f"{script}\n"
        f"COMP_WORDS=({quoted})\n"
        f"COMP_CWORD={len(line) - 1}\n"
        "_memanga\n"
        'printf "%s\\n" "${COMPREPLY[@]}"\n'
    )
    result = subprocess.run(["bash", "--norc", "--noprofile", "-c", program],
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    assert result.stderr == ""
    return [w for w in result.stdout.splitlines() if w]


class TestScript:
    def test_only_bash_is_offered(self):
        assert completion.SHELLS == ("bash",)

    def test_bash_script(self, parser):
        out = completion.script("bash", parser)
        assert out.endswith("\n")
        assert "complete -o default -F _memanga memanga" in out

    @pytest.mark.parametrize("shell", ["zsh", "fish", "powershell"])
    def test_unsupported_shell_raises(self, parser, shell):
        with pytest.raises(ValueError):
            completion.script(shell, parser)

    def test_hidden_options_are_left_out(self, monkeypatch):
        monkeypatch.setenv("MEMANGA_CLI_ONLY", "1")
        assert "gui" not in completion.script("bash", cli.build_parser())


class _NoConfig:
    """A config with no library and nothing disabled."""

    def get(self, key, default=None):
        return default


def _suggesting_parser(words):
    parser = argparse.ArgumentParser(prog="memanga")
    completion.suggest(parser.add_argument("--source"), words)
    return parser


# Odd words a suggestion list could hold; none may reach the script.
UNSAFE_WORDS = ["two words", "$(touch pwned)", "`id`", "a;b", "it's",
                'say"hi', "x|y", "*", "~", "", "tab\tword", "new\nline"]


class TestSuggest:
    def test_suggested_words_do_not_restrict_the_value(self):
        parser = _suggesting_parser(lambda: ["a.org", "b.net"])
        assert parser.parse_args(["--source", "WWW.Other.ORG"]).source == "WWW.Other.ORG"
        assert '"a.org b.net"' in completion.script("bash", parser)

    def test_words_are_only_read_when_generating(self):
        def words():
            raise AssertionError("read at parse time")

        parser = _suggesting_parser(words)
        assert parser.parse_args(["--source", "x"]).source == "x"
        with pytest.raises(AssertionError):
            completion.script("bash", parser)

    def test_unsafe_words_are_left_out(self):
        out = completion.script("bash", _suggesting_parser(
            lambda: ["ok.org", *UNSAFE_WORDS]))
        [line] = [ln for ln in out.splitlines() if "//--source)" in ln]
        assert 'compgen -W "ok.org" --' in line

    def test_search_source_accepts_any_value(self, parser):
        args = parser.parse_args(["search", "q", "--source", "WWW.Example.ORG"])
        assert args.source == "WWW.Example.ORG"

    def test_search_source_words_are_every_supported_source(self, parser):
        out = completion.script("bash", parser)
        assert " ".join(list_supported_sources()) in out


@needs_bash
class TestBashCompletion:
    @pytest.fixture
    def script(self, parser):
        return completion.script("bash", parser)

    def test_bash_syntax(self, script):
        result = subprocess.run(["bash", "-n"], input=script,
                                capture_output=True, text=True, timeout=30)
        assert result.returncode == 0, result.stderr

    def test_commands(self, script):
        reply = _complete(script, "")
        for name in ("list", "ls", "check", "completion", "failed", "doctor"):
            assert name in reply
        assert _complete(script, "ch") == ["check"]

    def test_global_options(self, script):
        reply = _complete(script, "--")
        assert {"--version", "--config-dir", "--help"} <= set(reply)

    def test_command_after_global_option_value(self, script):
        reply = _complete(script, "--config-dir", "/tmp/x", "check", "--dry")
        assert reply == ["--dry-run"]

    def test_alias_uses_command_options(self, script):
        assert "--json" in _complete(script, "ls", "--")

    def test_option_choices(self, script):
        assert _complete(script, "check", "--format", "c") == ["cbz"]
        assert set(_complete(script, "list", "--status", "")) == {
            "reading", "on-hold", "dropped", "completed"}

    def test_positional_choices(self, script):
        assert _complete(script, "completion", "") == ["bash"]
        assert _complete(script, "edit", "Some Title", "--status", "on") == ["on-hold"]

    def test_deprecated_set_is_not_offered(self, script):
        # Issue #348: `set` still runs but is no longer advertised.
        reply = _complete(script, "")
        assert {"edit", "update"} <= set(reply)
        assert "set" not in reply
        assert _complete(script, "se") == ["search", "send"]
        assert _complete(script, "update", "Some Title", "--st") == ["--status"]

    def test_read_unread(self, script):
        reply = _complete(script, "")
        assert {"read", "unread"} <= set(reply)
        assert _complete(script, "read", "Some Title", "--a") == ["--all"]
        assert _complete(script, "unread", "Some Title", "--a") == ["--all"]

    def test_nested_actions_and_their_options(self, script):
        assert "retry" in _complete(script, "failed", "")
        assert "--json" in _complete(script, "config", "show", "--")
        assert _complete(script, "failed", "retry", "--j") == []

    # `--opt=value`: bash splits it into `--opt`, `=`, `value` by default
    # (COMP_WORDBREAKS has "="); without "=" there it stays one word.
    def test_option_equals_value_split(self, script):
        assert _complete(script, "check", "--format", "=", "c") == ["cbz"]
        assert _complete(script, "list", "--sort", "=", "") == [
            "list", "title", "status", "last-chapter", "downloaded"]

    def test_option_equals_value_right_after_equals(self, script):
        assert "cbz" in _complete(script, "check", "--format", "=")

    def test_option_equals_value_one_word(self, script):
        assert _complete(script, "check", "--format=c") == ["--format=cbz"]

    @pytest.mark.parametrize("words", [
        ("--config-dir", "=", "/tmp", "check", "--dr"),
        ("--config-dir=/tmp", "check", "--dr"),
        ("--config-dir", "/tmp", "check", "--dr"),
    ])
    def test_global_option_value_before_command(self, script, words):
        assert _complete(script, *words) == ["--dry-run"]

    def test_global_option_equals_value_then_command_value(self, script):
        assert _complete(script, "--config-dir", "=", "/tmp", "check",
                         "--format", "=", "e") == ["epub"]

    def test_non_value_option_word_is_left_alone(self, script):
        assert _complete(script, "list", "--js") == ["--json"]
        assert _complete(script, "--config-dir=/tmp", "") != []

    def test_search_source_names(self, script):
        reply = _complete(script, "search", "Blue Lock", "--source", "")
        assert set(reply) == set(list_supported_sources())
        assert not any(w.startswith("www.") for w in reply)

    def test_search_source_default_and_non_default(self, script):
        # A default-sweep source, a registered one that is never swept,
        # and a single-manga template site are all valid --source values.
        swept = compute_search_sources(_NoConfig())
        assert "mangadex.org" in swept
        assert "mangasee123.com" in BROKEN_SEARCH_SOURCES
        template = sorted(TEMPLATE_SCRAPERS)[0].removeprefix("www.")
        assert template not in swept
        for source in ("mangadex.org", "mangasee123.com", template):
            assert source in _complete(script, "search", "q", "--source",
                                       source[:-1]), source

    def test_search_source_prefix(self, script):
        expected = {s for s in list_supported_sources() if s.startswith("mangadex")}
        assert "mangadex.org" in expected
        assert set(_complete(script, "search", "q", "--source", "mangadex")) == expected
        # Option before the query, too.
        assert set(_complete(script, "search", "--source", "mangadex")) == expected

    def test_search_source_equals_forms(self, script):
        expected = {s for s in list_supported_sources() if s.startswith("mangadex")}
        assert set(_complete(script, "search", "q", "--source", "=",
                             "mangadex")) == expected
        assert set(_complete(script, "search", "q", "--source=mangadex")) == {
            "--source=" + s for s in expected}

    def test_search_source_unknown_prefix_offers_nothing(self, script):
        assert _complete(script, "search", "q", "--source", "zz-no-such") == []

    def test_unsafe_suggestions_are_not_offered(self):
        script = completion.script("bash", _suggesting_parser(
            lambda: ["ok.org", *UNSAFE_WORDS]))
        assert _complete(script, "--source", "") == ["ok.org"]

    def test_tracked_titles_are_not_completed(self, script):
        # Titles are not completed (#260): TARGET falls back to bash's
        # default, never to option names or other words.
        assert _complete(script, "rm", "") == []

    def test_free_value_offers_no_words(self, script):
        # A title value falls back to bash's default (file names), never
        # to option names.
        assert not any(w.startswith("-") for w in
                       _complete(script, "add", "--title", ""))
