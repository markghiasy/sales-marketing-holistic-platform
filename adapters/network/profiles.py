"""Synthetic strategic assertions; validation checks provenance, not semantic truth."""

from copy import deepcopy
from datetime import datetime
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .model import GraphQuery, timestamp

Facet = Literal["experience", "need", "resource", "decision_role", "relationship", "constraint"]
Basis = Literal["self_declared", "reported", "observed"]
COVERAGE = (
    "Synthetic authored examples, not independently verified facts or successful model extraction. "
    "Quote, identity and time checks are mechanical, not semantic proof. Organization statements "
    "do not establish authority to represent the organization. Reviews and extraction are local "
    "demo memory and reset on restart/reset."
)


class Candidate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    evidence_id: str = Field(min_length=1, max_length=160)
    subject_id: str = Field(min_length=1, max_length=160)
    facet: Facet
    label: str = Field(min_length=1, max_length=500)
    context_id: str = Field(default="", max_length=160)
    basis: Basis
    quote: str = Field(min_length=1, max_length=3000)
    valid_from: datetime | None = None
    valid_to: datetime | None = None

    @field_validator("valid_from", "valid_to")
    @classmethod
    def normalize_time(cls, value):
        return timestamp(value) if value is not None else None

    @field_validator("label", "quote")
    @classmethod
    def nonempty(cls, value):
        if not value.strip():
            raise ValueError("Label and exact quotation cannot be blank")
        return value

    @model_validator(mode="after")
    def valid_interval(self):
        if self.valid_from and self.valid_to and self.valid_to <= self.valid_from:
            raise ValueError("Validity end must be after validity start")
        return self


class Extraction(BaseModel):
    model_config = ConfigDict(extra="forbid")
    assertions: list[Candidate] = Field(default_factory=list, max_length=12)


class StrategicAssertion(Candidate):
    # Stored records cite one or more sources; candidates cite exactly one source.
    evidence_id: str = Field(default="", max_length=160, exclude=True)
    id: str = Field(min_length=1, max_length=160)
    observed_at: datetime
    status: Literal["pending", "confirmed", "rejected"]
    evidence_ids: list[str] = Field(min_length=1, max_length=8)
    claimant_id: str = Field(min_length=1, max_length=160)
    model: str = Field(default="", max_length=200)
    synthetic: bool = True
    origin: str = Field(default="", max_length=200)
    reviewed_at: datetime | None = None

    @field_validator("observed_at", "reviewed_at")
    @classmethod
    def normalize_observation(cls, value):
        return timestamp(value) if value is not None else None


def validate_assertion(data, assertion):
    """Validate mechanical provenance only; a human must assess attribution and meaning."""
    value = StrategicAssertion.model_validate(assertion)
    nodes = {n["id"]: n for n in data["nodes"]}
    if value.subject_id not in nodes or value.claimant_id not in nodes:
        raise ValueError("Unknown subject or claimant")
    if nodes[value.claimant_id]["kind"] != "person":
        raise ValueError("Claimant must be a known person")
    if value.context_id and value.context_id not in nodes:
        raise ValueError("Unknown assertion context")
    evidence = {e["id"]: e for e in data.get("evidence", [])}
    for eid in value.evidence_ids:
        source = evidence.get(eid)
        if not source or value.quote not in source.get("text", ""):
            raise ValueError("Every cited source must contain the exact quotation")
        if source.get("author_id") != value.claimant_id:
            raise ValueError("Claimant must match the source author")
        if timestamp(source["at"]) > value.observed_at:
            raise ValueError("Assertion cannot be observed before its evidence")
    if (
        value.basis == "self_declared"
        and nodes[value.subject_id]["kind"] == "person"
        and value.subject_id != value.claimant_id
    ):
        raise ValueError("Personal self-declaration must be authored by the subject")
    if value.valid_from and value.valid_from > value.observed_at:
        raise ValueError("Future assertions cannot enter the profile")
    return value.model_dump(mode="json", exclude_none=True)


