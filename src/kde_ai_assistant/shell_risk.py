"""Decides whether a shell command is a ``danger`` action before it runs.

The assistant may run arbitrary shell commands, and the user's rule
(docs/ROADMAP.md, Permission Gate) is that a command needs approval only when
it deletes something or makes an OS-level change that could crash the system
or stop it booting. This module is the single place that rule is turned into
patterns, so it can be tested and tightened in one spot.

``classify_command`` returns ``(risk, reason)`` where risk is ``"danger"`` or
``"change"``; ``reason`` names what was found and is shown to the user on the
approval card.

How it looks at a command:

- The line is split into simple commands at ``;``, ``&&``, ``||``, ``|``,
  ``&`` and newlines, honouring quotes. Leading variable assignments and
  wrappers (``env``, ``nice``, ``nohup``, ``time``, ``timeout``, ...) are
  skipped to find the real program.
- Each program is checked against the lists below; some need a matching
  argument (``git clean``, ``pacman -R``, ``find -delete``). Installing or
  upgrading system software (``pacman -S``, ``yay -S``, ``apt install``,
  system-wide ``flatpak install``) is an OS-level change and counts too;
  searching and querying (``pacman -Ss``, ``-Q``) do not.
- Commands passed as strings (``sh -c``, ``bash -c``, ``xargs``, ``eval``,
  command substitution) are classified recursively.
- Inline interpreter code (``python -c``, ``perl -e``, ``node -e``) cannot be
  parsed, so it is searched for words that delete or run other programs.
- A ``>`` redirection onto a file that already exists overwrites it and
  counts as deletion; ``>>`` appends and does not.
- Running a script straight from the internet (``curl … | bash``,
  ``bash <(wget …)``, ``sh -c "$(curl …)"``) counts as an OS-level change:
  it runs code nobody has looked at, often with ``sudo`` inside. The reason
  names the site it comes from so the approval card says whose code it is.

This is best-effort pattern matching, not a sandbox. A deliberately
obfuscated command (encoded payloads, variables holding program names) can
evade it. It errs toward ``danger`` when a command cannot be tokenised.
"""

from __future__ import annotations

import os
import re
import shlex

DANGER = "danger"
CHANGE = "change"

