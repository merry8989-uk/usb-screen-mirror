# Log Types & Severity

Reference taxonomy for what PhoneMirror collects (source: the shared "Application Logs /
Log Types & Severity" note). Every structured event carries `category` (one of 12) and
`severity` (one of 6), plus the common fields.

## Common fields (every event)

`timestamp`, `severity`, `category`, `message`, `app_id`, `environment`, `request_id`,
plus sanitized metadata. Retention limits, access controls aur sensitive-data redaction bhi lagti hain.

## 12 log categories

| # | Category | Kya capture hota hai |
|---|---|---|
| 1 | Application Logs | App ke andar kya ho raha hai — session start/end, screen open, feature use |
| 2 | Error Logs | Crash, exception, failed request, invalid data |
| 3 | Security Logs | Failed auth/permission, suspicious requests (tokens log nahi) |
| 4 | Performance Logs | Load time, slow calls, response time, duration |
| 5 | User Activity Logs | Views, clicks, actions, navigation |
| 6 | Server & Infrastructure Logs | Startup/shutdown, metrics, availability, network errors |
| 7 | API & Network Logs | Method, endpoint, status, latency, retry, correlation id |
| 8 | Database Logs | Query errors, slow queries, connection/migration failures |
| 9 | Audit Logs | Kisne kya change kiya, kab, kis resource par |
| 10 | Analytics & Business Logs | Active users, popular pages, conversions (metrics; raw logs se alag) |
| 11 | Background Job & Event Logs | Scheduled tasks, retries, failed jobs, async events |
| 12 | Debug & Trace Logs | Detailed diagnostic steps, distributed tracing |

## 6 severity levels

| Level | Matlab | Example |
|---|---|---|
| TRACE | Bahut detailed execution | Function ke andar steps |
| DEBUG | Debugging information | Kitne records mile |
| INFO | Normal event | Import complete |
| WARN | Potential problem | Feed slow response |
| ERROR | Operation fail | Import fail |
| FATAL | Critical failure | Service start nahi ho pa rahi |

## PhoneMirror mapping

Yeh desktop app hai (koi server/DB/web analytics nahi), isliye applicable categories emit hoti hain:

| Category | PhoneMirror events |
|---|---|
| application | `session_start`, `session_end`, `mirror_result`, `device_state_resolved`, `device_refresh_result` |
| error | `error_state_shown`, `crash_report` (crash report file + event) |
| security | `device_authorization_failed` (USB debugging permission nahi mili) |
| performance | `performance_marker` (adb_command / device_scan / export duration) |
| user_activity | `screen_view`, `mirror_requested`, `preset_applied` |
| infrastructure | `environment_snapshot` (OS, Python, machine) |
| api_network | `adb_command` (command, outcome, latency_ms) |
| audit | `settings_changed`, `diagnostics_toggled`, `diagnostics_cleaned`, `export_saved`, `email_compose`, `share_bundle` |
| background_job | `reconnect_attempt`, `reconnect_result`, `reconnect_loop`, `tool_probe` |
| debug_trace | `queue_drain` (trace level, sirf bade backlog par) |
| analytics | `analytics_snapshot` — usage counters (mirrors started/succeeded/failed, devices seen, reconnects, exports, emails, shares, errors, crashes). Metrics ko raw logs se alag rakha gaya hai. |
| database | N/A — app me koi database nahi |

### Crash reporting

Uncaught exceptions (Tk callbacks + startup) par:

- `crash_report` event (`category: error`) — `exception_type`, `stack_trace_hash`, `last_screen`,
  `last_action`, `report_file` (raw traceback event me **nahi** jaata, sirf hash).
- Poora report file — `crash-reports/crash-<timestamp>.txt` (traceback + context), jo zip bundle me
  `crash_reports/` ke andar attach ho jaati hai.

### Analytics

Counters app ke andar maintain hote hain aur `analytics_snapshot` event me jaate hain (Diagnostics
kholne par aur session end par). Report me ek alag **Analytics** section/sheet bhi hota hai.

Severity: `trace` / `debug` / `info` / `warn` / `error` / `fatal` (schema me `log_level` aur
`severity` dono same value carry karte hain).

Schema: `logschema/event_schema.json` · Validator (CI gate): `logschema/validate_events.py`
