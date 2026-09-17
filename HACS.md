# Publishing UniFi EV Station through HACS

This guide is for the repository owner/maintainer.

## Repository structure

HACS expects an integration repository with a single integration beneath `custom_components/`.

Recommended layout:

```text
Unifi-EV-Lite-HomeAssistant/
├── README.md
├── API.md
├── HACS.md
├── hacs.json
├── .gitignore
└── custom_components/
    └── unifi_ev_station/
        ├── __init__.py
        ├── api.py
        ├── config_flow.py
        ├── const.py
        ├── coordinator.py
        ├── entity.py
        ├── manifest.json
        ├── sensor.py
        ├── strings.json
        ├── switch.py
        ├── brand/
        │   └── icon.png
        └── translations/
            └── en.json
```

## Before the first push

Replace every occurrence of:

```text
Woodhead02
```

with your real GitHub username.

If you choose a different repository name, also replace:

```text
Unifi-EV-Lite-HomeAssistant
```

where appropriate.

## GitHub repository settings

HACS requires a public GitHub repository.

Set a concise GitHub repository description, for example:

```text
Home Assistant integration for locally managed Ubiquiti UniFi Connect EV Stations.
```

Suggested GitHub topics:

```text
home-assistant
hacs
unifi
ubiquiti
unifi-connect
ev-charger
evse
home-automation
```

## hacs.json

The repository root should contain:

```json
{
  "name": "UniFi EV Station"
}
```

Additional HACS version constraints can be added later if needed.

## manifest.json

HACS expects the custom integration manifest to include at least:

```text
domain
documentation
issue_tracker
codeowners
name
version
```

The project manifest should therefore point to the public repository, for example:

```json
{
  "domain": "unifi_ev_station",
  "name": "UniFi EV Station",
  "codeowners": ["@Woodhead02"],
  "config_flow": true,
  "documentation": "https://github.com/Woodhead02/Unifi-EV-Lite-HomeAssistant#readme",
  "issue_tracker": "https://github.com/Woodhead02/Unifi-EV-Lite-HomeAssistant/issues",
  "integration_type": "hub",
  "iot_class": "local_polling",
  "requirements": [],
  "version": "0.1.0"
}
```

## Brand asset

HACS requires a brand asset for an integration repository.

Add at least:

```text
custom_components/unifi_ev_station/brand/icon.png
```

Use an icon you have the right to distribute. Avoid copying Ubiquiti trademarks or artwork unless the applicable license/permission allows it.

## Git initialization

From the repository root:

```bash
git init
git add .
git commit -m "Initial UniFi EV Station Home Assistant integration"
git branch -M main
git remote add origin https://github.com/Woodhead02/Unifi-EV-Lite-HomeAssistant.git
git push -u origin main
```

## Installing your own repository through HACS

You do not have to wait for the repository to be accepted into HACS's default repository list.

In Home Assistant:

1. Open **HACS**.
2. Open the menu.
3. Choose **Custom repositories**.
4. Enter:

   ```text
   https://github.com/Woodhead02/Unifi-EV-Lite-HomeAssistant
   ```

5. Select **Integration**.
6. Add the repository.
7. Install **UniFi EV Station**.
8. Restart Home Assistant.
9. Add the integration from **Settings -> Devices & services**.

## Releases

GitHub releases are optional for HACS, but they are recommended for a public integration.

For the first release:

```bash
git tag v0.1.0
git push origin v0.1.0
```

Then create a GitHub Release for `v0.1.0`.

Keep the version in:

```text
custom_components/unifi_ev_station/manifest.json
```

aligned with the software release version.

A simple release progression could be:

```text
v0.1.0 - Initial public prototype
v0.2.0 - Additional controls and Energy Dashboard improvements
v0.3.0 - Diagnostics and broader EV Station model support
```

## Validate before release

Before creating a release, verify:

- Home Assistant can install the integration through HACS.
- The config flow completes with a dedicated local UniFi account.
- EV Stations are discovered correctly.
- Charging-history sensors populate.
- Live power/current sensors populate while charging.
- Controls only appear when UniFi advertises the corresponding supported action.
- No credentials, cookies, CSRF tokens, private IP details from captures, or personal charging/payment data are committed.
- `__pycache__`, `.pyc`, `.DS_Store`, and development secrets are excluded.

## Optional: submit to the default HACS repository list

A custom repository can be installed manually through HACS without being added to HACS's default list.

If you later want broader discovery, follow the current HACS process for submitting a repository to the default list after the integration is stable and the repository satisfies HACS publishing requirements.

## Suggested public-repository checklist

- [x] GitHub owner set to `Woodhead02`.
- [x] Repository set to `Woodhead02/Unifi-EV-Lite-HomeAssistant`.
- [ ] Add `brand/icon.png`.
- [ ] Choose and add a license.
- [ ] Enable GitHub Issues.
- [ ] Add repository description.
- [ ] Add GitHub topics.
- [ ] Review README security/disclaimer language.
- [ ] Verify no secrets exist in Git history.
- [ ] Push to GitHub.
- [ ] Add as a HACS custom repository.
- [ ] Install on a test Home Assistant instance.
- [ ] Publish `v0.1.0` when ready.
