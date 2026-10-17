import unittest

from jobpilot.answering.engine import AnswerEngine
from jobpilot.answering.llm import parse_llm_json
from jobpilot.answering.normalize import clean_label, normalize_question
from jobpilot.answering.options import best_option, range_option
from jobpilot.domain.models import FormField, Job
from jobpilot.profile.profile import Profile
from jobpilot.settings import AnswerSettings
from jobpilot.storage.db import Repository


def make_profile(**kw):
    base = dict(
        first_name="Kiran", last_name="Kuyate", email="k@example.com", phone="9000000000",
        city="Mumbai", state="Maharashtra", country="India", zip_code="400708",
        total_years=3, current_company="NeoSoft", current_title="Software Engineer",
        notice_period_days=30, current_ctc=750000, expected_ctc=1800000,
        skills={"python": 3, "node.js": 3, "docker": 2}, degrees=["bachelor"],
        linkedin_url="https://linkedin.com/in/k", demographics={"gender": "Male", "disability": "No"},
        canned_answers=[{"match": "why.*interested", "answer": "Great fit for my backend skills."}])
    base.update(kw)
    return Profile.from_dict(base)


class FakeLLM:
    def __init__(self, reply): self.reply, self.calls = reply, 0
    def complete(self, prompt):
        self.calls += 1
        return self.reply


def field(label, kind="text", options=None):
    return FormField(label=label, kind=kind, options=options or [])


class HelperTests(unittest.TestCase):
    def test_normalize(self):
        self.assertEqual(normalize_question("Phone *"), "phone")
        self.assertEqual(normalize_question('Email address [ "Select an option", "a@b.c" ]'), "email address")
        self.assertEqual(clean_label("Phone\nPhone"), "Phone")
        self.assertEqual(normalize_question("Years of experience with Python?"), "years of experience with python")

    def test_best_option(self):
        self.assertEqual(best_option("Yes", ["Select an option", "Yes", "No"]), "Yes")
        self.assertEqual(best_option("No", ["Yes, I am", "No, I am not"]), "No, I am not")
        self.assertEqual(best_option("Decline", ["Male", "Female", "I prefer not to say"]), "I prefer not to say")
        self.assertEqual(best_option("India (+91)", ["United States (+1)", "India (+91)"]), "India (+91)")
        self.assertIsNone(best_option("Banana", ["Yes", "No"]))

    def test_range_option(self):
        opts = ["Less than 1 year", "1-3 years", "3-5 years", "5+ years"]
        self.assertEqual(range_option(0.5, opts), "Less than 1 year")
        self.assertEqual(range_option(3, opts), "1-3 years")
        self.assertEqual(range_option(7, opts), "5+ years")

    def test_parse_llm_json(self):
        self.assertEqual(parse_llm_json('```json\n{"answer": "Yes", "confidence": 0.9}\n```'), ("Yes", 0.9))
        self.assertIsNone(parse_llm_json("no json"))
        self.assertIsNone(parse_llm_json('{"answer": "", "confidence": 1}'))


