#! /usr/bin/env python
"""Driver functions for the Nimbie disc robot."""

import os
from . import config
from . import shared


def _run(args, log_file, error_file):
    cmd_str = " ".join(args)
    status, out, err = shared.launchSubProcess(args)

    try:
        with open(log_file, "r", encoding="utf-8", errors="replace") as fh:
            log_raw = fh.read()
    except OSError:
        log_raw = ""

    try:
        with open(error_file, "r", encoding="utf-8", errors="replace") as fh:
            err_raw = fh.read()
    except OSError:
        err_raw = ""

    try:
        log_utf8 = log_raw.encode("utf-8").decode("utf-16-le")
    except (UnicodeDecodeError, UnicodeEncodeError):
        log_utf8 = log_raw

    try:
        errors_utf8 = err_raw.encode("utf-8").decode("utf-16-le")
    except (UnicodeDecodeError, UnicodeEncodeError):
        errors_utf8 = err_raw

    for path in (log_file, error_file):
        try:
            os.remove(path)
        except OSError:
            pass

    return {"cmdStr": cmd_str, "status": status,
            "stdout": out, "stderr": err,
            "log": log_utf8, "errors": errors_utf8}


def prebatch():
    log_file   = os.path.join(config.tempDir, shared.randomString(12) + ".log")
    error_file = os.path.join(config.tempDir, shared.randomString(12) + ".err")
    args = [config.prebatchExe,
            "--drive=" + config.cdDriveLetter,
            "--logfile=" + log_file,
            "--passerrorsback=" + error_file]
    return _run(args, log_file, error_file)


def load():
    log_file   = os.path.join(config.tempDir, shared.randomString(12) + ".log")
    error_file = os.path.join(config.tempDir, shared.randomString(12) + ".err")
    args = [config.loadExe,
            "--drive=" + config.cdDriveLetter,
            "--rejectifnodisc",
            "--logfile=" + log_file,
            "--passerrorsback=" + error_file]
    return _run(args, log_file, error_file)


def unload():
    log_file   = os.path.join(config.tempDir, shared.randomString(12) + ".log")
    error_file = os.path.join(config.tempDir, shared.randomString(12) + ".err")
    args = [config.unloadExe,
            "--drive=" + config.cdDriveLetter,
            "--logfile=" + log_file,
            "--passerrorsback=" + error_file]
    return _run(args, log_file, error_file)


def reject():
    """Reject mirrors unload per SLWA readme."""
    return unload()
