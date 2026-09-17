 UniFi EV Station for Home Assistant

A custom Home Assistant integration for locally managed Ubiquiti UniFi Connect EV Stations.

This integration connects directly to a UniFi OS console, such as a Dream Machine, authenticates with a local UniFi account, discovers EV Stations managed by UniFi Connect, and exposes charging data and controls to Home Assistant.

> [!IMPORTANT]
> This is an independent community project. It is not affiliated with, endorsed by, or supported by Ubiquiti Inc. The UniFi Connect API used by this integration is undocumented and may change between UniFi Connect releases.

## Features

- Local communication with your UniFi OS console.
- UI-based configuration through Home Assistant.
- Automatic discovery of UniFi Connect EV Stations.
- Charging-session history.
- Live or recent power and current readings when exposed by the charger.
- Per-charger energy totals.
- 7-day and 30-day energy totals.
- Session count and last-session statistics.
- Charging status.
- Charging enable/disable control when the corresponding action is advertised by UniFi Connect.
- Uses the action descriptors returned by UniFi instead of hard-coding action UUIDs.

## Confirmed devices

Development and testing have been performed with UniFi EV Station Lite hardware managed by UniFi Connect.

Known connector/device examples include:

- J1773 EV Station Lite

Other UniFi Connect EV Station models may work, but are not yet confirmed.

## Installation with HACS

Until this integration is included in the default HACS repository list, add it as a custom repository.

1. Install HACS if you have not already done so.
2. In Home Assistant, open **HACS**.
3. Open the HACS menu and choose **Custom repositories**.
4. Add this GitHub repository URL:

   ```text
   https://github.com/Woodhead02/unifi-ev-station-ha
   ```

5. Select **Integration** as the repository type.
6. Find **UniFi EV Station** in HACS and install it.
7. Restart Home Assistant.
8. Go to **Settings -> Devices & services -> Add Integration**.
9. Search for **UniFi EV Station**.

See [HACS.md](HACS.md) for repository-owner setup and publishing notes.

## Manual installation

Copy:

```text
custom_components/unifi_ev_station/
```

into your Home Assistant configuration directory:

```text
/config/custom_components/unifi_ev_station/
```

Restart Home Assistant, then add the integration from **Settings -> Devices & services**.

## Configuration

Use the local address of your UniFi OS console, for example:

```text
https://192.168.1.1
```

Use a **local UniFi OS account**, not a ui.com cloud/SSO-only account.

If your console uses its default self-signed certificate, disable SSL certificate verification when prompted by the integration.

### Recommended account setup

Create a dedicated local UniFi account for Home Assistant instead of using your primary administrator account.

The account needs enough permission to:

- Read UniFi Connect devices.
- Read EV Station statistics and charging history.
- Read power statistics.
- Modify EV Station status if charging controls are desired.

The minimum practical UniFi Connect permission set has not yet been fully characterized. Start with a dedicated account that can manage Connect, verify functionality, and then reduce privileges as appropriate for your environment.

## Entities

The exact entities depend on what each charger and UniFi Connect version expose.

Current integration entities include or may include:

| Entity | Unit | Description |
| --- | --- | --- |
| Power | kW | Current/recent charging power |
| Current | A | Current/recent charging current |
| Charging status | - | Charger state reported by UniFi Connect |
| Last session energy | kWh | Energy delivered during the latest session |
| Last session charge time | time | Active charging duration |
| Historical energy | kWh | Total energy from retrieved charging history |
| Session count | sessions | Number of retrieved charging sessions |
| 7-day energy | kWh | Energy delivered during the previous seven days |
| 30-day energy | kWh | Energy delivered during the previous thirty days |
| Allow charging | switch | Enables/disables charging when supported |

## Data sources

The integration currently uses locally proxied UniFi Connect endpoints including:

```text
GET   /proxy/connect/api/v2/devices
GET   /proxy/connect/api/v2/devices/{device_id}/powerStats
GET   /proxy/connect/api/v2/stats/evs/chargingHistory
PATCH /proxy/connect/api/v2/devices/{device_id}/status
```

See [API.md](API.md) for the reverse-engineered API notes and examples.

## Authentication

The integration authenticates to the local UniFi OS console rather than storing browser session tokens.

At a high level:

```text
GET /
POST /api/auth/login
    -> UniFi OS session cookie
    -> CSRF token
GET/PATCH /proxy/connect/api/v2/...
```

A matching session cookie and CSRF token are used for protected requests. Session credentials remain local to Home Assistant and the UniFi console.

## Troubleshooting

### The integration cannot log in

Confirm that:

- The username is a local UniFi OS user.
- The account can sign in directly to the console's local IP address.
- The URL is the console itself, for example `https://192.168.1.1`.
- SSL verification is disabled if the console uses a self-signed certificate.

### No EV Stations appear

Confirm the charger is visible in the UniFi Connect application on the same console.

You can also inspect this endpoint while logged into the console:

```text
https://CONSOLE_IP/proxy/connect/api/v2/devices
```

### Enable debug logging

Add this to `configuration.yaml`:

```yaml
logger:
  logs:
    custom_components.unifi_ev_station: debug
```

Restart Home Assistant and inspect the logs under **Settings -> System -> Logs**.

## Security

- Use a dedicated local UniFi account for Home Assistant.
- Do not publish UniFi session cookies, CSRF tokens, passwords, or captured authorization data in GitHub issues.
- Do not copy browser session tokens into Home Assistant configuration.
- Prefer local access to the UniFi console rather than routing integration traffic through the public internet.

If you submit an issue, redact:

```text
Cookie
TOKEN
UOS_TOKEN
Authorization
X-CSRF-Token
passwords
public IP addresses
```

## API documentation

Reverse-engineered UniFi Connect API information collected during development is documented in [API.md](API.md).

The API documentation distinguishes between endpoints that have been directly observed and behavior that is still inferred or under investigation.

## Development status

This project is early-stage software. The underlying UniFi Connect API is not publicly documented by Ubiquiti and could change without notice.

Areas still being developed include:

- Broader EV Station model testing.
- Minimum-permission account guidance.
- Additional supported actions.
- Improved Energy Dashboard integration.
- Diagnostics.
- Automated tests against recorded/sanitized API fixtures.

## Contributing

Bug reports, sanitized API observations, and pull requests are welcome.

When reporting an API difference, useful information includes:

- UniFi OS version.
- UniFi Connect version.
- EV Station model.
- Sanitized endpoint path.
- Sanitized request payload.
- Sanitized response schema.

Never include credentials, cookies, CSRF tokens, or personally identifying charging/payment data.
