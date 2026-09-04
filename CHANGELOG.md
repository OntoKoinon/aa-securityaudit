# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.0.0] - 2026-09-04

Initial public release.

### Added

- Comprehensive security audit engine for AllianceAuth using MemberAudit data.
- Awoxing / friendly-fire detection with damage ownership, tackle contribution,
  HIC pilot, and blue-scouting analysis. Automatic exclusion of large-fleet
  crossfire, killmail whoring, structure bashes, and sparring in throwaway ships.
- Undisclosed alt detection via corp-history overlap analysis with configurable
  rule thresholds.
- Spy activity / enemy collusion detection from killmail participation.
- Flight-risk detection based on corporation-hopping frequency.
- Enemy connections flagging against a configurable enemy list.
- +10 standing contact checks against hostiles and blacklisted entities.
- Blacklist adjacency correlation with `allianceauth-blacklist`.
- Suspicious ISK movement detection: large donations, free contracts, and
  repeated transfers, with a financial-exceptions whitelist.
- Capital and supercapital ship observation tracking from zKill and MemberAudit
  asset / current-ship data.
- Automated new-join audits with a configurable lookback window.
- Manual per-character and per-corporation audits with per-run option toggles
  and per-run threshold overrides.
- Time-limited shareable summary links for leadership review.
- Real-time audit progress updates on the detail page.
- Policy Editor for all thresholds and master switches.
- Enemy List management page.
- Financial Exceptions management.
- Dark-mode-first UI built on Bootstrap 5.
- AllianceAuth 5 compatibility template forwarding to `base-bs5.html`.
- Auto-registered URL routing via the AllianceAuth `url_hook`.
