"""Config write service — the ONLY place the frontend API may write to disk.

Safety invariants:
- Writes ONLY to config/config.yaml via atomic os.replace — never in-place.
- NEVER writes to logs/ or data/.
- Uses SURGICAL text replacement: only lines whose values actually changed
  are modified; all other lines are byte-identical to the original.
  This guarantees:
    • Comments, blank lines, ordering are perfectly preserved.
    • Quoted strings ("09:45") keep their quotes.
    • Column-aligned keys (atm:  ON) keep their spacing.
    • ON/OFF boolean style is preserved (we always write ON/OFF for booleans).
    • git diff shows ONLY the changed lines.
- If nothing changed (no-op PUT), the file is NOT written at all.
- Line endings of the original (CRLF on Windows) are preserved.
- All writes are serialised under _WRITE_LOCK and are atomic.

ruamel.yaml is used ONLY for loading + validation (to get Python types),
NOT for dumping — we dump nothing; we do surgical text edits instead.

Real field shapes from config.yaml (observed keys, used for validation):
  feeds.active_feed                         "kite" | "upstox"
  feeds.healthcheck_timeout_seconds         number > 0
  feeds.upstox.enabled / kite.enabled       ON|OFF (bool)
  feeds.upstox.token_validity_days / kite.  int >= 1
  instruments.nifty_lot_size / banknifty_lot_size   int > 0
  All other bool fields (mode.*, etc.)      bool only
"""
from __future__ import annotations

import os
import re
import tempfile
import threading
from typing import Any, Dict, List, Optional, Tuple

from ruamel.yaml import YAML

from ..paths import CONFIG_PATH

_WRITE_LOCK = threading.Lock()
_yaml_rt = YAML(typ="rt")

# Keys that require a bot restart when changed
RESTART_REQUIRED_KEYS: frozenset = frozenset({
    "feeds.active_feed",
    "mode.order_place_mode",
})


# ---------------------------------------------------------------------------
# Boolean helpers
# ruamel.yaml 0.19+ uses YAML 1.2 schema: ON/OFF/yes/no are plain STRINGS,
# not booleans. Only `true`/`false` are booleans. Our config.yaml uses ON/OFF
# exclusively. All bool-related helpers must handle both str and bool forms.
# ---------------------------------------------------------------------------

_YAML_TRUE_STRINGS = frozenset({"on", "true", "yes", "y", "1"})
_YAML_FALSE_STRINGS = frozenset({"off", "false", "no", "n", "0"})


def _is_bool_like(v: Any) -> bool:
    """True if v represents a YAML boolean: Python bool OR ON/OFF/yes/no string."""
    if isinstance(v, bool):
        return True
    if isinstance(v, str):
        return v.lower() in _YAML_TRUE_STRINGS | _YAML_FALSE_STRINGS
    try:
        from ruamel.yaml.scalarboolean import ScalarBoolean
        return isinstance(v, ScalarBoolean)
    except ImportError:
        return False


def _bool_yaml(v: Any) -> bool:
    """Convert any bool-like YAML value (bool or ON/OFF string) to Python bool."""
    if isinstance(v, bool):
        return v
    if isinstance(v, str):
        return v.lower() in _YAML_TRUE_STRINGS
    try:
        from ruamel.yaml.scalarboolean import ScalarBoolean
        if isinstance(v, ScalarBoolean):
            return bool(v)
    except ImportError:
        pass
    return bool(v)


# Keep old name as alias (used elsewhere for isinstance checks)
def _is_yaml_bool(v: Any) -> bool:
    return _is_bool_like(v)


# ---------------------------------------------------------------------------
# Document load (ruamel — read-only, for validation only)
# ---------------------------------------------------------------------------

def load_doc() -> Any:
    """Load config.yaml as a ruamel.yaml round-trip CommentedMap (for validation)."""
    with CONFIG_PATH.open("r", encoding="utf-8") as f:
        return _yaml_rt.load(f)


