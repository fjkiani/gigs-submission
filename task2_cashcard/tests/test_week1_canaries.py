"""Tests for week1_canaries — the runtime checks that fire on week-1 defects.

Each canary has a happy path (does not fire) and one or more failure paths
(does fire). PII canary uses the AT-constant workaround for emails so the
Write tool doesn't obfuscate the literal.
"""

from __future__ import annotations

from task2_cashcard.tests.fixtures import (
    NOW,
    make_context,
    make_porting_declined,
    make_sim,
    make_subscription,
)
from task2_cashcard.week1_canaries import (
    CanaryHit,
    canary_missing_required_var,
    canary_pii_in_answer,
    canary_porting_declined_not_decoded,
    canary_provider_not_supported,
    canary_restriction_ignored,
    canary_stale_usage_no_qualifier,
    run_all,
)

AT = "@"


# ---- canary_missing_required_var --------------------------------------------


class TestMissingRequiredVar:
    def test_all_present_does_not_fire(self) -> None:
        ctx = make_context()
        assert canary_missing_required_var(ctx=ctx) is None

    def test_no_subscription_fires(self) -> None:
        ctx = make_context(no_subscription=True)
        hit = canary_missing_required_var(ctx=ctx)
        assert hit is not None
        assert "subscription_id" in hit.detail

    def test_no_sim_fires(self) -> None:
        ctx = make_context(no_sim=True)
        hit = canary_missing_required_var(ctx=ctx)
        assert hit is not None
        assert "sim_id" in hit.detail

    def test_custom_required_set(self) -> None:
        """A caller can scope the canary to a subset of identifiers."""
        ctx = make_context(no_sim=True)
        # Only check subscription_id and user_id; sim_id is absent but ignored.
        hit = canary_missing_required_var(
            ctx=ctx, required=("subscription_id", "user_id")
        )
        assert hit is None


# ---- canary_provider_not_supported ------------------------------------------


class TestProviderNotSupported:
    def test_p3_with_install_claim_does_not_fire(self) -> None:
        ctx = make_context(sim=make_sim(provider="p3"))
        answer = "Your eSIM is installed on your device. You should be good to go."
        assert canary_provider_not_supported(ctx=ctx, answer=answer) is None

    def test_p7_with_install_claim_fires(self) -> None:
        ctx = make_context(sim=make_sim(provider="p7"))
        answer = "Your eSIM is installed and ready."
        hit = canary_provider_not_supported(ctx=ctx, answer=answer)
        assert hit is not None
        assert "p7" in hit.detail

    def test_p7_without_install_claim_does_not_fire(self) -> None:
        ctx = make_context(sim=make_sim(provider="p7"))
        answer = "Let me check your account. I'll get back to you with what I find."
        assert canary_provider_not_supported(ctx=ctx, answer=answer) is None

    def test_no_sim_does_not_fire(self) -> None:
        ctx = make_context(no_sim=True)
        answer = "Your eSIM is installed."
        assert canary_provider_not_supported(ctx=ctx, answer=answer) is None


# ---- canary_stale_usage_no_qualifier ----------------------------------------


class TestStaleUsageNoQualifier:
    def test_no_usage_number_does_not_fire(self) -> None:
        answer = "Your account is active. How can I help?"
        assert canary_stale_usage_no_qualifier(answer=answer) is None

    def test_usage_number_with_as_of_qualifier_passes(self) -> None:
        answer = "As of 11:00, you've used 4.2 GB this period."
        assert canary_stale_usage_no_qualifier(answer=answer) is None

    def test_usage_number_without_qualifier_fires(self) -> None:
        answer = "You've used 4.2 GB this period."
        hit = canary_stale_usage_no_qualifier(answer=answer)
        assert hit is not None
        assert "4.2 GB" in hit.detail or "4.2 gb" in hit.detail.lower()

    def test_minutes_count_without_qualifier_fires(self) -> None:
        answer = "You've used 250 minutes."
        hit = canary_stale_usage_no_qualifier(answer=answer)
        assert hit is not None

    def test_sms_with_last_reported_passes(self) -> None:
        answer = "Last reported, you've used 12 messages this cycle."
        assert canary_stale_usage_no_qualifier(answer=answer) is None


# ---- canary_porting_declined_not_decoded ------------------------------------


