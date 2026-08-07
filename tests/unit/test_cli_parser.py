from __future__ import annotations

import pytest

from opportunity_engine.cli.main import COMMANDS, build_parser


@pytest.mark.parametrize(
    "argv",
    [
        ["migrate"],
        ["ingest"],
        ["ingest", "--days", "3"],
        ["dedup"],
        ["score"],
        ["rank"],
        ["track-topic", "en.wikipedia", "SSL_certificate"],
        ["track-topic", "en.wikipedia", "SSL_certificate", "--opportunity-id", "42"],
        ["sync-connectors"],
        ["deep-dive", "42"],
        ["deep-dive", "42", "--escalate", "--reason", "Haiku missed the regulatory angle"],
        ["import-archive", "/tmp/dump.jsonl"],
        ["import-archive", "/tmp/dump.zst", "--subreddits", "SaaS,Entrepreneur"],
        ["run-daily"],
    ],
)
def test_parser_accepts_every_documented_command(argv: list[str]) -> None:
    args = build_parser().parse_args(argv)
    assert args.command in COMMANDS


def test_ingest_defaults_to_one_day() -> None:
    args = build_parser().parse_args(["ingest"])
    assert args.days == 1


def test_missing_command_is_a_parse_error() -> None:
    with pytest.raises(SystemExit):
        build_parser().parse_args([])


def test_every_documented_command_has_a_handler() -> None:
    assert set(COMMANDS.keys()) == {
        "migrate",
        "ingest",
        "dedup",
        "score",
        "rank",
        "track-topic",
        "sync-connectors",
        "deep-dive",
        "import-archive",
        "run-daily",
    }
