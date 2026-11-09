"""Ordered, single-membership groups for a workspace or a saved collection."""
from .model import identifier

UNGROUPED = "Ungrouped"


def validate_groups(groups, suites=None):
    if not isinstance(groups, dict) or len(groups) > 128:
        raise ValueError("Define at most 128 test groups.")
    names, members = set(), set()
    for name, tests in groups.items():
        if (not isinstance(name, str) or not 1 <= len(name) <= 64 or name != name.strip() or
                any(ord(char) < 32 for char in name) or name.casefold() in names | {UNGROUPED.casefold()}):
            raise ValueError("Use a unique group name of 1–64 characters. Ungrouped is reserved.")
        names.add(name.casefold())
        if not isinstance(tests, list) or len(tests) > 1024:
            raise ValueError("A test group must contain an ordered list of tests.")
        for test in tests:
            identifier(test)
            if test in members:
                raise ValueError("A test can belong to only one group.")
            if suites is not None and test not in suites:
                raise ValueError("A group names a test outside this collection.")
            members.add(test)
    return groups


def group_membership(groups):
    return {test: name for name, tests in groups.items() for test in tests}


def move_test(groups, suite, target):
    identifier(suite)
    result = {name: [test for test in tests if test != suite] for name, tests in groups.items()}
    if target != UNGROUPED:
        result[target].append(suite)
    return validate_groups(result)
