# `doc/` — Technical documentation

User-facing documentation (install, setup, services, troubleshooting)
lives in the top-level [`README.md`](../README.md). This directory is
intentionally minimal: research notes, reverse-engineering artefacts,
and vendor copyrighted materials have been removed for legal reasons
(see [Why this directory is minimal](#why-this-directory-is-minimal)
below).

The integration code is the authoritative reference for protocol
details. Cross-references that used to point into research files now
point into the source tree:

| Topic | Where to look in the code |
|---|---|
| API endpoints used | `custom_components/powerocean_dev/api.py` |
| Authentication + region detection | `api.py::async_authorize`, `async_authorize_only` |
| Write-side parameter names | `custom_components/powerocean_dev/const.py` (`PARAM_*`) |
| OCPP request/response shapes | `custom_components/powerocean_dev/__init__.py::_build_ocpp_bind_req` and `services.yaml` |
| Sub-device detection (Battery, PowerPulse, PowerGlow) | `custom_components/powerocean_dev/utils.py::BOX_SCHEMAS` |
| Sensor/binary-sensor friendly names | `custom_components/powerocean_dev/strings.json` |
| Architectural model (PowerOcean ⇄ children) | `custom_components/powerocean_dev/parser.py` |

---

## Architecture quick-reference

The EcoFlow consumer cloud treats PowerPulse and PowerGlow as
**children** of a PowerOcean inverter. There is no standalone polling
path:

```
EcoFlow account
└── PowerOcean inverter (AC305)        ← polled by SN
    ├── Battery 1
    ├── Battery 2
    ├── PowerGlow heating rod          ← child, polled via inverter
    └── PowerPulse 11 kW (JT303/CP307) ← child, polled via inverter
```

The integration mirrors this in the HA device tree: each child gets
its own HA device with `via_device` pointing at the inverter, so
entities are grouped on the device the user expects.

The OCPP services in this integration manage the EcoFlow-side OCPP
backend catalog for PowerPulse. The runtime handover (proto
`vendorInfoSet`) is not yet wired up — see the in-code comments next
to the service handlers in `__init__.py` for status.

---

## Why this directory is minimal

The previous contents of this directory included:

- A decompiled copy of the EcoFlow Android APK (UrhG / German
  copyright concern when redistributed).
- Markdown documents that were derivative works of the decompile
  (`apk.md`, `apk-logs.md`, `ocpp-investigation.md`).
- Verbatim source extracts under `logs/raw_*.txt`.
- Vendor PDFs (`geninfo.pdf`, `powerocean.pdf`).
- A vendor sample-code archive (`ecoflow-open-demo.zip`).
- A reference-installation file containing a real personal name and
  device serial numbers (`equipment.md` — DSGVO/GDPR personal data).
- A refactor implementation log referencing the same personal data.

Those files have been removed from the working tree. Note that **`git
rm` does not purge history**: anyone with clone access can still
retrieve the deleted blobs from prior commits. If full removal is
required, use `git filter-repo` (or `git filter-branch`) on a fresh
clone and force-push, then ask collaborators to re-clone.

The integration itself remains fully functional without any of the
removed files: the API field names and OCPP request schema needed at
runtime are inlined in the code (`const.py`, `__init__.py`,
`services.yaml`).
