from app.detect_rules import detect


def _pairs(text):
    return {(finding.text, finding.category) for finding in detect(text)}


def test_detects_email_phone_and_indian_id_like_values():
    text = (
        "Email: morgan.example@example.invalid; "
        "Phone: +91 90000 12345; "
        "Aadhaar-like: 1234 5678 9012; PAN-like: ABCDE1234F"
    )
    pairs = _pairs(text)
    assert ("morgan.example@example.invalid", "EMAIL") in pairs
    assert ("+91 90000 12345", "PHONE") in pairs
    assert ("1234 5678 9012", "AADHAAR_LIKE_ID") in pairs
    assert ("ABCDE1234F", "PAN_LIKE_ID") in pairs


def test_detects_ifsc_pin_and_labelled_account_and_dob():
    text = (
        "IFSC: HDFC0001234; PIN: 110001; "
        "Account No: 123456789012; DOB: 01/08/2006"
    )
    pairs = _pairs(text)
    assert ("HDFC0001234", "IFSC") in pairs
    assert ("110001", "PIN_CODE") in pairs
    assert ("123456789012", "ACCOUNT_NUMBER") in pairs
    assert ("01/08/2006", "DATE_OF_BIRTH") in pairs


def test_returns_source_layer_location_and_stable_ids():
    text = "Contact morgan.example@example.invalid"
    first = detect(text, location="line 1")
    second = detect(text, location="line 1")
    assert len(first) == 1
    assert first[0].source_layer == "regex"
    assert first[0].location == "line 1"
    assert first[0].id == second[0].id


def test_no_findings_for_plain_text():
    assert detect("This is a harmless synthetic paragraph.") == []


def test_does_not_return_whole_label_for_account_or_dob():
    findings = detect("Account No: 123456789012; DOB: 01/08/2006")
    values = {finding.text for finding in findings}
    assert "123456789012" in values
    assert "Account No: 123456789012" not in values
    assert "01/08/2006" in values
    assert "DOB: 01/08/2006" not in values


def test_does_not_modify_input_text():
    text = "Email: morgan.example@example.invalid"
    before = text[:]
    detect(text)
    assert text == before


def test_card_number_does_not_also_emit_partial_aadhaar_match():
    findings = detect("Card test number: 4111 1111 1111 1111")
    matching = [f for f in findings if "4111" in f.text]
    assert any(f.category == "CARD_NUMBER" and f.text == "4111 1111 1111 1111" for f in matching)
    assert not any(f.category == "AADHAAR_LIKE_ID" and f.text == "4111 1111 1111" for f in matching)
