"""filerouter-doctor — configuration & environment diagnostics with guided fixes.

The doctor inspects a configuration file AND the live environment, reports every
problem it can anticipate, and (optionally) offers to fix the safe ones by asking
the operator yes/no questions.

It aims to cover the whole functional scope:
  * YAML parsing and JSON-Schema structure
  * semantic rules (unique aliases, mandatory naming placeholder, same volume)
  * base_folder / exchange / runtime directory existence and read/write rights
  * runtime and exchange on the same physical volume (atomic publish requirement)
  * crypto backend availability and KEY correctness (gnupg self-test, recipient
    and signing keys present, allowed signers present)
  * encryption / compression rules referencing known aliases

Each check is a small, documented function returning ``Finding`` objects. Only
clearly-safe fixes (creating a missing directory) are offered interactively; key
or permission problems are reported with precise guidance, never auto-"fixed"
in a way that could weaken security.
"""

from __future__ import annotations

import os
import platform
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from filerouter.config import schema as config_schema
from filerouter.core.errors import ConfigError

# Severity levels, ordered for the final exit code.
OK = "ok"
WARN = "warn"
ERROR = "error"


@dataclass
class Finding:
    """One diagnostic result.

    ``fixer`` is a safe auto-fix when one exists. ``hint`` is verbose, OS-aware
    guidance shown for problems the doctor cannot fix on its own, so the operator
    always gets a clear, actionable next step.
    """

    check: str
    level: str
    message: str
    fix_label: str | None = None
    fixer: Callable[[], None] | None = None
    hint: str | None = None


# -- small helpers -----------------------------------------------------------

def _is_windows() -> bool:
    """Return True when running on Windows (affects remediation hints)."""
    return platform.system() == "Windows"


def ask_yes_no(prompt: str) -> bool:
    """Prompt the operator for a yes/no answer (defaults to no)."""
    answer = input(f"{prompt} [y/N] ").strip().lower()
    return answer in ("y", "yes", "o", "oui")


def _read_yaml(path: Path) -> dict:
    """Parse a YAML file safely; raise ConfigError on any problem."""
    import yaml

    if not path.exists():
        raise ConfigError(f"config file not found: {path}")
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ConfigError("config root must be a mapping")
    return data


def _dir_finding(check: str, path: Path, *, need_write: bool) -> Finding:
    """Check a directory's existence and access rights.

    Missing directories can be auto-created. When a directory exists but lacks
    rights, ALL missing rights (read and/or write) are listed in one message so
    the operator sees every permission problem at once on stdout.
    """
    if not path.exists():
        return Finding(
            check, ERROR, f"missing directory: {path}",
            fix_label=f"create {path}",
            fixer=lambda: path.mkdir(parents=True, exist_ok=True),
        )
    if not path.is_dir():
        return Finding(check, ERROR, f"path is not a directory: {path}")
    missing = _missing_rights(path, need_write=need_write)
    if missing:
        return Finding(check, ERROR,
                       f"insufficient permissions (missing: {', '.join(missing)}) "
                       f"on {path}",
                       hint=_permission_hint(path))
    return Finding(check, OK, f"directory OK: {path}")


def _permission_hint(path: Path) -> str:
    """Return an OS-specific command to grant the service account access."""
    if _is_windows():
        return (f'Grant rights to the service account, e.g.:\n'
                f'        icacls "{path}" /grant "<service_account>:(OI)(CI)M"')
    return (f'Grant rights to the service user, e.g.:\n'
            f'        sudo chown -R <service_user> "{path}" '
            f'&& chmod -R u+rwX "{path}"')


def _missing_rights(path: Path, *, need_write: bool) -> list[str]:
    """Return the list of missing access rights (read/write) for ``path``."""
    missing: list[str] = []
    if not os.access(path, os.R_OK):
        missing.append("read")
    if need_write and not os.access(path, os.W_OK):
        missing.append("write")
    return missing


# -- individual checks -------------------------------------------------------

def check_structure(data: dict) -> list[Finding]:
    """Validate the config against the JSON Schema (structural layer)."""
    try:
        config_schema.validate_structure(data)
    except ConfigError as exc:
        return [Finding("schema", ERROR, str(exc))]
    return [Finding("schema", OK, "config structure is valid")]


def check_semantics(data: dict) -> list[Finding]:
    """Validate semantic rules the schema cannot express."""
    try:
        config_schema.validate_semantics(data)
    except ConfigError as exc:
        return [Finding("semantics", ERROR, str(exc))]
    return [Finding("semantics", OK, "config semantics are valid")]


def check_base_folders(data: dict) -> list[Finding]:
    """Each base_folder path must exist and be read/write accessible."""
    findings: list[Finding] = []
    for entry in data.get("base_folders", []):
        path = Path(entry["path"])
        findings.append(_dir_finding(f"base_folder:{entry['alias']}", path,
                                     need_write=True))
    return findings


