from django.apps import apps
from django.core.exceptions import FieldError


# Field lookups that may map a blacklist row to a character ID.
_ID_LOOKUPS = (
    "character_id",
    "char_id",
    "pilot_id",
    "offender_id",
    "entity_id",
    "eve_id",
    "character__character_id",
    "character__id",
    "pilot__character_id",
    "pilot__id",
)

# Field lookups that may map a blacklist row to a character name.
_NAME_LOOKUPS = (
    "character_name__iexact",
    "name__iexact",
    "character__character_name__iexact",
    "character__name__iexact",
    "pilot__character_name__iexact",
    "pilot__name__iexact",
)


class BlacklistAdapter:
    @staticmethod
    def is_available():
        return bool(BlacklistAdapter._blacklist_models())

    # ------------------------------------------------------------------
    # Model discovery
    # ------------------------------------------------------------------

    @staticmethod
    def _blacklist_models():
        models = []
        for model in apps.get_models():
            dotted = f"{model._meta.app_label}.{model.__name__}".lower()
            if "blacklist" not in dotted:
                continue
            models.append(model)
        return models

    # ------------------------------------------------------------------
    # Batched ID lookups
    # ------------------------------------------------------------------

    @staticmethod
    def get_blacklisted_character_ids(character_ids):
        """Return the subset of *character_ids* that appear on any blacklist.

        Uses ``__in`` batch queries — one query per (model, lookup) pair —
        instead of one query per character per lookup.
        """
        ids = BlacklistAdapter._normalize_ids(character_ids)
        if not ids:
            return set()

        matched = set()
        for model in BlacklistAdapter._blacklist_models():
            for lookup in _ID_LOOKUPS:
                matched |= BlacklistAdapter._batch_match_ids(model, lookup, ids)
        return matched

    @staticmethod
    def _batch_match_ids(model, lookup, ids):
        """Try a single ``filter(**{lookup + "__in"}): values_list`` query.

        Returns the set of IDs from *ids* that matched. Falls back to an
        empty set if the lookup is invalid for this model.
        """
        try:
            qs = model.objects.filter(**{f"{lookup}__in": ids})
            # values_list returns the raw column values; for relation lookups
            # these are the FK's _id column values, which match our integer IDs.
            raw_values = qs.values_list(lookup, flat=True)
            return {int(v) for v in raw_values if v is not None and int(v) in ids}
        except (FieldError, Exception):
            return set()

    # ------------------------------------------------------------------
    # Batched name lookups
    # ------------------------------------------------------------------

    @staticmethod
    def get_blacklisted_character_names(character_names):
        """Return the subset of *character_names* that appear on any blacklist."""
        names = {str(value).strip() for value in character_names if str(value).strip()}
        if not names:
            return set()

        matched = set()
        for model in BlacklistAdapter._blacklist_models():
            for lookup in _NAME_LOOKUPS:
                try:
                    qs = model.objects.filter(**{f"{lookup}__in": list(names)})
                    # Re-read the matched names from the records so we return
                    # the original casing from the input set.
                    raw_values = qs.values_list(lookup.replace("__iexact", ""), flat=True)
                    for raw in raw_values:
                        if raw:
                            for name in names:
                                if str(raw).lower() == name.lower():
                                    matched.add(name)
                except (FieldError, Exception):
                    continue
        return matched

    # ------------------------------------------------------------------
    # Batched reason lookups
    # ------------------------------------------------------------------

    @staticmethod
    def get_blacklist_reasons(character_ids):
        """Return ``{character_id: reason}`` for blacklisted characters.

        Uses batched ``__in`` queries and extracts reasons using
        ``values()`` to avoid instantiating full ORM objects.
        """
        if not character_ids or not BlacklistAdapter.is_available():
            return {}

        ids = BlacklistAdapter._normalize_ids(character_ids)
        if not ids:
            return {}

        reason_fields = ("reason", "notes", "description", "comment", "ban_reason")
        results = {}

        for model in BlacklistAdapter._blacklist_models():
            for lookup in _ID_LOOKUPS:
                try:
                    # Build a values() query that selects the lookup field
                    # plus any reason fields that exist on this model.
                    available = []
                    for f in reason_fields:
                        try:
                            model._meta.get_field(f)
                            available.append(f)
                        except Exception:
                            pass
                    if not available:
                        continue

                    qs = model.objects.filter(**{f"{lookup}__in": ids}).values(lookup, *available)
                    for row in qs:
                        raw = row.get(lookup)
                        if raw is None:
                            continue
                        try:
                            cid = int(raw)
                        except (TypeError, ValueError):
                            continue
                        if cid in ids and cid not in results:
                            reason = ""
                            for f in available:
                                val = row.get(f)
                                if val:
                                    reason = str(val)
                                    break
                            if reason and cid not in results:
                                results[cid] = reason
                except (FieldError, Exception):
                    continue

        return results

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _normalize_ids(character_ids):
        ids = set()
        for value in character_ids or []:
            if value is None:
                continue
            try:
                ids.add(int(value))
            except (TypeError, ValueError):
                continue
        return ids

    @staticmethod
    def _extract_reason(record):
        for field in ("reason", "notes", "description", "comment", "ban_reason"):
            value = getattr(record, field, None)
            if value:
                return str(value)
        return ""
