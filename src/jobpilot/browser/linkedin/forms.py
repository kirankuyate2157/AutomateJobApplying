"""Reading and filling Easy Apply form fields.

Splits the problem in two so each half is simple and testable:
  read_fields(driver) -> list[FormField]      (DOM -> neutral description)
  fill_field(driver, field, value)            (decision -> DOM)
The AnswerEngine in between never sees Selenium.

LinkedIn Easy Apply is an INLINE form on the job detail page, not a modal.
Fields are found page-wide.

Robustness strategy:
  * labels are read with multiple fallback strategies (label[for] tag,
    aria-label, aria-labelledby, placeholder, nearby text) so empty labels
    don't cause "unanswered: ; ;"
  * every element access is individually guarded against StaleElementReference
    so one bad field never poisons the whole step
  * JavaScript fallback: if Selenium can't find form elements, we scan the DOM
    with JS to find inputs, selects, textareas, and their labels
  * unknown/unrecognized inputs are still returned as text fields so they get
    a chance to be answered instead of being silently dropped
"""
from __future__ import annotations

import json
import logging
import re

from selenium.common.exceptions import WebDriverException, StaleElementReferenceException
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import Select

from ...answering.options import is_placeholder
from ...domain.models import FormField
from ..helpers import find_all, find_first, pause, safe_click, text_of
from . import selectors as S

log = logging.getLogger(__name__)


def _safe_text(el) -> str:
    """Read innerText from an element, returning '' on any failure."""
    try:
        return (el.get_attribute("innerText") or el.text or "").strip()
    except (WebDriverException, StaleElementReferenceException):
        return ""


def _label_from_input(root, inp) -> str:
    """Find the label for an input element using multiple strategies."""
    # 1. label[for="input_id"]
    try:
        inp_id = inp.get_attribute("id") or ""
    except WebDriverException:
        inp_id = ""
    if inp_id:
        try:
            label = root.find_element(By.CSS_SELECTOR, f'label[for="{inp_id}"]')
            txt = _safe_text(label)
            if txt:
                return txt
        except WebDriverException:
            pass

    # 2. aria-label on the input itself
    try:
        aria = inp.get_attribute("aria-label") or ""
        if aria:
            return aria
    except WebDriverException:
        pass

    # 3. placeholder on the input
    try:
        ph = inp.get_attribute("placeholder") or ""
        if ph:
            return ph
    except WebDriverException:
        pass

    # 4. nearest parent div text (first 100 chars)
    try:
        parent = inp.find_element(By.XPATH, "./ancestor::div[1]")
        txt = _safe_text(parent)
        if txt:
            # Take just the first meaningful line
            first_line = txt.split("\n")[0][:100]
            if first_line:
                return first_line
    except WebDriverException:
        pass

    # 5. Look for preceding-sibling text or parent container text
    try:
        # Try to find a label element anywhere nearby
        nearby_label = inp.find_element(By.XPATH, "./preceding-sibling::label | ./ancestor::div[1]//label[1]")
        txt = _safe_text(nearby_label)
        if txt:
            return txt
    except WebDriverException:
        pass

    return ""