class RuleTests(unittest.TestCase):
    def setUp(self):
        self.repo = Repository(":memory:")
        self.engine = AnswerEngine(self.repo, make_profile(), AnswerSettings())
        self.job = Job("1", "Dev", "Acme", "Pune, India")

    def ans(self, label, kind="text", options=None):
        a = self.engine.resolve(field(label, kind, options), self.job)
        return a.value if a else None

    def test_identity(self):
        self.assertEqual(self.ans("First name"), "Kiran")
        self.assertEqual(self.ans("Last name"), "Kuyate")
        self.assertEqual(self.ans("Mobile phone number"), "9000000000")
        self.assertEqual(self.ans("Phone country code", "select", ["Select an option", "India (+91)", "US (+1)"]), "India (+91)")
        self.assertEqual(self.ans("Email address", "select", ["Select an option", "other@x.com"]), "other@x.com")
        self.assertEqual(self.ans("City"), "Mumbai")

    def test_guard_stops_keyword_leaks(self):
        # 'state' / 'country' / 'location' inside long questions must NOT answer with city/state
        self.assertIsNone(self.ans("Please state your preferred work arrangement in detail"))
        self.assertIsNone(self.ans("Describe your notice period handover plan", "textarea"))
        self.assertEqual(self.ans("State"), "Maharashtra")
        self.assertEqual(self.ans("Are you legally authorized to work in the country?", "radio", ["Yes", "No"]), "Yes")

    def test_money_units(self):
        self.assertEqual(self.ans("What is your expected CTC in lakhs?"), "18")
        self.assertEqual(self.ans("Current CTC (LPA)", "number"), "7.5")
        self.assertEqual(self.ans("Expected monthly salary"), "150000")
        self.assertEqual(self.ans("Current salary"), "750000")

    def test_notice(self):
        self.assertEqual(self.ans("Notice period in days", "number"), "30")
        self.assertEqual(self.ans("Notice period (months)"), "1")
        self.assertEqual(self.ans("Can you join within 30 days?", "radio", ["Yes", "No"]), "Yes")
        self.assertEqual(self.ans("Can you join within 15 days?", "radio", ["Yes", "No"]), "No")

    def test_experience(self):
        self.assertEqual(self.ans("How many years of experience do you have with Python?", "number"), "3")
        self.assertEqual(self.ans("How many years of work experience do you have in iOS?"), "0")   # honest zero
        self.assertEqual(self.ans("Total years of software development experience", "number"), "3")
        self.assertEqual(self.ans("Do you have 5+ years of experience with Python?", "radio", ["Yes", "No"]), "No")
        self.assertEqual(self.ans("Do you have experience with Docker?", "radio", ["Yes", "No"]), "Yes")
        self.assertEqual(self.ans("Years of experience with Docker", "select", ["0-1", "1-3", "3-5"]), "1-3")

    def test_eligibility_and_demographics(self):
        self.assertEqual(self.ans("Will you require visa sponsorship?", "radio", ["Yes", "No"]), "No")
        self.assertEqual(self.ans("Have you completed a Bachelor's degree?", "radio", ["Yes", "No"]), "Yes")
        self.assertEqual(self.ans("Do you hold a Master's degree?", "radio", ["Yes", "No"]), "No")
        self.assertEqual(self.ans("Gender", "select", ["Select an option", "Male", "Female", "Decline"]), "Male")
        self.assertEqual(self.ans("Disability status", "select", ["Yes", "No", "Decline"]), "No")
        self.assertEqual(self.ans("I agree to the terms and conditions", "checkbox"), "Yes")

    def test_canned_beats_rules_and_low_confidence_is_not_used(self):
        self.assertEqual(self.ans("Why are you interested in this role?", "textarea"), "Great fit for my backend skills.")
        # generic willingness has confidence 0.6 < 0.7 -> no LLM -> queued for review, not guessed
        self.assertIsNone(self.ans("Are you willing to work night shifts?", "radio", ["Yes", "No"]))


class EngineFlowTests(unittest.TestCase):
    def setUp(self):
        self.repo = Repository(":memory:")

    def engine(self, llm=None):
        return AnswerEngine(self.repo, make_profile(), AnswerSettings(), llm)

    def test_unknown_question_queued_then_user_answer_wins(self):
        e = self.engine()
        f = field("What is your favourite colour?")
        self.assertIsNone(e.resolve(f))
        pending = self.repo.list_questions("pending")
        self.assertEqual([q["key"] for q in pending], ["what is your favourite colour"])
        self.repo.set_user_answer("what is your favourite colour", "Blue")
        self.assertEqual(e.resolve(field("What is your favourite colour?")).value, "Blue")
        self.assertEqual(self.repo.get_question("what is your favourite colour")["times_seen"], 2)

    def test_llm_answer_validated_cached_and_reused(self):
        llm = FakeLLM('{"answer": "Yes", "confidence": 0.9}')
        e = self.engine(llm)
        opts = ["Yes", "No"]
        first = e.resolve(field("Are you comfortable with pair programming sessions", "radio", opts))
        self.assertEqual((first.value, first.source), ("Yes", "llm"))
        second = e.resolve(field("Are you comfortable with pair programming sessions", "radio", opts))
        self.assertEqual((second.value, second.source), ("Yes", "cache"))
        self.assertEqual(llm.calls, 1)

    def test_llm_low_confidence_or_invalid_option_rejected(self):
        e = self.engine(FakeLLM('{"answer": "Yes", "confidence": 0.3}'))
        self.assertIsNone(e.resolve(field("Describe your dream job culture", "radio", ["Yes", "No"])))
        e = self.engine(FakeLLM('{"answer": "Banana", "confidence": 0.99}'))
        self.assertIsNone(e.resolve(field("Pick one thing", "radio", ["Yes", "No"])))

    def test_llm_crash_is_contained(self):
        class Boom:
            def complete(self, prompt): raise RuntimeError("quota")
        self.assertIsNone(self.engine(Boom()).resolve(field("Something unusual here")))

    def test_textarea_llm_answer_not_cached(self):
        llm = FakeLLM('{"answer": "I like this because X.", "confidence": 0.9}')
        e = self.engine(llm)
        e.resolve(field("What excites you about this company?", "textarea"))
        e.resolve(field("What excites you about this company?", "textarea"))
        self.assertEqual(llm.calls, 2)


if __name__ == "__main__":
    unittest.main()
