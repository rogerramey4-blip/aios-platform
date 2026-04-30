"""
AIOS Onboarding Blueprint — /onboard
Multi-step account creation wizard for new business tenants.
Accessible to super-admins (from admin panel) or via public invite link.
"""
import secrets
import logging
from datetime import datetime
from flask import (Blueprint, render_template, request, redirect,
                   url_for, session, flash, jsonify)
from models import Tenant, TenantUser, db
from security import validate_email, validate_name, audit

log = logging.getLogger(__name__)
onboard_bp = Blueprint('onboard', __name__)

INDUSTRY_LABELS = {
    'agency':       ('🏢', 'AI Automation Agency'),
    'legal':        ('⚖️', 'Legal / Law Firm'),
    'construction': ('🏗️', 'Construction'),
    'medical':      ('🏥', 'Medical / Dental Practice'),
    'brokerage':    ('🏠', 'Real Estate Brokerage'),
}

PLAN_LABELS = {
    'trial':      ('Trial',      '$0',       '14-day full access, no credit card'),
    'starter':    ('Starter',    '$497/mo',  'Up to 3 users · 5 AI agents · 10GB storage'),
    'growth':     ('Growth',     '$997/mo',  'Up to 10 users · 15 AI agents · 50GB storage'),
    'enterprise': ('Enterprise', 'Custom',   'Unlimited users · all agents · custom domain + SLA'),
}


@onboard_bp.route('/onboard', methods=['GET'])
def onboard_page():
    from auth import require_auth
    # Only super-admins can initiate onboarding (can be opened to public with invite token later)
    if not session.get('aios_auth'):
        return redirect(url_for('login'))
    return render_template('onboard.html',
                           industries=INDUSTRY_LABELS,
                           plans=PLAN_LABELS)


@onboard_bp.route('/onboard/create', methods=['POST'])
def onboard_create():
    if not session.get('aios_auth'):
        return jsonify({'ok': False, 'error': 'Unauthorized'}), 403

    firm_name     = request.form.get('firm_name', '').strip()
    firm_sub      = request.form.get('firm_sub', '').strip()
    industry      = request.form.get('industry', '').strip().lower()
    plan          = request.form.get('plan', 'trial').strip().lower()
    contact_name  = request.form.get('contact_name', '').strip()
    contact_email = request.form.get('contact_email', '').strip().lower()
    contact_phone = request.form.get('contact_phone', '').strip()
    admin_email   = request.form.get('admin_email', '').strip().lower()
    admin_name    = request.form.get('admin_name', '').strip()
    notes         = request.form.get('notes', '').strip()

    # Validation
    errors = []
    if not validate_name(firm_name):
        errors.append('Firm name is required.')
    if industry not in INDUSTRY_LABELS:
        errors.append('Invalid industry selection.')
    if plan not in PLAN_LABELS:
        errors.append('Invalid plan selection.')
    if not validate_email(admin_email):
        errors.append('A valid admin email is required.')
    if contact_email and not validate_email(contact_email):
        errors.append('Contact email format is invalid.')

    if errors:
        return jsonify({'ok': False, 'errors': errors}), 400

    # Check for duplicate admin email
    existing = TenantUser.query.filter_by(email=admin_email).first()
    if existing:
        return jsonify({'ok': False, 'errors': [f'{admin_email} already has an account.']}), 400

    try:
        # Create tenant
        tenant = Tenant(
            industry      = industry,
            firm_name     = firm_name,
            firm_sub      = firm_sub,
            contact_name  = contact_name,
            contact_email = contact_email,
            contact_phone = contact_phone,
            plan          = plan,
            status        = 'active',
            notes         = notes,
        )
        db.add(tenant)
        db.flush()  # get tenant.id before commit

        # Create admin user
        user = TenantUser(
            tenant_id = tenant.id,
            email     = admin_email,
            name      = admin_name or contact_name,
            role      = 'admin',
            active    = True,
        )
        db.add(user)
        db.commit()

        audit('tenant_created', f'tenant:{tenant.id}', 'success',
              f'firm={firm_name} industry={industry} admin={admin_email}')

        log.info('[AIOS Onboard] Created tenant %s (%s) for %s', tenant.id, industry, firm_name)
        return jsonify({
            'ok':       True,
            'tenant_id': tenant.id,
            'redirect':  url_for('admin.tenant_detail', tenant_id=tenant.id),
        })

    except Exception as exc:
        db.rollback()
        log.error('[AIOS Onboard] DB error: %s', exc)
        return jsonify({'ok': False, 'errors': ['Server error — please try again.']}), 500
