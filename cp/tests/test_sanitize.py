from cp.sanitize.sanitizer import Sanitizer, FieldRule, load_from_file


def test_mask_default_uses_stars():
    s = Sanitizer.new_from_rules([FieldRule(name="id_card", strategy="mask")])
    out = s.sanitize_data({"id_card": "110101199001011234"})
    assert out["id_card"] == "***"


def test_mask_keeps_prefix_suffix():
    s = Sanitizer.new_from_rules([
        FieldRule(name="phone", strategy="mask", keep_prefix=3, keep_suffix=4)
    ])
    out = s.sanitize_data({"phone": "13812341234"})
    assert out["phone"] == "138****1234"


def test_hash_returns_prefixed_hex():
    s = Sanitizer.new_from_rules([FieldRule(name="customer_id", strategy="hash")])
    out = s.sanitize_data({"customer_id": "C001"})
    assert out["customer_id"].startswith("h_")
    assert len(out["customer_id"]) == 2 + 16


def test_redact_removes_field_but_summary_records_it():
    s = Sanitizer.new_from_rules([FieldRule(name="remark", strategy="redact")])
    result = s.sanitize({"phone": "13812341234", "remark": "secret", "amount": 120})
    assert "remark" not in result.data
    fields = {f.field for f in result.summary}
    assert "remark" in fields
    assert result.data["amount"] == 120  # 非 PII 不动


def test_non_string_field_hashed():
    s = Sanitizer.new_from_rules([FieldRule(name="amount", strategy="hash")])
    out = s.sanitize_data({"amount": 120})
    assert out["amount"].startswith("h_")


def test_no_rules_passes_through():
    s = Sanitizer.new_from_rules([])
    out = s.sanitize_data({"x": 1})
    assert out == {"x": 1}


def test_load_from_file_reads_real_rules():
    s = load_from_file("examples/sanitization/pii_rules.yaml")
    out = s.sanitize_data({"phone": "13812341234", "customer_id": "C001", "remark": "s", "amount": 120})
    assert out["phone"] != "13812341234"
    assert out["customer_id"] != "C001"
    assert "remark" not in out
    assert out["amount"] == 120
