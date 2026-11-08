"""Explicit recording boundaries; raw events are always retained."""
import re


def validate_ranges(value):
    if not isinstance(value, list) or not 1 <= len(value) <= 16:
        raise ValueError("Select one to sixteen ordered recording clips")
    previous = 0
    result = []
    for span in value:
        if (not isinstance(span, dict) or set(span) != {"first", "last"} or
                type(span["first"]) is not int or type(span["last"]) is not int or
                not previous < span["first"] <= span["last"] <= 4096):
            raise ValueError("Recording clips need ordered, nonoverlapping sequence numbers from 1 to 4096")
        result.append(dict(span))
        previous = span["last"]
    return result


def parse_ranges(values):
    if values is None:
        return None
    spans = []
    for value in values:
        if not isinstance(value, str) or not re.fullmatch(r"[1-9][0-9]{0,3}:[1-9][0-9]{0,3}", value):
            raise ValueError("Use FIRST:LAST sequence numbers for each recording clip")
        first, last = map(int, value.split(":"))
        spans.append({"first": first, "last": last})
    return validate_ranges(spans)