# Programs whose purpose is to remove data, or that make OS-level changes.
DELETING_PROGRAMS = {
    "rm": "deletes files", "rmdir": "deletes folders", "unlink": "deletes a file", "shred": "destroys file contents",
    "truncate": "empties or cuts a file", "wipe": "destroys file contents", "trash": "moves files to the trash",
    "trash-put": "moves files to the trash", "gio": None, "kioclient": None, "kioclient6": None, "srm": "deletes files",
}
SYSTEM_PROGRAMS = {
    "dd": "writes raw data to a device or file", "wipefs": "erases filesystem signatures",
    "fdisk": "edits partitions", "sfdisk": "edits partitions", "cfdisk": "edits partitions", "parted": "edits partitions",
    "sgdisk": "edits partitions", "gdisk": "edits partitions", "blkdiscard": "discards a block device",
    "mkswap": "formats swap", "swapoff": "changes swap", "cryptsetup": "changes disk encryption",
    "lvremove": "removes a logical volume", "vgremove": "removes a volume group", "pvremove": "removes a physical volume",
    "grub-install": "changes the bootloader", "grub-mkconfig": "changes the bootloader", "bootctl": "changes the bootloader",
    "efibootmgr": "changes boot entries", "mkinitcpio": "rebuilds the boot image", "dracut": "rebuilds the boot image",
    "update-grub": "changes the bootloader", "update-initramfs": "rebuilds the boot image",
    "shutdown": "shuts the computer down", "poweroff": "shuts the computer down", "reboot": "restarts the computer",
    "halt": "halts the computer", "init": "changes the system run state", "telinit": "changes the system run state",
    "modprobe": "loads or removes a kernel module", "rmmod": "removes a kernel module", "insmod": "loads a kernel module",
    "sysctl": None, "chroot": "enters another system root", "mount": None, "umount": "unmounts a filesystem",
    "userdel": "deletes a user", "groupdel": "deletes a group", "passwd": "changes a password", "visudo": "edits sudo rules",
}
PRIVILEGE_PROGRAMS = {"sudo", "pkexec", "doas", "su", "run0", "kdesu", "kdesudo"}
WRAPPERS = {"env", "nice", "ionice", "nohup", "time", "command", "exec", "stdbuf", "setsid", "chrt", "builtin"}
WRAPPERS_WITH_ARGUMENT = {"timeout": 1, "flock": 1, "watch": 0}
SHELLS = {"sh", "bash", "zsh", "dash", "fish", "ksh"}
INTERPRETER_FLAGS = {"python": "-c", "python3": "-c", "perl": "-e", "ruby": "-e", "node": "-e", "php": "-r", "lua": "-e"}
PACKAGE_REMOVERS = {
    "pacman": ("-R", "-Rs", "-Rns", "-Rn", "-Rsc", "-Rdd", "--remove"), "yay": ("-R", "-Rs", "-Rns", "--remove"),
    "paru": ("-R", "-Rs", "-Rns", "--remove"), "apt": ("remove", "purge", "autoremove"),
    "apt-get": ("remove", "purge", "autoremove"), "dnf": ("remove", "erase", "autoremove"), "zypper": ("remove", "rm"),
    "flatpak": ("uninstall", "remove"), "snap": ("remove",), "pip": ("uninstall",), "pip3": ("uninstall",),
    "npm": ("uninstall", "rm", "remove"), "cargo": ("uninstall",), "pipx": ("uninstall",),
}
SYSTEM_PATHS = ("/boot", "/etc", "/usr", "/lib", "/lib64", "/bin", "/sbin", "/efi", "/sys", "/proc", "/dev", "/var/lib/pacman")
_INLINE_DANGER = re.compile(
    r"\b(rm|unlink|remove|rmtree|rmdir|shutil|truncate|os\.system|subprocess|exec|system|spawn|popen|"
    r"unlinkSync|rmSync|writeFile|open\s*\([^)]*['\"]w)\b")
_SHELLS_PATTERN = r"(?:sudo\s+(?:-\S+\s+)*)?(?:bash|sh|zsh|dash|ksh|fish|python3?|perl|ruby)\b"
_PIPE_TO_SHELL = re.compile(r"\b(?:curl|wget)\b[^|;&\n]*\|\s*" + _SHELLS_PATTERN)
_SHELL_FROM_DOWNLOAD = re.compile(
    r"\b(?:bash|sh|zsh|dash|ksh|fish|source|\.)\s+(?:-\S+\s+)*[\"']?(?:<\(|\$\()\s*(?:curl|wget)\b")
_URL_HOST = re.compile(r"https?://([^/\s\"']+)")
_SEPARATORS = re.compile(r"(\|\||&&|;|\||&|\n)")
_SUBSTITUTION = re.compile(r"\$\(([^()]*)\)|`([^`]*)`")


def _split_commands(line: str) -> list[str]:
    """Split on shell separators that are outside quotes."""
    parts: list[str] = []
    current: list[str] = []
    quote = ""
    index = 0
    while index < len(line):
        char = line[index]
        if quote:
            current.append(char)
            if char == "\\" and quote == '"' and index + 1 < len(line):
                index += 1
                current.append(line[index])
            elif char == quote:
                quote = ""
        elif char in "'\"":
            quote = char
            current.append(char)
        elif char == "\\" and index + 1 < len(line):
            current.append(line[index:index + 2])
            index += 1
        else:
            match = _SEPARATORS.match(line, index)
            if match and not (match.group(1) == "&" and current and current[-1] in "<>"):
                parts.append("".join(current))
                current = []
                index = match.end() - 1
            else:
                current.append(char)
        index += 1
    parts.append("".join(current))
    return [part.strip() for part in parts if part.strip()]


