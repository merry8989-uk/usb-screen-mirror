# ProGallery - Logging Checklist & Event Schema

> Source: `ProGallery_Logging_Spec.docx` (v1.0, Owner: Engineering).
> Yeh shared standard hai jo PhoneMirror ke structured logging me implement kiya gaya hai
> (dekho `logschema/event_schema.json` + `logschema/validate_events.py`).

ProGallery

Logging Checklist & Event Schema

A shared standard for capturing logs across the ProGallery Android app and website, so every issue is debuggable and every UX problem is measurable.

Version 1.0  |  Owner: Engineering  |  Applies to: Android app + web

# Why this exists

The diagnostics log from 21 Oct showed 71 "access fix requested" entries but not a single "fix result" line. The log proved a user was stuck in a loop, but could not say why. That is the core rule this document enforces: a log must capture intent, outcome and context together, not intent alone.

Follow this schema for every new event in both the app and the website. It is deliberately one shared standard so app and web data can be joined and compared.

# Part A — Logging Checklist

Every logging implementation must satisfy all of the following. Treat as a review gate before shipping.

- Structured format (JSON / key-value) — never free-text strings.

- Every event carries all three: intent, outcome, and context.

- A correlation id (session_id, and attempt_id for user actions) links related events into one story.

- Session context (device, OS, app version) logged once per session, not repeated on every event.

- Outcomes are logged, not just requests — success / failure / error code / no-op.

- Log levels used deliberately: debug, info, warn, error.

- Sampling applied at scale (100% of errors, sampled info events).

- Retention policy defined — how long each log class is kept.

- No PII is ever logged, and redaction rules are identical on app and web.

- Timestamps in ISO 8601, UTC.

- Schema is versioned; breaking changes bump schema_version.

- Events validated against this schema in CI, and tested on real devices / browsers.

# Part B — Common Event Envelope

Every event, on app or web, carries these fields. Event-specific properties are added on top (Parts C–E).

| Field | Type | Required | Example | Notes |
|---|---|---|---|---|
| event_name | string | Yes | access_fix_result | snake_case, object_action |
| schema_version | string | Yes | 1.0.0 | bump on breaking change |
| timestamp | ISO 8601 UTC | Yes | 2026-10-21T14:40:12Z | device clock; flag drift |
| session_id | string | Yes | sess_9f2a… | new per app launch / visit |
| attempt_id | string | Conditional | att_71c3 | groups intent → outcome |
| user_id | string | Optional | u_4b8d… | pseudonymous hash only |
| platform | enum | Yes | android / web |  |
| app_version | string | Yes | 2.4.1 (318) | build number included |
| os | string | Yes | Android 14 / Chrome 129 |  |
| device_model | string | Yes | Pixel 7 | or device class on web |
| network_type | enum | Optional | wifi / 4g / offline | captures connectivity issues |
| screen_or_route | string | Yes | MediaAccessDiagnostics | screen name or URL path |
| log_level | enum | Yes | info | debug/info/warn/error |
| release_channel | enum | Optional | production / beta |  |

# Part C — App Event Schema (Android)

| Event | When to log | Key properties |
|---|---|---|
| session_start | App cold or warm start | start_type, cold_start_ms, warm_start_ms |
| screen_view | A screen is shown | screen_name, previous_screen, duration_ms |
| permission_state_resolved | After checking media access | permission, state (granted / partial / denied / permanently_denied), media_item_count |
| access_fix_requested | User taps a fix action | permission, state_before, attempt_id |
| access_fix_result | Fix attempt finishes | attempt_id, action_taken, state_after, outcome (success / no_op / failed), error_code |
| media_query_result | After a MediaStore query | item_count, query_ms, folders_visible |
| api_request | Any network call | endpoint, method, status_code, latency_ms, retry_count |
| crash | Uncaught exception | fatal, exception_type, stack_trace_hash, last_screen, last_action |
| anr | App not responding | duration_ms, last_screen |
| performance_marker | Key flows complete | flow (app_start / screen_render / scroll), duration_ms, frame_drops |
| error_state_shown | An error UI is displayed | error_code, screen, message_key |

# Part D — Web Event Schema

| Event | When to log | Key properties |
|---|---|---|
| page_view | A page loads | url_path, referrer, title |
| web_vitals | After load / interaction | lcp_ms, cls, inp_ms, ttfb_ms |
| js_error | Unhandled error | error_type, message, stack_hash, url, browser |
| api_call | Any fetch / XHR | endpoint, status_code, latency_ms |
| form_start / form_abandon / form_submit | Form lifecycle | form_id, step, field_count, time_on_form_ms |
| search_performed | A search runs | query_length (not the raw query), result_count |
| search_no_results | Search returns zero | query_length, filters |
| conversion | A goal is reached | goal_name, value, source |
| feedback_submitted | Feedback widget used | rating, page |

# Part E — User-Friendliness Signals

These events directly expose friction. Capture them on both app and web — they are how you find UX problems before users complain.

| Signal | What it reveals | How to capture |
|---|---|---|
| rage_tap / rage_click | Something looks tappable but is broken | 3+ taps on same element within 2s |
| dead_click | A tap does nothing at all | Click with no state change / navigation |
| permission_loop | User keeps retrying a fix | access_fix_requested count per session |
| back_button_spam | User is lost or confused | 3+ back presses within 2s |
| error_shown | A friction point | Any error UI displayed |
| drop_off | A funnel leak | Last event before session ends on a step |
| time_to_first_value | Onboarding is slow | session_start → first meaningful action |
| scroll_depth | Engagement level | % of page / list scrolled |
| session_replay_marker | Qualitative context | Link a replay to the event timeline |

# Part F — Privacy & Compliance

Logs are the easiest place to accidentally leak personal data. For an India-facing product this is also a DPDP Act obligation, not just good practice.

- Never log: email, phone, name, exact location, raw file paths, raw search queries, auth tokens, or media file names.

- Store user_id only as a salted hash — never a raw identifier.

- Respect the DPDP Act 2023: consent, purpose limitation, data minimisation, and defined retention limits.

- Redaction rules must be identical across app and web — no exceptions.

- Provide a consent gate / opt-out for analytics collection.

- Encrypt logs in transit (TLS) and at rest.

- Define a retention and deletion policy, and enforce it automatically.

- Restrict access to log dashboards to those who need it.

# Part G — Naming & Implementation Notes

- event_name follows object_action in snake_case: access_fix_result, not FixAccessResult.

- Property names are snake_case and identical across app and web.

- Enums are fixed, documented, and never sent as free text.

- Bump schema_version on any breaking change and announce it to both teams.

- Use one shared schema / SDK for app and web (OpenTelemetry-style) so data joins cleanly.

- Validate every event against this schema in CI before it can ship.

- Sample high-volume info events; keep errors at 100%.

- Test the logging itself on real devices and browsers — a log that never fires is worse than none.

Apply this to the ProGallery diagnostics flow first: add access_fix_result with state_before, state_after and media_item_count, and the 71-attempt loop will explain itself on the next run.