def read_fields(driver) -> list[FormField]:
    """Describe every question currently visible on the page."""
    fields: list[FormField] = []

    # --- Select elements ---
    try:
        selects = driver.find_elements(By.TAG_NAME, "select")
    except WebDriverException:
        selects = []
    for sel in selects:
        try:
            if not sel.is_displayed():
                continue
        except WebDriverException:
            continue
        try:
            s = Select(sel)
            options = [o.text for o in s.options if o.text.strip()]
            current = s.first_selected_option.text
        except WebDriverException:
            options, current = [], ""
        label = _label_from_input(driver, sel)
        required = _is_required(sel)
        fields.append(FormField(label, "select", options, required, current, handle=sel))
        log.debug("  select field: label=%r options=%s required=%s", label, options[:3], required)

    # --- Textarea elements ---
    try:
        areas = driver.find_elements(By.TAG_NAME, "textarea")
    except WebDriverException:
        areas = []
    for area in areas:
        try:
            if not area.is_displayed():
                continue
        except WebDriverException:
            continue
        try:
            val = area.get_attribute("value") or ""
        except WebDriverException:
            val = ""
        label = _label_from_input(driver, area)
        required = _is_required(area)
        fields.append(FormField(label, "textarea", [], required, val, handle=area))
        log.debug("  textarea field: label=%r required=%s", label, required)

    # --- Input elements ---
    try:
        inputs = driver.find_elements(By.TAG_NAME, "input")
    except WebDriverException:
        inputs = []
    for inp in inputs:
        try:
            if not inp.is_displayed():
                continue
            itype = inp.get_attribute("type") or ""
            if itype == "hidden":
                continue
            if itype == "file":
                continue  # handled by upload_resume
        except WebDriverException:
            continue

        if itype == "radio":
            # Radio buttons are handled via fieldset grouping below
            continue

        try:
            val = inp.get_attribute("value") or ""
        except WebDriverException:
            val = ""

        label = _label_from_input(driver, inp)
        required = _is_required(inp)

        if itype == "checkbox":
            kind = "checkbox"
            current = "Yes" if inp.is_selected() else "No"
        elif itype == "number":
            kind = "number"
            current = val
        else:
            kind = "text"
            current = val

        fields.append(FormField(label, kind, [], required, current, handle=inp))
        log.debug("  %s field: label=%r required=%s current=%r", kind, label, required, current)

    # --- Radio fieldsets ---
    try:
        fieldsets = driver.find_elements(By.TAG_NAME, "fieldset")
    except WebDriverException:
        fieldsets = []
    for fs in fieldsets:
        try:
            if not fs.is_displayed():
                continue
        except WebDriverException:
            continue
        try:
            radios = fs.find_elements(By.XPATH, ".//input[@type='radio']")
        except WebDriverException:
            radios = []
        if not radios:
            continue

        # Fieldset label from legend
        label = ""
        try:
            legend = fs.find_element(By.TAG_NAME, "legend")
            label = _safe_text(legend)
        except WebDriverException:
            pass

        options, handle, current = [], {}, ""
        for inp in radios:
            try:
                inp_id = inp.get_attribute("id") or ""
            except WebDriverException:
                continue
            # Radio option label from multiple strategies:
            opt_label = ""
            # 1. label[for="input_id"]
            if inp_id:
                try:
                    lab = fs.find_element(By.CSS_SELECTOR, f'label[for="{inp_id}"]')
                    opt_label = _safe_text(lab)
                except WebDriverException:
                    pass
            # 2. Parent label that wraps the radio input
            if not opt_label:
                try:
                    parent_label = inp.find_element(By.XPATH, "./ancestor::label[1]")
                    opt_label = _safe_text(parent_label)
                except WebDriverException:
                    pass
            # 3. aria-label on the radio input itself
            if not opt_label:
                try:
                    opt_label = inp.get_attribute("aria-label") or ""
                except WebDriverException:
                    pass
            # 4. Nearest span/sibling text
            if not opt_label:
                try:
                    sibling = inp.find_element(By.XPATH, "./following-sibling::*[1]")
                    opt_label = _safe_text(sibling)
                except WebDriverException:
                    pass
            # 5. Fallback to value attribute
            if not opt_label:
                try:
                    opt_label = inp.get_attribute("value") or ""
                except WebDriverException:
                    opt_label = ""
            # Skip empty/placeholder options
            if not opt_label or opt_label.lower() in ("on", "off", "true", "false"):
                opt_label = inp.get_attribute("value") or f"option_{len(options)}"
            options.append(opt_label)
            handle[opt_label] = inp
            try:
                if inp.is_selected():
                    current = opt_label
            except WebDriverException:
                pass

        if not label:
            label = _label_from_input(driver, radios[0]) if radios else ""
        fields.append(FormField(label, "radio", options, True, current, handle=handle))
        log.debug("  radio field: label=%r options=%s current=%r", label, options, current)

    # JavaScript fallback: if Selenium found nothing, scan the DOM directly
    if not fields:
        log.debug("Selenium found no fields, trying JavaScript fallback")
        js_fields = _read_fields_via_js(driver)
        fields.extend(js_fields)

    return fields


def _read_fields_via_js(driver) -> list[FormField]:
    """Use JavaScript to find form fields when Selenium selectors fail."""
    js = """
    const fields = [];
    const inputs = Array.from(document.querySelectorAll('input, select, textarea'));
    for (const inp of inputs) {
        if (inp.type === 'hidden') continue;
        if (inp.type === 'file') continue;
        if (!inp.offsetParent && inp.offsetWidth === 0 && inp.offsetHeight === 0) continue;

        // Find label
        let label = '';
        if (inp.labels && inp.labels[0]) {
            label = inp.labels[0].textContent?.trim() || '';
        }
        if (!label && inp.id) {
            const lbl = document.querySelector('label[for="' + inp.id + '"]');
            if (lbl) label = lbl.textContent?.trim() || '';
        }
        if (!label) {
            label = inp.getAttribute('aria-label') || inp.placeholder || '';
        }

        let kind = 'text';
        let options = [];
        let required = false;
        let current = '';

        if (inp.tagName === 'SELECT') {
            kind = 'select';
            const opts = Array.from(inp.options).filter(o => o.text.trim());
            options = opts.map(o => o.text);
            required = inp.required;
            const sel = inp.options[inp.selectedIndex];
            current = sel ? sel.text : '';
        } else if (inp.type === 'radio') {
            continue; // handled by fieldset logic
        } else if (inp.type === 'checkbox') {
            kind = 'checkbox';
            required = inp.required;
            current = inp.checked ? 'Yes' : 'No';
        } else if (inp.type === 'number') {
            kind = 'number';
            current = inp.value || '';
        } else {
            kind = 'text';
            current = inp.value || '';
        }

        fields.push({label, kind, options, required, current});
    }

    // Radio fieldsets
    const fieldsets = Array.from(document.querySelectorAll('fieldset'));
    for (const fs of fieldsets) {
        const radios = Array.from(fs.querySelectorAll('input[type="radio"]'));
        if (radios.length === 0) continue;

        let label = '';
        const legend = fs.querySelector('legend');
        if (legend) label = legend.textContent?.trim() || '';

        const options = radios.map(r => {
            const lbl = fs.querySelector('label[for="' + r.id + '"]');
            return lbl ? lbl.textContent?.trim() || r.value : r.value;
        });

        let current = '';
        const checked = radios.find(r => r.checked);
        if (checked) {
            const lbl = fs.querySelector('label[for="' + checked.id + '"]');
            current = lbl ? lbl.textContent?.trim() || checked.value : checked.value;
        }

        fields.push({label, kind: 'radio', options, required: true, current});
    }

    return JSON.stringify(fields);
    """
    try:
        result = driver.execute_script(js)
        if result:
            data = json.loads(result)
            out = []
            for item in data:
                out.append(FormField(
                    label=item.get("label", ""),
                    kind=item.get("kind", "text"),
                    options=item.get("options", []),
                    required=item.get("required", False),
                    current=item.get("current", ""),
                    handle=None,
                ))
            return out
    except (WebDriverException, json.JSONDecodeError, Exception) as exc:
        log.debug("JavaScript field reading failed: %s", exc)
    return []