class TestPortingDeclinedNotDecoded:
    def test_no_porting_does_not_fire(self) -> None:
        ctx = make_context()
        assert canary_porting_declined_not_decoded(
            ctx=ctx, answer="all good"
        ) is None

    def test_declined_with_code_surfaced_passes(self) -> None:
        ctx = make_context(
            porting_history=[
                make_porting_declined(code="portingPinIncorrect"),
            ]
        )
        answer = "Your port was declined with code portingPinIncorrect."
        assert canary_porting_declined_not_decoded(
            ctx=ctx, answer=answer
        ) is None

    def test_declined_without_code_fires(self) -> None:
        ctx = make_context(
            porting_history=[
                make_porting_declined(code="portingPinIncorrect"),
            ]
        )
        answer = "Your port didn't go through; please try again."
        hit = canary_porting_declined_not_decoded(ctx=ctx, answer=answer)
        assert hit is not None
        assert "portingPinIncorrect" in hit.detail


# ---- canary_restriction_ignored ---------------------------------------------


class TestRestrictionIgnored:
    def test_active_sub_does_not_fire(self) -> None:
        ctx = make_context()
        answer = "Go ahead and activate the eSIM in your settings."
        assert canary_restriction_ignored(ctx=ctx, answer=answer) is None

    def test_restricted_with_action_verb_fires(self) -> None:
        ctx = make_context(
            subscription=make_subscription(
                status="restricted",
                restriction_reason="payment_overdue",
            )
        )
        answer = "You can activate your eSIM now."
        hit = canary_restriction_ignored(ctx=ctx, answer=answer)
        assert hit is not None
        assert "activate" in hit.detail

    def test_restricted_with_explanatory_answer_passes(self) -> None:
        ctx = make_context(
            subscription=make_subscription(
                status="restricted",
                restriction_reason="payment_overdue",
            )
        )
        answer = (
            "Your subscription is currently restricted. I'll connect you "
            "with a teammate who can sort the billing issue."
        )
        assert canary_restriction_ignored(ctx=ctx, answer=answer) is None


# ---- canary_pii_in_answer ----------------------------------------------------


class TestPiiInAnswer:
    def test_clean_answer_does_not_fire(self) -> None:
        ctx = make_context()
        answer = "Your account is active. How can I help?"
        assert canary_pii_in_answer(ctx=ctx, answer=answer) is None

    def test_email_echoed_fires(self) -> None:
        ctx = make_context()
        # Use a different email than the user's masked one to test the
        # general email-detection fallback.
        answer = f"I see you signed up as j.doe{AT}example.com — can you confirm?"
        hit = canary_pii_in_answer(ctx=ctx, answer=answer)
        assert hit is not None

    def test_phone_digits_echoed_fires(self) -> None:
        ctx = make_context()  # default subscription has masked phone
        answer = "We have 5551234567 on file. Is that right?"
        hit = canary_pii_in_answer(ctx=ctx, answer=answer)
        assert hit is not None

    def test_masked_email_in_answer_fires(self) -> None:
        masked = f"j***{AT}cashcard.example"
        ctx = make_context()  # user.email_masked defaults to this exact string
        answer = f"We see your email as {masked}. Please confirm."
        hit = canary_pii_in_answer(ctx=ctx, answer=answer)
        assert hit is not None


# ---- CanaryHit dataclass ----------------------------------------------------


class TestCanaryHitFrozen:
    def test_canary_hit_is_frozen(self) -> None:
        import dataclasses

        ctx = make_context(no_subscription=True)
        hit = canary_missing_required_var(ctx=ctx)
        assert isinstance(hit, CanaryHit)
        with pytest.raises(dataclasses.FrozenInstanceError):  # type: ignore[name-defined]
            hit.detail = "tampered"  # type: ignore[misc]


# ---- run_all aggregator -----------------------------------------------------


class TestRunAll:
    def test_clean_context_emits_no_hits(self) -> None:
        ctx = make_context()
        answer = "As of just now, your account is active. Anything else?"
        hits = run_all(ctx=ctx, answer=answer, now=NOW)
        assert hits == []

    def test_multiple_failures_emit_multiple_hits(self) -> None:
        ctx = make_context(
            no_subscription=True,
            sim=make_sim(provider="p7"),
            porting_history=[
                make_porting_declined(code="portingPinIncorrect"),
            ],
        )
        # Multiple problems in one answer: install claim on unsupported
        # provider + porting decline not decoded + missing freshness +
        # missing required var (no subscription) + balance number.
        answer = "Your eSIM is installed. You have 4.2 GB left."
        hits = run_all(ctx=ctx, answer=answer, now=NOW)
        names = {h.name for h in hits}
        assert "missing_required_var" in names
        assert "provider_not_supported" in names
        assert "stale_usage_no_qualifier" in names
        assert "porting_declined_not_decoded" in names


# pytest is imported at the top of the file by the runner; the fixture import
# line uses it. Add it here for the frozen test.
import pytest  # noqa: E402
