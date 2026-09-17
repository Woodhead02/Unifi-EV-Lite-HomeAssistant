# UniFi EV Station for Home Assistant

A local Home Assistant custom integration for UniFi Connect EV Stations managed by a UniFi OS console.

> **Status:** Early prototype. The API used by this integration is observed/undocumented UniFi Connect behavior and may change between UniFi releases.

## Features

- Authenticates directly to a local UniFi OS console with a local UniFi account.
- Discovers EV Stations from UniFi Connect.
- Reads live charging power and current.
- Reads charging-session history and exposes per-charger energy/session statistics.
- Exposes charging status.
- Creates an **Allow charging** switch when the charger advertises the relevant supported actions.
- Uses the action descriptors returned by UniFi instead of hard-coding per-device action UUIDs.

## Home Assistant entities

Per detected charger, the integration currently creates:

- Power (kW)
- Current (A)
- Charging status
- Last session energy (kWh)
- Last session charge time
- Historical energy (kWh)
- Session count
- Energy in the last 7 days (kWh)
- Energy in the last 30 days (kWh)
- Allow charging switch, when supported by the device

## Installation with HACS

This repository can be installed as a HACS custom repository.

1. Open **HACS** in Home Assistant.
2. Open the HACS menu and choose **Custom repositories**.
3. Add this GitHub repository URL.
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

```text
POST /api/auth/login
GET  /proxy/connect/api/v2/devices
GET  /proxy/connect/api/v2/devices/{device_id}/powerStats
GET  /proxy/connect/api/v2/stats/evs/chargingHistory
PATCH /proxy/connect/api/v2/devices/{device_id}/status
```

The client maintains the UniFi OS session cookie and CSRF token required by the console.

## Known limitations

- UniFi Connect's EV Station API is not publicly documented by Ubiquiti.
- Charging controls depend on the actions advertised in `type.supportedActions` by the charger/controller.
- `enable_charging` has been observed and tested. Other controls should be treated as experimental until independently validated.
- Charging history is refreshed every five minutes; live device data is polled more frequently.

## Troubleshooting

Enable debug logging:

```yaml
logger:
  logs:
    custom_components.unifi_ev_station: debug
```

Then inspect **Settings -> System -> Logs**.

## Development / validation

The repository includes GitHub Actions for:

- HACS repository validation
- Home Assistant `hassfest` validation

## License

MIT
