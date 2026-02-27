from functools import wraps
from flask import session, redirect, url_for, request


def login_required(*roles):
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            tenant_slug = kwargs.get('tenant_slug', '')
            if 'school_user_id' not in session or session.get('school_tenant') != tenant_slug:
                return redirect(url_for('school.school_login', tenant_slug=tenant_slug))
            if roles and session.get('school_role') not in roles:
                return 'Unauthorized', 403
            return f(*args, **kwargs)
        return decorated_function
    return decorator
