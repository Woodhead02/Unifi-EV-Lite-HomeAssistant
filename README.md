# UniFi EV Station for Home Assistant

A local Home Assistant custom integration for UniFi Connect EV Stations managed by a UniFi OS console.

> **Status:** Early but functional. This integration uses observed, undocumented UniFi Connect API behavior. Ubiquiti may change these endpoints or payloads in future UniFi releases.

## Features

Bring your UniFi EV chargers into Home Assistant with useful energy tracking and everyday charging controls.

- **See live charging activity** — view current power draw, amperage, and charging status while a vehicle is charging.
- **Track energy use over time** — see energy used today, month to date, over the last 7 days, over the last 30 days, and across recorded charging history.
- **Review charging sessions** — see the most recent session energy use and charging time, plus the total number of recorded sessions.
- **Control whether charging is allowed** — enable or disable charging directly from Home Assistant when supported by the charger.
- **Adjust charging amperage** — change the charger's maximum output from Home Assistant, with limits based on the configured circuit breaker.
- **Manage multiple chargers** — chargers are discovered automatically and appear as separate Home Assistant devices.
- **Works locally** — Home Assistant connects directly to your UniFi console on your local network; no UI.com cloud connection is required for normal operation.
- **Handles model differences gracefully** — features that are not supported by a particular charger are simply left unavailable instead of preventing the integration from loading.

### What this looks like in Home Assistant

For each supported charger, you can build dashboards and automations around information such as:

- Live charging power, current, and voltage
- Charging status
- Energy used today
- Energy used this month
- Recent and historical charging energy
- Last charging-session energy and duration
- Charging enable/disable
- Maximum charging amperage

This makes it possible to build automations such as lowering charging current during peak demand, disabling charging on a schedule, or tracking EV charging energy separately from the rest of the home.

## Home Assistant entities

Per detected charger, the integration currently creates the following entities when supported by that device.

### Live telemetry

- **Power** — live charging power in kW.
- **Current** — live current draw in A.
- **Voltage** — live charging voltage.
- **Session energy** — live energy meter reported during the active charging session.
- **Session duration** — live session duration reported by the charger.
- **Charging status** — current UniFi charging state.

### Energy and session statistics

- **Last session energy** — energy delivered during the most recent recorded session, in kWh.
- **Last session charge time** — active charging time for the most recent recorded session.
- **Historical energy** — total energy represented by the charging history currently returned by UniFi.
- **Session count** — number of recorded sessions in charging history.
- **Energy Today** — charging energy attributed to the current local calendar day.
- **Energy Month to Date** — charging energy attributed to the current local calendar month.
- **Energy in the last 7 days** — rolling 7-day charging energy.
- **Energy in the last 30 days** — rolling 30-day charging energy.

### Controls

- **Allow charging** — enables or disables charging when the EV Station advertises the applicable action.
- **Maximum output** — writable amperage control when the EV Station advertises `set_max_output_amp`.

## Installation with HACS

This repository can be installed as a HACS custom repository.

1. Open **HACS** in Home Assistant.
2. Open the HACS menu and choose **Custom repositories**.
3. Add:

   ```text
   https://github.com/Woodhead02/Unifi-EV-Lite-HomeAssistant
   ```

4. Select **Integration** as the repository type.
5. Install **UniFi EV Station**.
6. Restart Home Assistant.
7. Go to **Settings -> Devices & services -> Add integration**.
8. Search for **UniFi EV Station**.

## Configuration

Use the local address of your UniFi OS console, for example:

```text
https://192.168.1.1
```

Use a **local UniFi OS user**, not a UI.com cloud/SSO-only identity. A dedicated Home Assistant account is recommended.

If the console uses its default/self-signed certificate, disable SSL certificate verification during setup.

## UniFi endpoints currently used

The integration currently uses the following observed UniFi OS / UniFi Connect endpoints:

```text
POST  /api/auth/login
GET   /proxy/connect/api/v2/devices
GET   /proxy/connect/api/v2/devices/{device_id}/powerStats
GET   /proxy/connect/api/v2/stats/evs/chargingHistory
PATCH /proxy/connect/api/v2/devices/{device_id}/status
```

