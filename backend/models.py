"""Scheduling and standing constants"""

# Full-time floor and typical target for generated recommendations (credit hours)
SCHEDULE_TARGET_MIN_CREDITS = 12
SCHEDULE_TARGET_IDEAL_CREDITS = 15

# Class standing thresholds (earned credit hours). Used when student history has no explicit standing.
STANDING_ORDER = ("Freshman", "Sophomore", "Junior", "Senior")
STANDING_RANK = {name: i for i, name in enumerate(STANDING_ORDER)}
STANDING_THRESHOLDS = (
    (30, "Sophomore"),
    (60, "Junior"),
    (90, "Senior"),
)
