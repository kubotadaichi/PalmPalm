from src.serial_reader import VIBRATION_KEYWORD, should_record_pulse


def test_vibration_line_triggers_pulse():
    """'Vibration detected!' を含む行は True"""
    assert should_record_pulse("Vibration detected!") is True


def test_dots_line_does_not_trigger():
    """'...' は False"""
    assert should_record_pulse("...") is False


def test_empty_line_does_not_trigger():
    assert should_record_pulse("") is False


def test_keyword_is_correct():
    assert VIBRATION_KEYWORD == "Vibration detected!"