The client maintains the UniFi OS session cookie and CSRF token required by the console.

### Observed charging actions

The integration discovers supported actions dynamically from each device's `type.supportedActions` collection. Confirmed actions include:

```text
enable_charging
set_max_output_amp
```

For maximum-output changes, UniFi uses a payload shaped like:

```json
{
  "id": "<device-specific-action-uuid>",
  "name": "set_max_output_amp",
  "args": {
    "maxOutput": 26
  }
}
```

The action UUID is obtained from the charger at runtime and is not hard-coded.

## Energy rollups

**Energy Today** and **Energy Month to Date** are calculated from UniFi Connect charging history using Home Assistant's configured local timezone.

Because the charging-history API is session-based:

- Active sessions that cross local midnight are split at the boundary using the live session meter, so **Energy Today** starts from the post-midnight portion only. The same logic applies at month boundaries for **Energy Month to Date**.
- An active charging session may not be included until UniFi writes the completed or updated session into charging history.

These rollups are therefore best treated as UniFi session-history totals rather than utility-grade interval metering.

## Maximum output control

When an EV Station advertises the `set_max_output_amp` action, the integration exposes a Home Assistant **Maximum output** number entity.

Writes are sent through:

```text
PATCH /proxy/connect/api/v2/devices/{device_id}/status
```

with `args.maxOutput` expressed in amps.

### Limits

The integration only uses limits it can verify. The highest value the control offers is the lower of:

- the breaker-based limit from UniFi Connect metadata, when the console reports a breaker size (North American 80 % table);
- the **Maximum current per charger** option, if you set one.

If **neither** is known, the integration does not guess: the Maximum output control is locked, and no value is sent or re-sent to the charger. Set the option to the limit your electrician has approved for the circuit. The integration will never request more. EU chargers usually need this option.

If the verified limit is **below 6 A** (the lowest current a charger can signal), the integration never rounds it up to 6 A. It sends nothing, and the number entity reports why. Turn charging off instead. The options form only accepts 0 (not set) or 6 A and above.

The number entity's `verified_limit` and `limit_problem` attributes show the limit in use and, if the control is locked, why.

### How commands are sent (load-management safe)

The number entity shows the **desired** limit. The integration then decides when to send it:

- **Decreases are sent immediately.** Lowering current is always the safe direction.
- **Increases are rate limited** (default: at most one increase every 30 s), so automations cannot make the charger oscillate. A deferred increase is sent automatically by a later update.
- **The limit is re-sent periodically** (default every 300 s), and immediately after Home Assistant restarts, the console becomes reachable again, the telemetry stream reconnects, or a command fails. The EV Station Lite does not always report its active setpoint back, so re-sending is the only way to be sure the charger is where Home Assistant wants it.
- Every HTTP request gives up after 10 s, so a slow console is reported as a failure instead of blocking automations.
- **Home Assistant is in charge of the limit.** If you change the maximum output by hand in the UniFi app, the integration sets it back to Home Assistant's value at the next re-send (within 5 minutes by default). To change it, change the Home Assistant number entity, or turn your automation off first.

The **Maximum output pending** diagnostic sensor is on while the desired value has not been confirmed as sent (rate limited or failed). Its attributes show `desired`, `last_sent` and `last_error`. The number entity has the same attributes.

### EV Station Lite readback behavior

Some EV Station Lite firmware does not expose the current maximum-output value in the normal device shadow returned by the `/devices` endpoint. The integration therefore persists the desired value across restarts and re-asserts it as described above. If UniFi exposes a readback field, it is shown as the `reported_by_charger` attribute.

> [!IMPORTANT]
> Software load management is not a substitute for electrical protection. Also set a safe fixed limit in UniFi Connect (**Total Amps Available** / per-station maximum): if Home Assistant stops, the charger keeps its last setting.

## Live telemetry

Live charging measurements come from the local UniFi Connect WebSocket, the same event stream used by the Connect interface. This provides push updates for power, current, voltage, session energy, and session duration while the charger is streaming telemetry.

Historical charging and energy totals continue to come from the Connect REST API. No cloud polling is required.