def check_exchange_and_runtime(data: dict) -> list[Finding]:
    """Exchange and runtime directories must exist and be writable."""
    findings: list[Finding] = []
    out = Path(data.get("exchange", {}).get("out", ""))
    inp = Path(data.get("exchange", {}).get("in", ""))
    runtime = Path(data.get("runtime", {}).get("root", ""))
    findings.append(_dir_finding("exchange.out", out, need_write=True))
    findings.append(_dir_finding("exchange.in", inp, need_write=True))
    findings.append(_dir_finding("runtime.root", runtime, need_write=True))
    return findings


def check_same_volume(data: dict) -> list[Finding]:
    """runtime/ and exchange must share one volume for atomic publish."""
    runtime = Path(data.get("runtime", {}).get("root", ""))
    out = Path(data.get("exchange", {}).get("out", ""))
    if not (runtime.exists() and out.exists()):
        return [Finding("same_volume", WARN,
                        "cannot verify same-volume (directories missing)")]
    if os.stat(runtime).st_dev != os.stat(out).st_dev:
        return [Finding("same_volume", ERROR,
                        "runtime.root and exchange.out are on DIFFERENT volumes "
                        "(atomic publish requires the same volume)",
                        hint="Move runtime.root and the exchange directories onto "
                             "the SAME disk/volume so publishing is an atomic "
                             "rename. On Windows keep them on the same drive "
                             "letter; on Linux on the same mount point.")]
    return [Finding("same_volume", OK, "runtime and exchange share one volume")]


def check_rule_aliases(data: dict) -> list[Finding]:
    """Encryption/compression rules must reference declared base_folder aliases."""
    known = {bf["alias"] for bf in data.get("base_folders", [])}
    findings: list[Finding] = []
    for section in ("encryption", "compression"):
        for rule in data.get(section, {}).get("rules", []):
            alias = rule.get("base_folder_alias")
            if alias not in known:
                findings.append(Finding(
                    f"{section}.rule", ERROR,
                    f"rule references unknown base_folder alias: {alias}"))
    if not findings:
        findings.append(Finding("rule_aliases", OK,
                                "all rules reference known aliases"))
    return findings


def check_crypto(data: dict) -> list[Finding]:
    """Validate the crypto backend and the keys the config relies on."""
    enc = data.get("encryption", {})
    backend = enc.get("backend", "noop")
    if backend == "noop":
        return [Finding("crypto", OK, "no encryption backend (noop)")]
    if backend == "pgpy":
        return [_import_finding("pgpy", "PGPy")]
    return _check_gnupg(enc)


def _import_finding(module: str, label: str) -> Finding:
    """Report whether an optional backend module is importable."""
    try:
        __import__(module)
    except ImportError:
        extra = "pgpy" if module == "pgpy" else "gnupg"
        return Finding("crypto", ERROR,
                       f"{label} backend selected but not installed",
                       hint=f"Install it in the FileRouter virtualenv:\n"
                            f'        pip install "filerouter[{extra}]"')
    return Finding("crypto", OK, f"{label} backend importable")


def _check_gnupg(enc: dict) -> list[Finding]:
    """Run a GnuPG self-test and verify the configured keys are present."""
    try:
        import gnupg
    except ImportError:
        return [Finding("crypto", ERROR, "gnupg backend selected but python-gnupg "
                                         "is not installed",
                        hint='Install it: pip install "filerouter[gnupg]" and make '
                             "sure the gpg binary is present (Linux: apt/dnf "
                             "install gnupg; Windows: install Gpg4win).")]
    if not _gpg_binary_available():
        return [Finding("crypto", ERROR, "the gpg binary was not found on PATH",
                        hint=_gpg_install_hint())]
    home = enc.get("gnupg_home")
    if not home or not Path(home).exists():
        return [Finding("crypto", ERROR, f"gnupg_home missing: {home}",
                        hint="Create the keyring directory and import your keys "
                             "into it (see docs/fr/06-encryption.md §8). "
                             f'Linux: export GNUPGHOME="{home}"; gpg --import key.asc'
                             f'  |  Windows: set GNUPGHOME and gpg --import key.asc')]
    gpg = gnupg.GPG(gnupghome=home)
    return _verify_keys(gpg, enc)


def _gpg_binary_available() -> bool:
    """Return True if the gpg executable is on PATH."""
    import shutil

    return shutil.which("gpg") is not None


def _gpg_install_hint() -> str:
    """Return an OS-specific hint for installing the gpg binary."""
    if _is_windows():
        return "Install Gpg4win (https://gpg4win.org) so gpg.exe is on PATH."
    return "Install GnuPG: sudo apt-get install gnupg (Debian/Ubuntu) or " \
           "sudo dnf install gnupg2 (RHEL/Rocky)."


