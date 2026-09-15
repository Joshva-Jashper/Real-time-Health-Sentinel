from testsentry.ai_triage import parse_triage_response

def test_ai_parser_bounds_confidence_and_rejects_categories():
    result = parse_triage_response('{"category":"REAL_BUG","confidence_pct":250,"why_it_failed":"x","suggested_fix":"y","affected_module":"z"}')
    assert result["confidence_pct"] == 100
    try:
        parse_triage_response('{"category":"UNKNOWN","confidence_pct":50}')
    except ValueError:
        pass
    else:
        raise AssertionError("invalid category accepted")
