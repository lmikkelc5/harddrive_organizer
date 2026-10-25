"""Which organizer features are built. Scenarios for features not listed here
are reported as 'pending' instead of failed, so features can be built one at a time."""

BUILT_FEATURES = {
    "date-basic",
    "iphone",
    "sanity",
    "guesses",
    "folder-hints",
    "labels",
    "date-folders",
    "edge",
    "manual-edits",
    "big",
}

# Time zone the test drive is checked against (UTC video times are converted to it).
TEST_TIMEZONE = "America/Los_Angeles"
