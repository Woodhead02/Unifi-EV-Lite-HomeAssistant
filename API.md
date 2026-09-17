# UniFi Connect EV Station API Notes

This document describes the UniFi Connect EV Station API behavior observed while developing the **UniFi EV Station for Home Assistant** integration.

> [!WARNING]
> This is an unofficial, reverse-engineered API guide. Ubiquiti does not currently publish this as a supported public EV Station API. Endpoints, fields, authentication behavior, and action names may change between UniFi OS or UniFi Connect releases.

## Scope

These notes cover a UniFi EV Station managed by the **UniFi Connect** application running on a local UniFi OS console such as a Dream Machine.

The observed architecture is:

```text
Client / Home Assistant
        |
        v
Local UniFi OS console
        |
        +-- UniFi Connect API
        |
        v
EV Station
```

The browser-facing local Connect API is proxied through UniFi OS under:

```text
/proxy/connect/api/v2
```

## Authentication

### Login endpoint

Observed local UniFi OS login flow:

```http
POST /api/auth/login
Content-Type: application/json
```

Example request body:

```json
{
  "username": "homeassistant",
  "password": "REDACTED",
  "remember": true,
  "rememberMe": true
}
```

A client should maintain the returned UniFi OS session cookie. Current UniFi OS versions may use cookie names such as:

```text
TOKEN
UOS_TOKEN
```

Protected requests may also require a CSRF token sent as:

```http
X-CSRF-Token: <token>
```

The token may be returned in response headers such as:

```text
X-CSRF-Token
X-Updated-CSRF-Token
```

Some UniFi OS session JWTs also contain a `csrfToken` claim. Clients should prefer the token returned by the console and should be prepared for CSRF tokens to rotate.

### Session guidance

A robust client should:

1. Create a persistent HTTP session/cookie jar.
2. Request the console root to establish initial session/CSRF state if needed.
3. POST credentials to `/api/auth/login`.
4. Retain the returned session cookie.
5. Retain the current CSRF token.
6. Send the CSRF token on protected requests.
7. Capture an updated CSRF token from later responses.
8. Re-authenticate when the session expires.

Do **not** hard-code a browser cookie or CSRF token into an application.

## Device inventory

### Request

```http
GET /proxy/connect/api/v2/devices
```

### Purpose

Returns devices known to UniFi Connect. EV Station records can contain charger state, model information, feature flags, shadow state, and supported action descriptors.

### Useful EV Station fields observed

Depending on firmware/model/version, useful fields may include:

```text
id
name
mac
model
chargingStatus
chargingSession
evStationMode
maxOutput
derating
errorInfo
shadow
relayShadow
type.supportedActions
```

Observed relay shadow fields include:

```text
relayShadow.enabledCharing
relayShadow.evStationMode
relayShadow.displayLabel
relayShadow.adminMessage
```

`enabledCharing` is intentionally shown with the spelling observed in UniFi frontend data/code.

## Supported actions

EV Station controls appear to be data-driven.

The device record can advertise action descriptors under:

```text
type.supportedActions
```

An observed descriptor has the general form:

```json
{
  "id": "ACTION-UUID",
  "name": "enable_charging",
  "args": {}
}
```

Clients should use the action descriptor returned for the specific device rather than hard-coding action UUIDs.

## Execute a device action

### Request

```http
PATCH /proxy/connect/api/v2/devices/{device_id}/status
Content-Type: application/json; charset=utf-8
X-CSRF-Token: <current token>
```

### Confirmed example: enable charging

```json
{
  "id": "ACTION-UUID-FROM-SUPPORTED-ACTIONS",
  "name": "enable_charging",
  "args": {}
}
```

A successful request has been observed returning:

```text
HTTP 200 OK
```

The action UUID is device/action metadata and should not be copied from another installation.

### Generic action pattern

```json
{
  "id": "<action.id>",
  "name": "<action.name>",
  "category": "<action.category-if-present>",
  "args": {}
}
```

Only include fields actually supplied or required by the action descriptor.

