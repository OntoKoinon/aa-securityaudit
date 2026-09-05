from decimal import Decimal

from ...models import AuditFinding, AuditRelationshipCounterparty, FinancialException
from ..esi_client import EsiClient
from ..janice_client import JaniceClient
from ..memberaudit_adapter import MemberAuditAdapter

REQUIRED_WALLET_SCOPE = "esi-wallet.read_character_wallet.v1"
REQUIRED_CONTRACT_SCOPE = "esi-contracts.read_character_contracts.v1"

class FinancialMixin:

    def _load_financial_exceptions(self):
        chars = set(
            FinancialException.objects.filter(
                entity_type=FinancialException.TYPE_CHARACTER, is_active=True
            ).values_list("entity_id", flat=True)
        )
        corps = set(
            FinancialException.objects.filter(
                entity_type=FinancialException.TYPE_CORPORATION, is_active=True
            ).values_list("entity_id", flat=True)
        )
        self.exception_character_ids = chars
        self.exception_corporation_ids = corps
        self.exception_ids = chars | corps
        self.exception_corp_cache = {}

    def _is_financial_exception(self, entity_id):
        if not entity_id:
            return False
        if entity_id in self.exception_ids:
            return True
        if not self.exception_corporation_ids:
            return False
        if entity_id in self.exception_corp_cache:
            return self.exception_corp_cache[entity_id]
        try:
            character = self.esi.get_character(entity_id)
            corp_id = character.get("corporation_id")
            if corp_id and corp_id in self.exception_corporation_ids:
                result = True
            else:
                result = False
        except Exception:
            result = False
        self.exception_corp_cache[entity_id] = result
        return result

    def _process_transactional_signals(self, audit_run, character_ids, progress_callback=None):
        missing_scopes = set()
        total_score = 0
        all_counterparties = {}
        resolved = self.esi.resolve_names(character_ids)
        self_identity_ids = set(character_ids)
        total_chars = max(len(character_ids), 1)

        # Batch-fetch alliance IDs for all characters. ESI's get_character
        # is cached, so this avoids N separate MemberAudit snapshot lookups.
        character_alliances = {}
        for _cid in character_ids:
            try:
                _alliance = (self.esi.get_character(_cid) or {}).get("alliance_id")
            except Exception:
                _alliance = None
            if not _alliance:
                _snapshot = MemberAuditAdapter.get_character_snapshot(character_id=_cid)
                _alliance = _snapshot.get("alliance_id") if _snapshot else None
            character_alliances[_cid] = _alliance

        corp_cache = {}

        for idx, char_id in enumerate(character_ids, start=1):
            available_scopes = MemberAuditAdapter.get_available_scopes_for_character(char_id)
            if REQUIRED_WALLET_SCOPE not in available_scopes:
                missing_scopes.add(REQUIRED_WALLET_SCOPE)
                if callable(progress_callback):
                    progress_callback(idx, total_chars, char_id)
                continue

            journal = MemberAuditAdapter.get_wallet_journal(char_id)
            if journal is None:
                token = MemberAuditAdapter.get_token_for_character(char_id)
                if token:
                    try:
                        journal = self.esi.get_character_wallet_journal(char_id, token=token)
                    except Exception:
                        journal = None

            if not journal:
                if callable(progress_callback):
                    progress_callback(idx, total_chars, char_id)
                continue

            threshold = self.policy.large_donation_isk_threshold
            for row in journal:
                ref_type = row.get("ref_type")
                if ref_type is None:
                    ref_type = getattr(row, "ref_type", None)
                if ref_type != "player_donation":
                    continue
                raw_amount = Decimal(str(row.get("amount") or 0))
                if abs(raw_amount) < threshold:
                    continue
                first_party = row.get("first_party_id")
                second_party = row.get("second_party_id")
                if not first_party or not second_party:
                    continue
                if first_party == char_id:
                    counterparty_id = second_party
                elif second_party == char_id:
                    counterparty_id = first_party
                elif raw_amount > 0:
                    counterparty_id = first_party
                else:
                    counterparty_id = second_party
                if not counterparty_id or counterparty_id in self_identity_ids:
                    continue
                if self._is_financial_exception(counterparty_id):
                    continue

                if counterparty_id not in corp_cache:
                    try:
                        corp_cache[counterparty_id] = (self.esi.get_corporation(counterparty_id) or {}).get("alliance_id")
                    except Exception:
                        corp_cache[counterparty_id] = False
                source_alliance = character_alliances.get(char_id)
                if source_alliance and corp_cache[counterparty_id] == source_alliance:
                    continue

                if counterparty_id not in all_counterparties:
                    all_counterparties[counterparty_id] = {
                        "total": Decimal("0"),
                        "sources": set(),
                        "count": 0,
                    }
                all_counterparties[counterparty_id]["total"] += raw_amount
                all_counterparties[counterparty_id]["sources"].add(char_id)
                all_counterparties[counterparty_id]["count"] += 1
            if callable(progress_callback):
                progress_callback(idx, total_chars, char_id)

        if not all_counterparties:
            return sorted(missing_scopes), total_score

        ids_to_resolve = set(all_counterparties.keys()) | self_identity_ids
        resolved.update(self.esi.resolve_names(ids_to_resolve - set(resolved.keys())))
        target_name = audit_run.target.character_name or resolved.get(min(character_ids)) or str(min(character_ids))

        counterparties_to_create = []
        for counterparty_id, data in all_counterparties.items():
            net_amount = data["total"]
            total_amount = abs(net_amount)
            counterparty_name = resolved.get(counterparty_id) or str(counterparty_id)
            occurrence_count = data.get("count", 1)
            source_list = sorted(str(resolved.get(s) or s) for s in data["sources"])

            if occurrence_count == 1:
                severity = AuditFinding.SEVERITY_LOW
                score = 10
                title = "Large player donation detected"
                if net_amount < 0:
                    details = f"{target_name} sent {total_amount:,.2f} ISK to {counterparty_name}."
                else:
                    details = f"{target_name} received {total_amount:,.2f} ISK from {counterparty_name}."
            else:
                severity = AuditFinding.SEVERITY_MEDIUM
                score = occurrence_count * 10
                title = "Large player donation detected"
                if net_amount < 0:
                    details = f"{target_name} sent {total_amount:,.2f} ISK to {counterparty_name} across {occurrence_count} donations."
                else:
                    details = f"{target_name} received {total_amount:,.2f} ISK from {counterparty_name} across {occurrence_count} donations."

            counterparties_to_create.append(AuditRelationshipCounterparty(
                audit_run=audit_run,
                counterparty_type=AuditRelationshipCounterparty.COUNTERPARTY_ISK_DONATION,
                character_id=counterparty_id,
                character_name=counterparty_name,
                total_amount=total_amount,
                is_outgoing=(net_amount < 0),
                event_count=occurrence_count,
                notes=f"Sources: {', '.join(source_list)}; occurrences: {occurrence_count}; total: {total_amount:,.2f} ISK",
            ))
            self._create_finding(
                audit_run,
                AuditFinding.TYPE_LARGE_DONATION,
                severity,
                title,
                details,
                score,
                evidence=[
                    ("counterparty_character_id", str(counterparty_id)),
                    ("total_isk", str(total_amount)),
                    ("occurrence_count", str(occurrence_count)),
                    ("source_characters", ", ".join(source_list)),
                ],
            )
            total_score += score

        if counterparties_to_create:
            AuditRelationshipCounterparty.objects.bulk_create(counterparties_to_create, batch_size=500)

        return sorted(missing_scopes), total_score

    def _process_contract_signals(self, audit_run, character_ids, progress_callback=None):
        missing_scopes = set()
        total_score = 0
        resolved = self.esi.resolve_names(character_ids)
        threshold = self.policy.free_contract_value_threshold
        total_chars = max(len(character_ids), 1)
        contract_counterparties_to_create = []

        for idx, char_id in enumerate(character_ids, start=1):
            available_scopes = MemberAuditAdapter.get_available_scopes_for_character(char_id)
            if REQUIRED_CONTRACT_SCOPE not in available_scopes:
                missing_scopes.add(REQUIRED_CONTRACT_SCOPE)
                if callable(progress_callback):
                    progress_callback(idx, total_chars, char_id)
                continue

            try:
                contracts = MemberAuditAdapter.get_character_contracts(char_id)
            except Exception:
                if callable(progress_callback):
                    progress_callback(idx, total_chars, char_id)
                continue
            if not contracts:
                if callable(progress_callback):
                    progress_callback(idx, total_chars, char_id)
                continue

            candidate_contracts = []
            contract_party_ids = set()
            for contract in contracts:
                if contract.get("type") != "item_exchange":
                    continue
                if contract.get("status") != "finished":
                    continue
                if float(contract.get("price") or 0) != 0:
                    continue
                acceptor = contract.get("acceptor_id")
                assignee = contract.get("assignee_id")
                if char_id not in {acceptor, assignee}:
                    continue

                contract_id = contract.get("contract_id")
                if not contract_id:
                    continue
                issuer = contract.get("issuer_id")
                if self._is_financial_exception(issuer) or self._is_financial_exception(acceptor):
                    continue
                if issuer:
                    contract_party_ids.add(issuer)
                if acceptor:
                    contract_party_ids.add(acceptor)
                candidate_contracts.append(contract)

            if contract_party_ids:
                unresolved_party_ids = contract_party_ids - set(resolved.keys())
                if unresolved_party_ids:
                    resolved.update(self.esi.resolve_names(unresolved_party_ids))

            # Fetch the token once per character, not per contract.
            token = MemberAuditAdapter.get_token_for_character(char_id)
            for contract in candidate_contracts:
                acceptor = contract.get("acceptor_id")
                contract_id = contract.get("contract_id")
                try:
                    items = self.esi.get_character_contract_items(char_id, contract_id, token=token)
                except Exception:
                    continue
                if not items:
                    continue

                items = [
                    {"type_id": item.get("type_id"), "quantity": item.get("quantity") or 1}
                    for item in items
                    if item.get("is_included") and item.get("type_id")
                ]
                value = self.janice.price_items(items)
                if value <= threshold:
                    continue

                issuer = contract.get("issuer_id")
                target_name = resolved.get(char_id) or str(char_id)
                details = (
                    f"Character {target_name} accepted free item-exchange contract {contract_id} "
                    f"worth {value:,.2f} ISK."
                )
                issuer_name = resolved.get(issuer) or str(issuer)
                acceptor_name = resolved.get(acceptor) or str(acceptor)

                contract_counterparties_to_create.append(AuditRelationshipCounterparty(
                    audit_run=audit_run,
                    counterparty_type=AuditRelationshipCounterparty.COUNTERPARTY_FREE_CONTRACT,
                    character_id=acceptor,
                    character_name=acceptor_name,
                    total_amount=value,
                    event_count=1,
                    notes=(
                        f"Contract {contract_id}; issuer: {issuer_name}; "
                        f"acceptor: {acceptor_name}; value: {value:,.2f} ISK"
                    ),
                ))
                self._create_finding(
                    audit_run,
                    AuditFinding.TYPE_FREE_CONTRACT,
                    AuditFinding.SEVERITY_HIGH,
                    "Free item-exchange contract above threshold",
                    details,
                    20,
                    evidence=[
                        ("contract_id", str(contract_id)),
                        ("source_character", str(target_name)),
                        ("issuer_id", str(issuer)),
                        ("acceptor_id", str(acceptor)),
                        ("item_value_isk", str(value)),
                    ],
                )
                total_score += 20
            if callable(progress_callback):
                progress_callback(idx, total_chars, char_id)

        if contract_counterparties_to_create:
            AuditRelationshipCounterparty.objects.bulk_create(contract_counterparties_to_create, batch_size=500)

        return sorted(missing_scopes), total_score