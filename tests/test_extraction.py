import unittest

from jobpilot.extraction.contacts import analyze_post, classify_link, extract_emails, extract_phones
from jobpilot.extraction.skills import extract_skills, find_skills, required_years


class SkillTests(unittest.TestCase):
    def test_aliases_and_symbols(self):
        text = "Strong Node.js, ReactJS, C++ and .NET; FastAPI + PostgreSQL on AWS (EC2)."
        self.assertEqual(extract_skills(text),
                         {"node.js", "react", "c++", ".net", "fastapi", "postgresql", "aws"})

    def test_java_not_in_javascript(self):
        self.assertEqual(extract_skills("JavaScript developer"), {"javascript"})
        self.assertEqual(extract_skills("Java and JavaScript"), {"java", "javascript"})

    def test_order_by_first_occurrence(self):
        self.assertEqual(find_skills("years with Docker and Python"), ["docker", "python"])

    def test_required_years_uses_headline(self):
        self.assertEqual(required_years("Experience: 3-5 years overall; 8 years in sales"), (3.0, 5.0))
        self.assertEqual(required_years("Minimum 4+ years of experience"), (4.0, None))
        self.assertEqual(required_years("No numbers here"), (None, None))
        self.assertEqual(required_years("Founded 10 years ago, we are great"), (None, None))


class ContactTests(unittest.TestCase):
    def test_emails_including_obfuscated(self):
        text = "Send CV to HR@Acme.com or jobs [at] beta [dot] io. logo@2x.png noreply@acme.com"
        self.assertEqual(extract_emails(text), ["hr@acme.com", "jobs@beta.io"])

    def test_phones(self):
        text = "Call +91 98765 43210 or 9123456789. Job id 7123456789012345678 https://x.com/7123456789"
        self.assertEqual(extract_phones(text), ["+919876543210", "+919123456789"])

    def test_intl_phone(self):
        self.assertEqual(extract_phones("US office +1 415-555-2671"), ["+14155552671"])

    def test_link_classes(self):
        self.assertEqual(classify_link("https://forms.gle/abc"), "form")
        self.assertEqual(classify_link("https://boards.greenhouse.io/x/jobs/1"), "ats")
        self.assertEqual(classify_link("https://lnkd.in/abc"), "short")

    def test_hiring_post(self):
        post = ("We are hiring! Python Developer (3-5 yrs) and Senior Backend Engineer. "
                "Send your resume to talent@foo.com or apply https://forms.gle/xyz. #hiring")
        a = analyze_post(post)
        self.assertTrue(a.is_hiring)
        self.assertEqual(a.emails, ["talent@foo.com"])
        self.assertIn("https://forms.gle/xyz", a.links)
        self.assertIn("Python Developer", a.roles)

    def test_job_seeker_post_rejected(self):
        a = analyze_post("I am looking for new opportunities. #OpenToWork Python dev, email me me@x.com")
        self.assertFalse(a.is_hiring)

    def test_mailto_href_used(self):
        a = analyze_post("Hiring Node developers, apply by email", extra_hrefs=["mailto:cv@firm.in"])
        self.assertEqual(a.emails, ["cv@firm.in"])
        self.assertTrue(a.is_hiring)


if __name__ == "__main__":
    unittest.main()
