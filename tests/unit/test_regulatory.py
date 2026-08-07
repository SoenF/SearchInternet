from __future__ import annotations

from opportunity_engine.tools.regulatory import classify_regulatory_risk


def test_bank_sic_code_is_regulated() -> None:
    risk = classify_regulatory_risk(text=None, sic_code="6022", app_store_genre=None)
    assert risk.regulated
    assert "sic:depository_institutions" in risk.reasons


def test_insurance_sic_code_is_regulated() -> None:
    risk = classify_regulatory_risk(text=None, sic_code="6311", app_store_genre=None)
    assert risk.regulated


def test_unclassified_sic_is_not_regulated() -> None:
    """The common case for Form D filers -- no SIC on file at all."""
    risk = classify_regulatory_risk(text=None, sic_code=None, app_store_genre=None)
    assert not risk.regulated
    assert risk.reasons == []


def test_ordinary_software_sic_is_not_regulated() -> None:
    risk = classify_regulatory_risk(
        text=None, sic_code="7372", app_store_genre=None
    )  # prepackaged software
    assert not risk.regulated


def test_medical_app_store_genre_is_regulated() -> None:
    risk = classify_regulatory_risk(text=None, sic_code=None, app_store_genre="Medical")
    assert risk.regulated
    assert "app_store_genre:Medical" in risk.reasons


def test_productivity_app_store_genre_is_not_regulated() -> None:
    risk = classify_regulatory_risk(text=None, sic_code=None, app_store_genre="Productivity")
    assert not risk.regulated


def test_hipaa_keyword_in_text_is_regulated() -> None:
    risk = classify_regulatory_risk(
        text="Our platform is fully HIPAA compliant for clinics.",
        sic_code=None,
        app_store_genre=None,
    )
    assert risk.regulated
    assert any("hipaa" in reason for reason in risk.reasons)


def test_multiple_signals_all_recorded() -> None:
    risk = classify_regulatory_risk(
        text="We are a HIPAA-compliant telehealth app.", sic_code="8011", app_store_genre="Medical"
    )
    assert risk.regulated
    assert len(risk.reasons) == 3
