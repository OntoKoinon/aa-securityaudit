import json

from django.utils import timezone

from ..blacklist_adapter import BlacklistAdapter
from ..memberaudit_adapter import MemberAuditAdapter

class CollusionDetectionMixin:

    def _has_enemy_collusion_pattern(self, character_id, kills):
        if not kills or not character_id:
            return None

        enemy_character_ids, enemy_corp_ids, enemy_alliance_ids = self._get_enemy_sets()

        matched_killmail_ids = []
        matched_killmail_entries = []
        matched_killmail_count = 0
        matched_entities = {}
        matched_last_180_days = 0
        now = timezone.now()

        for kill in kills:
            attackers = kill.get("attackers") or []
            if not any((attacker or {}).get("character_id") == character_id for attacker in attackers):
                continue

            teammate_ids = {
                (attacker or {}).get("character_id")
                for attacker in attackers
                if (attacker or {}).get("character_id") and (attacker or {}).get("character_id") != character_id
            }
            blacklisted_teammate_ids = BlacklistAdapter.get_blacklisted_character_ids(teammate_ids)

            kill_has_match = False
            kill_matched = []
            kill_matched_keys = set()
            for attacker in attackers:
                attacker = attacker or {}
                teammate_id = attacker.get("character_id")
                if not teammate_id or teammate_id == character_id:
                    continue

                teammate_corp_id = attacker.get("corporation_id")
                teammate_alliance_id = attacker.get("alliance_id")

                if teammate_id in blacklisted_teammate_ids:
                    kill_has_match = True
                    key = f"blacklist:character:{teammate_id}"
                    matched_entities[key] = {
                        "source": "blacklist",
                        "entity_type": "character",
                        "entity_id": teammate_id,
                    }
                    if key not in kill_matched_keys:
                        kill_matched_keys.add(key)
                        kill_matched.append({"source": "blacklist", "entity_type": "character", "entity_id": teammate_id})
                if teammate_id in enemy_character_ids:
                    kill_has_match = True
                    key = f"enemy:character:{teammate_id}"
                    matched_entities[key] = {
                        "source": "enemy",
                        "entity_type": "character",
                        "entity_id": teammate_id,
                    }
                    if key not in kill_matched_keys:
                        kill_matched_keys.add(key)
                        kill_matched.append({"source": "enemy", "entity_type": "character", "entity_id": teammate_id})
                if teammate_corp_id and teammate_corp_id in enemy_corp_ids:
                    kill_has_match = True
                    key = f"enemy:corporation:{teammate_corp_id}"
                    matched_entities[key] = {
                        "source": "enemy",
                        "entity_type": "corporation",
                        "entity_id": teammate_corp_id,
                    }
                    if key not in kill_matched_keys:
                        kill_matched_keys.add(key)
                        kill_matched.append({"source": "enemy", "entity_type": "corporation", "entity_id": teammate_corp_id})
                if teammate_alliance_id and teammate_alliance_id in enemy_alliance_ids:
                    kill_has_match = True
                    key = f"enemy:alliance:{teammate_alliance_id}"
                    matched_entities[key] = {
                        "source": "enemy",
                        "entity_type": "alliance",
                        "entity_id": teammate_alliance_id,
                    }
                    if key not in kill_matched_keys:
                        kill_matched_keys.add(key)
                        kill_matched.append({"source": "enemy", "entity_type": "alliance", "entity_id": teammate_alliance_id})

            if not kill_has_match:
                continue

            matched_killmail_count += 1
            killmail_id = kill.get("killmail_id")
            kill_time = self.esi.parse_esi_time(kill.get("killmail_time"))
            if killmail_id:
                matched_killmail_ids.append(str(killmail_id))
                matched_killmail_entries.append(
                    {
                        "killmail_id": str(killmail_id),
                        "date": kill_time.strftime("%Y-%m-%d %H:%M") if kill_time else "unknown date",
                        "matches": kill_matched,
                    }
                )

            if kill_time and (now - kill_time).days <= 180:
                matched_last_180_days += 1

        if matched_killmail_count == 0:
            return None

        details = (
            f"{matched_killmail_count} killmails show the audited character on the same side as "
            f"blacklisted or enemy entities; {matched_last_180_days} occurred in the last 180 days."
        )

        ids_to_resolve = {
            int(item.get("entity_id"))
            for item in matched_entities.values()
            if item.get("entity_id")
        }
        resolved_names = self.esi.resolve_names(ids_to_resolve) if ids_to_resolve else {}
        matched_entity_rows = []
        for item in sorted(
            matched_entities.values(),
            key=lambda x: (str(x.get("source")), str(x.get("entity_type")), int(x.get("entity_id") or 0)),
        ):
            entity_type = item.get("entity_type")
            entity_id = int(item.get("entity_id"))
            if entity_type == "character":
                image_url = MemberAuditAdapter._portrait_url(entity_id)
            elif entity_type == "corporation":
                image_url = MemberAuditAdapter._corp_logo_url(entity_id)
            elif entity_type == "alliance":
                image_url = MemberAuditAdapter._alliance_logo_url(entity_id)
            else:
                image_url = ""
            matched_entity_rows.append(
                {
                    "source": item.get("source") or "enemy",
                    "entity_type": entity_type,
                    "entity_id": entity_id,
                    "name": resolved_names.get(entity_id) or str(entity_id),
                    "image_url": image_url,
                }
            )

        match_lookup = {
            (row["source"], row["entity_type"], row["entity_id"]): row
            for row in matched_entity_rows
        }
        for entry in matched_killmail_entries:
            for match in entry.get("matches", []):
                row = match_lookup.get((match["source"], match["entity_type"], match["entity_id"]))
                if row:
                    match["name"] = row["name"]
                    match["image_url"] = row["image_url"]

        return {
            "details": details,
            "evidence": [
                ("collusion_killmail_count", str(matched_killmail_count)),
                ("collusion_last_180_days", str(matched_last_180_days)),
                ("collusion_killmail_ids", json.dumps(matched_killmail_entries[:20])),
                ("matched_enemy_or_blacklist_entities", json.dumps(matched_entity_rows) if matched_entity_rows else "[]"),
            ],
        }