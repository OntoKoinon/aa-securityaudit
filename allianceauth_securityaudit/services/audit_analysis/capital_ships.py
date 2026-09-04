"""Capital/super/titan ship inventory helpers.

Tracks which capital hulls (carriers, dreadnoughts, force auxiliaries,
supercarriers, and titans) an audit subject's main and alts have been
observed flying in zkill killmails.
"""

from datetime import datetime
from django.utils import timezone

from ...models import AuditCapitalShipObservation


# Static registry of capital/super/titan hull type IDs. These are stable,
# well-known EVE Online type IDs verified against ESI and do not require
# ESI lookups at runtime. Special/limited edition reskins (Interbus, Justice,
# Wiyrkomi, Sarum editions) are excluded since they are cosmetic variants of
# the T1 hulls.
CAPITAL_SHIPS = {
    # --- Carriers (group 547) ---
    23757: ("carrier", "Archon"),
    23911: ("carrier", "Thanatos"),
    23915: ("carrier", "Chimera"),
    24483: ("carrier", "Nidhoggur"),
    # Faction carrier
    42132: ("carrier", "Vanguard"),
    # --- T2 Command Carriers (group 5120) ---
    92822: ("carrier", "Salvation"),
    92823: ("carrier", "Simurgh"),
    92824: ("carrier", "Gaia"),
    92825: ("carrier", "Ymir"),
    # --- Dreadnoughts (group 485) ---
    19720: ("dread", "Revelation"),
    19722: ("dread", "Naglfar"),
    19724: ("dread", "Moros"),
    19726: ("dread", "Phoenix"),
    # Faction dreadnoughts (navy)
    73787: ("dread", "Naglfar Fleet Issue"),
    73790: ("dread", "Revelation Navy Issue"),
    73792: ("dread", "Moros Navy Issue"),
    73793: ("dread", "Phoenix Navy Issue"),
    # Faction dreadnoughts (pirate)
    42124: ("dread", "Vehement"),
    42243: ("dread", "Chemosh"),
    45647: ("dread", "Caiman"),
    87381: ("dread", "Sarathiel"),
    # Precursor dreadnought
    52907: ("dread", "Zirnitra"),
    # --- T2 Lancer Dreadnoughts (group 4594) ---
    77281: ("dread", "Hubris"),
    77283: ("dread", "Bane"),
    77284: ("dread", "Karura"),
    77288: ("dread", "Valravn"),
    # --- Force Auxiliaries (group 1538) ---
    37604: ("fax", "Apostle"),
    37605: ("fax", "Minokawa"),
    37606: ("fax", "Lif"),
    37607: ("fax", "Ninazu"),
    # Faction force auxiliaries
    42133: ("fax", "Venerable"),
    42242: ("fax", "Dagon"),
    45645: ("fax", "Loggerhead"),
    # --- Supercarriers (group 659) ---
    22852: ("supercarrier", "Hel"),
    23913: ("supercarrier", "Nyx"),
    23917: ("supercarrier", "Wyvern"),
    23919: ("supercarrier", "Aeon"),
    3514: ("supercarrier", "Revenant"),
    # Faction supercarrier
    42125: ("supercarrier", "Vendetta"),
    # --- Titans (group 30) ---
    671: ("titan", "Erebus"),
    3764: ("titan", "Leviathan"),
    11567: ("titan", "Avatar"),
    23773: ("titan", "Ragnarok"),
    # Faction titans
    42126: ("titan", "Vanquisher"),
    42241: ("titan", "Molok"),
    45649: ("titan", "Komodo"),
    78576: ("titan", "Azariel"),
}

# EVE ship inventory group IDs that contain capital hulls we care about.
# Used to query zKill by group for more targeted loss lookups.
CAPITAL_SHIP_GROUPS = [30, 485, 4594, 5120, 547, 659, 1538]

# Map category -> list of group IDs (for reference/display ordering).
CATEGORY_TO_GROUPS = {
    "carrier": [547, 5120],
    "dread": [485, 4594],
    "fax": [1538],
    "supercarrier": [659],
    "titan": [30],
}

CATEGORY_ORDER = ["titan", "supercarrier", "fax", "dread", "carrier"]
CATEGORY_LABELS = {
    "carrier": "Carriers",
    "dread": "Dreadnoughts",
    "fax": "Force Auxiliaries",
    "supercarrier": "Supercarriers",
    "titan": "Titans",
}

GROUP_TO_CATEGORY = {
    547: "carrier",
    5120: "carrier",
    485: "dread",
    4594: "dread",
    1538: "fax",
    659: "supercarrier",
    30: "titan",
}