def _is_required(el) -> bool:
    try:
        return bool(el.get_attribute("required")) or el.get_attribute("aria-required") == "true"
    except WebDriverException:
        return False


def is_prefilled(field: FormField) -> bool:
    """True when LinkedIn already filled something meaningful in."""
    return bool(field.current) and not is_placeholder(field.current) and field.kind != "checkbox"


def _match_select_option(answer_value: str, options: list[str]) -> str | None:
    """Try to match `answer_value` to one of the `options`, with conversions.

    Conversions:
      * "3" + options in months → "36 months"
      * "3 years" + options in years → "3 years"
      * Fuzzy contains match
    """
    if not options:
        return None

    # Direct match
    for opt in options:
        if opt.lower() == answer_value.lower():
            return opt

    # Try number → months conversion
    try:
        num = float(answer_value)
        for opt in options:
            opt_lower = opt.lower()
            if "month" in opt_lower:
                months = int(round(num * 12))
                if str(months) in opt_lower:
                    return opt
            if "year" in opt_lower:
                years = int(round(num))
                if str(years) in opt_lower:
                    return opt
    except ValueError:
        pass

    # Try "X years" → months conversion
    m = re.search(r"(\d+)\s*year", answer_value.lower())
    if m:
        years = int(m.group(1))
        months = years * 12
        for opt in options:
            opt_lower = opt.lower()
            if "month" in opt_lower and str(months) in opt_lower:
                return opt

    # Fuzzy contains match
    answer_lower = answer_value.lower()
    for opt in options:
        opt_lower = opt.lower()
        if answer_lower in opt_lower or opt_lower in answer_lower:
            return opt

    # Try matching just the number part
    m = re.search(r"(\d+)", answer_value)
    if m:
        num_str = m.group(1)
        for opt in options:
            if num_str in opt:
                return opt

    return None


def fill_field(driver, field: FormField, value: str) -> bool:
    """Write `value` into the field. Returns False if the DOM refused."""
    try:
        if field.kind == "select":
            matched = _match_select_option(value, field.options)
            if matched is None:
                log.warning("    select no match for %r in options %s", value, field.options[:5])
                return False
            Select(field.handle).select_by_visible_text(matched)
            log.info("    select matched %r → %r", value, matched)
        elif field.kind == "radio":
            matched = _match_select_option(value, field.options)
            if matched is None:
                log.warning("    radio no match for %r in options %s", value, field.options[:5])
                return False
            return safe_click(driver, field.handle[matched])
        elif field.kind == "checkbox":
            want = value.lower() == "yes"
            if field.handle.is_selected() != want:
                return safe_click(driver, field.handle)
        else:
            _type(driver, field.handle, value)
        return True
    except (WebDriverException, KeyError) as exc:
        log.warning("failed to fill %r with %r: %s", field.label, value, exc)
        return False


def _type(driver, el, value: str) -> None:
    el.clear()
    try:
        if el.get_attribute("value"):
            el.send_keys(Keys.CONTROL, "a", Keys.DELETE)
    except WebDriverException:
        pass
    el.send_keys(value)
    try:
        if el.get_attribute("role") == "combobox":
            pause(1.0, 1.8)
            el.send_keys(Keys.ARROW_DOWN, Keys.ENTER)
    except WebDriverException:
        pass


def upload_resume(driver, path: str) -> bool:
    """Attach a resume if this page shows a file input. Missing input is fine."""
    el = find_first(driver, S.FILE_INPUT, timeout=0)
    if el is None:
        # Try JavaScript to find file input
        try:
            result = driver.execute_script(
                "return Array.from(document.querySelectorAll('input[type=file]')).find(f => f.offsetParent);"
            )
            if result:
                el = result
        except WebDriverException:
            pass
    if el is None:
        return False
    try:
        el.send_keys(path)
        return True
    except WebDriverException:
        log.warning("resume upload failed", exc_info=True)
        return False
