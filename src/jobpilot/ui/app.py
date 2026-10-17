"""Tiny local web dashboard (Flask). Review unanswered questions, browse data.

Binds to 127.0.0.1 only: it has no login, so it must never be exposed.
Requires the optional extra:  pip install "jobpilot[ui]"

SUGGESTION: add pages for editing mail drafts, approving mails in one click and
a chart of applications per day.
"""
from __future__ import annotations

from flask import Flask, redirect, render_template_string, request, url_for

from ..answering.normalize import normalize_question
from ..core.context import AppContext
from ..reporting.datasets import build_datasets
from ..reporting.report import today_report

BASE = """<!doctype html><title>JobPilot</title>
<style>body{font:14px system-ui;margin:2rem auto;max-width:1100px;padding:0 1rem}nav a{margin-right:1rem}
table{border-collapse:collapse;width:100%}td,th{border:1px solid #ddd;padding:4px 8px;vertical-align:top;text-align:left}
th{background:#1f4e78;color:#fff}pre{background:#f4f4f4;padding:1rem}input[type=text]{width:100%}</style>
<nav><a href="/">Dashboard</a><a href="/answers">Answers</a><a href="/data/applications">Applications</a>
<a href="/data/contacts">Contacts</a><a href="/data/hiring_posts">Hiring posts</a><a href="/data/mail_queue">Mail</a></nav><hr>
{{ body|safe }}"""


def create_app(ctx: AppContext) -> Flask:
    app = Flask(__name__)

    def page(body: str, **kw) -> str:
        return render_template_string(BASE, body=render_template_string(body, **kw))

    @app.get("/")
    def index():
        return page("<pre>{{ report }}</pre>", report=today_report(ctx.repo, ctx.settings.apply.daily_target))

    @app.get("/answers")
    def answers():
        rows = ctx.repo.list_questions("pending") + ctx.repo.list_questions("legacy")
        return page("""<h3>Questions needing an answer ({{ rows|length }})</h3>
        <p>Answers you save here are reused for every future application.</p>
        <table><tr><th>Question</th><th>Type / options</th><th>Seen</th><th>Suggestion / your answer</th></tr>
        {% for q in rows %}<tr><td>{{ q.text }}</td><td>{{ q.qtype }}<br><small>{{ q.options_json }}</small></td>
        <td>{{ q.times_seen }}</td><td><form method="post" action="/answers/save">
        <input type="hidden" name="key" value="{{ q.key }}"><input type="text" name="answer" value="{{ q.answer or '' }}">
        <button>Save</button></form>{% if q.status == 'legacy' %}<small>(old bot's answer: verify)</small>{% endif %}</td></tr>
        {% endfor %}</table>""", rows=rows)

    @app.post("/answers/save")
    def save_answer():
        key, answer = request.form["key"], request.form["answer"].strip()
        if answer:
            ctx.repo.set_user_answer(normalize_question(key) if " " in key else key, answer)
        return redirect(url_for("answers"))

    @app.get("/data/<name>")
    def data(name: str):
        datasets = build_datasets(ctx.repo)
        if name not in datasets:
            return page("<p>Unknown dataset.</p>"), 404
        cols, rows = datasets[name]
        return page("""<h3>{{ name }} ({{ rows|length }})</h3><table><tr>{% for c in cols %}<th>{{ c }}</th>{% endfor %}</tr>
        {% for r in rows[:500] %}<tr>{% for v in r %}<td>{{ (v|string)[:200] if v is not none else '' }}</td>{% endfor %}</tr>{% endfor %}
        </table>""", name=name, cols=cols, rows=rows)

    return app