If the WebSocket is disconnected, **Power**, **Current**, **Voltage** and **Session duration** become *unavailable* instead of reporting 0. A charger that is simply idle (stream connected, no frames for 90 s) still reports 0. The **Live telemetry** diagnostic sensor shows whether the stream is connected, so automations can stop trusting live values when it is off.

## Options

**Settings -> Devices & services -> UniFi EV Station -> Configure**:

| Option | Default | Meaning |
|---|---|---|
| Maximum current per charger | 0 (not set: use the breaker size from the console only) | Hard upper limit for the Maximum output control. Required if the console does not report a breaker size. 6 A or more. |
| Minimum time between current increases | 30 s | Rate limit for increases; decreases are never delayed |
| Re-send the current limit every | 300 s | Periodic re-assertion of the desired limit |
| Polling interval | 30 s | REST polling of devices and history |

If the console rejects the stored login (for example after a password change), Home Assistant asks you to sign in again instead of failing.

## Known limitations

- UniFi Connect's EV Station API is undocumented and may change without notice.
- Entity availability varies by model, firmware, and the actions/features advertised by UniFi Connect.
- Maximum-output readback is incomplete on some EV Station Lite firmware even though the write action is available.
- Energy Today and Month to Date combine completed session history with the live session meter. Cross-midnight/month sessions are split from the first boundary observed while Home Assistant is running.
- Charging-history freshness depends on when UniFi Connect records or updates a session.
- Controls discovered from `type.supportedActions` should be considered experimental until tested across more device and firmware combinations.

## Troubleshooting

Enable debug logging in Home Assistant:

```yaml
logger:
  logs:
    custom_components.unifi_ev_station: debug
```

Then inspect **Settings -> System -> Logs**.

When reporting an issue, useful details include:

- Home Assistant version
- UniFi OS version
- UniFi Connect version
- EV Station model
- EV Station firmware version
- Relevant debug log entries

Do not post UniFi session cookies, JWTs, passwords, or CSRF tokens in public issues.

## API documentation

See [API.md](API.md) for the reverse-engineered UniFi Connect EV Station API notes, observed request formats, and tested endpoints.

## Development / validation

The repository includes GitHub Actions for:

- HACS repository validation
- Home Assistant `hassfest` validation

Unit tests for the setpoint policy and current limits run with the standard library only:

```bash
python3 -m unittest discover tests
```

## License

MIT

## Release notes

### v1.1.0

Before relying on this version for load management, follow **[TESTING.md](TESTING.md)** on your own charger.

- **Verified current limits only:** the Maximum output control uses the console's breaker size and/or the new *Maximum current per charger* option. If neither is known, the control is locked and nothing is sent, instead of assuming a default. **Upgrade note:** if your console does not report a breaker size (common on EU chargers), set the option after upgrading, or the control stays locked.
- A limit below 6 A is never rounded up to 6 A; no setpoint is sent and the reason is shown on the entity.
- Manual changes in the UniFi app are overwritten by the next re-send; this is now documented.
- **Setpoint watchdog:** the desired limit is persisted and re-sent periodically, after restarts, after console outages, after telemetry reconnects and after failed commands.
- **Rate limiting:** decreases are sent immediately; increases are limited to one per configurable interval. Unchanged values are not re-sent on every automation run.
- **Request timeouts:** every HTTP call gives up after 10 s; network errors are reported as integration errors.
- **Telemetry state:** new *Live telemetry* diagnostic sensor. Live sensors become unavailable while the WebSocket is down instead of reporting 0.
- New *Maximum output pending* diagnostic sensor with `desired`, `last_sent` and `last_error` attributes.
- **Re-authentication flow** when the stored login stops working, and an **options flow** for limits and intervals.
- Logins are serialised so the WebSocket and polling never log in at the same time.
- Entity actions now raise Home Assistant errors with clear messages.
- Unit tests for the setpoint policy and limits. Removed the duplicate `Readme.md`.

### v1.0.1

