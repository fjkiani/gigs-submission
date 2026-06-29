"""Tests for cashcard_config.InstanceConfig.

Covers the contract: every validator rejects the wrong thing, the frozen
model can't be mutated, and a happy-path config round-trips through JSON.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from task2_cashcard.cashcard_config import (
    CONTACT_BUCKETS,
    SUPPORTED_PROVIDERS,
    ContextVarSpec,
    Guardrails,
    InstanceConfig,
    IntentHandler,
    RoutingRule,
    TriggerKindSpec,
    TriggerSpec,
    TwoHopEscalation,
)

# Local email-literal workaround (Write tool obfuscates raw '@' patterns).
AT = "@"


# ---- helpers -----------------------------------------------------------------


def _good_routing_rules() -> tuple[RoutingRule, ...]:
    """A routing rule set that covers every contact bucket."""
    return (
        RoutingRule(intent="install_esim", handler=IntentHandler.AGENT, bucket="esim_activation"),
        RoutingRule(intent="plan_info", handler=IntentHandler.AGENT, bucket="plan_questions"),
        RoutingRule(intent="device_compat", handler=IntentHandler.AGENT, bucket="devices"),
        RoutingRule(intent="roaming_info", handler=IntentHandler.AGENT, bucket="roaming"),
        RoutingRule(intent="submit_porting", handler=IntentHandler.TIER1_HUMAN, bucket="port_in"),
        RoutingRule(intent="other", handler=IntentHandler.TIER1_HUMAN, bucket="other"),
    )


def _good_context_vars() -> tuple[ContextVarSpec, ...]:
    return (
        ContextVarSpec(name="subscription_id", required=True, source="session.subscription_id"),
        ContextVarSpec(name="sim_id", required=True, source="session.sim_id"),
        ContextVarSpec(name="user_id", required=True, source="session.user_id"),
        ContextVarSpec(name="device_model", required=False, source="session.device_model"),
    )


def _good_triggers() -> tuple[TriggerSpec, ...]:
    return (
        TriggerSpec(kind=TriggerKindSpec.LOW_CONFIDENCE, priority=1),
        TriggerSpec(kind=TriggerKindSpec.WRITE_REQUESTED, priority=2),
        TriggerSpec(kind=TriggerKindSpec.RESTRICTED_SUBSCRIPTION, priority=3),
    )


def _good_mix() -> dict[str, float]:
    return {
        "esim_activation": 0.35,
        "plan_questions": 0.25,
        "devices": 0.15,
        "roaming": 0.10,
        "port_in": 0.10,
        "other": 0.05,
    }


def _good_two_hop() -> TwoHopEscalation:
    return TwoHopEscalation(
        tier1_target=f"tier1{AT}cashcard.example",
        tier2_target=f"tier2{AT}gigs.example",
    )


def _good_config(**overrides: object) -> InstanceConfig:
    defaults: dict[str, object] = {
        "tenant_id": "proj_cashcard",
        "country": "US",
        "sim_types": ("eSIM",),
        "providers": ("p3",),
        "contact_mix_prior": _good_mix(),
        "routing_rules": _good_routing_rules(),
        "context_variables": _good_context_vars(),
        "guardrails": Guardrails(),
        "escalation_triggers": _good_triggers(),
        "two_hop": _good_two_hop(),
    }
    defaults.update(overrides)
    return InstanceConfig(**defaults)  # type: ignore[arg-type]


# ---- happy path --------------------------------------------------------------


class TestHappyPath:
    def test_minimal_valid_config_builds(self) -> None:
        cfg = _good_config()
        assert cfg.tenant_id == "proj_cashcard"
        assert cfg.country == "US"
        assert cfg.sim_types == ("eSIM",)

    def test_default_guardrails_are_read_only(self) -> None:
        cfg = _good_config()
        assert cfg.guardrails.read_only_writes is True
        assert cfg.guardrails.refuse_pii_writes is True
        assert cfg.guardrails.refuse_irreversible_actions is True

    def test_default_staleness_ceiling_one_hour(self) -> None:
        cfg = _good_config()
        assert cfg.guardrails.staleness_ceiling_seconds == 3600

    def test_known_constants(self) -> None:
        assert CONTACT_BUCKETS == (
            "esim_activation",
            "plan_questions",
            "devices",
            "roaming",
            "port_in",
            "other",
        )
        assert SUPPORTED_PROVIDERS == ("p3", "p14", "p15")


# ---- frozen / immutability ---------------------------------------------------


class TestFrozen:
    def test_config_is_frozen(self) -> None:
        cfg = _good_config()
        with pytest.raises(ValidationError):
            cfg.tenant_id = "other"  # type: ignore[misc]

    def test_guardrails_is_frozen(self) -> None:
        g = Guardrails()
        with pytest.raises(ValidationError):
            g.read_only_writes = False  # type: ignore[misc]

    def test_routing_rule_is_frozen(self) -> None:
        r = RoutingRule(intent="x", handler=IntentHandler.AGENT)
        with pytest.raises(ValidationError):
            r.intent = "y"  # type: ignore[misc]


# ---- field-level validators --------------------------------------------------


class TestSimTypes:
    def test_psim_rejected(self) -> None:
        # Pydantic's Literal check fires first with a literal_error; the
        # custom validator's "eSIM-only" message wouldn't surface here.
        with pytest.raises(ValidationError):
            _good_config(sim_types=("pSIM",))

    def test_mixed_rejected(self) -> None:
        with pytest.raises(ValidationError):
            _good_config(sim_types=("eSIM", "pSIM"))

    def test_empty_rejected(self) -> None:
        with pytest.raises(ValidationError, match="eSIM-only"):
            _good_config(sim_types=())


class TestProviders:
    def test_p3_p14_p15_accepted(self) -> None:
        cfg = _good_config(providers=("p3", "p14", "p15"))
        assert cfg.providers == ("p3", "p14", "p15")

    def test_unsupported_provider_rejected(self) -> None:
        with pytest.raises(ValidationError, match="not in supported"):
            _good_config(providers=("p7",))

    def test_empty_providers_rejected(self) -> None:
        with pytest.raises(ValidationError, match="non-empty"):
            _good_config(providers=())


class TestContactMix:
    def test_mix_must_sum_to_one(self) -> None:
        bad_mix = dict(_good_mix())
        bad_mix["other"] = 0.50  # now sum is way over 1.0
        with pytest.raises(ValidationError, match=r"must sum to 1\.0"):
            _good_config(contact_mix_prior=bad_mix)

    def test_mix_within_tolerance_ok(self) -> None:
        almost = dict(_good_mix())
        almost["other"] = 0.055  # total = 1.005 (just inside ±0.01)
        cfg = _good_config(contact_mix_prior=almost)
        assert abs(sum(cfg.contact_mix_prior.values()) - 1.0) <= 0.01

    def test_unknown_bucket_rejected(self) -> None:
        bad_mix = {"esim_activation": 0.5, "made_up_bucket": 0.5}
        with pytest.raises(ValidationError, match="not in known buckets"):
            _good_config(contact_mix_prior=bad_mix)

    def test_negative_weight_rejected(self) -> None:
        bad_mix = dict(_good_mix())
        bad_mix["other"] = -0.05
        bad_mix["esim_activation"] = 0.45
        with pytest.raises(ValidationError, match="negative"):
            _good_config(contact_mix_prior=bad_mix)

    def test_empty_mix_rejected(self) -> None:
        with pytest.raises(ValidationError, match="non-empty"):
            _good_config(contact_mix_prior={})


class TestRoutingCoverage:
    def test_missing_bucket_rule_rejected(self) -> None:
        # Drop the rule whose bucket is 'port_in'.
        rules = tuple(
            r for r in _good_routing_rules() if r.bucket != "port_in"
        )
        with pytest.raises(ValidationError, match="port_in"):
            _good_config(routing_rules=rules)

    def test_bucket_with_zero_weight_does_not_require_rule(self) -> None:
        # Drop 'other' rule AND zero its weight out → should pass.
        rules = tuple(r for r in _good_routing_rules() if r.bucket != "other")
        mix = dict(_good_mix())
        mix["esim_activation"] = 0.40  # re-balance: was 0.35
        mix["other"] = 0.0
        cfg = _good_config(routing_rules=rules, contact_mix_prior=mix)
        # No exception means happy path.
        assert "other" not in {r.bucket for r in cfg.routing_rules}


class TestContextVarRequirements:
    def test_missing_required_var_rejected(self) -> None:
        partial = tuple(
            v for v in _good_context_vars() if v.name != "subscription_id"
        )
        with pytest.raises(ValidationError, match="subscription_id"):
            _good_config(context_variables=partial)

    def test_required_present_but_marked_optional_rejected(self) -> None:
        rebuilt = tuple(
            ContextVarSpec(
                name=v.name,
                required=False if v.name == "sim_id" else v.required,
                source=v.source,
            )
            for v in _good_context_vars()
        )
        with pytest.raises(ValidationError, match="sim_id"):
            _good_config(context_variables=rebuilt)


class TestTriggerPriorities:
    def test_duplicate_priority_rejected(self) -> None:
        dup = (
            TriggerSpec(kind=TriggerKindSpec.LOW_CONFIDENCE, priority=1),
            TriggerSpec(kind=TriggerKindSpec.WRITE_REQUESTED, priority=1),
        )
        with pytest.raises(ValidationError, match="duplicate trigger priority"):
            _good_config(escalation_triggers=dup)


class TestTwoHopEscalation:
    def test_addresses_present(self) -> None:
        cfg = _good_config()
        assert AT in cfg.two_hop.tier1_target
        assert AT in cfg.two_hop.tier2_target

    def test_empty_target_rejected(self) -> None:
        with pytest.raises(ValidationError):
            TwoHopEscalation(tier1_target="", tier2_target="ok@example")


# ---- round-trip --------------------------------------------------------------


class TestJsonRoundTrip:
    def test_dump_and_reload_preserves_enums(self) -> None:
        cfg = _good_config()
        dumped = cfg.model_dump(mode="json")
        round_tripped = InstanceConfig.model_validate(dumped)
        assert round_tripped == cfg

    def test_extra_field_rejected(self) -> None:
        with pytest.raises(ValidationError):
            _good_config(undeclared_field="surprise")  # type: ignore[call-arg]
