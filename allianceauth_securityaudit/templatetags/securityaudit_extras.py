from django import template
from django.utils.safestring import mark_safe

register = template.Library()


@register.filter
def format_isk(value):
    try:
        amount = float(value)
    except (TypeError, ValueError):
        return value
    if amount == int(amount):
        return f"{amount:,.0f} ISK"
    return f"{amount:,.2f} ISK"


@register.filter
def get(mapping, key):
    """Return mapping[key] for use in templates."""
    if not mapping:
        return None
    return mapping.get(key)


@register.filter
def get_field(form, name):
    """Return a form field by name for use in templates."""
    if not form:
        return None
    try:
        return form[name]
    except (KeyError, TypeError):
        return None


@register.filter
def entity_image_url(entity_type, entity_id):
    if not entity_id:
        return ""
    if entity_type == "character":
        return f"https://images.evetech.net/characters/{entity_id}/portrait?size=64"
    if entity_type == "corporation":
        return f"https://images.evetech.net/corporations/{entity_id}/logo?size=64"
    if entity_type == "alliance":
        return f"https://images.evetech.net/alliances/{entity_id}/logo?size=64"
    return ""


@register.simple_tag(takes_context=True)
def url_replace(context, key, value):
    """Return the current request URL with a query parameter updated.

    Preserves all existing query parameters (including filters and pagination)
    while replacing or adding the specified key. Toggling sort direction is
    handled by the caller passing the desired value.
    """
    request = context.get("request")
    if not request:
        return ""
    query = request.GET.copy()
    # Toggle sort direction if clicking the same column
    if key == "sort" and query.get("sort") == value:
        value = "-" + value
    query[key] = value
    # Remove page so the user doesn't land on an empty page after re-sorting
    query.pop("page", None)
    return f"?{query.urlencode()}"
