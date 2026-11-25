"""Outreach feature: turn harvested emails into reviewed, rate-limited
application mails, plus LinkedIn network outreach (connect, dm, followup,
referral).

Importing this package registers the `outreach` stage/command (email) and the
`network` stage/command (LinkedIn native).
"""
from . import stage  # noqa: F401  (email outreach stage + `mail` command)
from . import network_stage  # noqa: F401  (LinkedIn network stage + `network` command)
