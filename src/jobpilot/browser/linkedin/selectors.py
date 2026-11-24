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
    XP("//div[@role='button'][contains(@componentkey, 'job-card-component-ref')]"),
    XP("//div[contains(@componentkey, 'job-card-component-ref')]"),
    XP("//li[@data-occludable-job-id]"),                                  # [legacy-proven]
    XP("//div[contains(@class, 'job-card-container') and (@data-job-id or .//a[contains(@href, '/jobs/view/')])]"),
    XP("//li[contains(@class, 'jobs-search-results__list-item')]"),
    XP("//div[.//a[contains(@href, '/jobs/view/')]][.//button[contains(@aria-label, 'Apply')]]"
       "[not(.//div[.//a[contains(@href, '/jobs/view/')]][.//button[contains(@aria-label, 'Apply')]])]"),
]
CARD_LINK = [XP(".//a[contains(@href, '/jobs/view/')]"), XP(".//a")]     # [legacy-proven]
CARD_SUBTITLE = [CLS("artdeco-entity-lockup__subtitle"), CSS("a[href*='/company/']")]
CARD_META = [XP(".//p[.//span[contains(normalize-space(), ' ago')]]")]
CARD_STATE = [CLS("job-card-container__footer-job-state")]                # "Applied" [legacy-proven]
JOB_DESCRIPTION = [
    CSS("#job-details"),
    CLS("jobs-description__content"),
    CLS("jobs-box__html-content"),
    CLS("jobs-description-content__text"),
    CSS("article.jobs-description__container"),
    XP("//div[contains(@class,'jobs-description')]"),
    XP("//div[contains(@class, 'k4dl5v') and contains(@class, 'k4dlcd')][string-length(normalize-space()) > 200]"),
]
TOP_CARD = [CLS("job-details-jobs-unified-top-card__primary-description-container"),
            CLS("job-details-jobs-unified-top-card__primary-description"),
            CLS("jobs-unified-top-card__primary-description"), CLS("jobs-details__main-content")]
POSTED_TEXT = [XP(".//span[contains(normalize-space(), ' ago')]")]       # [legacy-proven]
HIRER_CARD = [CLS("hirer-card__hirer-information")]                       # [legacy-proven]