def _visible_assertions(data, query):
    reviews = sorted(data.get("strategic_reviews", []), key=lambda r: timestamp(r["at"]))
    for original in data.get("strategic_assertions", []):
        row = deepcopy(original)
        for event in reviews:
            if event["id"] == row["id"] and timestamp(event["at"]) <= query.as_of:
                row.update(
                    status=event["status"], subject_id=event["subject_id"], reviewed_at=event["at"]
                )
        try:
            item = validate_assertion(data, row)
        except (ValueError, KeyError, TypeError):
            continue
        if timestamp(item["observed_at"]) > query.as_of:
            continue
        start, end = item.get("valid_from"), item.get("valid_to")
        if start and timestamp(start) > query.as_of:
            continue
        item["active"] = not end or query.as_of < timestamp(end)
        if not item["active"] and query.mode != "history":
            continue
        yield item


def eligible_assertions(data, query, include_pending=False):
    """Answer retrieval never inherits the query's UI pending toggle."""
    statuses = {"confirmed", "pending"} if include_pending else {"confirmed"}
    return [r for r in _visible_assertions(data, query) if r["status"] in statuses]


def profile_context(data, query: GraphQuery):
    nodes = {n["id"]: n for n in data["nodes"]}
    if query.focus not in nodes:
        raise KeyError(query.focus)
    rows = (
        list(_visible_assertions(data, query))
        if query.include_pending
        else eligible_assertions(data, query)
    )
    rows = [r for r in rows if query.focus in (r["subject_id"], r["claimant_id"], r["context_id"])]
    evidence_ids = {eid for row in rows for eid in row["evidence_ids"]}
    return {
        "entity": deepcopy(nodes[query.focus]),
        "assertions": rows,
        "evidence": [deepcopy(e) for e in data.get("evidence", []) if e["id"] in evidence_ids],
        "entities": deepcopy(data["nodes"]),
        "as_of": query.as_of.isoformat(),
        "mode": query.mode,
        "coverage": COVERAGE,
    }


def prepare_extraction(data, query: GraphQuery):
    nodes = {n["id"]: n for n in data["nodes"]}
    if query.focus not in nodes:
        raise KeyError(query.focus)
    # Subject/context attribution comes from authored demo records, never model-generated links.
    related = {
        eid
        for r in data.get("strategic_assertions", [])
        if query.focus in (r["subject_id"], r["claimant_id"], r.get("context_id"))
        and timestamp(r["observed_at"]) <= query.as_of
        for eid in r["evidence_ids"]
    }
    evidence = [
        deepcopy(e)
        for e in data.get("evidence", [])
        if e.get("synthetic") is True
        and e.get("author_id") in nodes
        and nodes[e["author_id"]]["kind"] == "person"
        and (e["id"] in related or e["author_id"] == query.focus)
        and timestamp(e["at"]) <= query.as_of
        and 0 < len(e.get("text", "")) <= 4000
    ][:24]
    return {
        "entity": deepcopy(nodes[query.focus]),
        "entities": deepcopy(data["nodes"]),
        "evidence": evidence,
        "as_of": query.as_of.isoformat(),
        "mode": query.mode,
        "instructions": (
            "Propose at most 12 assertions from these synthetic sources. Copy an exact quotation. "
            "Preserve the actual subject: an organization need belongs to the organization, not "
            "the author. Claimants are derived from source authors. Self-declared personal "
            "assertions must name the author. A reported need is not personal ownership. Preserve "
            "conditions, dates and explicit lack of budget authority. Do not infer abilities, "
            "buying authority, introduction willingness or relationships. Use only listed IDs. "
            "Return no assertion where the source is insufficient. All results await human review."
        ),
    }


def validate_extraction(data, query, result, model):
    result = Extraction.model_validate(result)
    allowed = {e["id"]: e for e in prepare_extraction(data, query)["evidence"]}
    pending = []
    for candidate in result.assertions:
        source = allowed.get(candidate.evidence_id)
        if source is None:
            raise ValueError("Extraction source is not in the allowed evidence pack")
        item = candidate.model_dump(mode="json")
        evidence_id = item.pop("evidence_id")
        item.update(
            id=f"strategy:{uuid4().hex}",
            evidence_ids=[evidence_id],
            claimant_id=source["author_id"],
            status="pending",
            observed_at=query.as_of.isoformat(),
            model=model,
            synthetic=True,
            origin="model_proposal_mechanically_validated",
        )
        pending.append(validate_assertion(data, item))
    return pending
