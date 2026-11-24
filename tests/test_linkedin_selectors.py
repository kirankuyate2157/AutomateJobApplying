import unittest
from selenium.webdriver.common.by import By

from jobpilot.browser.linkedin import selectors as S


class LinkedInSelectorTests(unittest.TestCase):
    def test_job_apply_buttons(self):
        buttons = S.job_apply_buttons("123456", easy_only=True)
        self.assertTrue(len(buttons) >= 4)
        # Verify first selectors look at top card / details pane rather than being restricted to left card item
        first_by, first_xp = buttons[0]
        self.assertEqual(first_by, By.XPATH)
        self.assertIn("jobs-apply-button--top-card", first_xp)

        # Non-easy apply includes general apply
        any_buttons = S.job_apply_buttons("123456", easy_only=False)
        self.assertTrue(len(any_buttons) >= 4)
        self.assertIn("Apply", any_buttons[0][1])

    def test_easy_apply_buttons_list(self):
        self.assertTrue(len(S.EASY_APPLY_BUTTON) >= 4)
        # Must include top-card and details pane selectors
        xpaths = [xp for by, xp in S.EASY_APPLY_BUTTON if by == By.XPATH]
        self.assertTrue(any("top-card" in xp for xp in xpaths))
        self.assertTrue(any("jobs-details" in xp for xp in xpaths))

    def test_form_elements_fallbacks(self):
        # Must include multiple container fallbacks, not just data-test-form-element
        self.assertTrue(len(S.FORM_ELEMENTS) >= 4)
        xpaths = [xp for by, xp in S.FORM_ELEMENTS if by == By.XPATH]
        self.assertTrue(any("jobs-easy-apply-form-section__grouping" in xp for xp in xpaths))
        self.assertTrue(any("fieldset" in xp for xp in xpaths))

    def test_button_builder(self):
        next_btns = S.button("Next")
        self.assertEqual(len(next_btns), 2)
        # Checks both span child and button element itself
        self.assertIn(".//span", next_btns[0][1])
        self.assertIn(".//button[contains", next_btns[1][1])