# ---------------------------------------------------------------- easy apply
EASY_APPLY_BUTTON = [
    # aria-label patterns (most common)
    XP("//button[contains(@aria-label,'Easy Apply to') or contains(@aria-label,'Easy Apply')]"),
    XP("//button[normalize-space(.)='Easy Apply' or contains(normalize-space(.), 'Easy Apply')]"),
    # Top card / details pane containers
    XP("//div[contains(@class,'jobs-apply-button--top-card')]//button[contains(@aria-label,'Easy Apply') or .//span[contains(normalize-space(),'Easy Apply')]]"),
    XP("//div[contains(@class,'jobs-details')]//button[contains(@aria-label,'Easy Apply') or .//span[contains(normalize-space(),'Easy Apply')]]"),
    # jobs-apply-button class combinations
    XP("//button[contains(@class,'jobs-apply-button')][contains(@aria-label,'Easy') or .//span[contains(normalize-space(),'Easy Apply')]]"),
    XP(".//button[contains(@aria-label,'Easy Apply')]"),
    XP(".//button[contains(@class,'jobs-apply-button') and contains(@aria-label,'Easy')]"),   # [legacy-proven]
    XP("//button[contains(@class,'jobs-apply-button')][.//span[contains(.,'Easy Apply')]]"),
    # data-test attributes
    XP("//button[contains(@data-test,'apply-button') or contains(@data-test,'easy-apply')]"),
    XP("//button[contains(@data-test,'easy-apply-button')]"),
    # artdeco-button class with Easy Apply text
    XP("//button[contains(@class,'artdeco-button')][contains(.,'Easy Apply')]"),
    XP("//button[contains(@class,'artdeco-button')][contains(@aria-label,'Easy Apply')]"),
    # Broad fallbacks
    XP("//button[contains(@class,'jobs-apply-button')]"),
    XP("//button[contains(@aria-label,'Apply') and contains(.,'Easy')]"),
    XP(".//button[contains(.,'Easy Apply')]"),
    XP("//button[.//span[contains(normalize-space(),'Easy Apply')]]"),
    # Keep as last resort
    XP("//button[contains(.,'Easy Apply')]"),
]
ANY_APPLY_BUTTON = [
    XP("//button[contains(@aria-label,'Apply to') or contains(@aria-label,'Apply')]"),
    XP("//button[normalize-space(.)='Apply' or contains(normalize-space(.), 'Apply')]"),
    XP("//div[contains(@class,'jobs-apply-button--top-card')]//button"),
    XP("//div[contains(@class,'jobs-details')]//button[contains(@class,'jobs-apply-button') or contains(@aria-label,'Apply')]"),
    XP("//button[contains(@class,'jobs-apply-button')]"),
    XP(".//button[contains(@aria-label,'Apply')]"),
    XP(".//button[contains(@class,'jobs-apply-button')]"),
    XP("//button[contains(@data-test,'apply-button')]"),
    XP("//button[contains(@class,'artdeco-button')][contains(.,'Apply')]"),
    XP(".//button[contains(.,'Apply')]"),
]
MODAL = [
    XP("//div[contains(@class, 'k4da2a') or contains(@class, 'jobs-easy-apply-modal') or (@role='dialog' and not(contains(@class, 'vjs')))]"),
    XP("//div[.//button[normalize-space(.)='Next' or @aria-label='Next' or contains(., 'Review') or contains(., 'Submit')]][.//button[@aria-label='Dismiss']]"),
    CLS("jobs-easy-apply-modal"),
    CSS("div[role='dialog']"),
    # Broad fallback: any dialog with form elements
    XP("//div[@role='dialog'][.//input or .//select or .//textarea or .//fieldset]"),
]
FORM_ELEMENTS = [
    XP(".//div[@data-test-form-element]"),                                 # [legacy-proven]
    XP(".//div[contains(@class,'jobs-easy-apply-form-section__grouping')]"),
    XP(".//div[contains(@class,'fb-dash-form-element')]"),
    XP(".//div[contains(@class,'jobs-easy-apply-form-element')]"),
    XP(".//div[.//label and (.//input or .//select or .//textarea or .//fieldset)]"),
    XP(".//fieldset[.//input or .//select]"),
    XP(".//div[contains(@class,'artdeco-text-input--container')]"),
    # Additional fallbacks for current LinkedIn markup
    XP(".//div[contains(@class,'jobs-easy-apply-form-element__grouping')]"),
    XP(".//div[contains(@class,'artdeco-text-input--input')]/.."),
    XP(".//div[contains(@class,'jobs-easy-apply-form-element__grouping')]//input"),
    # Any div containing a form control directly
    XP(".//div[.//input[@type='text' or @type='email' or @type='tel' or @type='number' or not(@type)]]"),
    XP(".//div[.//textarea]"),
    XP(".//div[.//select]"),
    XP(".//div[.//input[@type='checkbox']]"),
    XP(".//div[.//fieldset]"),
]
RADIO_FIELDSET = [
    XP('.//fieldset[@data-test-form-builder-radio-button-form-component="true"]'),  # [legacy-proven]
    XP('.//fieldset[.//input[@type="radio"]]'),
    XP('.//div[contains(@class,"radio")]//fieldset'),
    XP('.//fieldset[.//label and .//input[@type="radio"]]'),
]
RADIO_TITLE = [XP(".//span[@data-test-form-builder-radio-button-form-component__title]"), XP(".//legend")]
TEXT_INPUT = [XP(".//input[not(@type) or @type='text' or @type='number' or @type='tel' or @type='email' or @type='url']")]
TEXTAREA = [XP(".//textarea")]
SELECT = [XP(".//select")]
CHECKBOX = [XP(".//input[@type='checkbox']")]
FILE_INPUT = [XP(".//input[@type='file']")]
FIELD_ERRORS = [
    XP(".//*[contains(@class,'artdeco-inline-feedback--error')]"),
    XP(".//*[contains(@class,'error') and contains(@class,'feedback')]"),
    XP(".//span[contains(@class,'error')]"),
]
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
    button_label = "Easy Apply" if easy_only else "Apply"
    legacy_match = ("[contains(@aria-label,'Easy') or .//span[contains(.,'Easy Apply')]]"
                    if easy_only else "")
    res = [
        XP(f"//div[contains(@class,'jobs-apply-button--top-card')]//button[contains(@aria-label, '{button_label}') or .//span[contains(., '{button_label}')]]"),
        XP(f"//div[contains(@class,'jobs-details')]//button[contains(@aria-label, '{button_label}') or .//span[contains(., '{button_label}')]]"),
        XP(f"//button[contains(@class,'jobs-apply-button')]{legacy_match}"),
        XP(f"//button[contains(@aria-label, '{button_label}')]"),
    ]
    if job_id and job_id.isdecimal():
        res.append(XP(f"//li[@data-occludable-job-id='{job_id}']//button[contains(@class,'jobs-apply-button')]{legacy_match}"))
    return res


