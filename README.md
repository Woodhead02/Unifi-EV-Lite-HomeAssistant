# UniFi EV Station for Home Assistant

A local Home Assistant custom integration for UniFi Connect EV Stations managed by a UniFi OS console.

> **Status:** Early but functional. This integration uses observed, undocumented UniFi Connect API behavior. Ubiquiti may change these endpoints or payloads in future UniFi releases.

## Features

- Authenticates directly to a local UniFi OS console with a local UniFi account.
- Uses the UniFi OS session cookie and CSRF-token flow used by the local console.
- Discovers UniFi Connect EV Stations automatically.
- Reads live charging power and current when the charger supports UniFi Connect Power Insight.
- Reads charging-session history and exposes per-charger energy/session statistics.
- Exposes charging status.
- Provides daily and month-to-date energy rollups from charging history.
- Creates an **Allow charging** switch when the charger advertises the relevant supported actions.
- Creates a writable **Maximum output** control when the charger advertises the `set_max_output_amp` action.
- Uses the supported-action descriptors returned by UniFi instead of hard-coding per-device action UUIDs.
- Continues loading devices that do not support the optional `powerStats` endpoint.

## Home Assistant entities

Per detected charger, the integration currently creates the following entities when supported by that device.

### Live telemetry

- **Power** — current charging power in kW.
- **Current** — current draw in A.
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

## Power Insight support

Not every EV Station exposes the Connect `powerStats` endpoint.

If UniFi returns an error such as:

```text
device does not support power insight
```

the integration will continue to load that charger. The **Power** and **Current** sensors will simply be unavailable while charging history, status, energy rollups, and supported controls continue to work.

## Known limitations

- UniFi Connect's EV Station API is undocumented and may change without notice.
- Entity availability varies by model, firmware, and the actions/features advertised by UniFi Connect.
- Live Power and Current require Connect Power Insight support on the device.
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

### v0.1.5

- Fixed live **Power** and **Current** sensors showing `Unknown`.
- Correctly handles the UniFi Connect `powerStats?current=true` response when `data` is a single live-sample object rather than a list.
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
