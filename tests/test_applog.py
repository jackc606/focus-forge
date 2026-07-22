"""Tests for the event log + diagnostic report (core/applog.py)."""
from __future__ import annotations

from core import applog


def test_install_log_and_tail(tmp_path):
    applog.install(tmp_path, force=True)
    applog.logger().info("open %s", "some_project.focusforge.json")
    applog.logger().warning("something odd")
    text = applog.tail(10)
    assert "open some_project.focusforge.json" in text
    assert "WARNING something odd" in text


def test_tail_respects_line_limit(tmp_path):
    applog.install(tmp_path, force=True)
    for i in range(30):
        applog.logger().info("line %d", i)
    text = applog.tail(5)
    assert "line 29" in text and "line 24" not in text


def test_build_report_contains_info_and_log(tmp_path):
    applog.install(tmp_path, force=True)
    applog.logger().info("export 12 files -> somewhere")
    report = applog.build_report({"app": "v9.9.9", "project": "Test [EGY]"})
    assert "=== Focus Forge diagnostic report ===" in report
    assert "app: v9.9.9" in report
    assert "project: Test [EGY]" in report
    assert "export 12 files -> somewhere" in report
    assert "os:" in report and "python:" in report


def test_log_exception_lands_in_log(tmp_path):
    applog.install(tmp_path, force=True)
    try:
        raise ValueError("boom for the log")
    except ValueError:
        import sys
        applog.log_exception(*sys.exc_info())
    text = applog.tail(30)
    assert "UNHANDLED EXCEPTION" in text and "boom for the log" in text