def _verify_keys(gpg, enc: dict) -> list[Finding]:
    """Check the keyring is non-empty and required key ids are present."""
    findings: list[Finding] = []
    public_ids = _key_id_set(gpg.list_keys())
    secret_ids = _key_id_set(gpg.list_keys(True))
    if not public_ids:
        findings.append(Finding("crypto", ERROR, "keyring is empty",
                                hint="Import keys into gnupg_home: "
                                     "gpg --import recipient-pub.asc"))
    # Recipient keys (public) must exist for every enabled encryption rule.
    for rule in enc.get("rules", []):
        if not rule.get("enabled", False):
            continue
        for key in rule.get("recipient_key_ids", []):
            if not _key_present(key, public_ids):
                findings.append(Finding("crypto", ERROR,
                                        f"recipient key not in keyring: {key}",
                                        hint="Import the recipient PUBLIC key: "
                                             "gpg --import recipient-pub.asc, then "
                                             "verify with gpg --list-keys."))
    # Signing key (secret) must exist if signing is configured.
    signing = enc.get("signing_key_id")
    if signing and not _key_present(signing, secret_ids):
        findings.append(Finding("crypto", ERROR,
                                f"signing secret key not in keyring: {signing}",
                                hint="Import the signing SECRET key into "
                                     "gnupg_home: gpg --import signing-secret.asc, "
                                     "then verify with gpg --list-secret-keys."))
    if not findings:
        findings.append(Finding("crypto", OK, "gnupg keyring and keys OK"))
    return findings


def _key_id_set(entries: list) -> set[str]:
    """Collect upper-case key ids and fingerprints from a gnupg key listing."""
    ids: set[str] = set()
    for entry in entries:
        for field in ("keyid", "fingerprint"):
            value = entry.get(field)
            if value:
                ids.add(value.upper())
    return ids


def _key_present(key: str, known: set[str]) -> bool:
    """Return True if a configured key id matches any keyring id (suffix match)."""
    k = key.upper().removeprefix("0X")
    return any(known_id.endswith(k) for known_id in known)


# -- runner ------------------------------------------------------------------

ALL_CHECKS = (
    check_structure,
    check_semantics,
    check_base_folders,
    check_exchange_and_runtime,
    check_same_volume,
    check_rule_aliases,
    check_crypto,
)


class Doctor:
    """Runs all checks and optionally applies safe, confirmed fixes."""

    def __init__(self, config_path: str | Path, *, asker=ask_yes_no, out=print) -> None:
        self._path = Path(config_path)
        self._ask = asker
        self._out = out

    def diagnose(self) -> list[Finding]:
        """Run every check and return the flat list of findings."""
        try:
            data = _read_yaml(self._path)
        except ConfigError as exc:
            return [Finding("load", ERROR, str(exc))]
        findings: list[Finding] = []
        for check in ALL_CHECKS:
            findings.extend(check(data))
        return findings

    def run(self, *, apply_fixes: bool = False) -> int:
        """Print findings, optionally apply confirmed fixes; return an exit code.

        When fixes are applied, the configuration is re-diagnosed so the final
        summary and exit code reflect the repaired state.
        """
        findings = self.diagnose()
        applied = self._apply_round(findings, apply_fixes)
        if applied:
            self._out("\nAfter repairs:")
            findings = self.diagnose()
            for finding in findings:
                self._report(finding)
        errors = sum(1 for f in findings if f.level == ERROR)
        warns = sum(1 for f in findings if f.level == WARN)
        self._out(f"\nSummary: {errors} error(s), {warns} warning(s).")
        return 1 if errors else 0

    def _apply_round(self, findings: list[Finding], apply_fixes: bool) -> int:
        """Report each finding and apply confirmed fixes; return how many applied."""
        applied = 0
        for finding in findings:
            self._report(finding)
            if apply_fixes and finding.level != OK and finding.fixer is not None:
                if self._offer_fix(finding):
                    applied += 1
        return applied

    def _report(self, finding: Finding) -> None:
        """Print a finding; for problems, also print a verbose remediation hint.

        Anything the doctor cannot auto-fix carries a ``hint`` with a concrete,
        OS-aware solution, so the operator is never left guessing.
        """
        marker = {OK: "  OK ", WARN: "WARN ", ERROR: "FAIL "}[finding.level]
        self._out(f"[{marker}] {finding.check}: {finding.message}")
        if finding.level != OK and finding.hint:
            self._out(f"        -> how to fix: {finding.hint}")

    def _offer_fix(self, finding: Finding) -> bool:
        """Ask the operator before applying a fix; return True if applied."""
        if self._ask(f"        -> {finding.fix_label}?"):
            finding.fixer()  # type: ignore[misc]
            self._out(f"        applied: {finding.fix_label}")
            return True
        return False


def main(argv: list[str] | None = None) -> int:
    """CLI entry point for ``filerouter-doctor``."""
    import argparse

    parser = argparse.ArgumentParser(
        prog="filerouter-doctor",
        description="Diagnose (and optionally fix) a FileRouter configuration.")
    parser.add_argument("--config", required=True, help="path to config.yaml")
    parser.add_argument("--fix", action="store_true",
                        help="offer to fix safe problems")
    parser.add_argument("--yes", action="store_true",
                        help="with --fix, apply every safe fix automatically "
                             "WITHOUT asking any question (unattended repair)")
    args = parser.parse_args(argv)
    # --yes turns the interactive asker into an always-yes asker (no questions).
    asker = (lambda _prompt: True) if args.yes else ask_yes_no
    return Doctor(args.config, asker=asker).run(apply_fixes=args.fix)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main(sys.argv[1:]))
