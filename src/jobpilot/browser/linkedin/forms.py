"""Reading and filling Easy Apply form fields.

Splits the problem in two so each half is simple and testable:
  read_fields(modal) -> list[FormField]      (DOM -> neutral description)
  fill_field(driver, field, value)           (decision -> DOM)
The AnswerEngine in between never sees Selenium.
"""
from __future__ import annotations

import logging

from selenium.common.exceptions import WebDriverException
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import Select

from ...answering.options import is_placeholder
from ...domain.models import FormField
from ..helpers import find_all, find_first, pause, safe_click, text_of
from . import selectors as S

log = logging.getLogger(__name__)


def _label(box) -> str:
    el = find_first(box, [S.XP(".//label"), *S.RADIO_TITLE])
    return text_of(el) if el is not None else ""


def _is_required(el, label: str) -> bool:
    try:
        return bool(el.get_attribute("required")) or el.get_attribute("aria-required") == "true"
    except WebDriverException:
        return False


def read_fields(modal) -> list[FormField]:
    """Describe every question currently visible in the modal."""
    fields: list[FormField] = []
    for box in find_all(modal, S.FORM_ELEMENTS):
        try:
            field = _read_one(box)
        except WebDriverException:
            log.debug("skipping unreadable form element", exc_info=True)
            continue
        if field is not None:
            fields.append(field)
    return fields


def _read_one(box) -> FormField | None:
    label = _label(box)

    if (sel := find_first(box, S.SELECT)) is not None:
        s = Select(sel)
        return FormField(label, "select", [o.text for o in s.options], _is_required(sel, label),
                         s.first_selected_option.text, handle=sel)

    fieldset = box.find_elements(*S.RADIO_FIELDSET)
    if fieldset:
        options, handle, current = [], {}, ""
        for inp in fieldset[0].find_elements("tag name", "input"):
            lab = find_first(fieldset[0], [S.XP(f'.//label[@for="{inp.get_attribute("id")}"]')])
            name = text_of(lab) if lab is not None else (inp.get_attribute("value") or "")
            options.append(name)
            handle[name] = lab if lab is not None else inp
            if inp.is_selected():
                current = name
        return FormField(label, "radio", options, True, current, handle=handle)

    if (area := find_first(box, S.TEXTAREA)) is not None:
        return FormField(label, "textarea", [], _is_required(area, label), area.get_attribute("value") or "", handle=area)

    if (inp := find_first(box, S.TEXT_INPUT)) is not None:
        kind = "number" if (inp.get_attribute("type") == "number") else "text"
        return FormField(label, kind, [], _is_required(inp, label), inp.get_attribute("value") or "", handle=inp)

    if (cb := find_first(box, S.CHECKBOX)) is not None:
        lab = find_first(box, [S.XP(".//label[@for]")])
        return FormField(text_of(lab) if lab is not None else label, "checkbox", [], _is_required(cb, label),
                         "Yes" if cb.is_selected() else "No", handle=cb)
    return None


def is_prefilled(field: FormField) -> bool:
    """True when LinkedIn already filled something meaningful in."""
    return bool(field.current) and not is_placeholder(field.current) and field.kind != "checkbox"


def fill_field(driver, field: FormField, value: str) -> bool:
    """Write `value` into the field. Returns False if the DOM refused."""
    try:
        if field.kind == "select":
            Select(field.handle).select_by_visible_text(value)
        elif field.kind == "radio":
            return safe_click(driver, field.handle[value])
        elif field.kind == "checkbox":
            want = value.lower() == "yes"
            if field.handle.is_selected() != want:
                return safe_click(driver, field.handle)
        else:
            _type(driver, field.handle, value)
        return True
    except (WebDriverException, KeyError):
        log.warning("failed to fill %r with %r", field.label, value, exc_info=True)
        return False


def _type(driver, el, value: str) -> None:
    el.clear()
    if el.get_attribute("value"):                       # React inputs ignore clear(): select-all + delete
        el.send_keys(Keys.CONTROL, "a", Keys.DELETE)
    el.send_keys(value)
    if el.get_attribute("role") == "combobox":          # typeahead (city/location): choose first suggestion
        pause(1.0, 1.8)
        el.send_keys(Keys.ARROW_DOWN, Keys.ENTER)


def upload_resume(modal, path: str) -> bool:
    """Attach a resume if this step shows a file input. Missing input is fine."""
    el = find_first(modal, S.FILE_INPUT)
    if el is None:
        return False
    try:
        el.send_keys(path)
        return True
    except WebDriverException:
        log.warning("resume upload failed", exc_info=True)
        return False
