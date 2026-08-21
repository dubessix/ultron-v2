"""
Ultron Command Risk Guard
Prevents destructive / system-damaging terminal commands from running.
Safe everyday commands (ls, cd, pwd, git status, npm build, pytest, python ...)
are allowed; commands that could wipe the system or destroy data are blocked.
"""
import re

# Blocks destructive or clearly-dangerous command patterns (loop risk 💪).
_DANGEROUS = [
    r"\brm\s+(-[a-z]*r[a-z]*f[a-z]*|-f[a-z]*r[a-z]*)\s+(/|~|\$HOME|/\*|~/)",  # rm -rf /, ~, /*, etc.
    r"\brm\s+(-[a-z]*r[a-z]*f[a-z]*|-f[a-z]*r[a-z]*)\s+[\w.]*/\.\.",        # rm -rf .. traversal
    r"\bmkfs\b",                                     # format disk
    r"\bdd\s+if=.*\s+of=/dev/",                      # dd to raw device
    r":\s*\(\s*\)\s*\{",                                # fork bomb :(){ ...
    r"\bshutdown\b|\breboot\b|\binit\s+0\b",         # power off
    r"\bkill\s+-9\s+1\b",                            # kill PID 1
    r"\b>\\s*/dev/sd",                               # write to raw disk
    r"\bchmod\s+(-R\s+)?777\s+/\b",                  # chmod root world-writable
    r"\bcurl[^|]*\|\s*(ba)?sh\b",                    # curl | sh (arbitrary code)
    r"\bwget[^|]*\|\s*(ba)?sh\b",
    r"\bgit\s+push\s+.*\s+--force\b",                # force push (destructive)
    r"\bgit\s+reset\s+--hard\b",
    r"\bdropdb\b|\bdrop\s+database\b",
    r"\bpython\s+-c\s+['\"]import\s+os;\s*os\.remove",
]


def is_command_safe(command: str) -> bool:
    """Return True if the command is safe to run."""
    if not command or not command.strip():
        return False
    for pat in _DANGEROUS:
        if re.search(pat, command, re.IGNORECASE):
            return False
    return True