def ship_image_url(type_id, size=128):
    return f"https://images.evetech.net/types/{type_id}/render?size={size}"


def _parse_kill_time(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None


def _category_from_group(group_id):
    try:
        return GROUP_TO_CATEGORY.get(int(group_id))
    except (TypeError, ValueError):
        return None


class CapitalShipMixin:
    """Records capital/super/titan hulls observed in zkill killmails."""

    def _capital_ship_meta(self, type_id):
        """Return (category, ship_name) for a capital type id, else None.

        Uses static known IDs first, then falls back to ESI type/group data so
        newly introduced capital hull IDs are still detected and displayed.
        """
        if type_id in CAPITAL_SHIPS:
            return CAPITAL_SHIPS[type_id]
        cache = getattr(self, "_capital_ship_meta_cache", None)
        if cache is None:
            cache = {}
            self._capital_ship_meta_cache = cache
        if type_id in cache:
            return cache[type_id]
        try:
            info = self.esi.get_type_info(int(type_id))
        except Exception:
            cache[type_id] = None
            return None
        group_id = info.get("group_id")
        category = _category_from_group(group_id)
        if not category:
            cache[type_id] = None
            return None
        ship_name = info.get("name") or f"Type {type_id}"
        cache[type_id] = (category, ship_name)
        return cache[type_id]

    def _record_capital_ship_observations(self, audit_run, character_ids, character_name_map):
        character_id_set = {int(cid) for cid in character_ids if cid is not None}

        # Aggregation: {(char_id, type_id): {"count": int, "first": dt, "last": dt}}
        agg = {}

        def _observe(char_id, type_id, when):
            if char_id is None or type_id is None:
                return
            try:
                char_id = int(char_id)
                type_id = int(type_id)
            except (TypeError, ValueError):
                return
            if char_id not in character_id_set:
                return
            if self._capital_ship_meta(type_id) is None:
                return
            entry = agg.setdefault((char_id, type_id), {"count": 0, "first": None, "last": None})
            entry["count"] += 1
            if when is not None:
                if entry["first"] is None or when < entry["first"]:
                    entry["first"] = when
                if entry["last"] is None or when > entry["last"]:
                    entry["last"] = when

        # Attacker-side: query zKill per character per capital group. zKill's
        # kills/characterID/{id}/groupID/{gid}/ endpoint filters by the
        # attacker's ship, so this returns only killmails where the character
        # was flying a capital hull. This is far more reliable than scanning
        # generic kills (which only goes back as far as page 1 of all kills).
        kill_pages = int(self.policy.zkill_capital_kill_pages)
        for char_id in character_ids:
            for group_id in CAPITAL_SHIP_GROUPS:
                try:
                    grouped_kills = self.zkill.get_kills_by_group(char_id, group_id, max_pages=kill_pages)
                except Exception:
                    grouped_kills = []
                for kill in grouped_kills:
                    when = _parse_kill_time(kill.get("killmail_time"))
                    for attacker in kill.get("attackers") or []:
                        attacker = attacker or {}
                        if attacker.get("character_id") == char_id:
                            _observe(char_id, attacker.get("ship_type_id"), when)
                            break
                    # Also catch the case where the subject is the victim.
                    victim = kill.get("victim") or {}
                    if (victim.get("character_id") or None) == char_id:
                        _observe(char_id, victim.get("ship_type_id"), when)

        # Victim-side: query zKill for each capital group so we catch capital
        # losses for each alt without wading through pages of non-capital losses.
        loss_pages = int(self.policy.zkill_capital_loss_pages)
        for char_id in character_ids:
            for group_id in CAPITAL_SHIP_GROUPS:
                try:
                    losses = self.zkill.get_losses_by_group(char_id, group_id, max_pages=loss_pages)
                except Exception:
                    losses = []
                for loss in losses:
                    when = _parse_kill_time(loss.get("killmail_time"))
                    victim = loss.get("victim") or {}
                    if (victim.get("character_id") or None) == char_id:
                        _observe(char_id, victim.get("ship_type_id"), when)

        if not agg:
            # Even with no zKill observations, we still want to record
            # capital ownership from MemberAudit assets/current ship.
            self._record_capital_asset_ownership(audit_run, character_ids, character_name_map)
            return

        # Batch-fetch existing observations for this audit run so we can
        # split into bulk_create (new) and bulk_update (existing) instead of
        # per-row update_or_create queries.
        existing_obs = {}
        for obs in AuditCapitalShipObservation.objects.filter(
            audit_run=audit_run,
            character_id__in={cid for cid, _ in agg},
            ship_type_id__in={tid for _, tid in agg},
        ):
            existing_obs[(obs.character_id, obs.ship_type_id)] = obs

        to_create = []
        to_update = []
        for (char_id, type_id), stats in agg.items():
            meta = self._capital_ship_meta(type_id)
            if meta is None:
                continue
            category, ship_name = meta
            char_name = character_name_map.get(char_id) or str(char_id)
            obj = existing_obs.get((char_id, type_id))
            if obj is None:
                to_create.append(AuditCapitalShipObservation(
                    audit_run=audit_run,
                    character_id=char_id,
                    ship_type_id=type_id,
                    character_name=char_name,
                    ship_name=ship_name,
                    ship_category=category,
                    observation_count=stats["count"],
                    first_seen=stats["first"],
                    last_seen=stats["last"],
                ))
            else:
                obj.character_name = char_name
                obj.ship_name = ship_name
                obj.ship_category = category
                obj.observation_count = stats["count"]
                obj.first_seen = stats["first"]
                obj.last_seen = stats["last"]
                to_update.append(obj)

        if to_create:
            AuditCapitalShipObservation.objects.bulk_create(to_create)
        if to_update:
            AuditCapitalShipObservation.objects.bulk_update(
                to_update,
                ["character_name", "ship_name", "ship_category",
                 "observation_count", "first_seen", "last_seen"],
            )

        # Merge in MemberAudit asset/ownership data on top of zKill observations.
        self._record_capital_asset_ownership(audit_run, character_ids, character_name_map)

    def _record_capital_asset_ownership(self, audit_run, character_ids, character_name_map):
        """Record capital ship ownership from MemberAudit assets, current ship,
        active contracts, and market sell orders.

        This supplements zKill observations with ownership data: ships the
        character owns but may never have lost or appeared on a killmail with,
        plus ships they're actively trying to sell via contracts or market orders.
        Updates existing observations with asset_count/is_current_ship/contract_count/
        market_order_count, and creates new observations for owned/listed capitals
        with no zKill record.
        """
        from ..memberaudit_adapter import MemberAuditAdapter

        try:
            ownership = MemberAuditAdapter.get_capital_ownership(character_ids)
        except Exception:
            ownership = {}
        if not ownership:
            return

        # Collect all (char_id, type_id) pairs we need to update/create.
        needed = []
        for char_id, ships in ownership.items():
            for type_id, info in ships.items():
                if self._capital_ship_meta(type_id) is None:
                    continue
                asset_count = max(info.get("asset_count", 0), 0)
                is_current = bool(info.get("is_current_ship", False))
                contract_count = max(info.get("contract_count", 0), 0)
                market_order_count = max(info.get("market_order_count", 0), 0)
                if not asset_count and not is_current and not contract_count and not market_order_count:
                    continue
                needed.append((char_id, type_id, info, asset_count, is_current, contract_count, market_order_count))

        if not needed:
            return

        # Batch-fetch existing observations for all needed pairs.
        existing_obs = {}
        for obs in AuditCapitalShipObservation.objects.filter(
            audit_run=audit_run,
            character_id__in={item[0] for item in needed},
            ship_type_id__in={item[1] for item in needed},
        ):
            existing_obs[(obs.character_id, obs.ship_type_id)] = obs

        to_create = []
        to_update = []
        for char_id, type_id, info, asset_count, is_current, contract_count, market_order_count in needed:
            char_name = character_name_map.get(char_id) or str(char_id)
            meta = self._capital_ship_meta(type_id)
            if meta is None:
                continue
            category, ship_name = meta
            obj = existing_obs.get((char_id, type_id))
            if obj is None:
                to_create.append(AuditCapitalShipObservation(
                    audit_run=audit_run,
                    character_id=char_id,
                    ship_type_id=type_id,
                    character_name=char_name,
                    ship_name=ship_name,
                    ship_category=category,
                    asset_count=asset_count,
                    is_current_ship=is_current,
                    contract_count=contract_count,
                    market_order_count=market_order_count,
                ))
            else:
                obj.asset_count = asset_count
                obj.is_current_ship = is_current
                obj.contract_count = contract_count
                obj.market_order_count = market_order_count
                if not obj.character_name:
                    obj.character_name = char_name
                if not obj.ship_name:
                    obj.ship_name = ship_name
                if not obj.ship_category:
                    obj.ship_category = category
                to_update.append(obj)

        if to_create:
            AuditCapitalShipObservation.objects.bulk_create(to_create)
        if to_update:
            AuditCapitalShipObservation.objects.bulk_update(
                to_update,
                ["asset_count", "is_current_ship",
                 "contract_count", "market_order_count",
                 "character_name", "ship_name", "ship_category"],
            )
