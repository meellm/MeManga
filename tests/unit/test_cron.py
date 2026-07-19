"""Tests for memanga.cron shell-safe crontab line construction (#109)."""

import shlex

from memanga.cron import build_cron_line, quote_cron_path


class TestQuoteCronPath:
    def test_plain_path_unchanged(self):
        assert quote_cron_path("/opt/memanga") == "/opt/memanga"

    def test_path_with_spaces_is_quoted(self):
        assert quote_cron_path("/opt/My Manga") == "'/opt/My Manga'"

    def test_shell_metacharacters_neutralized(self):
        evil = "/tmp/$(touch pwned); echo"
        assert shlex.split(quote_cron_path(evil)) == [evil]

    def test_percent_escaped_for_cron(self):
        # crontab(5) turns an unescaped % into a newline.
        assert quote_cron_path("/opt/100%manga") == r"/opt/100\%manga"


class TestBuildCronLine:
    def test_plain_paths(self):
        line = build_cron_line(0, 6, "/opt/memanga", "/usr/bin/python3")
        assert line == (
            "0 6 * * * cd /opt/memanga && /usr/bin/python3 "
            "-m memanga check --auto --quiet >> /opt/memanga/memanga.log 2>&1"
        )

    def test_paths_with_spaces(self):
        line = build_cron_line(30, 7, "/opt/My Manga",
                               "/opt/My Manga/venv/bin/python3")
        assert line == (
            "30 7 * * * cd '/opt/My Manga' && "
            "'/opt/My Manga/venv/bin/python3' "
            "-m memanga check --auto --quiet "
            ">> '/opt/My Manga/memanga.log' 2>&1"
        )

    def test_metacharacter_paths_stay_single_words(self):
        evil = "/tmp/x; touch pwned"
        line = build_cron_line(0, 6, evil, "/usr/bin/python3")
        command = line.split("* * * ", 1)[1]
        # The shell must see the whole path as one word, not extra commands.
        assert evil in shlex.split(command)
