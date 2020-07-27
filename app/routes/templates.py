"""
Template engine enhancements
"""
import re

from markupsafe import Markup

from app.web import app, BASEURI, db


@app.template_filter(name="highlight")
def highlight(value, query):
    if query is not None and query.strip() != "":
        query = r"(" + re.escape(query.strip()) + ")"
        value = Markup.escape(value)
        value = re.sub(query, lambda g: '<span class="ds_highlight">%s</span>' % g.group(1),
                       value, flags=re.IGNORECASE)

    return Markup(value)