## Power statistics

### Request

```http
GET /proxy/connect/api/v2/devices/{device_id}/powerStats?interval=15m&current=false
```

Parameters observed:

| Parameter | Example | Meaning |
| --- | --- | --- |
| `interval` | `15m` | Requested aggregation/sample interval |
| `current` | `false` | Historical samples when false; current/recent behavior when true |
| `port` | implementation-specific | Optional port selector in frontend code |

### Example response shape

```json
{
  "err": null,
  "type": "collection",
  "data": [
    {
      "dataTime": 1789609899,
      "instantMA": 47629.3,
      "instantMW": 11632
    }
  ]
}
```

### Field interpretation

Observed values strongly indicate:

| Field | Interpretation |
| --- | --- |
| `dataTime` | Unix timestamp, seconds |
| `instantMA` | Current in milliamps |
| `instantMW` | Power value numerically behaving as watts |

Example conversion:

```text
47629.3 / 1000 = 47.6293 A
11632 / 1000 = 11.632 kW
```

The name `instantMW` is retained exactly as observed. Despite the name, observed values are consistent with watts when converted to kW by dividing by 1000.

Because this API is undocumented, applications should avoid treating this interpretation as revenue-grade metering without independent validation.

## Charging history

### Request

```http
GET /proxy/connect/api/v2/stats/evs/chargingHistory?offset=0&limit=50
```

### Observed fields

Charging-history rows have included:

```text
accountId
chargeTime
currency
date
deviceName
groupName
id
idleTime
mac
maxPowerRate
model
powerUsage
pricePerUnit
pricingMode
qrCodeName
revenue
totalTime
transactionId
transactionStatus
usageMode
```

### Confirmed/strongly supported interpretations

| Field | Interpretation |
| --- | --- |
| `date` | Unix timestamp in seconds |
| `deviceName` | UniFi Connect device name |
| `mac` | EV Station MAC address |
| `model` | EV Station model |
| `powerUsage` | Energy delivered, observed as kWh |
| `chargeTime` | Active charging time in seconds |
| `idleTime` | Plugged-in/non-charging time in seconds |
| `totalTime` | Total session duration in seconds |
| `usageMode` | Charging/access mode, e.g. `plugAndCharge` |

Observed records satisfy:

```text
chargeTime + idleTime = totalTime
```

Example calculation of average active charging power:

```text
average kW = powerUsage / (chargeTime / 3600)
```

### Pagination

Observed query parameters:

```text
offset
limit
sort
order
```

A client should paginate rather than assume the entire history fits in a single response.

## Charging-history CSV export

The UniFi Connect frontend contains support for an export endpoint of the form:

```http
GET /proxy/connect/api/v2/stats/evs/chargingHistory/export?format=csv
```

Additional observed query parameters include:

```text
sort
order
```

This endpoint should be treated as **observed in frontend code** unless independently tested on the target console/version.

## EV statistics endpoint

The UniFi Connect frontend contains an EV statistics request of the form:

```http
POST /proxy/connect/api/v2/stats/evs/statistics
```

Observed request fields include combinations of:

```text
mac
start
end
pStart
pEnd
timeUnit
types
```

Observed statistic type names include:

```text
energyDelivered
chargingSessions
revenue
chargingTime
sessionTime
avgEnergyDelivered
```

Observed ranking type names include:

```text
energyRankingEVS
energyRankingUser
energyRankingQrCode
```

Observed time units include:

```text
hours
days
```

This endpoint is currently considered **frontend-derived** rather than fully integration-tested.

## Historic EV Station devices

Frontend code indicates:

```http
GET /proxy/connect/api/v2/stats/evs/historicDevices
```

This endpoint has not yet been fully characterized by this project.

## Device configuration

Frontend code indicates a general configuration endpoint:

```http
PUT /proxy/connect/api/v2/devices/{device_id}
```

with a configuration payload supplied by UniFi Connect.

Do not blindly replay or invent configuration fields. Capture the request produced by the official UI for the specific setting and device first.

