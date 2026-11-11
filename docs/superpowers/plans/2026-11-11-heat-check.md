# Heat Check Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A `tado heat-check` command, run each morning by launchd, that reads yesterday's Tado day reports and raises a macOS notification when a room warmed up with no call for heat or a valve was offline, and whenever the check itself couldn't run.

**Architecture:** Pure detection (`core/heat_detect.py`) and pure alert rules (`core/heat_alerts.py`) are fed by a local cache of day reports (`core/heat_store.py`). The command (`commands/heat_check.py`) wires them to the API client and a small notifier (`core/notify.py`). Login handling in `core/auth.py` becomes atomic, locked and able to fail without prompting, so the job can run unattended.

**Tech Stack:** Python ≥3.12, Click, requests, stdlib `fcntl`, `zoneinfo`, `subprocess` (`osascript`), launchd. pytest.

**Spec:** `docs/superpowers/specs/2026-11-11-heat-check-design.md`

## Global Constraints

- Never call the live Tado API from tests or development commands (CLAUDE.md). Stub `requests.post`, `TadoClient` and the notifier.
- British English in code, comments, output, notifications and docs.
- No new dependencies. Stdlib and the existing `click`/`requests` only.
- Writes to `stored_data/` and `tokens.json` are atomic (temp file, `fsync`, `os.replace`). Reuse `core.storage._save_json` for JSON under `stored_data/`.
- Detection values: rise threshold **2.0°**, carry-over **30 minutes** from each spell's real start, offline minimum **1 hour** in total within the day.
- Weekly repeat: **7 days** after `last_notified`. Catch-up: at most **7 days** back.
- Days are UK local days in `Europe/London`. Report timestamps are UTC (`...Z`); show times in local time as `HH:MM`.
- The scheduled run must never start `device_code_flow`.
- The repo is public: no personal paths in committed files. The fixture has its `weather` block removed.
- Keep the existing layout (`core/`, `commands/` at the root; this project hasn't moved to `src/` yet). Add any new module directories to `[tool.hatch.build.targets.wheel] packages` only if new packages are created (none are planned).

## Review Focus

1. **A zone offline all day has no temperature points.** Expect an offline finding only, no crash and no warming finding. Test in Task 3 (`test_offline_all_day_without_temperatures`).
2. **A day when the clocks change.** On 25 October 2026 (25 hours) and 29 March 2026 (23 hours), the window must follow `Europe/London`, and times must show in local time. Test in Task 3 (`test_summer_time_day_window_and_local_times`).
3. **A damaged cached day report or state file.** It must be refused loudly, reported in a notification and never overwritten. Test in Task 4 (`test_damaged_state_file_is_refused`) and Task 6 (`test_scheduled_damaged_state_notifies`).
4. **The notifier itself failing.** If `osascript` is missing or exits non-zero, the run must log it to stderr and exit non-zero, never crash with a traceback or pass silently. Test in Task 6 (`test_notify_failure_is_reported_on_stderr`).
5. **A zone with no `callForHeat` or `measuringDeviceConnected` series**, which Tado omits for some states. Expect no findings and no crash. Test in Task 3 (`test_missing_series_give_no_findings`).

---

### Task 1: Safe, lockable, non-interactive login

**Files:**
- Modify: `core/auth.py` (`save_tokens`, `refresh_access_token`, `get_access_token`; add exceptions and lock)
- Modify: `core/client.py:22-58` (`connect`)
- Modify: `tests/conftest.py` (add `token_file` fixture)
- Create: `tests/test_auth.py`

**Interfaces:**
- Produces, in `core/auth.py`:
  - `class AuthError(Exception)`: base. Subclasses: `LoginNeeded`, `AuthNetworkError`, `TokenLockBusy`.
  - `TOKEN_LOCK_FILE = TOKEN_FILE.with_name("tokens.json.lock")`, `TOKEN_LOCK_TIMEOUT = 5.0` (seconds).
  - `save_tokens(tokens: dict) -> None`: atomic, final mode `0o600`.
  - `refresh_access_token(refresh_token: str) -> dict | None`: returns new tokens (saved), or `None` when Tado rejects the token (HTTP 400/401). Raises `AuthNetworkError` on `requests.RequestException` or HTTP ≥500.
  - `get_access_token() -> str`: takes the lock, loads tokens **inside** the lock, refreshes. Raises `LoginNeeded` (no file, no refresh token, or rejected), `AuthNetworkError`, `TokenLockBusy`.
- Produces, in `core/client.py`: `TadoClient.connect(interactive: bool = True) -> bool`.
  - Interactive: `LoginNeeded` starts `device_code_flow()` as now. `AuthNetworkError` and `TokenLockBusy` echo the reason to stderr and return `False`.
  - Non-interactive: never calls `device_code_flow`, and re-raises the `AuthError`. For now a `/me` failure still returns `False`. Task 2 changes it to raise `TadoAPIError`.

- [ ] **Step 1: Add the `token_file` fixture to `tests/conftest.py`.** It monkeypatches `core.auth.TOKEN_FILE` and `core.auth.TOKEN_LOCK_FILE` into `tmp_path`.

- [ ] **Step 2: Write the failing tests in `tests/test_auth.py`** (stub `core.auth.requests.post`):

```python
def test_save_tokens_is_atomic_and_private(token_file, monkeypatch):
    token_file.write_text('{"refresh_token": "old"}')
    # fsync fails after the new text is written: the old code never fsyncs and
    # writes in place, so this test fails against it, as it should
    monkeypatch.setattr(auth.os, "fsync", lambda fd: (_ for _ in ()).throw(OSError("disk full")))
    with pytest.raises(OSError):
        auth.save_tokens({"refresh_token": "new"})
    assert json.loads(token_file.read_text()) == {"refresh_token": "old"}

def test_saved_tokens_are_owner_only(token_file):
    auth.save_tokens({"refresh_token": "new"})
    assert stat.S_IMODE(token_file.stat().st_mode) == 0o600

def test_rejected_refresh_means_login_needed(token_file, monkeypatch):  # post returns 400
    with pytest.raises(auth.LoginNeeded): auth.get_access_token()

def test_no_token_file_means_login_needed(token_file): ...

def test_network_failure_is_not_login_needed(token_file, monkeypatch):  # post raises ConnectionError
    with pytest.raises(auth.AuthNetworkError): auth.get_access_token()
    assert json.loads(token_file.read_text())["refresh_token"] == "old"  # untouched

def test_server_error_is_a_network_failure(token_file, monkeypatch): ...  # 503 → AuthNetworkError

def test_successful_refresh_saves_the_rotated_token(token_file, monkeypatch):
    assert auth.get_access_token() == "access-2"
    assert json.loads(token_file.read_text())["refresh_token"] == "refresh-2"

def test_held_lock_gives_up_after_timeout(token_file, monkeypatch):
    monkeypatch.setattr(auth, "TOKEN_LOCK_TIMEOUT", 0.2)
    with open(auth.TOKEN_LOCK_FILE, "w") as held:
        fcntl.flock(held, fcntl.LOCK_EX)
        with pytest.raises(auth.TokenLockBusy): auth.get_access_token()

def test_token_is_read_inside_the_lock(token_file, monkeypatch):
    """A second run must refresh with the token the first run saved, not the one it read before waiting."""
    # stub post to record the refresh_token it was sent; call get_access_token twice;
    # assert the second call sent "refresh-2", not "old"

def test_non_interactive_connect_never_starts_device_login(token_file, monkeypatch):
    monkeypatch.setattr(client_mod, "device_code_flow", lambda: pytest.fail("prompted"))
    with pytest.raises(auth.LoginNeeded): TadoClient().connect(interactive=False)
```

- [ ] **Step 3: Run them and confirm they fail.** `uv run python -m pytest tests/test_auth.py -q`: expect failures and errors (`AttributeError: LoginNeeded`, …).

- [ ] **Step 4: Implement the interfaces above.**
  - The lock: `fcntl.flock(fd, LOCK_EX | LOCK_NB)`, retried every 0.1 s until `TOKEN_LOCK_TIMEOUT`, released in `finally`. The OS releases it if the process dies, so a leftover lock file is harmless.
  - `save_tokens`: write `tokens.json.tmp` opened with mode `0o600`, `fsync`, `os.replace`.
  - `device_code_flow` keeps calling `save_tokens`.
  - `load_tokens` is unchanged. A damaged `tokens.json` still reads as no tokens, so the result is `LoginNeeded`.

- [ ] **Step 5: Run the whole suite.** `uv run python -m pytest -q`: all pass (the existing 101 plus the new ones).

- [ ] **Step 6: Commit.** `git commit -m "Make the Tado login safe to refresh unattended"` (add the attribution trailer).

---

### Task 2: Strict API requests, day reports and rate limits

**Files:**
- Modify: `core/client.py` (`_request`, add `get_day_report`, exceptions)
- Create: `tests/test_client.py`

**Interfaces:**
- Produces, in `core/client.py`:
  - `class TadoAPIError(Exception)` with `.status: int | None`. Subclass `RateLimited` for HTTP 429.
  - `_request(method, path, strict: bool = False)`. Non-strict behaves exactly as now. Strict raises `TadoAPIError`/`RateLimited` instead of echoing and returning `None`, and turns `requests.RequestException` into `TadoAPIError(status=None)`.
  - `TadoClient.rate_limit: str | None`: after each response, the response headers whose names contain `ratelimit` (case-insensitive) joined as `name=value; …`, or `None`.
  - `get_day_report(zone_id: int, day: date) -> dict`: strict `GET /homes/{home_id}/zones/{zone_id}/dayReport?date=YYYY-MM-DD`.

- [ ] **Step 1: Write the failing tests** (replace `client.session.request` with a stub returning a fake response):
  - `test_strict_request_raises_rate_limited_on_429`
  - `test_strict_request_raises_on_server_error`, with `.status == 500`
  - `test_strict_request_wraps_network_errors`, with `.status is None`
  - `test_non_strict_request_still_returns_none`, the existing behaviour
  - `test_day_report_path_and_date`, which asserts the URL ends `/homes/42/zones/12/dayReport?date=2026-11-10`
  - `test_rate_limit_headers_are_kept`: headers `{"RateLimit-Remaining": "19000", "Content-Type": "x"}` → `client.rate_limit == "RateLimit-Remaining=19000"`

- [ ] **Step 2: Run them.** `uv run python -m pytest tests/test_client.py -q` should FAIL.

- [ ] **Step 3: Implement.** In `connect(interactive=False)`, `/me` now goes through strict mode, which finishes Task 1's non-interactive contract.

- [ ] **Step 4: Run the whole suite.** `uv run python -m pytest -q` should all PASS.

- [ ] **Step 5: Commit.** `"Add strict requests, day reports and rate-limit handling to the client"`.

---

### Task 3: Detection from a day report

**Files:**
- Create: `tests/fixtures/dayreport_fault.json`
- Create: `core/heat_detect.py`
- Create: `tests/test_heat_detect.py`

**Interfaces:**
- Produces, in `core/heat_detect.py`:

```python
LONDON = ZoneInfo("Europe/London")
RISE_THRESHOLD = 2.0                     # °C
CARRY_OVER = timedelta(minutes=30)
MIN_OFFLINE = timedelta(hours=1)

@dataclass(frozen=True)
class Finding:
    kind: str                 # "warming" | "offline"
    start: datetime           # aware; warming: time of the low point; offline: first moment offline in the day
    end: datetime | None      # warming: time of the high point; offline: None
    rise: float | None = None
    low: float | None = None
    high: float | None = None

def day_window(day: date) -> tuple[datetime, datetime]   # local midnight to next local midnight, aware
def find_problems(report: dict, day: date) -> list[Finding]   # warming findings first, in time order, then offline
```

- [ ] **Step 1: Create the fixture.** Copy `/private/tmp/claude-501/-Users-duncan-Developer-Program-scripts-tado-data/874106e1-de02-4999-8e33-3c0d2b03f6f9/scratchpad/loo_dayreport_2026-11-10.json` with the top-level `weather` key deleted, written with `indent=2`. If the scratchpad file has gone, stop and ask Duncan to rerun the one-off fetch. Never fetch it yourself.

- [ ] **Step 2: Write the failing tests.** Add a `make_report(points, calls, connected)` helper that builds a minimal report from `("HH:MMZ-ish ISO", value)` tuples.

```python
def test_fault_day_flags_the_loo():
    found = find_problems(load_fixture(), date(2026, 11, 10))
    warming = [f for f in found if f.kind == "warming"]
    assert len(warming) == 1
    assert warming[0].rise == pytest.approx(6.62, abs=0.01)
    assert warming[0].low == pytest.approx(18.56) and warming[0].start == utc(2026, 11, 10, 10, 0)
    assert warming[0].high == pytest.approx(25.18) and warming[0].end == utc(2026, 11, 10, 18, 0)

def test_fault_day_reports_offline_from_1935():
    offline = [f for f in find_problems(load_fixture(), date(2026, 11, 10)) if f.kind == "offline"]
    assert len(offline) == 1 and offline[0].start == utc(2026, 11, 10, 19, 35, 55)

def test_warm_room_without_a_rise_is_not_flagged(): ...      # steady 24° all day, no calls
def test_rise_inside_the_carry_over_is_ignored(): ...        # call ends 06:00; 17° at 06:05 → 20° at 06:25, flat after
def test_rise_just_under_threshold_is_not_flagged(): ...     # 1.9°
def test_call_for_heat_splits_spells(): ...                  # +1.5° before a LOW call, +1.5° after: no finding
def test_rise_must_come_after_the_low(): ...                 # 22° falling to 18°: no finding
def test_short_offline_drop_is_ignored(): ...                # 59 minutes offline
def test_offline_spells_add_up_to_the_hour(): ...            # 40 + 30 minutes → one finding at the first drop
def test_offline_all_day_without_temperatures(): ...         # connected False all day, no points → exactly one offline finding
def test_missing_series_give_no_findings(): ...              # report {} and report without callForHeat → []
def test_points_outside_the_day_are_ignored(): ...           # a big rise from 23:45 the day before to 00:10 doesn't count
def test_summer_time_day_window_and_local_times():
    start, end = day_window(date(2026, 7, 1))
    assert start == utc(2026, 6, 30, 23, 0) and end == utc(2026, 7, 1, 23, 0)
    assert day_window(date(2026, 10, 25))[1] - day_window(date(2026, 10, 25))[0] == timedelta(hours=25)
```

- [ ] **Step 3: Run them.** `uv run python -m pytest tests/test_heat_detect.py -q` should FAIL with `ModuleNotFoundError`.

- [ ] **Step 4: Implement `find_problems`.**
  - Spells are the `callForHeat` intervals whose value is `NONE`.
  - For each spell, take the points in `[max(spell.from + CARRY_OVER, day start), min(spell.to, day end))`.
  - Find the largest later-minus-earlier rise in one pass, keeping the running minimum and its time. Report the spell if the rise is ≥ `RISE_THRESHOLD`. That gives at most one warming finding per spell.
  - Offline: clip the `False` intervals of `measuringDeviceConnected` to the day and sum them. If the total ≥ `MIN_OFFLINE`, report one finding starting at the first clipped `False` moment.
  - Missing keys mean empty series.

- [ ] **Step 5: Check the carry-over against the fixture.** The fixture test must pass with 30 minutes. If it does, keep 30. Record the check in a comment above `CARRY_OVER`: "Checked against the 10 November 2026 loo report: flagged at 6.6° with 30 minutes."

- [ ] **Step 6: Run the whole suite.** `uv run python -m pytest -q` should all PASS.

- [ ] **Step 7: Commit.** `"Detect rooms warming with no call for heat, and offline valves"`.

---

### Task 4: Local store for day reports and check state

**Files:**
- Create: `core/heat_store.py`
- Modify: `tests/conftest.py` (add a `heat_store_dir` fixture that redirects `STORED_DATA_DIR`-based paths into `tmp_path`)
- Create: `tests/test_heat_store.py`

**Interfaces:**
- Consumes: `core.storage._save_json`, `_load_json`, `BatteryHistoryError` (raised for damaged files; its message names the file, which is what's needed).
- Produces, in `core/heat_store.py`:
  - `DAY_REPORTS_DIR = <stored_data>/day_reports`, `HEAT_STATE_FILE = <stored_data>/heat_check.json`
  - `load_day_report(day: date, zone_id: int) -> dict | None`, read from `day_reports/YYYY-MM-DD/<zone_id>.json`
  - `save_day_report(day: date, zone_id: int, report: dict) -> None`, atomic
  - `load_state() -> dict`. Returns `{"last_checked": None, "faults": {}}` when the file is absent. Shape: `{"last_checked": "YYYY-MM-DD" | None, "faults": {"<zone_id>:<kind>": {"zone": str, "kind": str, "first_seen": str, "last_seen": str, "last_notified": str}}}`
  - `save_state(state: dict) -> None`, atomic

- [ ] **Step 1: Write the failing tests:**
  - `test_day_report_round_trip`
  - `test_missing_day_report_is_none`
  - `test_state_defaults_when_absent`
  - `test_state_round_trip_keeps_backup`, which checks that `heat_check.json.bak` exists after the second save
  - `test_damaged_state_file_is_refused`: write `"{"` and expect `BatteryHistoryError`, with the file left unchanged
  - `test_damaged_day_report_is_refused`

- [ ] **Step 2: Run them.** They should FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run the whole suite.** `uv run python -m pytest -q` should all PASS.
- [ ] **Step 5: Commit.** `"Store day reports and heat-check state locally"`.

---

### Task 5: When to notify: new, weekly and cleared faults

**Files:**
- Create: `core/heat_alerts.py`
- Create: `tests/test_heat_alerts.py`

**Interfaces:**
- Produces, in `core/heat_alerts.py`:

```python
REPEAT_AFTER = timedelta(days=7)

def update_faults(faults: dict, day: date, current: dict[str, tuple[str, str]]) -> tuple[dict, list[str]]
    # current: {"<zone_id>:<kind>": (zone_name, kind)} for the faults found on `day`
    # returns (new faults dict, lines to notify), never mutating the input
```

Rules (from the spec):
- A key not in `faults` is a new fault. Record `first_seen = last_seen = last_notified = day` and notify.
- A key in both updates `last_seen = day`. If `day - last_notified >= REPEAT_AFTER`, it notifies and sets `last_notified = day`.
- A key in `faults` but not `current` has cleared. Remove it and notify the cleared wording.

Notification lines:
- warming: `"{zone} warmed with the heating off"`
- offline: `"{zone} is offline"`
- cleared warming: `"{zone} has stopped warming with the heating off"`
- cleared offline: `"{zone} is back online"`

- [ ] **Step 1: Write the failing tests:**
  - `test_new_fault_notifies`
  - `test_known_fault_is_quiet_for_six_days`
  - `test_known_fault_repeats_on_day_seven`, which notifies on the 7th day and resets `last_notified`
  - `test_cleared_offline_says_back_online`, which also checks the key is removed
  - `test_cleared_warming_wording`
  - `test_two_zones_are_independent`
  - `test_input_is_not_mutated`
- [ ] **Step 2: Run them.** They should FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run the whole suite.** All PASS.
- [ ] **Step 5: Commit.** `"Decide when a heat-check fault is notified"`.

---

### Task 6: The `heat-check` command, notifier and scheduled run

**Files:**
- Create: `core/notify.py`
- Create: `commands/heat_check.py`
- Modify: `tado.py` (register `heat_check_command` under "Reporting")
- Create: `tests/test_heat_check.py`

**Interfaces:**
- Consumes: `TadoClient.connect(interactive)`, `get_zones()`, `get_day_report()`, `rate_limit`, `TadoAPIError`, `RateLimited` (Task 2); `AuthError` and its subclasses (Task 1); `find_problems`, `Finding`, `LONDON` (Task 3); the `heat_store` functions (Task 4); `update_faults` (Task 5).
- Produces:
  - `core/notify.py`: `notify(title: str, message: str) -> None`. Runs `["osascript", "-e", "on run argv", "-e", "display notification (item 2 of argv) with title (item 1 of argv)", "-e", "end run", title, message]` with `check=True` and a 10 s timeout. Passing text as arguments means no quoting or injection problems. It raises `NotifyError` on `FileNotFoundError`, `CalledProcessError` or timeout.
  - `commands/heat_check.py`:
    - `MAX_CATCH_UP = 7`
    - `days_to_check(today: date, last_checked: date | None) -> tuple[list[date], list[date]]` returns (days to check oldest first, skipped days older than `MAX_CATCH_UP`). With no `last_checked`, it returns `[yesterday]`.
    - `check_day(client, day: date, zones: list[dict]) -> dict[int, list[Finding]]`. Covers `HEATING` zones only, uses the cache first, saves each fetched report, and never saves a report for today or later.
    - `format_finding(zone: str, finding: Finding) -> str`, matching the spec's lines exactly in shape:
      - `"warmed 6.6° (18.6° → 25.2°) between 10:00 and 18:00 with no call for heat"`
      - `"offline from 19:35"`
      - times in `LONDON`
    - The Click command is `heat-check`, with `--date` (`YYYY-MM-DD`, refuses today and later with `click.BadParameter`) and `--scheduled` (flag).

**Behaviour:**
- **Manual** (`tado heat-check [--date]`):
  - Checks one day (yesterday by default) and prints `  {zone:<width}  {format_finding}` per finding, or `No problems on YYYY-MM-DD`.
  - Uses `connect()` interactively.
  - Never notifies, and never changes `last_checked` or `faults`.
- **Scheduled** (`--scheduled`; `--date` with it is a usage error):
  - Connects with `connect(interactive=False)`.
  - For each day from `days_to_check`, oldest first, it runs `check_day`, then `update_faults`, then `save_state` with `last_checked = day` (after each successful day).
  - All the notify lines from the run go into **one** notification, titled `"Tado heat check"`, with lines joined by `"; "`. If there are none, nothing is sent.
  - Each step is logged to stdout as `YYYY-MM-DDTHH:MM:SS <message>`, including the findings, any skipped days and `client.rate_limit`.
- **Failure notifications** (title `"Tado heat check"`), after which the run exits with code 1:

| Failure | Message |
|---|---|
| `LoginNeeded` | `"Heat check didn't run: Tado login has expired. Run tado auth."` |
| `AuthNetworkError` | `"Heat check didn't run: couldn't reach Tado's login server."` |
| `TokenLockBusy` | `"Heat check didn't run: another tado command was using the login. It will try again tomorrow."` |
| `RateLimited` | `"Tado's daily request limit was reached; the check will carry on tomorrow."` |
| other `TadoAPIError` | `"Heat check didn't run: Tado returned an error ({status})."` |
| `BatteryHistoryError` (damaged store) | `"Heat check didn't run: a saved file is damaged. See the log."` |
| anything else | `"Heat check didn't run: unexpected error. See the log."`, then re-raise so the traceback reaches the log |

- **If notifying fails:** write `"Couldn't show the notification: …"` and the intended message to stderr, then exit with code 1. Don't raise.

- [ ] **Step 1: Write the failing tests.** Use a `FakeHeatClient` with `connect`, `get_zones` and `get_day_report`, which counts calls and returns the fixture for zone 12. Monkeypatch `commands.heat_check.TadoClient` and `commands.heat_check.notify` (a recording stub), pin today with `FrozenDate` on `commands.heat_check.date`, and use the `heat_store_dir` fixture.

```python
def test_days_to_check_first_run_is_yesterday(): ...
def test_days_to_check_catches_up_oldest_first(): ...        # last 2026-08-21, today 2026-08-25 → 22, 23, 24
def test_days_to_check_skips_beyond_seven_days(): ...
def test_format_finding_matches_the_spec():
    assert format_finding(...warming from fixture...) == "warmed 6.6° (18.6° → 25.2°) between 10:00 and 18:00 with no call for heat"
    assert format_finding(...offline...) == "offline from 19:35"
def test_manual_run_prints_findings_and_never_notifies(...)
def test_manual_run_clean_day(...)                            # "No problems on 2026-08-24"
def test_manual_run_refuses_today(...)
def test_cached_day_makes_no_report_requests(...)             # second run: get_day_report call count unchanged
def test_hot_water_zones_are_skipped(...)
def test_scheduled_new_fault_notifies_once_then_quiet(...)    # run on 25th, then (today=26th) again: one notification total
def test_scheduled_clean_day_sends_nothing(...)
def test_scheduled_login_needed_notifies_and_exits_1(...)
def test_scheduled_never_prompts(...)                         # connect called with interactive=False
def test_scheduled_rate_limited_keeps_saved_days(...)         # 429 on second day: first day's report saved, last_checked = first day
def test_failed_run_does_not_move_last_checked(...)
def test_scheduled_damaged_state_notifies(...)
def test_scheduled_with_date_is_a_usage_error(...)
def test_notify_passes_text_as_arguments(monkeypatch):        # stub subprocess.run; title and message are the last two argv items
def test_notify_failure_is_reported_on_stderr(...)            # notify raises NotifyError → stderr message, exit 1, no traceback
```

- [ ] **Step 2: Run them.** `uv run python -m pytest tests/test_heat_check.py -q` should FAIL.
- [ ] **Step 3: Implement `core/notify.py`, `commands/heat_check.py`, and register the command in `tado.py`.**
- [ ] **Step 4: Run the whole suite.** All PASS. Then run `uv run python tado.py heat-check --help`, which makes no API call. It should show `--date` and `--scheduled`.
- [ ] **Step 5: Commit.** `"Add the heat-check command with scheduled notifications"`.

---

### Task 7: launchd schedule, install script and docs

**Files:**
- Create: `tools/heat-check.plist.template`
- Create: `tools/install-heat-check.sh`
- Modify: `CLAUDE.md` (Running Commands, a new "Heat Check" architecture section, File Structure)
- Modify: `.gitignore` if needed (`stored_data/` is already ignored; check that this covers `day_reports/`)

**Decisions:**
- **Label:** `uk.local.tado-data.heat-check` (no personal names).
- **Template placeholders:** `__UV__` (absolute path to `uv`), `__REPO__` (repo path) and `__LOG__` (`~/Library/Logs/tado-heat-check.log`, expanded).
- **ProgramArguments:** `__UV__ run --directory __REPO__ python tado.py heat-check --scheduled`.
- **StartCalendarInterval:** `Hour 7, Minute 0`. `RunAtLoad` is false. `StandardOutPath` and `StandardErrorPath` are both `__LOG__`.
- **Install script:** `set -euo pipefail`. It finds `uv` with `command -v uv` (failing clearly if it's missing) and the repo from the script's own location. It writes `~/Library/LaunchAgents/uk.local.tado-data.heat-check.plist`, runs `launchctl bootout` for any old copy (ignoring errors), then `launchctl bootstrap gui/$(id -u) <plist>`. Finally it prints how to test it: `launchctl kickstart gui/$(id -u)/uk.local.tado-data.heat-check`, which does make real API calls (about 19), so it's Duncan's to run.
- **CLAUDE.md, in British English:** how detection works (2.0°, 30 minutes, 1 hour), the once-a-week repeat and cleared notifications, the 7-day catch-up, the log location, that `--scheduled` never prompts, and the one-time notification permission. The first notification from `osascript` may appear under "Script Editor" in System Settings → Notifications, where it must be allowed. Add the new files to File Structure.

- [ ] **Step 1: Write the template and script.** Then run `bash -n tools/install-heat-check.sh` (no output means OK) and `plutil -lint` on a copy rendered into the scratchpad with dummy paths (it should print `OK`). Don't run the install.
- [ ] **Step 2: Update CLAUDE.md.**
- [ ] **Step 3: Run the whole suite.** `uv run python -m pytest -q` should all PASS.
- [ ] **Step 4: Commit.** `"Schedule the heat check with launchd and document it"`.