def _is_system_path(path: str) -> bool:
    expanded = os.path.abspath(os.path.expanduser(path))
    return any(expanded == root or expanded.startswith(root + "/") for root in SYSTEM_PATHS)


def _check_redirections(tokens: list[str], cwd: str) -> str:
    for index, token in enumerate(tokens):
        match = re.match(r"^(\d*|&)>(?!>)(\|?)(.*)$", token)
        if not match or token.startswith(">>") or re.match(r"^\d*>>", token):
            continue
        target = match.group(3) or (tokens[index + 1] if index + 1 < len(tokens) else "")
        if not target or target.startswith("&") or target == "/dev/null":
            continue
        path = os.path.expanduser(target)
        path = path if os.path.isabs(path) else os.path.join(cwd, path)
        if _is_system_path(path):
            return f"writes to the system path {target}"
        if os.path.isfile(path) and os.path.getsize(path) > 0:
            return f"overwrites the existing file {target}"
    return ""


def _classify_simple(command: str, cwd: str, depth: int) -> str:
    """Return a reason if this single command is dangerous, else ''."""
    try:
        tokens = shlex.split(command, posix=True)
    except ValueError:
        return "could not be read reliably (unbalanced quotes)"
    reason = _check_redirections(tokens, cwd)
    if reason:
        return reason
    while tokens:
        head = tokens[0]
        if re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", head):
            tokens = tokens[1:]
        elif os.path.basename(head) in WRAPPERS:
            tokens = tokens[1:]
            # Skip the wrapper's own options, their numeric values (nice -n 5)
            # and variable assignments (env A=1) to reach the real program.
            while tokens and (
                    tokens[0].startswith("-") or tokens[0].isdigit()
                    or re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", tokens[0])):
                tokens = tokens[1:]
        elif os.path.basename(head) in WRAPPERS_WITH_ARGUMENT:
            tokens = tokens[1:]
            while tokens and tokens[0].startswith("-"):
                tokens = tokens[1:]
            tokens = tokens[WRAPPERS_WITH_ARGUMENT[os.path.basename(head)]:]
        else:
            break
    if not tokens:
        return ""
    program = os.path.basename(tokens[0])
    arguments = tokens[1:]

    if program in PRIVILEGE_PROGRAMS:
        return f"runs with administrator rights ({program})"
    if program in SHELLS or program in ("eval", "xargs", "parallel"):
        if "-c" in arguments and arguments.index("-c") + 1 < len(arguments):
            inner = arguments[arguments.index("-c") + 1]
        elif program in ("eval", "xargs", "parallel"):
            inner = " ".join(argument for argument in arguments if not argument.startswith("-"))
        else:
            inner = ""
        if inner and depth < 4:
            return _classify_line(inner, cwd, depth + 1)
        return ""
    for interpreter, flag in INTERPRETER_FLAGS.items():
        if program.startswith(interpreter) and flag in arguments and arguments.index(flag) + 1 < len(arguments):
            if _INLINE_DANGER.search(arguments[arguments.index(flag) + 1]):
                return f"runs {program} code that may delete files or start other programs"
            return ""
    if program in DELETING_PROGRAMS:
        if program == "gio":
            return "moves files to the trash or removes them" if arguments[:1] and arguments[0] in ("trash", "remove") else ""
        if program.startswith("kioclient"):
            verbs = [argument for argument in arguments if not argument.startswith("-")][:1]
            if verbs and verbs[0] in ("remove", "rm"):
                return "removes files"
            return "moves files to the trash" if any("trash:" in argument for argument in arguments) else ""
        return DELETING_PROGRAMS[program] or "removes data"
    if program.startswith("mkfs"):
        return "formats a filesystem"
    if program in SYSTEM_PROGRAMS:
        if program == "sysctl":
            return "changes a kernel setting" if any("=" in a or a in ("-w", "--write") for a in arguments) else ""
        if program == "mount":
            return "mounts a filesystem" if [a for a in arguments if not a.startswith("-")] else ""
        return SYSTEM_PROGRAMS[program] or "changes the system"
    if program == "systemctl":
        verbs = [argument for argument in arguments if not argument.startswith("-")][:1]
        if "--user" in arguments:
            return ""
        if verbs and verbs[0] in ("poweroff", "reboot", "halt", "kexec", "suspend", "hibernate", "emergency", "rescue",
                                  "isolate", "mask", "disable", "stop", "kill", "set-default", "daemon-reexec"):
            return f"changes system services or power state (systemctl {verbs[0]})"
        return ""
    if program == "loginctl":
        verb = arguments[:1]
        return "ends a login session" if verb and verb[0] in ("terminate-session", "terminate-user", "kill-session", "kill-user") else ""
    if program in PACKAGE_REMOVERS:
        for argument in arguments:
            if argument in PACKAGE_REMOVERS[program] or (
                    program in ("pacman", "yay", "paru") and re.match(r"^-[A-Za-z]*R", argument)):
                return f"removes installed software ({program} {argument})"
        installing = _installs_software(program, arguments)
        if installing:
            return installing
        return ""
    if program == "find":
        if "-delete" in arguments:
            return "deletes the files it finds"
        for flag in ("-exec", "-execdir", "-ok", "-okdir"):
            if flag in arguments:
                inner = " ".join(arguments[arguments.index(flag) + 1:]).split(" ;")[0].replace("{}", "x").rstrip("+ ")
                return _classify_line(inner, cwd, depth + 1) if depth < 4 else ""
        return ""
    if program == "git":
        words = [argument for argument in arguments if not argument.startswith("-")]
        verb = words[:1]
        if verb == ["clean"]:
            return "deletes untracked files (git clean)"
        if verb == ["reset"] and "--hard" in arguments:
            return "discards uncommitted changes (git reset --hard)"
        if verb in (["checkout"], ["restore"]) and ("--" in arguments or "." in words[1:] or verb == ["restore"]):
            return "discards uncommitted changes" if "--staged" not in arguments else ""
        if verb == ["push"] and any(a in ("--force", "-f", "--force-with-lease", "--delete", "-d") for a in arguments):
            return "rewrites or deletes remote history"
        if verb == ["branch"] and any(a in ("-D", "-d", "--delete") for a in arguments):
            return "deletes a branch"
        if verb == ["stash"] and words[1:2] in (["drop"], ["clear"]):
            return "deletes stashed changes"
        return ""
    if program in ("docker", "podman"):
        words = [argument for argument in arguments if not argument.startswith("-")]
        if words[:1] in (["rm"], ["rmi"]) or words[1:2] in (["rm"], ["prune"], ["remove"]) or words[:2] == ["system", "prune"]:
            return "removes containers, images or volumes"
        return ""
    if program in ("mv", "cp", "install", "rsync", "ln"):
        targets = [argument for argument in arguments if not argument.startswith("-")]
        if program == "rsync" and any(argument.startswith("--delete") or argument == "--remove-source-files" for argument in arguments):
            return "deletes files while synchronising"
        if targets:
            destination = os.path.expanduser(targets[-1])
            destination = destination if os.path.isabs(destination) else os.path.join(cwd, destination)
            if _is_system_path(destination):
                return f"writes to the system path {targets[-1]}"
            if len(targets) == 2 and os.path.isfile(destination) and not any(a in ("-n", "--no-clobber", "-i", "-b") for a in arguments):
                return f"overwrites the existing file {targets[-1]}"
        return ""
    if program in ("tee", "sed", "chmod", "chown", "touch", "mkdir", "kwriteconfig6"):
        if program == "sed" and not any(a == "-i" or a.startswith("-i") or a == "--in-place" for a in arguments):
            return ""
        for argument in arguments:
            if not argument.startswith("-") and argument.startswith(("/", "~")) and _is_system_path(argument):
                return f"changes the system path {argument}"
        return ""
    if program == "kill" and "1" in arguments:
        return "signals the init process"
    return ""


def _runs_downloaded_script(line: str) -> str:
    if _PIPE_TO_SHELL.search(line) or _SHELL_FROM_DOWNLOAD.search(line):
        host = _URL_HOST.search(line)
        return f"runs a script downloaded from {host.group(1) if host else 'the internet'} without reviewing it"
    return ""


def _classify_line(line: str, cwd: str, depth: int) -> str:
    reason = _runs_downloaded_script(line)
    if reason:
        return reason
    for match in _SUBSTITUTION.finditer(line):
        inner = match.group(1) or match.group(2) or ""
        if inner.strip() and depth < 4:
            reason = _classify_line(inner, cwd, depth + 1)
            if reason:
                return reason
    for command in _split_commands(line):
        reason = _classify_simple(command.strip("(){} \t"), cwd, depth)
        if reason:
            return reason
    return ""


def _installs_software(program: str, arguments: list[str]) -> str:
    """A reason when a package-manager call installs or upgrades system software, else ''."""
    if program in ("pacman", "yay", "paru"):
        for argument in arguments:
            # -S with anything but search/info/print/list, or -U; never -Q or -F.
            if re.match(r"^-[A-Za-z]*U", argument) or (
                    re.match(r"^-[A-Za-z]*S", argument) and not re.search(r"[sicpgl]", argument.lstrip("-")[1:])):
                return f"installs or upgrades system software ({program} {argument})"
        if program in ("yay", "paru") and not arguments:
            return f"upgrades all system software ({program})"
        return ""
    verbs = {"apt": ("install", "upgrade", "full-upgrade", "dist-upgrade", "reinstall"),
             "apt-get": ("install", "upgrade", "dist-upgrade", "reinstall"),
             "dnf": ("install", "upgrade", "update", "reinstall", "distro-sync"),
             "zypper": ("install", "in", "update", "up", "dist-upgrade", "dup"),
             "snap": ("install", "refresh"), "flatpak": ("install", "update", "upgrade")}
    words = [argument for argument in arguments if not argument.startswith("-")]
    if program in verbs and words[:1] and words[0] in verbs[program]:
        if program == "flatpak" and "--user" in arguments:
            return ""
        return f"installs or upgrades system software ({program} {words[0]})"
    return ""


# Programs that would stop to ask for a password on a terminal. Without one
# they fail or hang, so such commands must run where the user can answer.
_PASSWORD_PROGRAMS = {"sudo", "su", "doas", "run0", "passwd", "kdesu", "kdesudo"}


def needs_password(command: str) -> str:
    """A reason when the command would ask for a password on a terminal, else ''."""
    for part in _split_commands(command):
        try:
            tokens = shlex.split(part.strip("(){} \t"), posix=True)
        except ValueError:
            continue
        while tokens and re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", tokens[0]):
            tokens = tokens[1:]
        if not tokens:
            continue
        program, arguments = os.path.basename(tokens[0]), tokens[1:]
        if program in _PASSWORD_PROGRAMS:
            return f"{program} asks for your password"
        if program in ("yay", "paru") and _installs_software(program, arguments):
            return f"{program} asks for your password to install"
        if program in ("pacman", "apt", "apt-get", "dnf", "zypper") and (
                _installs_software(program, arguments) or any(a.startswith("-R") or a in ("remove", "purge") for a in arguments)):
            return f"{program} must run as root"
    return ""


def classify_command(command: str, cwd: str | None = None) -> tuple[str, str]:
    """Classify a shell command line. Returns ``("danger", reason)`` or ``("change", "")``."""
    reason = _classify_line(command, cwd or os.path.expanduser("~"), 0)
    return (DANGER, reason) if reason else (CHANGE, "")
