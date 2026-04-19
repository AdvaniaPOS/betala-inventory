"""
Context processors for betala_sync app.
Gjør organisasjonsinformasjon tilgjengelig i alle templates.
"""


def betala_context(request):
    """Legg til Betala-relatert informasjon i template context."""
    return {
        'betala_organizations': request.session.get('betala_organizations', []),
        'betala_selected_org_id': request.session.get('betala_selected_org_id'),
        'betala_selected_org_name': request.session.get('betala_selected_org_name'),
        'betala_selected_area_id': request.session.get('betala_selected_area_id'),
        'betala_selected_area_name': request.session.get('betala_selected_area_name'),
        'betala_user': request.session.get('betala_user', {}),
    }