def doc_to_plain(obj: Any) -> Any:
    """Convert a ruamel CommentedMap tree to plain JSON-serialisable types.

    ON/OFF strings (YAML 1.2 — not parsed as booleans by ruamel 0.19) are
    converted to Python bool so the React frontend always receives true/false,
    never the raw "ON"/"OFF" strings.
    """
    if isinstance(obj, dict):
        return {k: doc_to_plain(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [doc_to_plain(v) for v in obj]
    if _is_bool_like(obj):
        return _bool_yaml(obj)
    return obj


def get_config_json() -> Dict[str, Any]:
    """Read config.yaml and return as a plain JSON-serialisable dict."""
    return doc_to_plain(load_doc())


# ---------------------------------------------------------------------------
# Value equality — used to detect what actually changed
# ---------------------------------------------------------------------------

def _values_equal(new_val: Any, existing: Any) -> bool:
    """Return True when new_val and existing represent the same YAML value.

    Handles the ruamel 0.19 / YAML 1.2 reality where ON/OFF are plain strings:
    - bool True   ==  string "ON"   (or "yes", "true")
    - bool False  ==  string "OFF"  (or "no", "false")
    - Strings / numbers: str(new) == str(existing)  [handles "09:45" vs 09:45]
    - Lists: element-by-element
    - Dicts: always False (recursion handles them)
    """
    # Both are bool-like (bool, ScalarBoolean, or ON/OFF string)
    if _is_bool_like(new_val) and _is_bool_like(existing):
        return _bool_yaml(new_val) == _bool_yaml(existing)
    # One is bool-like, the other is not → not equal
    if _is_bool_like(new_val) or _is_bool_like(existing):
        return False
    if isinstance(new_val, list) and isinstance(existing, list):
        if len(new_val) != len(existing):
            return False
        return all(_values_equal(a, b) for a, b in zip(new_val, existing))
    if isinstance(new_val, dict):
        return False
    return str(new_val) == str(existing)


def compute_changes(
    doc: Any, changes: Dict[str, Any], _path: str = ""
) -> List[Tuple[str, Any]]:
    """Return (dotted_path, new_python_val) for every leaf that actually changed."""
    result: List[Tuple[str, Any]] = []
    for key, val in changes.items():
        full = f"{_path}.{key}" if _path else key
        existing = doc.get(key) if isinstance(doc, dict) else None
        if isinstance(val, dict) and isinstance(existing, dict):
            result.extend(compute_changes(existing, val, full))
        elif not _values_equal(val, existing):
            result.append((full, val))
    return result


# ---------------------------------------------------------------------------
# YAML scalar serialisation (for surgical replacement)
# ---------------------------------------------------------------------------

def _to_yaml_str(v: Any) -> str:
    """Convert a Python value to the YAML string we'll write into the file.

    All booleans → ON/OFF (matching the existing config.yaml style).
    Numbers → str(n).
    Strings → the value itself (no quoting; preserves existing style).
    """
    if isinstance(v, bool) or _is_yaml_bool(v):
        return "ON" if bool(v) else "OFF"
    return str(v)


# ---------------------------------------------------------------------------
# Surgical text replacement
# ---------------------------------------------------------------------------

def _surgical_set(text: str, path: List[str], yaml_val: str) -> str:
    """Replace a single scalar value at `path` in the YAML text.

    Walks the nested path by matching indent levels:
      depth 0 → 0 spaces, depth 1 → 2 spaces, depth 2 → 4 spaces, etc.

    For the matched leaf line, ONLY the value token is replaced; the key,
    its colon, inter-column spacing, and inline comment are all preserved.
    Non-leaf lines (section headers) are never modified.
    """
    lines = text.split("\n")
    search_from = 0

    for depth, key in enumerate(path):
        indent = "  " * depth
        is_last = depth == len(path) - 1
        key_prefix = f"{indent}{key}:"

        for i in range(search_from, len(lines)):
            line = lines[i]
            if not line.startswith(key_prefix):
                continue
            # Found the key at this depth
            if is_last:
                # Surgical replace: capture (prefix)(value)(rest_of_line)
                m = re.match(
                    rf"^({re.escape(indent)}{re.escape(key)}:[ \t]*)(\S+)(.*)$",
                    line,
                )
                if m:
                    lines[i] = m.group(1) + yaml_val + m.group(3)
                # If no match (key without value), leave line unchanged
            else:
                search_from = i + 1  # next depth: search after this header
            break  # found — move to next path component

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Atomic file write
# ---------------------------------------------------------------------------

def _atomic_write_text(text: str, use_crlf: bool) -> None:
    """Write `text` to config.yaml atomically (temp → fsync → os.replace)."""
    if use_crlf:
        text = text.replace("\n", "\r\n")

    config_dir = CONFIG_PATH.parent
    fd, tmp_path = tempfile.mkstemp(
        dir=config_dir, suffix=".yaml.tmp", prefix="config_write_"
    )
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(text.encode("utf-8"))
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, CONFIG_PATH)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


# ---------------------------------------------------------------------------
# Restart-required detection
# ---------------------------------------------------------------------------

def find_restart_required(changes: Dict[str, Any], _path: str = "") -> List[str]:
    result: List[str] = []
    for key, val in changes.items():
        full = f"{_path}.{key}" if _path else key
        if full in RESTART_REQUIRED_KEYS:
            result.append(full)
        if isinstance(val, dict):
            result.extend(find_restart_required(val, full))
    return result


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def _nested_get(d: Any, dotted: str) -> Optional[Any]:
    cur = d
    for part in dotted.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return None
        cur = cur[part]
    return cur


def _walk_bool_checks(doc_node: Any, changes_node: Any, errors: List[str], path: str) -> None:
    for key, new_val in changes_node.items():
        full = f"{path}.{key}" if path else key
        existing = doc_node.get(key) if isinstance(doc_node, dict) else None
        if isinstance(new_val, dict) and isinstance(existing, dict):
            _walk_bool_checks(existing, new_val, errors, full)
        elif not isinstance(new_val, dict) and _is_bool_like(existing):
            # existing is a toggle field — new value must also be boolean
            if not isinstance(new_val, bool):
                errors.append(
                    f"{full} must be a boolean (true/false), got {type(new_val).__name__}."
                )


def validate_changes(doc: Any, changes: Dict[str, Any]) -> List[str]:
    """Validate a nested partial change dict. Returns [] on success."""
    errors: List[str] = []

    new_feed = _nested_get(changes, "feeds.active_feed")
    if new_feed is not None:
        if new_feed not in ("kite", "upstox"):
            errors.append(f"feeds.active_feed must be 'kite' or 'upstox', got '{new_feed}'.")
        else:
            enabled = _nested_get(changes, f"feeds.{new_feed}.enabled")
            if enabled is None:
                enabled = _nested_get(doc, f"feeds.{new_feed}.enabled")
            # Use _bool_yaml: bool('OFF') is True in Python — must check semantically
            if enabled is not None and not _bool_yaml(enabled):
                errors.append(
                    f"Cannot switch to '{new_feed}': feeds.{new_feed}.enabled is OFF. "
                    "Enable it first, then switch."
                )

    for feed in ("upstox", "kite"):
        tvd = _nested_get(changes, f"feeds.{feed}.token_validity_days")
        if tvd is not None:
            if not isinstance(tvd, int) or isinstance(tvd, bool) or tvd < 1:
                errors.append(f"feeds.{feed}.token_validity_days must be an integer >= 1.")

    hts = _nested_get(changes, "feeds.healthcheck_timeout_seconds")
    if hts is not None:
        if not isinstance(hts, (int, float)) or isinstance(hts, bool) or hts <= 0:
            errors.append("feeds.healthcheck_timeout_seconds must be a positive number.")

    for sym in ("nifty", "banknifty"):
        ls = _nested_get(changes, f"instruments.{sym}_lot_size")
        if ls is not None:
            if not isinstance(ls, int) or isinstance(ls, bool) or ls <= 0:
                errors.append(f"instruments.{sym}_lot_size must be a positive integer.")

    _validate_strike(doc, changes, errors)
    _validate_stop_loss(changes, errors)
    _validate_risk_reward(changes, errors)
    _validate_position_sizing(changes, errors)
    _validate_circuit_breakers(changes, errors)

    _walk_bool_checks(doc, changes, errors, "")
    return errors


# ---------------------------------------------------------------------------
# Per-section validators (Frontend Phase 4 — Strike/StopLoss/RiskMoney editor)
# ---------------------------------------------------------------------------

def _is_positive_int(v: Any) -> bool:
    return isinstance(v, int) and not isinstance(v, bool) and v > 0


def _is_non_neg_int(v: Any) -> bool:
    return isinstance(v, int) and not isinstance(v, bool) and v >= 0


def _is_positive_number(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and v > 0


_ALERT_STRIKE_KEYS = ("itm3", "itm2", "itm1", "atm", "otm1", "otm2", "otm3")


def _validate_strike(doc: Any, changes: Dict[str, Any], errors: List[str]) -> None:
    mdev = _nested_get(changes, "strike.max_deviation_from_atm")
    if mdev is not None and not _is_non_neg_int(mdev):
        errors.append("strike.max_deviation_from_atm must be a non-negative integer.")

    lep = _nested_get(changes, "strike.late_entry_threshold_percent")
    if lep is not None and not _is_positive_number(lep):
        errors.append("strike.late_entry_threshold_percent must be a positive number.")

    new_alert = _nested_get(changes, "strike.alert_strikes")
    if isinstance(new_alert, dict):
        existing_alert = _nested_get(doc, "strike.alert_strikes") or {}
        merged: Dict[str, Any] = {}
        for k in _ALERT_STRIKE_KEYS:
            if k in existing_alert:
                merged[k] = existing_alert[k]
        for k, v in new_alert.items():
            merged[k] = v
        any_on = any(
            _bool_yaml(merged[k]) for k in _ALERT_STRIKE_KEYS if k in merged
        )
        if not any_on:
            errors.append(
                "strike.alert_strikes: at least one alert strike must be enabled."
            )


def _validate_stop_loss(changes: Dict[str, Any], errors: List[str]) -> None:
    method = _nested_get(changes, "stop_loss.method")
    if method is not None:
        if not isinstance(method, int) or isinstance(method, bool) or method not in (1, 2, 3):
            errors.append("stop_loss.method must be one of 1, 2, or 3.")

    sma_period = _nested_get(changes, "stop_loss.sma_trail.sma_period")
    if sma_period is not None and not _is_positive_int(sma_period):
        errors.append("stop_loss.sma_trail.sma_period must be a positive integer.")

    aam = _nested_get(changes, "stop_loss.sma_trail.activate_after_minutes")
    if aam is not None and not _is_positive_int(aam):
        errors.append("stop_loss.sma_trail.activate_after_minutes must be a positive integer.")

    uim = _nested_get(changes, "stop_loss.sma_trail.update_interval_minutes")
    if uim is not None and not _is_positive_int(uim):
        errors.append("stop_loss.sma_trail.update_interval_minutes must be a positive integer.")

    fdir = _nested_get(changes, "stop_loss.sma_trail.follow_direction")
    if fdir is not None and fdir not in ("both", "ratchet"):
        errors.append("stop_loss.sma_trail.follow_direction must be 'both' or 'ratchet'.")


def _validate_risk_reward(changes: Dict[str, Any], errors: List[str]) -> None:
    for key in (
        "target_risk_per_trade",
        "risk_range_min",
        "risk_range_max",
        "normal_day_tp1_r",
        "normal_day_tp2_r",
        "expiry_day_tp1_r",
        "expiry_day_tp2_r",
    ):
        v = _nested_get(changes, f"risk_reward.{key}")
        if v is not None and not _is_positive_number(v):
            errors.append(f"risk_reward.{key} must be a positive number.")


def _validate_position_sizing(changes: Dict[str, Any], errors: List[str]) -> None:
    for key in ("nifty_max_lots", "banknifty_max_lots"):
        v = _nested_get(changes, f"position_sizing.{key}")
        if v is not None and not _is_positive_int(v):
            errors.append(f"position_sizing.{key} must be a positive integer.")


def _validate_circuit_breakers(changes: Dict[str, Any], errors: List[str]) -> None:
    msl = _nested_get(changes, "circuit_breakers.max_sl_per_day")
    if msl is not None:
        if not isinstance(msl, int) or isinstance(msl, bool) or msl < 1:
            errors.append("circuit_breakers.max_sl_per_day must be an integer >= 1.")

    mlpd = _nested_get(changes, "circuit_breakers.max_loss_per_day_rupees")
    if mlpd is not None and not _is_positive_number(mlpd):
        errors.append("circuit_breakers.max_loss_per_day_rupees must be a positive number.")


# ---------------------------------------------------------------------------
# Public write entry-point (called by the router under _WRITE_LOCK)
# ---------------------------------------------------------------------------

def safe_write(changes: Dict[str, Any]) -> Dict[str, Any]:
    """Validate → compute diff → surgically write only changed lines.

    Raises ValueError(list_of_errors) on validation failure.
    Returns a response dict on success.
    """
    doc = load_doc()

    errors = validate_changes(doc, changes)
    if errors:
        raise ValueError(errors)

    changed_pairs = compute_changes(doc, changes)

    if not changed_pairs:
        # Nothing actually changed — do NOT write the file
        return {
            "ok": True,
            "updated": False,
            "restart_required": [],
            "message": "No changes — all values are already set to those values.",
        }

    # Surgical text replacement
    raw = CONFIG_PATH.read_bytes()
    use_crlf = b"\r\n" in raw
    text = raw.decode("utf-8").replace("\r\n", "\n")

    for dotted_path, new_val in changed_pairs:
        path_parts = dotted_path.split(".")
        yaml_val = _to_yaml_str(new_val)
        text = _surgical_set(text, path_parts, yaml_val)

    _atomic_write_text(text, use_crlf)

    restart_keys = find_restart_required(changes)
    return {
        "ok": True,
        "updated": True,
        "restart_required": restart_keys,
        "message": (
            "Saved — restart run.bat for this change to take effect."
            if restart_keys
            else "Saved — applies on the bot's next scan."
        ),
    }