def button(*labels: str):
    """Button whose visible text OR aria-label contains one of `labels`."""
    span_cond = " or ".join(f"normalize-space(.)='{l}' or contains(@aria-label,'{l}')" for l in labels)
    btn_cond = " or ".join(f"contains(normalize-space(.),'{l}') or contains(@aria-label,'{l}')" for l in labels)
    return [
        XP(f".//button[.//span[{span_cond}]]"),
        XP(f".//button[{btn_cond}]"),
    ]


NEXT_BUTTON = [
    *button("Next", "Continue to next step"),
    XP("//button[contains(@class,'artdeco-button--primary')][contains(.,'Next') or contains(@aria-label,'Next')]"),
    XP("//button[contains(@data-test,'next-button') or contains(@data-test,'continue-button')]"),
    XP(".//button[contains(.,'Next')]"),
]
REVIEW_BUTTON = [
    *button("Review", "Review your application"),
    XP("//button[contains(@class,'artdeco-button--primary')][contains(.,'Review') or contains(@aria-label,'Review')]"),
    XP("//button[contains(@data-test,'review-button')]"),
    XP(".//button[contains(.,'Review')]"),
]
SUBMIT_BUTTON = [
    *button("Submit application"),
    XP("//button[contains(@class,'artdeco-button--primary')][contains(.,'Submit') or contains(@aria-label,'Submit')]"),
    XP("//button[contains(@data-test,'submit-button')]"),
    XP(".//button[contains(.,'Submit')]"),
]
DONE_BUTTON = button("Done")
DISMISS_BUTTON = button("Dismiss")
DISCARD_CONFIRM = [XP("//button[.//span[normalize-space(.)='Discard']]")]
DAILY_LIMIT_TEXT = "exceeded the daily application limit"
SUCCESS_TEXTS = ("application sent", "your application was sent")

# ---------------------------------------------------------------- post search
POST_CONTAINERS = [
    # broad: any div carrying an activity URN (covers current + legacy markup)
    CSS("div[data-urn]"),
    # semantic article wrapper
    CSS("article"),
    # most stable: LinkedIn activity URN attribute (doesn't rotate with CSS hashes)
    CSS("div[data-urn*='urn:li:activity']"),
    # generic update-component containers
    CSS("div[class*='update-components']"),
    # legacy class (may still match)
    CSS("div.feed-shared-update-v2"),
    # current LinkedIn post-search feed containers (hash classes rotate frequently)
    CSS("div.dr0hiu.dr0hr1.dr0kdh"),
    CSS("div.dr0ayq.dr0kdh"),
    CSS("li.reusable-search__result-container"),
    CSS("div.update-components-text"),
]
POST_TEXT = [CSS(".update-components-text"), CSS(".feed-shared-inline-show-more-text"), CSS("span.break-words")]
POST_AUTHOR = [CSS(".update-components-actor__title span[aria-hidden='true']"), CSS(".update-components-actor__name")]
POST_TIME = [CSS(".update-components-actor__sub-description span[aria-hidden='true']"),
             CSS(".update-components-actor__sub-description")]
POST_SEE_MORE = [CSS("button.feed-shared-inline-show-more-text__see-more-less-toggle"),
                 XP(".//button[contains(normalize-space(.),'more') and contains(@class,'see-more')]"),
                 XP(".//button[normalize-space(.)='…more' or normalize-space(.)='...more']")]
# LinkedIn content search uses a "Load more" button instead of infinite scroll.
# Click it when a scroll round surfaces no new posts.
LOAD_MORE_BUTTON = [
    XP(".//*[contains(normalize-space(.),'Load more') and (self::button or self::a or @role='button')]"),
]
PostLinks = [CSS("a[href]")]

# ---------------------------------------------------------------- single post page
# When we open a post's own URL (feed/update/...), LinkedIn renders the full
# post plus comments. Comments often carry the real "send CV to..." email that
# the post body truncates, so deep per-page analysis is worth one extra load.
POST_PAGE_TEXT = [CSS("div.update-components-text"), CSS("div.feed-shared-update-v2__content"),
                  CSS("span.break-words"), CSS("article div[dir='auto']")]
POST_PAGE_COMMENTS = [CSS("div.comments-comments-list"),
                      CSS("div.feed-shared-social-bar__social-counts")]
POST_COMMENT_ITEM = [CSS("li.comments-comment-item"), CSS("div.comments-comment-entity")]
POST_COMMENT_TEXT = [CSS(".comments-comment-item__main-content"), CSS("span.break-words")]