## Other device endpoints observed in the frontend

These paths have been identified in UniFi Connect frontend behavior/code:

```text
POST  /proxy/connect/api/v2/devices/update
POST  /proxy/connect/api/v2/devices/{device_id}/setupConfig
PATCH /proxy/connect/api/v2/devices/status?group={group_id}
```

They are not required for the current Home Assistant integration and have not been exhaustively tested.

## EV Station system settings observed

Frontend code contains EV Station system routes corresponding to:

```text
PUT    /proxy/connect/api/v2/system/evstation/businessInfo
DELETE /proxy/connect/api/v2/system/evstation/businessInfo
PUT    /proxy/connect/api/v2/system/evstation/chargingFee
```

Payment-related functionality also exists in the frontend. This project does not currently use or test payment configuration endpoints.

## Charging states observed

UniFi frontend strings/code have exposed states including:

```text
Available
CableConnected
CableDisconnected
ChargeComplete
ChargeStopped
Charging
ChargingStopped
Error
Locked
Unavailable
```

Exact wire values and capitalization should be taken from the device response rather than assumed from UI labels.

## Example: read charging history with JavaScript

Run from an authenticated local UniFi OS browser session:

```js
const response = await fetch(
  '/proxy/connect/api/v2/stats/evs/chargingHistory?offset=0&limit=50',
  { credentials: 'include' }
);

if (!response.ok) {
  throw new Error(`HTTP ${response.status}: ${await response.text()}`);
}

const result = await response.json();
console.table(result.data ?? result);
```

## Example: read power statistics with JavaScript

```js
const deviceId = 'YOUR_DEVICE_ID';

const response = await fetch(
  `/proxy/connect/api/v2/devices/${deviceId}/powerStats?interval=15m&current=false`,
  { credentials: 'include' }
);

const result = await response.json();
console.log(result);
```

## Example: execute an advertised action

This example assumes the caller already has the current CSRF token for its authenticated UniFi OS session.

```js
const deviceId = 'YOUR_DEVICE_ID';
const csrfToken = 'CURRENT_SESSION_CSRF_TOKEN';

const action = {
  id: 'ACTION_UUID_RETURNED_BY_UNIFI',
  name: 'enable_charging',
  args: {}
};

const response = await fetch(
  `/proxy/connect/api/v2/devices/${deviceId}/status`,
  {
    method: 'PATCH',
    credentials: 'include',
    headers: {
      'Content-Type': 'application/json; charset=utf-8',
      'X-CSRF-Token': csrfToken
    },
    body: JSON.stringify(action)
  }
);

console.log(response.status, await response.text());
```

## Security notes for API research

When sharing captures or filing issues, redact:

```text
Cookie headers
TOKEN / UOS_TOKEN values
Authorization headers
X-CSRF-Token values
passwords
account identifiers that are not required for troubleshooting
payment/transaction data
public IP addresses
```

If an authentication token is accidentally published, invalidate the session and rotate any affected credentials.

## Compatibility

This API is not guaranteed stable. When reporting a change, include:

- UniFi OS version.
- UniFi Connect version.
- EV Station model.
- Whether the endpoint was observed directly or inferred from frontend code.
- Sanitized request and response examples.

## Endpoint status summary

| Endpoint | Status in this project |
| --- | --- |
| `POST /api/auth/login` | Used by integration |
| `GET /proxy/connect/api/v2/devices` | Used by integration |
| `GET /proxy/connect/api/v2/devices/{id}/powerStats` | Tested/used |
| `GET /proxy/connect/api/v2/stats/evs/chargingHistory` | Tested/used |
| `PATCH /proxy/connect/api/v2/devices/{id}/status` | Tested; `enable_charging` confirmed |
| `GET .../chargingHistory/export` | Found in frontend code |
| `POST .../stats/evs/statistics` | Found in frontend code |
| `GET .../stats/evs/historicDevices` | Found in frontend code |
| EV Station system/payment endpoints | Found in frontend code; not used |