- Fixed **Energy Today** for charging sessions that cross local midnight.
- Fixed **Energy Month to Date** for sessions that cross a month boundary.
- Live session energy is now split using the cumulative WebSocket `meter` value observed at the day/month boundary instead of assigning the entire active session to its start date.
- Preserves the post-boundary portion after UniFi moves the completed session into `chargingHistory`, preventing the daily total from dropping back to zero after session reconciliation.
- Persists completed cross-boundary adjustments across Home Assistant restarts.

### v1.0.0

- First stable release, promoted from the proven v0.1.8 feature set.
- **Energy Today** updates while a vehicle is actively charging instead of waiting for the session to finish.
- **Energy Month to Date** includes the current live charging session.
- **Session energy** is driven by the live `EV_POWER_STATS.meter` value.
- Added session reconciliation so the live meter is retained when charging stops and removed only after UniFi writes the completed session into `chargingHistory`.
- Handles EV Station Lite behavior where the live telemetry stream may stop without an explicit `streaming=false` message.

### v0.1.7

- Idle chargers now report **0 kW** and **0 A** instead of `Unknown`, keeping aggregate/combined power sensors stable.
- Added a 90-second live-telemetry staleness guard so a charger cannot remain stuck at its last non-zero power reading after streaming stops.
- Fixed **Charging status** so it reads `shadow.chargingStatus` when available, matches Connect's `Available` fallback when the field is absent, and reports `Charging` while live telemetry is actively streaming.

### v0.1.6

- Moved real-time EV telemetry to the UniFi Connect WebSocket instead of the unsupported `powerStats?current=true` REST request.
- Fixed live **Power** and **Current** remaining `Unknown` on EV Station Lite.
- Added live **Voltage**.
- Added live **Session energy** and **Session duration** from `EV_POWER_STATS` events.
- Added automatic WebSocket reconnect behavior while keeping REST polling for device metadata, history, and controls.

### v0.1.5

- Attempted support for a `powerStats?current=true` live-sample response shape. EV Station Lite was later confirmed to reject this request with HTTP 400; v0.1.6 replaces this approach with the Connect WebSocket.
- Historical `powerStats?current=false` list responses remain supported.

### v0.1.4

- Corrected **Maximum Output** limits to follow the EV Station breaker/output table: 20A→16A, 30A→24A, 40A→32A, 50A→40A, 60A→48A, 80A→64A, and 100A→80A.
- Removed `deratingMaxCurrent` as the Home Assistant slider cap; it is derating telemetry, not the configured circuit-breaker limit.
- Fixed Maximum Output readback so nested `supportedActions` argument/schema data cannot be mistaken for the current setpoint.
- Added optimistic last-known Maximum Output state after a successful `set_max_output_amp` command.
- Added Home Assistant state restoration so the last known Maximum Output survives restarts when EV Station Lite does not expose the current setpoint in `/devices`.

### v0.1.3

- Added writable **Maximum Output** Home Assistant number entities for chargers advertising `set_max_output_amp`.
- Uses each charger's runtime action UUID instead of hard-coding action identifiers.
- Sends maximum-output changes through the confirmed Connect device-status action API.
- Added breaker-aware maximum bounds for amperage controls when breaker metadata is available.
- Added fallback in-memory setpoint behavior for EV Station Lite devices that do not expose maximum-output readback in the device shadow.

### v0.1.2

- Added **Energy Today** per charger.
- Added **Energy Month to Date** per charger.
- Added local-timezone-aware energy rollups based on UniFi charging history.
- Added maximum-output discovery groundwork and exposed related device metadata where available.

### v0.1.1

- Fixed integration setup failures when an EV device does not support the optional UniFi Connect `powerStats` / Power Insight endpoint.
- Power and Current now become unavailable for unsupported devices instead of preventing the entire integration from loading.
- Charging history, status, energy statistics, and supported controls continue to load on those devices.

### v0.1.0

- Initial public prototype.
- Added local UniFi OS authentication using session cookies and CSRF tokens.
- Added automatic UniFi Connect EV Station discovery.
- Added live Power and Current sensors when supported.
- Added Charging status.
- Added Last session energy and charge-time sensors.
- Added Historical energy and Session count.
- Added rolling 7-day and 30-day energy sensors.
- Added **Allow charging** control based on UniFi-supported action descriptors.
