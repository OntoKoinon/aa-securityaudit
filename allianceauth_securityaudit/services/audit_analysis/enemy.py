from ...models import EnemyEntity
from ..esi_client import EsiClient
from ..memberaudit_adapter import MemberAuditAdapter

class EnemyDetectionMixin:

    def _has_enemy_connections(self, character, corp_history, character_id=None):
        alliance_id = character.get("alliance_id")
        corp_id = character.get("corporation_id")
        match = None
        if alliance_id and EnemyEntity.objects.filter(
            entity_type=EnemyEntity.TYPE_ALLIANCE,
            entity_id=alliance_id,
            is_active=True,
        ).exists():
            match = {
                "type": "alliance",
                "id": int(alliance_id),
                "source": "current_alliance",
                "reason": "Direct connection: character is currently in a configured enemy alliance.",
            }
        elif corp_id and EnemyEntity.objects.filter(
            entity_type=EnemyEntity.TYPE_CORP,
            entity_id=corp_id,
            is_active=True,
        ).exists():
            match = {
                "type": "corporation",
                "id": int(corp_id),
                "source": "current_corporation",
                "reason": "Direct connection: character is currently in a configured enemy corporation.",
            }
        else:
            for row in corp_history or []:
                hist_corp_id = row.get("corporation_id")
                if hist_corp_id and EnemyEntity.objects.filter(
                    entity_type=EnemyEntity.TYPE_CORP,
                    entity_id=hist_corp_id,
                    is_active=True,
                ).exists():
                    match = {
                        "type": "corporation",
                        "id": int(hist_corp_id),
                        "source": "corporation_history",
                        "reason": (
                            "Direct connection: corporation history includes a configured enemy corporation."
                        ),
                    }
                    break
        if not match and character_id:
            match = self._find_plus_ten_enemy_connection(character_id)
        if not match:
            return None
        return self._resolve_enemy_match(match)

    def _find_plus_ten_enemy_connection(self, character_id):
        contact_standings = MemberAuditAdapter.get_contact_character_standings(character_id)
        if not contact_standings:
            return None

        enemy_character_ids = set(
            EnemyEntity.objects.filter(
                entity_type=EnemyEntity.TYPE_CHARACTER,
                is_active=True,
            ).values_list("entity_id", flat=True)
        )
        enemy_corp_ids = set(
            EnemyEntity.objects.filter(
                entity_type=EnemyEntity.TYPE_CORP,
                is_active=True,
            ).values_list("entity_id", flat=True)
        )
        enemy_alliance_ids = set(
            EnemyEntity.objects.filter(
                entity_type=EnemyEntity.TYPE_ALLIANCE,
                is_active=True,
            ).values_list("entity_id", flat=True)
        )

        plus_ten_contact_ids = []
        for raw_id, standing in (contact_standings or {}).items():
            try:
                standing_value = float(standing)
            except (TypeError, ValueError):
                continue
            if standing_value < 10:
                continue
            try:
                plus_ten_contact_ids.append((int(raw_id), standing_value))
            except (TypeError, ValueError):
                continue

        if not plus_ten_contact_ids:
            return None

        plus_ten_contact_ids.sort(key=lambda item: item[0])
        contact_name_map = self.esi.resolve_names({item[0] for item in plus_ten_contact_ids}) or {}

        for contact_id, standing_value in plus_ten_contact_ids:
            contact_name = contact_name_map.get(contact_id) or str(contact_id)
            if contact_id in enemy_character_ids:
                return {
                    "type": "character",
                    "id": contact_id,
                    "source": "plus_ten_standing",
                    "reason": (
                        f"Direct connection: +{standing_value:g} standing set for configured enemy "
                        f"character {contact_name}."
                    ),
                }

            try:
                contact_char = self.esi.get_character(contact_id)
            except Exception:
                contact_char = {}
            contact_corp_id = contact_char.get("corporation_id")
            contact_alliance_id = contact_char.get("alliance_id")

            if contact_corp_id and contact_corp_id in enemy_corp_ids:
                return {
                    "type": "corporation",
                    "id": int(contact_corp_id),
                    "source": "plus_ten_standing",
                    "reason": (
                        f"Direct connection: +{standing_value:g} standing set for {contact_name}, "
                        "who is in a configured enemy corporation."
                    ),
                }
            if contact_alliance_id and contact_alliance_id in enemy_alliance_ids:
                return {
                    "type": "alliance",
                    "id": int(contact_alliance_id),
                    "source": "plus_ten_standing",
                    "reason": (
                        f"Direct connection: +{standing_value:g} standing set for {contact_name}, "
                        "who is in a configured enemy alliance."
                    ),
                }
        return None

    def _resolve_enemy_match(self, match):
        entity_id = match["id"]
        entity_type = match["type"]
        ids_to_resolve = {entity_id}
        secondary_corp_id = None
        secondary_alliance_id = None

        if entity_type == "character":
            try:
                char = self.esi.get_character(entity_id)
                secondary_corp_id = char.get("corporation_id")
                secondary_alliance_id = char.get("alliance_id")
                if secondary_corp_id:
                    ids_to_resolve.add(secondary_corp_id)
                if secondary_alliance_id:
                    ids_to_resolve.add(secondary_alliance_id)
            except Exception:
                pass
        elif entity_type == "corporation":
            try:
                corp = self.esi.get_corporation(entity_id)
                secondary_alliance_id = corp.get("alliance_id")
                if secondary_alliance_id:
                    ids_to_resolve.add(secondary_alliance_id)
            except Exception:
                pass

        names = self.esi.resolve_names(ids_to_resolve) or {}
        result = {
            "entity_type": entity_type,
            "entity_id": entity_id,
            "name": names.get(entity_id) or str(entity_id),
            "source": match.get("source", ""),
            "reason": match.get("reason", ""),
            "image_url": "",
            "corp_id": None,
            "corp_name": "",
            "corp_logo_url": "",
            "alliance_id": None,
            "alliance_name": "",
            "alliance_logo_url": "",
        }

        if entity_type == "character":
            result["image_url"] = MemberAuditAdapter._portrait_url(entity_id)
            if secondary_corp_id:
                result["corp_id"] = secondary_corp_id
                result["corp_name"] = names.get(secondary_corp_id) or str(secondary_corp_id)
                result["corp_logo_url"] = MemberAuditAdapter._corp_logo_url(secondary_corp_id)
            if secondary_alliance_id:
                result["alliance_id"] = secondary_alliance_id
                result["alliance_name"] = names.get(secondary_alliance_id) or str(secondary_alliance_id)
                result["alliance_logo_url"] = f"https://images.evetech.net/alliances/{secondary_alliance_id}/logo?size=64"
        elif entity_type == "corporation":
            result["image_url"] = MemberAuditAdapter._corp_logo_url(entity_id)
            if secondary_alliance_id:
                result["alliance_id"] = secondary_alliance_id
                result["alliance_name"] = names.get(secondary_alliance_id) or str(secondary_alliance_id)
                result["alliance_logo_url"] = f"https://images.evetech.net/alliances/{secondary_alliance_id}/logo?size=64"
        elif entity_type == "alliance":
            result["image_url"] = f"https://images.evetech.net/alliances/{entity_id}/logo?size=64"

        return result

    def _is_enemy_corp(self, corp_id):
        return EnemyEntity.objects.filter(
            entity_type=EnemyEntity.TYPE_CORP,
            entity_id=corp_id,
            is_active=True,
        ).exists()