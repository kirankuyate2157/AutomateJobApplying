"""Exception hierarchy.

WHY: the pipeline needs to tell "skip this job" problems apart from "stop the
whole run" problems. Typed exceptions make that decision explicit instead of
string-matching error messages (a weakness of the legacy bot).
"""


class JobPilotError(Exception):
    """Base class for every error we raise on purpose."""


class ConfigError(JobPilotError):
    """Settings/profile file is missing, malformed or has unknown keys."""


class ManualInterventionRequired(JobPilotError):
    """A captcha / checkpoint / 2FA needs a human. The run pauses or stops."""


class DailyLimitReached(JobPilotError):
    """LinkedIn refused further Easy Applies today. Stop the run cleanly."""


class ApplyFailed(JobPilotError):
    """One application failed; the run continues with the next job."""
