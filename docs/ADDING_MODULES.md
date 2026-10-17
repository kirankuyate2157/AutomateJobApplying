# Adding modules: recipes

Everything below is **additive**: no existing file needs editing except config.

## 1. A new pipeline stage (e.g. Naukri applications)

Create `my_plugins/naukri.py` in your project folder (project root is auto-added to `sys.path`):

```python
from jobpilot.core.registry import stages
from jobpilot.core.stage import StageResult

class NaukriStage:
    name = "naukri"
    description = "Apply to fresh Naukri jobs"

    def run(self, ctx):                     # ctx: settings, profile, repo, engine, llm, driver
        # reuse: JobScorer, AnswerEngine (ctx.engine), DailyRunner with your own JobSource/Applier
        return StageResult(self.name, True, {"applied": 0})

stages.register("naukri")(NaukriStage())
```

`config/settings.yaml`:

```yaml
plugins: [my_plugins.naukri]
pipeline:
  stages: [posts, jobs, naukri, outreach]
```

Cheapest path for a new JOB BOARD: implement `JobSource.iter_jobs(spec) -> Iterator[Job]` and `Applier.apply(job, resume_path) -> ApplyResult` (see `features/jobs/ports.py`), then pass them to `DailyRunner`. You inherit scoring, quota, throttle, dedupe, contact harvesting and reporting for free.

## 2. A new CLI command

```python
from jobpilot.core.command import Command
from jobpilot.core.registry import commands
commands.register("hello")(Command("hello", "say hi", lambda ctx, args: print(ctx.profile.first_name) or 0))
```
Add `needs_context=False` for commands that must run before configuration exists.

## 3. A new answer rule

In `answering/rules.py` (or a plugin importing `rule`):

```python
@rule("github_stars", r"how many (github )?stars", confidence=0.8, max_words=8)
def _(ctx, m): return "120"
```
Specific rules must be registered BEFORE generic ones (the file order is the priority order). Add a test in `tests/test_answering.py`.

Don't want code? Add a regex to `canned_answers` in `config/profile.yaml`.

## 4. A new skill

Add `"canonical": ["alias", ...]` to `SKILLS` in `extraction/skills.py`, and list the canonical name under `skills:` in your profile.

## 5. A new exporter (JSON, Google Sheets...)

```python
from jobpilot.core.registry import exporters
@exporters.register("json")
def export_json(datasets, out_dir): ...      # return list of written Paths
```
Then `jobpilot export --format json`.

## 6. A new database column/table

Append a new SQL string to `MIGRATIONS` in `storage/db.py` (never edit old ones). The schema upgrades automatically on next start. Add a method to `Repository` and a test.

## 7. A new LLM provider

Implement `complete(prompt) -> str` (see `GeminiClient`) and branch in `make_llm`. Any OpenAI-compatible server (Groq, OpenRouter, Ollama, LM Studio) already works with `provider: openai` + `base_url`.

## 8. Fixing a broken LinkedIn selector

See `docs/OPERATIONS.md`. Edit only `browser/linkedin/selectors.py`.
