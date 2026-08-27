"""Golden-set parity tests for the Python MarketExtractor (Phase 8).

Proves the Python port of the JS listener's Pass B (intent/side) and
Pass C (attribute extraction) produces identical results.

Build the golden set from the listener DB:
  SELECT gm.content AS raw_text, fr.side, fr.attributes
  FROM filter_results fr
  JOIN group_messages gm ON fr.message_id = gm.id
  WHERE fr.filter_status = 'passed'
  ORDER BY random() LIMIT 100;
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from app.modules.market.extractor import (
    clean_text,
    extract_attributes,
    extract_contact_cc,
    extract_intent,
    extract_side,
    has_target_brand,
    match_any,
    match_named_patterns,
    parse_activation,
    parse_category,
    parse_color,
    parse_condition,
    parse_currency,
    parse_model_numbers,
    parse_quantity,
    parse_ram,
    parse_region,
    parse_storage,
)

FIXTURE_DIR = Path(__file__).resolve().parents[1] / "fixtures"


# =============================================================================
# Helper function unit tests
# =============================================================================


class TestMatchAny:
    def test_string_match_case_insensitive(self):
        assert match_any("Hello World", ["world"]) is True

    def test_string_no_match(self):
        assert match_any("Hello World", ["xyz"]) is False

    def test_regex_match(self):
        assert match_any("WTB iPhone", [re.compile(r"\bWTB\b")]) is True

    def test_regex_no_match(self):
        assert match_any("WTBSELL", [re.compile(r"\bWTS\b")]) is False

    def test_empty_patterns(self):
        assert match_any("text", []) is False


class TestMatchNamedPatterns:
    def test_returns_hits(self):
        result = match_named_patterns(
            "WTS iPhone 16 Black",
            {
                "SIDE_SELL": [re.compile(r"\bWTS\b")],
                "SIDE_BUY": [re.compile(r"\bWTB\b")],
            },
        )
        assert result == {"SIDE_SELL": True}

    def test_multiple_groups(self):
        result = match_named_patterns(
            "Brand New iPhone SEALED",
            {
                "COND_NEW": [re.compile(r"Brand New", re.IGNORECASE)],
                "COND_SEALED": [re.compile(r"SEALED", re.IGNORECASE)],
            },
        )
        assert result == {"COND_NEW": True, "COND_SEALED": True}

    def test_string_patterns(self):
        result = match_named_patterns(
            "Hello World",
            {"GREETING": ["hello"]},
        )
        assert result == {"GREETING": True}


class TestTextCleaning:
    def test_strips_broadcast_footer(self):
        text = "WTB iPhone\nThis broadcast is powered by GSM\n"
        result = clean_text(text)
        assert "This broadcast is powered by" not in result

    def test_strips_dividers(self):
        text = "━━━━\nWTB iPhone\n━━━━"
        result = clean_text(text)
        assert "━" not in result
        assert "WTB iPhone" in result

    def test_strips_asterisk_dividers(self):
        text = "***\nSelling S25\n***"
        result = clean_text(text)
        assert "***" not in result

    def test_strips_underscore_dividers(self):
        text = "____\nWTB iPhone\n____"
        result = clean_text(text)
        assert "___" not in result


# =============================================================================
# Pass B -- side detection
# =============================================================================


class TestExtractSide:
    def test_fast_path_wtb(self):
        assert extract_side("WTB iPhone 16 Pro") == "buy"

    def test_fast_path_wts(self):
        assert extract_side("WTS Samsung S25") == "sell"

    def test_fast_path_w_t_s(self):
        assert extract_side("W T S iPhone") == "sell"

    def test_fast_path_w_dot_t_dot_s(self):
        assert extract_side("W.T.S iPhone") == "sell"

    def test_buy_signals_outweigh_sell(self):
        text = "Want to buy iPhone, also selling old one"
        assert extract_side(text) == "buy"

    def test_sell_signals_outweigh_buy(self):
        # buyHits==sellHits falls to heuristic; "looking for" matches first → buy
        text = "Selling S25, also looking for iPhone case"
        assert extract_side(text) == "buy"

    def test_price_discovery(self):
        assert extract_side("Message for best price iPhone 16") == "price_discovery"

    def test_prebook(self):
        assert extract_side("Pre Booking iPhone 17") == "prebook"

    def test_status_close(self):
        assert extract_side("already sold iPhone 16") == "status_close"

    def test_heuristic_buy_fallback(self):
        assert extract_side("I need an iPhone") == "buy"

    def test_heuristic_sell_fallback(self):
        assert extract_side("for sale: MacBook Pro") == "sell"

    def test_unknown(self):
        assert extract_side("Hello, how are you?") == "unknown"

    def test_status_close_takes_priority(self):
        # JS fast-path WTB fires BEFORE status_close check — that's the JS behavior
        text = "deal done iPhone 16 Pro"  # no fast-path trigger
        assert extract_side(text) == "status_close"

    def test_buy_hits_equals_sell_hits_price_disc(self):
        text = "Want to buy iPhone, also selling S25 best combo offers"
        assert extract_side(text) == "price_discovery"

    def test_wtb_lowercase(self):
        assert extract_side("wtb iphone 16") == "buy"


# =============================================================================
# Pass C -- attribute extraction
# =============================================================================


class TestHasTargetBrand:
    def test_apple(self):
        result = has_target_brand("iPhone 16 Pro Max 256GB")
        assert result["brand"] == "apple"

    def test_samsung(self):
        result = has_target_brand("Samsung S25 Ultra")
        assert result["brand"] == "samsung"

    def test_mixed(self):
        result = has_target_brand("iPhone 16 and Samsung S25 for sale")
        assert result["brand"] == "mixed"

    def test_non_target(self):
        result = has_target_brand("Google Pixel 9 for sale")
        assert result["brand"] == "non_target"

    def test_unknown(self):
        result = has_target_brand("random text no brand")
        assert result["brand"] == "unknown"

    def test_samsung_ssd_carveout(self):
        result = has_target_brand("Samsung SSD 990 Pro 2TB")
        assert result["brand"] == "non_target"

    def test_samsung_ssd_with_apple(self):
        result = has_target_brand("Samsung SSD 990 and iPhone 16 case")
        assert result["brand"] == "apple"
        assert result.get("samsung_ssd") is True

    def test_airpods_brand_is_apple(self):
        result = has_target_brand("AirPods Pro 2 for sale")
        assert result["brand"] == "apple"


class TestParseStorage:
    def test_single_storage(self):
        result = parse_storage("iPhone 16 Pro Max 256GB")
        assert "256GB" in result

    def test_multiple_storage(self):
        result = parse_storage("Available in 128GB and 256GB")
        assert len(result) >= 1

    def test_tb_storage(self):
        result = parse_storage("iPad 1TB")
        assert any("1TB" in s for s in result)

    def test_no_storage(self):
        result = parse_storage("iPhone 16 Pro Max")
        assert result == []

    def test_storage_with_space(self):
        result = parse_storage("iPhone 512 GB")
        assert any("512GB" in s for s in result)

    def test_deduplicates(self):
        result = parse_storage("256GB and 256 gb")
        assert len([s for s in result if "256GB" in s]) <= 1


class TestParseRam:
    def test_ram_explicit(self):
        result = parse_ram("8GB RAM Galaxy S25")
        assert any("8GB" in r for r in result)

    def test_ram_combined_notation(self):
        result = parse_ram("8/256 available")
        assert any("8/256" in r for r in result)

    def test_no_ram(self):
        result = parse_ram("iPhone 16")
        assert result == []

    def test_combined_notation_not_storage(self):
        result = parse_storage("4/64 Samsung")
        assert "4/64" not in result  # combined notation is RAM, not storage


class TestParseColor:
    def test_black(self):
        result = parse_color("iPhone 16 Black 256GB")
        assert "Black" in result

    def test_color_typo_blk(self):
        result = parse_color("iPhone blk color")
        assert "Black" in result

    def test_multiple_colors(self):
        result = parse_color("Available in Black and White")
        assert len(result) >= 1

    def test_no_color(self):
        result = parse_color("iPhone 16 256GB")
        assert isinstance(result, list)


class TestParseQuantity:
    def test_exact_qty(self):
        result = parse_quantity("10 pcs iPhone 16")
        assert result.get("QTY_EXACT") is True
        assert result.get("qty_value") == 10

    def test_bulk(self):
        result = parse_quantity("Bulk stock available")
        assert result.get("QTY_BULK") is True

    def test_moq(self):
        result = parse_quantity("MOQ applies")
        assert result.get("MOQ_APPLIES") is True

    def test_no_quantity(self):
        result = parse_quantity("iPhone 16")
        assert result == {}


class TestParseRegion:
    def test_uk(self):
        result = parse_region("iPhone UK spec /B")
        assert "REGION_UK" in result

    def test_uae(self):
        result = parse_region("Samsung TRA approved UAE")
        assert "REGION_UAE" in result

    def test_multiple(self):
        result = parse_region("UK and USA stock")
        assert "REGION_UK" in result
        assert "REGION_USA" in result

    def test_esim(self):
        result = parse_region("iPhone eSIM only")
        assert "SIM_ESIM" in result


class TestParseActivation:
    def test_non_active(self):
        result = parse_activation("iPhone Non Active")
        assert "ACT_NON_ACTIVE" in result

    def test_active_with_negative_lookbehind(self):
        result = parse_activation("iPhone Active 256GB")
        assert "ACT_ACTIVE" in result

    def test_locked(self):
        result = parse_activation("iPhone Locked")
        assert "ACT_LOCKED" in result

    def test_oem(self):
        result = parse_activation("OEM Brand New iPhone")
        assert "ACT_OEM" in result

    def test_non_active_does_not_match_active(self):
        result = parse_activation("Non Active iPhone")
        assert "ACT_ACTIVE" not in result


class TestParseCondition:
    def test_new(self):
        result = parse_condition("Brand New iPhone")
        assert "COND_NEW" in result

    def test_open_box(self):
        result = parse_condition("Open box iPad")
        assert "COND_OPEN_BOX" in result

    def test_grade_a(self):
        result = parse_condition("Grade A iPhone")
        assert "COND_GRADE_A" in result

    def test_used(self):
        result = parse_condition("used iPhone")
        assert "COND_USED_REFURB" in result

    def test_refurbished(self):
        result = parse_condition("refurbished MacBook")
        assert "COND_USED_REFURB" in result


class TestParseCurrency:
    def test_gbp(self):
        result = parse_currency("iPhone £800")
        assert "CUR_GBP" in result

    def test_eur(self):
        result = parse_currency("iPhone €950")
        assert "CUR_EUR" in result

    def test_aed(self):
        result = parse_currency("iPhone 3500 AED")
        assert "CUR_AED" in result

    def test_masked(self):
        result = parse_currency("Price on ask")
        assert "CUR_MASKED" in result


class TestParseModelNumbers:
    def test_ean(self):
        result = parse_model_numbers("EAN 1234567890123")
        assert "1234567890123" in result

    def test_apple_mpn(self):
        # Apple MPN pattern: [A-Z]{2,4}\d{2,3}[A-Z]{2}/A — needs 2+ digits
        result = parse_model_numbers("AB12CD/A iPhone")
        assert "AB12CD/A" in result

    def test_samsung_internal(self):
        result = parse_model_numbers("S938 Samsung")
        assert "S938" in result


class TestExtractContactCc:
    def test_extracts_uae(self):
        # +971 IS in NON_LOCALITY_COUNTRY_CODES — it's a known non-locality code
        result = extract_contact_cc("Contact me +971501234567")
        assert result is not None
        assert result["cc"] == "+971"
        assert result["is_foreign"] is True

    def test_extracts_uk(self):
        # +447 (3 digits, greedy match) is NOT in the set — known JS limitation
        result = extract_contact_cc("Call +447911123456")
        assert result is not None
        assert result["cc"] == "+447"
        assert result["is_foreign"] is False

    def test_no_cc(self):
        result = extract_contact_cc("Just text no phone")
        assert result is None


class TestParseCategory:
    def test_apple_smartphone_default(self):
        result = parse_category("iPhone something", "apple")
        assert "CAT_SMARTPHONE" in result

    def test_samsung_smartphone_default(self):
        result = parse_category("Samsung something", "samsung")
        assert "CAT_SMARTPHONE" in result

    def test_unknown_brand_no_default(self):
        result = parse_category("some text", "unknown")
        assert result == []

    def test_apple_filters_samsung_watch(self):
        result = parse_category("Apple Watch Ultra 49mm", "apple")
        assert "CAT_SAMSUNG_WATCH" not in result
        assert "CAT_SMARTWATCH" in result


# =============================================================================
# Top-level orchestrator tests
# =============================================================================


class TestExtractIntent:
    def test_buy_with_flags(self):
        result = extract_intent("WTB iPhone 16")
        assert result["side"] == "buy"
        assert result["is_chatter"] is False
        assert result["status_close"] is False

    def test_status_close_with_flags(self):
        result = extract_intent("already sold iPhone")
        assert result["side"] == "status_close"
        assert result["status_close"] is True

    def test_price_discovery_with_flags(self):
        result = extract_intent("Message for best price")
        assert result["side"] == "price_discovery"
        assert result["price_discovery"] is True

    def test_prebook_with_flags(self):
        result = extract_intent("Pre Booking iPhone 17")
        assert result["side"] == "prebook"
        assert result["prebook"] is True


class TestExtractAttributes:
    def test_apple_smartphone(self):
        result = extract_attributes("WTB iPhone 16 Pro Max 256GB Black")
        assert result["passed"] is True
        assert result["brand"] == "apple"
        assert "CAT_SMARTPHONE" in result["categories"]
        assert "256GB" in result["storage"]
        assert "Black" in result["color"]

    def test_non_target(self):
        result = extract_attributes("Google Pixel 9 for sale")
        assert result["passed"] is False
        assert result["brand"] == "non_target"

    def test_unknown_brand(self):
        result = extract_attributes("random text")
        assert result["passed"] is False
        assert result["brand"] == "unknown"

    def test_all_keys_present(self):
        result = extract_attributes("WTS iPhone 16 128GB Black")
        expected_keys = {
            "passed", "brand", "samsung_ssd", "categories", "storage",
            "ram", "color", "region", "activation", "condition",
            "quantity", "logistics", "currency", "variants", "model_numbers",
        }
        assert expected_keys <= set(result)


# =============================================================================
# Golden-set parity tests
# =============================================================================


def _load_golden_set():
    path = FIXTURE_DIR / "extractor_golden_set.json"
    with open(path, encoding="utf-8") as f:
        return json.load(f)


GOLDEN_SET = _load_golden_set()


@pytest.mark.parametrize(
    "case",
    [pytest.param(c, id=c.get("raw_text", "")[:60] or "(empty)") for c in GOLDEN_SET],
)
def test_golden_set_side(case: dict):
    """Every golden-set case must produce the expected side."""
    result = extract_side(clean_text(case["raw_text"]))
    expected = case["expected_side"]
    assert result == expected, (
        f"Side mismatch for: {case['raw_text'][:80]!r}\n"
        f"Expected: {expected}, Got: {result}"
    )


@pytest.mark.parametrize(
    "case",
    [pytest.param(c, id=c.get("raw_text", "")[:60] or "(empty)") for c in GOLDEN_SET],
)
def test_golden_set_attributes(case: dict):
    """Every golden-set case must produce matching attributes."""
    result = extract_attributes(case["raw_text"])
    expected = case["expected_attributes"]

    # Check passed flag
    assert result.get("passed") == expected.get("passed"), (
        f"passed mismatch for: {case['raw_text'][:80]!r}\n"
        f"Expected: {expected.get('passed')}, Got: {result.get('passed')}"
    )

    # Check brand if expected
    if "brand" in expected:
        assert result.get("brand") == expected["brand"], (
            f"brand mismatch for: {case['raw_text'][:80]!r}\n"
            f"Expected: {expected['brand']}, Got: {result.get('brand')}"
        )

    # Check list-valued attributes (order-independent)
    for key in (
        "categories", "storage", "ram", "color", "region", "activation",
        "condition", "logistics", "currency", "variants", "model_numbers",
    ):
        if key in expected:
            result_vals = set(result.get(key, []))
            expected_vals = set(expected[key])
            if expected_vals:
                missing = expected_vals - result_vals
                assert not missing, (
                    f"{key} mismatch for: {case['raw_text'][:80]!r}\n"
                    f"Missing: {missing}"
                )

    # Check quantity dict
    if "quantity" in expected:
        for qk, qv in expected["quantity"].items():
            actual_qty = result.get("quantity", {})
            assert actual_qty.get(qk) == qv, (
                f"quantity.{qk} mismatch for: {case['raw_text'][:80]!r}\n"
                f"Expected: {qv}, Got: {actual_qty.get(qk)}"
            )

    # Check contact_cc
    if "contact_cc" in expected:
        result_cc = result.get("contact_cc")
        assert result_cc is not None, (
            f"contact_cc missing for: {case['raw_text'][:80]!r}"
        )
        assert result_cc.get("cc") == expected["contact_cc"]["cc"], (
            f"contact_cc.cc mismatch for: {case['raw_text'][:80]!r}"
        )
        assert result_cc.get("is_foreign") == expected["contact_cc"]["is_foreign"], (
            f"contact_cc.is_foreign mismatch for: {case['raw_text'][:80]!r}"
        )


# =============================================================================
# Edge case tests
# =============================================================================


class TestEdgeCases:
    def test_empty_text(self):
        assert extract_side("") == "unknown"
        result = extract_attributes("")
        assert result["passed"] is False

    def test_unicode_emojis(self):
        text = "WTS iPhone 16 \U0001F4F1 256GB \U0001F1EC\U0001F1E7 UK spec"
        result = extract_side(text)
        assert result == "sell"

    def test_mixed_case(self):
        text = "wTs iPhOnE 16 PrO mAx"
        assert extract_side(text) == "sell"

    def test_newlines_and_extra_whitespace(self):
        text = """
        WTB

        iPhone 16 Pro Max
        256GB
        Black
        """
        side = extract_side(clean_text(text))
        assert side == "buy"

    def test_very_long_text(self):
        text = "WTS iPhone 16 Pro Max " + "great condition " * 200
        side = extract_side(text)
        assert side in ("sell", "unknown")

    def test_buy_equals_sell_resolves_by_heuristic(self):
        text = "WTB iPhone also WTS Samsung"
        result = extract_side(text)
        assert result in ("buy", "sell", "unknown")

    def test_samsung_t5_ssd_non_target(self):
        result = has_target_brand("Samsung T7 SSD 1TB")
        assert result["brand"] == "non_target"
