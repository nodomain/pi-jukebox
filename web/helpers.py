"""Shell helper utilities for Jukebox Pi."""

import subprocess  # pylint: disable=import-error


def run(cmd, timeout=5):
    """Run a shell command and return stdout.

    Args:
        cmd: Shell command string to execute.
        timeout: Maximum seconds to wait for the command.

    Returns:
        Stripped stdout string, or empty string on timeout.
    """
    try:
        result = subprocess.run(
            cmd, shell=True, capture_output=True, text=True,
            timeout=timeout, check=False,
        )
        return result.stdout.strip()
    except subprocess.TimeoutExpired:
        return ""


def run_pw(cmd):
    """Run a PipeWire command with the correct XDG_RUNTIME_DIR.

    Args:
        cmd: Command string (without the env prefix).

    Returns:
        Stripped stdout string.
    """
    return run(f"XDG_RUNTIME_DIR=/run/user/1000 {cmd}")
