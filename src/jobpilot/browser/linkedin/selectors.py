"""EVERY LinkedIn selector lives here.

WHY: LinkedIn changes its markup every few months, and that is the #1 reason
browser bots break. With all selectors in one file (each as an ordered list of
fallbacks) a UI change is a 5-minute edit instead of a hunt through 900 lines.

HOW TO FIX A BROKEN SELECTOR: open the page, right-click the element ->
Inspect, then add the new XPath/CSS at the FRONT of the relevant list. Old
entries can stay as fallbacks. Selectors marked [legacy-proven] come from the
old bot, which worked against the live site.
"""
from ..helpers import CLS, CSS, XP

# ------------------------------------------------------------------ jobs list
JOB_CARDS = [
    XP("//li[@data-occludable-job-id]"),                                  # [legacy-proven]
    XP("//div[.//a[contains(@href, '/jobs/view/')]][.//button[contains(@aria-label, 'Apply')]]"
       "[not(.//div[.//a[contains(@href, '/jobs/view/')]][.//button[contains(@aria-label, 'Apply')]])]"),
]
CARD_LINK = [XP(".//a[contains(@href, '/jobs/view/')]"), XP(".//a")]     # [legacy-proven]
CARD_SUBTITLE = [CLS("artdeco-entity-lockup__subtitle"), CSS("a[href*='/company/']")]
CARD_META = [XP(".//p[.//span[contains(normalize-space(), ' ago')]]")]
CARD_STATE = [CLS("job-card-container__footer-job-state")]                # "Applied" [legacy-proven]
JOB_DESCRIPTION = [CLS("jobs-box__html-content"), CSS("#job-details"), CLS("jobs-description__content")]
TOP_CARD = [CLS("job-details-jobs-unified-top-card__primary-description-container"),
            CLS("job-details-jobs-unified-top-card__primary-description"),
            CLS("jobs-unified-top-card__primary-description"), CLS("jobs-details__main-content")]
POSTED_TEXT = [XP(".//span[contains(normalize-space(), ' ago')]")]       # [legacy-proven]
HIRER_CARD = [CLS("hirer-card__hirer-information")]                       # [legacy-proven]

# ---------------------------------------------------------------- easy apply
EASY_APPLY_BUTTON = [
    XP(".//button[contains(@aria-label,'Easy Apply')]"),
    XP(".//button[contains(@class,'jobs-apply-button') and contains(@aria-label,'Easy')]"),   # [legacy-proven]
    XP("//button[contains(@class,'jobs-apply-button')][.//span[contains(.,'Easy Apply')]]"),
]
ANY_APPLY_BUTTON = [
    XP(".//button[contains(@aria-label,'Apply')]"),
    XP(".//button[contains(@class,'jobs-apply-button')]"),
]
MODAL = [CLS("jobs-easy-apply-modal"), CSS("div[role='dialog']")]         # [legacy-proven]
FORM_ELEMENTS = [XP(".//div[@data-test-form-element]")]                   # [legacy-proven]
RADIO_FIELDSET = XP('.//fieldset[@data-test-form-builder-radio-button-form-component="true"]')  # [legacy-proven]
RADIO_TITLE = [XP(".//span[@data-test-form-builder-radio-button-form-component__title]"), XP(".//legend")]
TEXT_INPUT = [XP(".//input[not(@type) or @type='text' or @type='number' or @type='tel' or @type='email' or @type='url']")]
TEXTAREA = [XP(".//textarea")]
SELECT = [XP(".//select")]
CHECKBOX = [XP(".//input[@type='checkbox']")]
FILE_INPUT = [XP(".//input[@type='file']")]
FIELD_ERRORS = [XP(".//*[contains(@class,'artdeco-inline-feedback--error')]")]
FOLLOW_CHECKBOX_LABEL = [XP(".//label[@for='follow-company-checkbox']")]  # [legacy-proven]
FOLLOW_CHECKBOX = [XP(".//input[@id='follow-company-checkbox']")]


def job_card(job_id: str):
    if not job_id.isdecimal():
        return []
    href = f"/jobs/view/{job_id}"
    return [
        XP(f"//div[.//a[contains(@href, '{href}')]][.//button[contains(@aria-label, 'Apply')]]"
           f"[not(.//div[.//a[contains(@href, '{href}')]][.//button[contains(@aria-label, 'Apply')]])]"),
        XP(f"//li[@data-occludable-job-id='{job_id}']"),
    ]


def job_apply_buttons(job_id: str, easy_only: bool = False):
    cards = job_card(job_id)
    if not cards:
        return []
    button_label = "Easy Apply" if easy_only else "Apply"
    legacy_match = ("[contains(@aria-label,'Easy') or .//span[contains(.,'Easy Apply')]]"
                    if easy_only else "")
    return [
        XP(f"{cards[0][1]}//button[contains(@aria-label, '{button_label}')]"),
        XP(f"//li[@data-occludable-job-id='{job_id}']//button[contains(@class,'jobs-apply-button')]{legacy_match}"),
    ]


def button(*labels: str):
    """Button whose visible text OR aria-label contains one of `labels`."""
    cond = " or ".join(f"normalize-space(.)='{l}' or contains(@aria-label,'{l}')" for l in labels)
    return [XP(f".//button[.//span[{cond}] or {cond.replace('normalize-space(.)', 'normalize-space(@aria-label)')}]")]


NEXT_BUTTON = button("Next", "Continue to next step")
REVIEW_BUTTON = button("Review", "Review your application")
SUBMIT_BUTTON = button("Submit application")
DONE_BUTTON = button("Done")
DISMISS_BUTTON = button("Dismiss")
DISCARD_CONFIRM = [XP("//button[.//span[normalize-space(.)='Discard']]")]
DAILY_LIMIT_TEXT = "exceeded the daily application limit"
SUCCESS_TEXTS = ("application sent", "your application was sent")

# ---------------------------------------------------------------- post search
POST_CONTAINERS = [CSS("div.feed-shared-update-v2"), CSS("div[data-urn*='urn:li:activity']"),
                   CSS("li.reusable-search__result-container"), CSS("div.update-components-text")]
POST_TEXT = [CSS(".update-components-text"), CSS(".feed-shared-inline-show-more-text"), CSS("span.break-words")]
POST_AUTHOR = [CSS(".update-components-actor__title span[aria-hidden='true']"), CSS(".update-components-actor__name")]
POST_TIME = [CSS(".update-components-actor__sub-description span[aria-hidden='true']"),
             CSS(".update-components-actor__sub-description")]
POST_SEE_MORE = [CSS("button.feed-shared-inline-show-more-text__see-more-less-toggle"),
                 XP(".//button[contains(normalize-space(.),'more') and contains(@class,'see-more')]"),
                 XP(".//button[normalize-space(.)='…more' or normalize-space(.)='...more']")]
PostLinks = [CSS("a[href]")]
