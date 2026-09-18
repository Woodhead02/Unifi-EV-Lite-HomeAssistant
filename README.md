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

- A session that crosses midnight is attributed according to the timestamp UniFi records for that session rather than being split across calendar days.
- An active charging session may not be included until UniFi writes the completed or updated session into charging history.

These rollups are therefore best treated as UniFi session-history totals rather than utility-grade interval metering.

## Maximum output control

When an EV Station advertises the `set_max_output_amp` action, the integration exposes a Home Assistant **Maximum output** number entity.

Writes are sent through:

```text
PATCH /proxy/connect/api/v2/devices/{device_id}/status
```

with `args.maxOutput` expressed in amps.

The integration uses breaker metadata, when available, to establish a sensible upper bound for the control.

### EV Station Lite readback behavior

Some EV Station Lite firmware does not expose the current maximum-output value in the normal device shadow returned by the `/devices` endpoint. In that case:

- The control can still write a new amperage value if `set_max_output_amp` is advertised.
- The number entity may initially have an unknown state after a fresh Home Assistant restart.
- After a value is set through Home Assistant, the integration keeps the latest setpoint in memory for the running session.

If UniFi exposes a reliable readback field in a future firmware/API version, the integration can be updated to use it.

## Live telemetry

Live charging measurements come from the local UniFi Connect WebSocket, the same event stream used by the Connect interface. This provides push updates for power, current, voltage, session energy, and session duration while the charger is streaming telemetry.

Historical charging and energy totals continue to come from the Connect REST API. No cloud polling is required.

## Known limitations

- UniFi Connect's EV Station API is undocumented and may change without notice.
- Entity availability varies by model, firmware, and the actions/features advertised by UniFi Connect.
- Maximum-output readback is incomplete on some EV Station Lite firmware even though the write action is available.
- Energy Today and Month to Date are derived from session history, not sub-session interval metering.
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

## License

MIT

## Release notes

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
