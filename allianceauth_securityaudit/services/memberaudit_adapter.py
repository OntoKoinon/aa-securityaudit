import logging

from django.apps import apps
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.core.exceptions import FieldError
from django.db.models import F, Q
from django.utils import timezone

from .esi_client import EsiClient

LOGGER = logging.getLogger(__name__)


class MemberAuditAdapter:
    """
    Thin compatibility layer so plugin can integrate with MemberAudit while keeping
    hard dependency points isolated.
    """

    SEARCH_CACHE_TTL = 120

    @staticmethod
    def find_user_by_main_name(character_name):
        user_model = get_user_model()
        return user_model.objects.filter(username__iexact=character_name).first()

    @staticmethod
    def get_declared_characters(user):
        if not user:
            return []
        profile = getattr(user, "profile", None)
        chars = getattr(profile, "characters", None)
        if chars is None:
            return []
        try:
            return list(chars.all())
        except Exception:
            return []

    @staticmethod
    def search_corporations(query, limit=10):
        term = (query or "").strip()
        if len(term) < 2:
            return []
        cache_key = f"securityaudit:corp_search:{term.casefold()}:{int(limit)}"
        cached = cache.get(cache_key)
        if cached is not None:
            return cached

        rows = []
        seen = set()
        model_specs = [
            ("esi", "Corporation", {}),
            ("memberaudit", "Corporation", {}),
            ("eveonline", "EveCorporationInfo", {}),
            ("allianceauth.eveonline", "EveCorporationInfo", {}),
            ("eveuniverse", "EveEntity", {"category": "corporation"}),
        ]
        for app_label, model_name, extra in model_specs:
            model = MemberAuditAdapter._get_model(app_label, model_name)
            if model is None:
                continue
            for lookup in ("corporation_name__icontains", "name__icontains"):
                try:
                    queryset = model.objects.filter(**{lookup: term}, **extra).order_by("id")[: max(limit * 2, 20)]
                except (FieldError, Exception):
                    continue
                for corp in queryset:
                    corp_id = MemberAuditAdapter._extract_int(corp, "corporation_id", "corp_id", "id")
                    corp_name = MemberAuditAdapter._extract_text(corp, "corporation_name", "name")
                    ticker = MemberAuditAdapter._extract_text(corp, "ticker")
                    if not corp_name:
                        continue
                    dedupe_key = corp_id or corp_name.casefold()
                    if dedupe_key in seen:
                        continue
                    seen.add(dedupe_key)
                    rows.append(
                        {
                            "corporation_id": corp_id,
                            "name": corp_name,
                            "ticker": ticker or "",
                            "logo_url": MemberAuditAdapter._corp_logo_url(corp_id),
                        }
                    )
                    if len(rows) >= limit:
                        cache.set(cache_key, rows, MemberAuditAdapter.SEARCH_CACHE_TTL)
                        return rows

        cache.set(cache_key, rows, MemberAuditAdapter.SEARCH_CACHE_TTL)
        return rows

    @staticmethod
    def get_corporation_summaries(corp_ids):
        ids = []
        seen = set()
        for value in corp_ids or []:
            try:
                corp_id = int(value)
            except (TypeError, ValueError):
                continue
            if corp_id in seen:
                continue
            seen.add(corp_id)
            ids.append(corp_id)
        if not ids:
            return []

        rows = []
        found = set()
        models = [
            MemberAuditAdapter._get_model("esi", "Corporation"),
            MemberAuditAdapter._get_model("memberaudit", "Corporation"),
        ]
        for model in models:
            if model is None:
                continue
            for lookup in ("corporation_id__in", "corp_id__in", "id__in"):
                try:
                    queryset = model.objects.filter(**{lookup: ids})
                except (FieldError, Exception):
                    continue
                for corp in queryset:
                    corp_id = MemberAuditAdapter._extract_int(corp, "corporation_id", "corp_id", "id")
                    if not corp_id or corp_id in found:
                        continue
                    corp_name = MemberAuditAdapter._extract_text(corp, "corporation_name", "name") or str(corp_id)
                    ticker = MemberAuditAdapter._extract_text(corp, "ticker") or ""
                    found.add(corp_id)
                    rows.append(
                        {
                            "corporation_id": corp_id,
                            "name": corp_name,
                            "ticker": ticker,
                            "logo_url": MemberAuditAdapter._corp_logo_url(corp_id),
                        }
                    )

        for corp_id in ids:
            if corp_id in found:
                continue
            rows.append(
                {
                    "corporation_id": corp_id,
                    "name": str(corp_id),
                    "ticker": "",
                    "logo_url": MemberAuditAdapter._corp_logo_url(corp_id),
                }
            )
        return rows

    @staticmethod
    def search_character_targets(query, limit=10):
        term = (query or "").strip()
        if len(term) < 2:
            return []
        cache_key = f"securityaudit:char_search:{term.casefold()}:{int(limit)}"
        cached = cache.get(cache_key)
        if cached is not None:
            return cached

        rows = []
        seen = set()
        needle = term.casefold()

        user_model = get_user_model()
        for user in user_model.objects.order_by("username"):
            main_name = MemberAuditAdapter._extract_main_character_name(user)
            if not main_name or needle not in main_name.casefold():
                continue

            snapshot = MemberAuditAdapter.get_character_snapshot(character_name=main_name, user=user)
            character_id = snapshot.get("character_id") if snapshot else None
            dedupe_key = character_id or main_name.casefold()
            if dedupe_key in seen:
                continue
            seen.add(dedupe_key)

            rows.append(
                {
                    "character_id": character_id,
                    "character_name": main_name,
                    "subtitle": f"Main: {user.username}",
                    "portrait_url": MemberAuditAdapter._portrait_url(character_id),
                }
            )
            if len(rows) >= limit:
                cache.set(cache_key, rows, MemberAuditAdapter.SEARCH_CACHE_TTL)
                return rows

        if len(rows) < limit:
            char_specs = [
                ("esi", "Character", {}),
                ("memberaudit", "Character", {}),
                ("eveonline", "EveCharacter", {}),
                ("allianceauth.eveonline", "EveCharacter", {}),
                ("eveuniverse", "EveEntity", {"category": "character"}),
            ]
            for app_label, model_name, extra in char_specs:
                model = MemberAuditAdapter._get_model(app_label, model_name)
                if model is None:
                    continue
                for lookup in ("character_name__icontains", "name__icontains"):
                    try:
                        queryset = model.objects.filter(**{lookup: term}, **extra).order_by("id")[: max(limit * 2, 20)]
                    except (FieldError, Exception):
                        continue
                    for char in queryset:
                        character_id = MemberAuditAdapter._extract_int(char, "character_id", "id")
                        character_name = MemberAuditAdapter._extract_text(char, "character_name", "name")
                        if not character_name:
                            continue
                        dedupe = character_id or character_name.casefold()
                        if dedupe in seen:
                            continue
                        seen.add(dedupe)
                        rows.append(
                            {
                                "character_id": character_id,
                                "character_name": character_name,
                                "subtitle": "",
                                "portrait_url": MemberAuditAdapter._portrait_url(character_id),
                            }
                        )
                        if len(rows) >= limit:
                            cache.set(cache_key, rows, MemberAuditAdapter.SEARCH_CACHE_TTL)
                            return rows

        cache.set(cache_key, rows, MemberAuditAdapter.SEARCH_CACHE_TTL)
        return rows

    @staticmethod
    def get_character_snapshot(character_name=None, character_id=None, user=None):
        character = MemberAuditAdapter._find_character_object(
            character_name=character_name,
            character_id=character_id,
            user=user,
        )
        if character is None:
            return None
        return {
            "character_id": MemberAuditAdapter._extract_int(character, "character_id", "id"),
            "corporation_id": MemberAuditAdapter._extract_int(
                character,
                "corporation_id",
                "corp_id",
                "corporation",
                "corporationpk",
            ),
            "alliance_id": MemberAuditAdapter._extract_int(
                character,
                "alliance_id",
                "alliance",
                "alliancepk",
            ),
            "name": MemberAuditAdapter._extract_text(character, "character_name", "name", "character"),
        }

    @staticmethod
    def _extract_main_character_name(user):
        profile = getattr(user, "profile", None)
        if profile is None:
            return ""
        for attr in ("main_character_name", "main_character", "character_name"):
            value = getattr(profile, attr, None)
            if not value:
                continue
            if isinstance(value, str):
                return value.strip()
            nested_name = getattr(value, "character_name", None) or getattr(value, "name", None)
            if nested_name:
                return str(nested_name).strip()
        return ""

    @staticmethod
    def find_user_by_character_id(character_id):
        if not character_id:
            return None
        candidate_models = [
            ("memberaudit", "Character"),
            ("allianceauth.eveonline", "CharacterOwnership"),
            ("esi", "Character"),
        ]
        for app_label, model_name in candidate_models:
            model = MemberAuditAdapter._get_model(app_label, model_name)
            if model is None:
                continue
            for filter_kwargs in (
                {"character_id": character_id},
                {"character__character_id": character_id},
                {"character__id": character_id},
                {"id": character_id},
            ):
                try:
                    obj = model.objects.filter(**filter_kwargs).select_related("user").first()
                except (FieldError, Exception):
                    continue
                if not obj:
                    continue
                user = getattr(obj, "user", None) or getattr(obj, "user__", None)
                if user:
                    return user
        return None

    @staticmethod
    def get_user_declared_character_ids(user):
        if not user:
            return set()

        ids = set()

        # AllianceAuth CharacterOwnership / profile characters
        ownership_model = None
        for app_label in ("authentication", "allianceauth.authentication", "eveonline", "allianceauth.eveonline"):
            ownership_model = MemberAuditAdapter._get_model(app_label, "CharacterOwnership")
            if ownership_model is not None:
                break
        if ownership_model is not None:
            try:
                for ownership in ownership_model.objects.filter(user=user).select_related("character"):
                    char_id = MemberAuditAdapter._extract_int(
                        getattr(ownership, "character", None),
                        "character_id",
                        "id",
                    )
                    if char_id:
                        ids.add(char_id)
            except Exception:
                pass

        # MemberAudit
        for app_label in ("memberaudit", "esi"):
            model = MemberAuditAdapter._get_model(app_label, "Character")
            if model is None:
                continue
            for filter_kwargs in (
                {"user": user},
                {"user_id": user.id},
            ):
                try:
                    for char in model.objects.filter(**filter_kwargs):
                        char_id = MemberAuditAdapter._extract_int(char, "character_id", "id")
                        if char_id:
                            ids.add(char_id)
                except (FieldError, Exception):
                    continue

        # profile.characters many-to-many if present
        profile = getattr(user, "profile", None)
        if profile:
            chars = getattr(profile, "characters", None)
            if chars is not None:
                try:
                    for char in chars.all():
                        char_id = MemberAuditAdapter._extract_int(char, "character_id", "id")
                        if char_id:
                            ids.add(char_id)
                except Exception:
                    pass

        return ids

    @staticmethod
    def get_user_for_character_id(character_id):
        if not character_id:
            return None
        ownership_model = None
        for app_label in ("authentication", "allianceauth.authentication", "eveonline", "allianceauth.eveonline"):
            ownership_model = MemberAuditAdapter._get_model(app_label, "CharacterOwnership")
            if ownership_model is not None:
                break
        if ownership_model is None:
            return None
        try:
            ownership = ownership_model.objects.filter(
                character__character_id=int(character_id)
            ).select_related("character").first()
            return getattr(ownership, "user", None)
        except Exception:
            return None

    @staticmethod
    def _portrait_url(character_id):
        if not character_id:
            return ""
        return f"https://images.evetech.net/characters/{character_id}/portrait?size=64"

    @staticmethod
    def _corp_logo_url(corp_id):
        if not corp_id:
            return ""
        return f"https://images.evetech.net/corporations/{corp_id}/logo?size=64"

    @staticmethod
    def get_main_character_ids_for_corp(corp_id):
        """Return (character_id, character_name) tuples for known mains in a corporation."""
        if not corp_id:
            return []
        EveCharacter = MemberAuditAdapter._get_model("eveonline", "EveCharacter")
        if EveCharacter is None:
            return []
        results = []
        seen = set()
        try:
            qs = EveCharacter.objects.filter(
                corporation_id=int(corp_id),
                character_ownership__user__profile__main_character__character_id=F("character_id"),
            ).only("character_id", "character_name")
            for obj in qs:
                char_id = obj.character_id
                if char_id and char_id not in seen:
                    seen.add(char_id)
                    results.append((char_id, obj.character_name or ""))
        except Exception:
            pass
        return results

    @staticmethod
    def get_character_corp_history(character_name=None, character_id=None, user=None):
        character = MemberAuditAdapter._find_character_object(
            character_name=character_name,
            character_id=character_id,
            user=user,
        )
        if character is None:
            return []

        history_obj = None
        for attr in ("corporationhistory_set", "corporation_history", "corp_history"):
            value = getattr(character, attr, None)
            if value is None:
                continue
            history_obj = value
            break

        if history_obj is None:
            return []

        rows = []
        try:
            iterable = history_obj.all() if hasattr(history_obj, "all") else history_obj
            for row in iterable:
                corp_id = MemberAuditAdapter._extract_int(row, "corporation_id", "corp_id")
                start_date = getattr(row, "start_date", None)
                if corp_id:
                    rows.append({"corporation_id": corp_id, "start_date": str(start_date) if start_date else None})
        except Exception:
            return []
        return rows

    @staticmethod
    def get_contact_character_ids(character_id):
        character = MemberAuditAdapter._find_character_object(character_id=character_id)
        if character is None:
            return set()

        contacts_obj = None
        for attr in ("contacts", "contact_set", "character_contacts"):
            value = getattr(character, attr, None)
            if value is None:
                continue
            contacts_obj = value
            break

        if contacts_obj is None:
            return set()

        ids = set()
        try:
            iterable = contacts_obj.all() if hasattr(contacts_obj, "all") else contacts_obj
            for row in iterable:
                contact_id = MemberAuditAdapter._extract_int(
                    row,
                    "contact_id",
                    "character_id",
                    "target_id",
                    "other_character_id",
                )
                if contact_id:
                    ids.add(contact_id)
        except Exception:
            return set()
        return ids

    @staticmethod
    def get_contact_character_standings(character_id):
        character = MemberAuditAdapter._find_character_object(character_id=character_id)
        if character is None:
            return {}

        contacts_obj = None
        for attr in ("contacts", "contact_set", "character_contacts"):
            value = getattr(character, attr, None)
            if value is None:
                continue
            contacts_obj = value
            break

        if contacts_obj is None:
            return {}

        standings = {}
        try:
            iterable = contacts_obj.all() if hasattr(contacts_obj, "all") else contacts_obj
            for row in iterable:
                contact_id = MemberAuditAdapter._extract_int(
                    row,
                    "contact_id",
                    "character_id",
                    "target_id",
                    "other_character_id",
                )
                if not contact_id:
                    continue

                standing_value = None
                for standing_attr in ("standing", "contact_standing", "watchlist_standing"):
                    raw_value = getattr(row, standing_attr, None)
                    if raw_value is None:
                        continue
                    try:
                        standing_value = float(raw_value)
                        break
                    except (TypeError, ValueError):
                        continue
                standings[contact_id] = standing_value
        except Exception:
            return {}
        return standings

    @staticmethod
    def get_token_for_character(_character_id):
        tokens = MemberAuditAdapter._candidate_tokens_for_character(_character_id)
        for token in tokens:
            try:
                validator = getattr(token, "valid_access_token", None)
                if callable(validator):
                    if validator():
                        return token
                elif validator:
                    return token
                else:
                    return token
            except Exception:
                continue
        return None

    @staticmethod
    def get_available_scopes_for_character(_character_id):
        scopes = set()
        for token in MemberAuditAdapter._candidate_tokens_for_character(_character_id):
            scopes.update(MemberAuditAdapter._extract_scopes_from_token(token))
        return scopes

    @staticmethod
    def get_wallet_journal(character_id):
        character = MemberAuditAdapter._find_character_object(character_id=character_id)
        if character is None:
            return None

        journal_obj = None
        for attr in ("walletjournalentry_set", "wallet_journal", "wallet_journals"):
            value = getattr(character, attr, None)
            if value is None:
                continue
            journal_obj = value
            break

        if journal_obj is None:
            return None

        rows = []
        try:
            iterable = journal_obj.all() if hasattr(journal_obj, "all") else journal_obj
            for row in iterable:
                amount = getattr(row, "amount", None)
                first_party_id = MemberAuditAdapter._extract_int(
                    row,
                    "first_party_id",
                    "first_party",
                )
                second_party_id = MemberAuditAdapter._extract_int(
                    row,
                    "second_party_id",
                    "other_party_id",
                    "context_id",
                )
                ref_type = (
                    getattr(row, "ref_type", None)
                    or getattr(row, "ref_type_id", None)
                    or getattr(row, "journal_ref_type", None)
                )
                if ref_type is not None and not isinstance(ref_type, str):
                    ref_type = str(ref_type)
                date_value = getattr(row, "date", None) or getattr(row, "timestamp", None)
                rows.append(
                    {
                        "amount": amount,
                        "first_party_id": first_party_id,
                        "second_party_id": second_party_id,
                        "ref_type": ref_type,
                        "date": str(date_value) if date_value else None,
                    }
                )
        except Exception:
            return None

        return rows

    @staticmethod
    def get_character_contracts(character_id):
        character = MemberAuditAdapter._find_character_object(character_id=character_id)
        if character is not None:
            contracts_obj = None
            for attr in ("charactercontract_set", "contracts", "character_contracts"):
                value = getattr(character, attr, None)
                if value is None:
                    continue
                contracts_obj = value
                break

            if contracts_obj is not None:
                try:
                    iterable = contracts_obj.all() if hasattr(contracts_obj, "all") else contracts_obj
                    rows = []
                    for row in iterable:
                        contract_type = (
                            getattr(row, "type", None) or getattr(row, "contract_type", None)
                        )
                        status = getattr(row, "status", None)
                        price = getattr(row, "price", None)
                        rows.append(
                            {
                                "contract_id": MemberAuditAdapter._extract_int(row, "contract_id", "id"),
                                "type": str(contract_type).lower() if contract_type else "",
                                "status": str(status).lower() if status else "",
                                "price": float(price) if price is not None else 0.0,
                                "assignee_id": MemberAuditAdapter._extract_int(row, "assignee_id", "assignee"),
                                "acceptor_id": MemberAuditAdapter._extract_int(row, "acceptor_id", "acceptor"),
                            }
                        )
                    return rows
                except Exception:
                    pass

        token = MemberAuditAdapter.get_token_for_character(character_id)
        if token:
            return EsiClient().get_character_contracts(character_id, token=token)
        return []

    @staticmethod
    def _candidate_tokens_for_character(character_id):
        token_model = MemberAuditAdapter._get_model("esi", "Token")
        if token_model is None:
            return []

        candidates = []
        candidate_filters = [
            {"character_id": character_id},
            {"character__character_id": character_id},
            {"character__id": character_id},
            {"character_ownership__character__character_id": character_id},
            {"character_ownership__character__id": character_id},
        ]

        for filter_kwargs in candidate_filters:
            try:
                queryset = token_model.objects.filter(**filter_kwargs).order_by("-id")
                if queryset.exists():
                    candidates.extend(list(queryset[:10]))
                    break
            except (FieldError, Exception):
                continue

        deduped = []
        seen_ids = set()
        for token in candidates:
            token_id = getattr(token, "pk", None)
            if token_id in seen_ids:
                continue
            seen_ids.add(token_id)
            deduped.append(token)
        return deduped

    @staticmethod
    def _extract_scopes_from_token(token):
        values = set()

        for attr in ("scopes", "scope", "token_scopes"):
            data = getattr(token, attr, None)
            if not data:
                continue
            if isinstance(data, str):
                values.update(x.strip() for x in data.split() if x.strip())
                values.update(x.strip() for x in data.split(",") if x.strip())
                continue
            try:
                values.update(str(x).strip() for x in list(data) if str(x).strip())
            except Exception:
                pass

        try:
            related = getattr(token, "scopes", None)
            if related is not None and hasattr(related, "all"):
                for row in related.all():
                    scope_value = getattr(row, "name", None) or getattr(row, "scope", None) or str(row)
                    if scope_value:
                        values.add(str(scope_value).strip())
        except Exception:
            pass

        return {v for v in values if v}

    # --- Capital ship asset/ownership scan ---

    CAPITAL_OWNERSHIP_CACHE_TTL = 300  # 5 minutes

    @staticmethod
    def get_capital_ownership(character_ids):
        """Return capital ship ownership data from MemberAudit assets, current ship,
        active contracts, and market sell orders.

        Returns a dict keyed by character_id, then by eve_type_id:
            {char_id: {type_id: {
                "asset_count": int,
                "is_current_ship": bool,
                "contract_count": int,
                "market_order_count": int,
            }}}

        Returns an empty dict if MemberAudit is not installed or no characters
        are found. This is a read-only query against MemberAudit's local
        database -- no ESI calls are made.

        Each character is processed and cached independently (per-character
        cache key) so that memory usage scales with one character's data at
        a time rather than the full set.
        """
        ids = set()
        for value in character_ids or []:
            if value is None:
                continue
            try:
                ids.add(int(value))
            except (TypeError, ValueError):
                continue
        if not ids:
            return {}

        result = {}
        for char_id in sorted(ids):
            char_data = MemberAuditAdapter._get_capital_ownership_single(char_id)
            if char_data:
                result[char_id] = char_data
        return result

    @staticmethod
    def _get_capital_ownership_single(char_id):
        """Fetch capital ownership data for a single character, with per-character caching."""
        from .audit_analysis.capital_ships import CAPITAL_SHIPS, CAPITAL_SHIP_GROUPS

        capital_type_ids = list(CAPITAL_SHIPS.keys())
        capital_group_ids = set(CAPITAL_SHIP_GROUPS)
        if not capital_type_ids:
            return {}

        CharacterModel = MemberAuditAdapter._get_model("memberaudit", "Character")
        CharacterAsset = MemberAuditAdapter._get_model("memberaudit", "CharacterAsset")
        CharacterShip = MemberAuditAdapter._get_model("memberaudit", "CharacterShip")
        CharacterContract = MemberAuditAdapter._get_model("memberaudit", "CharacterContract")
        CharacterContractItem = MemberAuditAdapter._get_model("memberaudit", "CharacterContractItem")
        CharacterMarketOrder = MemberAuditAdapter._get_model("memberaudit", "CharacterMarketOrder")
        if CharacterModel is None or (CharacterAsset is None and CharacterShip is None and CharacterContract is None and CharacterMarketOrder is None):
            return {}

        cache_key = f"securityaudit:capital_ownership:{char_id}"
        cached = cache.get(cache_key)
        if cached is not None:
            return cached

        # Active contract statuses that indicate the capital hasn't changed
        # hands yet. MemberAudit stores these as 2-char codes (see
        # CharacterContract.STATUS_OUTSTANDING / STATUS_IN_PROGRESS).
        ACTIVE_CONTRACT_STATUSES = {"os", "ip"}

        # Fetch the MemberAudit Character object for this character.
        ma_char = None
        try:
            ma_char = CharacterModel.objects.select_related("eve_character").get(
                eve_character__character_id=char_id
            )
        except CharacterModel.DoesNotExist:
            pass
        except Exception:
            LOGGER.debug("MemberAudit Character lookup failed for %s", char_id, exc_info=True)

        if ma_char is None:
            return {}

        char_data = {}

        def _ensure_entry(type_id):
            return char_data.setdefault(
                type_id, {
                    "asset_count": 0,
                    "is_current_ship": False,
                    "contract_count": 0,
                    "market_order_count": 0,
                }
            )

        # --- Assets ---
        if CharacterAsset is not None:
            try:
                # Prefer group-based matching so new capital hulls are
                # detected without maintaining a static type-id list.
                try:
                    assets = CharacterAsset.objects.filter(
                        character=ma_char,
                    ).filter(
                        Q(eve_type_id__in=capital_type_ids)
                        | Q(eve_type__eve_group_id__in=capital_group_ids)
                        | Q(eve_type__eve_group__id__in=capital_group_ids)
                    )
                except Exception:
                    assets = CharacterAsset.objects.filter(
                        character=ma_char,
                        eve_type_id__in=capital_type_ids,
                    )
                for asset in assets:
                    type_id = asset.eve_type_id
                    qty = max(asset.quantity or 0, 1 if asset.is_singleton else 0)
                    if type_id and qty:
                        entry = _ensure_entry(type_id)
                        entry["asset_count"] += qty
            except Exception:
                LOGGER.debug("CharacterAsset query failed for %s", char_id, exc_info=True)

        # --- Current ship ---
        if CharacterShip is not None:
            try:
                ship = CharacterShip.objects.get(character=ma_char)
                type_id = ship.eve_type_id
                group_id = None
                eve_type = getattr(ship, "eve_type", None)
                if eve_type is not None:
                    group_id = getattr(eve_type, "eve_group_id", None)
                    if group_id is None:
                        eve_group = getattr(eve_type, "eve_group", None)
                        group_id = getattr(eve_group, "id", None)
                if type_id and (type_id in CAPITAL_SHIPS or group_id in capital_group_ids):
                    entry = _ensure_entry(type_id)
                    entry["is_current_ship"] = True
            except CharacterShip.DoesNotExist:
                pass
            except Exception:
                LOGGER.debug("CharacterShip query failed for %s", char_id, exc_info=True)

        # --- Active contracts with capital items ---
        # Contracts where the character is the issuer and the contract is
        # still active (outstanding or in_progress). We check contract items
        # for capital ship type IDs. MemberAudit stores contracts from the
        # character's perspective (both issued and received), so we must
        # filter to issuer-only to detect capitals the character is selling.
        #
        # EveEntity (used for the issuer FK) uses the EVE Online ID as its
        # primary key, so contract.issuer_id IS the EVE character ID — no
        # need to resolve the related object.
        if CharacterContract is not None and CharacterContractItem is not None:
            capital_type_set = set(capital_type_ids)
            try:
                # prefetch_related batches all contract items into a single
                # follow-up query instead of one query per contract.
                contracts = CharacterContract.objects.prefetch_related(
                    "items"
                ).filter(character=ma_char)
                # MemberAudit can hold stale contract rows where status
                # remains "OS"/"IP" even after expiry. Apply an expiry
                # guard so we only treat currently active contracts as
                # ownership signals.
                try:
                    contracts = contracts.filter(
                        Q(date_expired__isnull=True) | Q(date_expired__gte=timezone.now())
                    )
                except Exception:
                    pass
                active_count = 0
                for contract in contracts:
                    try:
                        status = str(getattr(contract, "status", "") or "").lower()
                        if status not in ACTIVE_CONTRACT_STATUSES:
                            continue
                        active_count += 1
                        # issuer_id is the EveEntity PK = EVE character ID.
                        issuer_id = getattr(contract, "issuer_id", None)
                        if issuer_id is not None and int(issuer_id) != char_id:
                            continue
                        items = contract.items.all() if hasattr(contract, "items") else []
                        for item in items:
                            item_type_id = getattr(item, "eve_type_id", None)
                            if not item_type_id:
                                item_type_id = getattr(item, "type_id", None)
                            if not item_type_id:
                                continue
                            is_capital_type = int(item_type_id) in capital_type_set
                            if not is_capital_type:
                                eve_type = getattr(item, "eve_type", None)
                                group_id = getattr(eve_type, "eve_group_id", None) if eve_type else None
                                if group_id is None and eve_type is not None:
                                    eve_group = getattr(eve_type, "eve_group", None)
                                    group_id = getattr(eve_group, "id", None)
                                is_capital_type = group_id in capital_group_ids
                            if not is_capital_type:
                                continue
                            # is_included=True means the item is being
                            # offered by the issuer (selling). Skip items
                            # that are being requested in exchange.
                            is_included = getattr(item, "is_included", True)
                            if not is_included:
                                continue
                            qty = getattr(item, "quantity", None)
                            is_singleton = bool(getattr(item, "is_singleton", False))
                            try:
                                qty = int(qty) if qty is not None else 0
                            except (TypeError, ValueError):
                                qty = 0
                            qty = max(qty, 1 if is_singleton else 0, 1)
                            entry = _ensure_entry(int(item_type_id))
                            # Count hull units on active contracts, not just
                            # number of contracts containing a hull.
                            entry["contract_count"] += qty
                    except Exception:
                        LOGGER.debug(
                            "Failed to process contract %s for char %s",
                            getattr(contract, "pk", "?"), char_id, exc_info=True,
                        )
                if active_count > 0 and not char_data:
                    LOGGER.debug(
                        "Character %s has %d active contracts but no "
                        "capital items found in any of them.",
                        char_id, active_count,
                    )
            except Exception:
                LOGGER.warning(
                    "CharacterContract query failed for %s", char_id, exc_info=True,
                )

        # --- Active market sell orders for capitals ---
        # MemberAudit (as of 5.1.0) does not persist market orders as a
        # Django model, so we fall back to ESI. If a future MemberAudit
        # version adds a CharacterMarketOrder model, we'll use it;
        # otherwise we query ESI directly with the character's token.
        if CharacterMarketOrder is not None:
            try:
                orders = CharacterMarketOrder.objects.filter(
                    character=ma_char,
                    eve_type_id__in=capital_type_ids,
                )
                for order in orders:
                    # Only count sell orders (is_buy_order is False or None).
                    is_buy = getattr(order, "is_buy_order", False)
                    if is_buy:
                        continue
                    # Check if the order is still active. MemberAudit may
                    # store state as "open" or use a boolean is_active.
                    state = str(getattr(order, "state", "") or "").lower()
                    if state and state not in {"open", "active", ""}:
                        continue
                    type_id = getattr(order, "eve_type_id", None) or getattr(order, "type_id", None)
                    if type_id:
                        entry = _ensure_entry(int(type_id))
                        entry["market_order_count"] += 1
            except Exception:
                LOGGER.debug("CharacterMarketOrder query failed for %s", char_id, exc_info=True)
        else:
            # ESI fallback: fetch the character's market orders via ESI.
            # This requires a valid token for the character.
            token = MemberAuditAdapter.get_token_for_character(char_id)
            if token:
                try:
                    from .esi_client import EsiClient

                    esi_orders = EsiClient().get_character_market_orders(
                        char_id, token=token
                    )
                    capital_type_set = set(capital_type_ids)
                    for order in esi_orders or []:
                        if order.get("is_buy_order"):
                            continue
                        state = str(order.get("state", "") or "").lower()
                        # ESI market order states: open, closed, expired,
                        # cancelled, character. Only "open" orders are active.
                        if state and state != "open":
                            continue
                        type_id = order.get("type_id")
                        if not type_id:
                            continue
                        try:
                            type_id_int = int(type_id)
                        except (TypeError, ValueError):
                            continue
                        is_capital = type_id_int in capital_type_set
                        if not is_capital:
                            try:
                                type_info = EsiClient().get_type_info(type_id_int)
                                group_id = type_info.get("group_id")
                                is_capital = group_id in capital_group_ids
                            except Exception:
                                is_capital = False
                        if is_capital:
                            entry = _ensure_entry(type_id_int)
                            entry["market_order_count"] += 1
                except Exception:
                    LOGGER.debug(
                        "ESI market orders fetch failed for %s",
                        char_id,
                        exc_info=True,
                    )

        cache.set(cache_key, char_data, MemberAuditAdapter.CAPITAL_OWNERSHIP_CACHE_TTL)
        return char_data

    @staticmethod
    def _get_model(app_label, model_name):
        try:
            return apps.get_model(app_label, model_name)
        except LookupError:
            LOGGER.debug("Model not found: %s.%s", app_label, model_name)
            return None

    @staticmethod
    def _find_character_object(character_name=None, character_id=None, user=None):
        candidates = []

        if user is not None:
            candidates.extend(MemberAuditAdapter.get_declared_characters(user))
        elif character_name:
            implied_user = MemberAuditAdapter.find_user_by_main_name(character_name)
            if implied_user is not None:
                candidates.extend(MemberAuditAdapter.get_declared_characters(implied_user))

        for model in (
            MemberAuditAdapter._get_model("esi", "Character"),
            MemberAuditAdapter._get_model("memberaudit", "Character"),
        ):
            if model is None:
                continue
            for query in MemberAuditAdapter._character_queries(character_name=character_name, character_id=character_id):
                try:
                    row = model.objects.filter(**query).first()
                    if row is not None:
                        candidates.append(row)
                        break
                except (FieldError, Exception):
                    continue

        for row in candidates:
            row_id = MemberAuditAdapter._extract_int(row, "character_id", "id")
            row_name = MemberAuditAdapter._extract_text(row, "character_name", "name", "character")
            if character_id and row_id == int(character_id):
                return row
            if character_name and row_name and row_name.casefold() == character_name.casefold():
                return row

        return candidates[0] if candidates else None

    @staticmethod
    def _character_queries(character_name=None, character_id=None):
        queries = []
        if character_id is not None:
            queries.extend(
                [
                    {"character_id": character_id},
                    {"id": character_id},
                ]
            )
        if character_name:
            queries.extend(
                [
                    {"character_name__iexact": character_name},
                    {"name__iexact": character_name},
                ]
            )
        return queries

    @staticmethod
    def _extract_text(obj, *attrs):
        for attr in attrs:
            value = getattr(obj, attr, None)
            if isinstance(value, str) and value.strip():
                return value.strip()
        return None

    @staticmethod
    def _extract_int(obj, *attrs):
        for attr in attrs:
            value = getattr(obj, attr, None)
            if hasattr(value, "pk"):
                value = value.pk
            try:
                if value is not None:
                    return int(value)
            except (TypeError, ValueError):
                continue
        return None

    @staticmethod
    def _alliance_logo_url(alliance_id, size=64):
        if not alliance_id:
            return ""
        return f"https://images.evetech.net/alliances/{alliance_id}/logo?size={size}"

    @staticmethod
    def search_entities(term, limit=20, allowed_types=None):
        """Search character/corporation/alliance names from available EVE universe tables."""
        if allowed_types is None:
            allowed_types = ("character", "corporation", "alliance")
        term = (term or "").strip()
        if len(term) < 2:
            return []
        cache_key = f"securityaudit:entity_search:{term.casefold()}:{int(limit)}:{','.join(sorted(allowed_types))}"
        cached = cache.get(cache_key)
        if cached is not None:
            return cached

        rows = []
        seen = set()
        type_config = [
            (
                "character",
                [
                    ("esi", "Character"),
                    ("memberaudit", "Character"),
                    ("eveonline", "EveCharacter"),
                    ("eveuniverse", "EveEntity"),
                ],
                MemberAuditAdapter._portrait_url,
            ),
            (
                "corporation",
                [
                    ("esi", "Corporation"),
                    ("memberaudit", "Corporation"),
                    ("eveonline", "EveCorporationInfo"),
                    ("eveuniverse", "EveEntity"),
                ],
                MemberAuditAdapter._corp_logo_url,
            ),
            (
                "alliance",
                [
                    ("esi", "Alliance"),
                    ("memberaudit", "Alliance"),
                    ("eveonline", "EveAllianceInfo"),
                    ("eveuniverse", "EveEntity"),
                ],
                MemberAuditAdapter._alliance_logo_url,
            ),
        ]
        type_config = [c for c in type_config if c[0] in allowed_types]
        for entity_type, model_specs, image_url_fn in type_config:
            for app_label, model_name in model_specs:
                model = MemberAuditAdapter._get_model(app_label, model_name)
                if model is None:
                    continue
                for lookup in ("name__icontains", "character_name__icontains", "corporation_name__icontains", "alliance_name__icontains"):
                    try:
                        extra = {}
                        if model._meta.app_label == "eveuniverse" and model._meta.model_name == "eveentity":
                            extra = {"category": entity_type}
                        queryset = model.objects.filter(**{lookup: term}, **extra).order_by("id")[: max(limit * 2, 20)]
                    except (FieldError, Exception):
                        continue
                    for obj in queryset:
                        entity_id = MemberAuditAdapter._extract_int(obj, "eve_character_id", "character_id", "corporation_id", "alliance_id", "id")
                        entity_name = MemberAuditAdapter._extract_text(obj, "character_name", "corporation_name", "alliance_name", "name")
                        if not entity_name:
                            continue
                        dedupe = (entity_type, entity_id)
                        if dedupe in seen:
                            continue
                        seen.add(dedupe)
                        rows.append(
                            {
                                "id": entity_id,
                                "name": entity_name,
                                "type": entity_type,
                                "image_url": image_url_fn(entity_id) if entity_id and entity_id > 0 else "",
                            }
                        )
                        if len(rows) >= limit:
                            cache.set(cache_key, rows, MemberAuditAdapter.SEARCH_CACHE_TTL)
                            return rows
        cache.set(cache_key, rows, MemberAuditAdapter.SEARCH_CACHE_TTL)
        return rows
