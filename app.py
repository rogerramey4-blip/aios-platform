import os, secrets
import time as _time
from datetime import datetime
from flask import Flask, render_template, request, session, redirect, url_for, jsonify

try:
    from dotenv import load_dotenv; load_dotenv()
except ImportError:
    pass

from auth import (request_otp, verify_otp, check_authorized,
                  require_auth, require_admin, mask_email, ALLOWED_EMAILS)
from models import init_db, Tenant, TenantUser, Document, Domain, TenantIntegration, db
from security import init_security, audit
from onboarding import onboard_bp
from admin_bp import admin_bp
from sync_bp import sync_bp
from totp_bp import totp_bp, totp_enabled, verify_totp_code
import werkzeug.utils as wz

app = Flask(__name__)
app.secret_key = os.getenv('SECRET_KEY') or secrets.token_hex(32)
app.config['MAX_CONTENT_LENGTH'] = 25 * 1024 * 1024  # 25 MB upload limit

# ── Initialise DB + security middleware ───────────────────────────────────────
with app.app_context():
    try:
        init_db()
    except Exception as _e:
        import logging; logging.getLogger(__name__).warning('DB init: %s', _e)

init_security(app)
app.register_blueprint(onboard_bp)
app.register_blueprint(admin_bp)
app.register_blueprint(sync_bp)
app.register_blueprint(totp_bp)

# ── Custom-domain tenant routing ──────────────────────────────────────────────
@app.before_request
def _resolve_tenant_domain():
    """Map incoming custom domains to the correct tenant context."""
    host = request.host.split(':')[0].lower()
    if host in ('localhost', '127.0.0.1') or host.endswith('.railway.app'):
        return  # internal / hosting domain — no tenant mapping needed
    dom = Domain.query.filter_by(domain=host, verified=True).first()
    if dom:
        session['_domain_tenant'] = dom.tenant_id

# ── Helpers ───────────────────────────────────────────────────────────────────
def _greeting():
    h = datetime.now().hour
    return 'Good Morning' if h < 12 else ('Good Afternoon' if h < 17 else 'Good Evening')

def _date_str():
    n = datetime.now()
    return f"{n.strftime('%A, %B')} {n.day}, {n.year}"

def _ctx(data):
    return {**data, 'greeting': _greeting(), 'now': _date_str()}

# ── Nav Builders ──────────────────────────────────────────────────────────────
def _nav(industry, active_key, pipeline_label, tools):
    def _item(icon, label, href, key, badge=None):
        return {'icon': icon, 'label': label, 'href': href,
                'active': key == active_key, 'badge': badge}
    tool_links = [_item(t['icon'], t['title'], f'/{industry}/tool/{t["key"]}',
                        f'tool_{t["key"].replace("-","_")}') for t in tools]
    return [
        {'section': 'COMMAND CENTER', 'links': [
            _item('◎', 'Dashboard',          f'/{industry}',               'dashboard'),
            _item('≡', 'Daily Brief',         f'/{industry}/brief',         'brief'),
            _item('⬡', pipeline_label,        f'/{industry}/pipeline',      'pipeline'),
            _item('✉', 'Email Intelligence',  f'/{industry}/email',         'email'),
            _item('◈', 'Goals & Strategy',   f'/{industry}/goals',         'goals'),
        ]},
        {'section': 'AI TOOLS', 'links': tool_links},
        {'section': 'AI AGENTS', 'links': [
            _item('⬡', 'Agent Overview',   f'/{industry}/agents',     'agents', badge=5),
            _item('⚡', 'Use Cases',        f'/{industry}/use-cases',  'use_cases'),
            _item('+', 'Deploy New Agent',  f'/{industry}/deploy',     'deploy'),
            _item('≡', 'Agent Logs',       f'/{industry}/logs',       'logs'),
        ]},
        {'section': 'SETTINGS', 'links': [
            _item('▤', 'Data Import',    f'/{industry}/import',    'import'),
            _item('◷', 'Integrations',   f'/{industry}/integrations','integrations'),
            _item('◈', 'Team & Roles',   f'/{industry}/team',      'team'),
            _item('◫', 'Documents',      f'/{industry}/documents', 'documents'),
            _item('◉', 'Domain & SSL',   f'/{industry}/domain',    'domain'),
            _item('📖', 'User Guide',    f'/{industry}/guide',     'guide'),
            _item('🔑', 'Authenticator (2FA)', '/totp/setup',      'totp_setup'),
        ]},
    ]

# ── Industry Configs ──────────────────────────────────────────────────────────
INDUSTRIES = {
    'agency': {
        'firm_name': 'APEX AI SOLUTIONS', 'firm_sub': 'LLC',
        'user_name': 'Alex Rivera', 'user_title': 'CEO', 'greeting_name': 'Alex',
        'pipeline_label': 'Client Projects',
        'tools': [
            {'key': 'proposal', 'title': 'Proposal Writer',  'icon': '▤'},
            {'key': 'roi',      'title': 'ROI Calculator',   'icon': '◷'},
            {'key': 'sow',      'title': 'SOW Generator',    'icon': '◈'},
            {'key': 'report',   'title': 'Report Builder',   'icon': '⚡'},
        ],
        'kpis': [
            {'label': 'ACTIVE CLIENT PROJECTS',  'value': '24',      'sub': '6 onboarding · 14 running · 4 at risk'},
            {'label': 'MONTHLY RECURRING REVENUE','value': '$47,200', 'sub': '+$3,100 from last month', 'highlight': True},
            {'label': 'AGENTS DEPLOYED & LIVE',  'value': '142',     'sub': '12 erroring · 4 paused'},
            {'label': 'DELIVERABLES THIS WEEK',  'value': '9',       'sub': '3 overdue · 2 awaiting approval'},
        ],
        'actions': [
            {'text': 'Client "Apex Dental" automation agent down 4hrs — intervention needed',   'badge': 'URGENT',    'btype': 'urgent',   'dot': 'red'},
            {'text': 'Proposal for "Riviera Realty" due by 3PM — AI draft ready for review',   'badge': 'DUE TODAY', 'btype': 'due',      'dot': 'amber'},
            {'text': 'Monthly ROI report for "Metro HVAC" — compiled and ready to send',       'badge': '2:00 PM',   'btype': 'time',     'dot': 'blue'},
            {'text': 'Churn signal: "TechStart Inc" — no login in 18 days, outreach needed',  'badge': 'AT RISK',   'btype': 'risk',     'dot': 'red'},
            {'text': '"LakeView Law" at 80% plan capacity — upsell proposal queued',           'badge': 'TOMORROW',  'btype': 'tomorrow', 'dot': 'gray'},
        ],
        'alerts': [
            {'cat': 'AI TOOLS',   'ctype': 'ai',         'headline': 'Anthropic Releases Claude 4 Opus — 3× Better at Multi-Step Agentic Tasks',  'source': 'Anthropic Blog', 'rel': '2h ago'},
            {'cat': 'INDUSTRY',   'ctype': 'industry',   'headline': 'OpenAI Announces GPT-5 With Native Tool Use and Long-Context Reasoning',     'source': 'The Verge',      'rel': '4h ago'},
            {'cat': 'AUTOMATION', 'ctype': 'automation', 'headline': 'Make.com Adds Native AI Agent Builder — Implications for No-Code Workflows', 'source': 'Auto Insider',   'rel': '6h ago'},
            {'cat': 'BUSINESS',   'ctype': 'business',   'headline': '67% of SMBs Plan to Increase AI Automation Spend 40% in 2026',             'source': 'Forbes',         'rel': '8h ago'},
        ],
        'goals': [
            {'name': 'Revenue Goal',     'pct': 78, 'color': 'amber'},
            {'name': 'Client Retention', 'pct': 94, 'color': 'green'},
            {'name': 'Agent Uptime',     'pct': 99, 'color': 'blue'},
            {'name': 'Win Rate',         'pct': 61, 'color': 'purple'},
        ],
        'pipeline_label_kpi': 'PIPELINE BY SERVICE TIER',
        'pipeline': [
            {'name': 'Starter Plan',    'pct': 35, 'value': '$8,400/mo'},
            {'name': 'Growth Plan',     'pct': 58, 'value': '$22,800/mo'},
            {'name': 'Enterprise',      'pct': 75, 'value': '$16,000/mo'},
            {'name': 'Custom Projects', 'pct': 22, 'value': 'Pending'},
        ],
        'agents': [
            {'name': 'Client Health Monitor', 'status': 'active', 'detail': 'Scanning 24 clients · Updated 3 min ago'},
            {'name': 'Proposal Generator',    'status': 'active', 'detail': 'Draft ready for Riviera Realty'},
            {'name': 'Churn Predictor',       'status': 'active', 'detail': 'Alert issued: TechStart Inc'},
            {'name': 'ROI Reporter',          'status': 'active', 'detail': 'Metro HVAC report compiled'},
            {'name': 'Lead Intelligence',     'status': 'idle',   'detail': 'Next scan in 2h'},
            {'name': 'Email Drafter',         'status': 'active', 'detail': '3 outreach drafts queued'},
        ],
        'extra_panes': 'agency',
        'client_health': [
            {'name': 'Apex Dental',    'engagement': 'red',   'uptime': 'red',   'delivery': 'green', 'payment': 'green', 'score': 58},
            {'name': 'Riviera Realty', 'engagement': 'green', 'uptime': 'green', 'delivery': 'amber', 'payment': 'green', 'score': 85},
            {'name': 'Metro HVAC',     'engagement': 'green', 'uptime': 'green', 'delivery': 'green', 'payment': 'green', 'score': 97},
            {'name': 'TechStart Inc',  'engagement': 'red',   'uptime': 'amber', 'delivery': 'amber', 'payment': 'green', 'score': 41},
            {'name': 'LakeView Law',   'engagement': 'green', 'uptime': 'green', 'delivery': 'green', 'payment': 'amber', 'score': 88},
            {'name': 'Summit Clinic',  'engagement': 'amber', 'uptime': 'green', 'delivery': 'green', 'payment': 'green', 'score': 79},
        ],
    },
    'legal': {
        'firm_name': 'MERIDIAN LAW GROUP', 'firm_sub': 'PLLC',
        'user_name': 'Jordan Hayes', 'user_title': 'Managing Partner', 'greeting_name': 'Jordan',
        'pipeline_label': 'Active Cases',
        'tools': [
            {'key': 'motion',   'title': 'Motion Drafter',    'icon': '▤'},
            {'key': 'research', 'title': 'Legal Research',    'icon': '◷'},
            {'key': 'contract', 'title': 'Contract Analyzer', 'icon': '◈'},
            {'key': 'demand',   'title': 'Demand Letter',     'icon': '⚡'},
        ],
        'kpis': [
            {'label': 'ACTIVE CASES',           'value': '18',   'sub': '6 securities · 7 PI · 5 transactional'},
            {'label': 'PENDING RECOVERY VALUE', 'value': '$4.2M','sub': '3 cases at trial stage', 'highlight': True},
            {'label': 'EMAILS TO REVIEW',       'value': '12',   'sub': '5 urgent · 4 drafts ready'},
            {'label': 'DEADLINES THIS WEEK',    'value': '7',    'sub': '2 filing deadlines · 5 responses'},
        ],
        'actions': [
            {'text': 'SOL expires in 4 days on Martinez v. Citywide Transport — file today',       'badge': 'URGENT',    'btype': 'urgent',   'dot': 'red'},
            {'text': 'Opposition brief due 5PM — AI draft complete, needs review',                 'badge': 'DUE TODAY', 'btype': 'due',      'dot': 'amber'},
            {'text': 'New client consult — Patterson (employment) — 2PM today',                   'badge': '2:00 PM',   'btype': 'time',     'dot': 'blue'},
            {'text': 'Billing: $18,400 outstanding across 6 matters — 90+ day aging',             'badge': 'OVERDUE',   'btype': 'risk',     'dot': 'red'},
            {'text': 'Depositions for Chen v. Harlow scheduled — prep materials ready',           'badge': 'TOMORROW',  'btype': 'tomorrow', 'dot': 'gray'},
        ],
        'alerts': [
            {'cat': 'COURTS',     'ctype': 'courts',     'headline': 'New E-Filing Rules Take Effect June 1 — 3rd Circuit Updates Standing Orders', 'source': 'PACER',         'rel': '1h ago'},
            {'cat': 'LEGISLATION','ctype': 'legislation','headline': 'NLRB Issues Guidance on AI-Generated Work Product in Legal Proceedings',       'source': 'Law360',        'rel': '3h ago'},
            {'cat': 'PRECEDENT',  'ctype': 'precedent',  'headline': 'SCOTUS Grants Cert in Securities Fraud Case — Implications for 10b-5 Claims', 'source': 'SCOTUSblog',    'rel': '5h ago'},
            {'cat': 'BILLING',    'ctype': 'billing',    'headline': 'ABA Survey: Firms Using AI Billing Tools See 23% Faster Realization Rates',    'source': 'ABA Journal',   'rel': '7h ago'},
        ],
        'goals': [
            {'name': 'Billable Hours Target', 'pct': 82, 'color': 'amber'},
            {'name': 'Case Resolution Rate',  'pct': 71, 'color': 'green'},
            {'name': 'Client Satisfaction',   'pct': 94, 'color': 'blue'},
            {'name': 'Collection Rate',       'pct': 87, 'color': 'purple'},
        ],
        'pipeline_label_kpi': 'MATTERS BY PRACTICE AREA',
        'pipeline': [
            {'name': 'Securities',      'pct': 45, 'value': '6 active'},
            {'name': 'Personal Injury', 'pct': 58, 'value': '7 active'},
            {'name': 'Transactional',   'pct': 35, 'value': '5 active'},
            {'name': 'Employment',      'pct': 20, 'value': '2 incoming'},
        ],
        'agents': [
            {'name': 'Deadline Sentinel',  'status': 'active', 'detail': '7 deadlines monitored · 2 critical'},
            {'name': 'Legal Research Agent','status': 'active', 'detail': 'Precedent search: Martinez v. Citywide'},
            {'name': 'Motion Drafter',     'status': 'active', 'detail': 'Opposition brief draft ready'},
            {'name': 'Billing Agent',      'status': 'active', 'detail': '6 invoices generated this week'},
            {'name': 'PACER Monitor',      'status': 'active', 'detail': '3 dockets updated overnight'},
            {'name': 'Email Intelligence', 'status': 'idle',   'detail': 'Next triage in 15 min'},
        ],
        'extra_panes': 'legal',
        'sol_watchlist': [
            {'case': 'Martinez v. Citywide Transport', 'type': 'PI',          'sol_date': 'May 4, 2026',  'days_left': 4,  'urgency': 'red'},
            {'case': 'Chen v. Harlow Manufacturing',   'type': 'Employment',  'sol_date': 'May 18, 2026', 'days_left': 18, 'urgency': 'amber'},
            {'case': 'Patterson Estate Matter',        'type': 'Estate',      'sol_date': 'Jun 2, 2026',  'days_left': 33, 'urgency': 'green'},
            {'case': 'Rivera Securities Claim',        'type': 'Securities',  'sol_date': 'Jul 11, 2026', 'days_left': 72, 'urgency': 'green'},
        ],
    },
    'construction': {
        'firm_name': 'IRONCLAD CONSTRUCTION', 'firm_sub': 'LLC',
        'user_name': 'Mike Torres', 'user_title': 'Project Director', 'greeting_name': 'Mike',
        'pipeline_label': 'Active Projects',
        'tools': [
            {'key': 'estimate',     'title': 'Estimate Builder',   'icon': '▤'},
            {'key': 'rfi',          'title': 'RFI Drafter',        'icon': '◷'},
            {'key': 'change-order', 'title': 'Change Order Gen.',  'icon': '◈'},
            {'key': 'permit',       'title': 'Permit Tracker',     'icon': '⚡'},
        ],
        'kpis': [
            {'label': 'ACTIVE PROJECTS',          'value': '11',   'sub': '4 commercial · 5 residential · 2 civil'},
            {'label': 'BUDGET UNDER MANAGEMENT',  'value': '$8.3M','sub': '2 projects >5% variance', 'highlight': True},
            {'label': 'OPEN RFIs & SUBMITTALS',   'value': '34',   'sub': '8 overdue · 12 awaiting approval'},
            {'label': 'SAFETY INCIDENTS (30-DAY)','value': '0',    'sub': '847 incident-free days · 1 near-miss'},
        ],
        'actions': [
            {'text': 'Permit for "Lakeshore Condos" expires in 12 days — renewal not submitted',   'badge': 'URGENT',    'btype': 'urgent',   'dot': 'red'},
            {'text': 'Harmon Carpentry (Block C) is 6 days behind schedule',                       'badge': 'BEHIND',    'btype': 'due',      'dot': 'amber'},
            {'text': 'Budget variance 7.3% on Commerce Park Phase 2 — review change orders',      'badge': 'REVIEW',    'btype': 'time',     'dot': 'blue'},
            {'text': 'RFI #118 unanswered 4 days — architect unresponsive',                       'badge': 'FOLLOW UP', 'btype': 'risk',     'dot': 'red'},
            {'text': '3-day rain event starts Monday — update schedule for 4 affected projects',  'badge': 'TOMORROW',  'btype': 'tomorrow', 'dot': 'gray'},
        ],
        'alerts': [
            {'cat': 'MATERIALS',  'ctype': 'materials',  'headline': 'Lumber Futures Up 12% — PNW Mill Disruption Affecting Framing Lead Times',     'source': 'ENR',         'rel': '2h ago'},
            {'cat': 'OSHA',       'ctype': 'osha',       'headline': 'OSHA Updates Fall Protection Standards — New Training Requirements July 2026', 'source': 'OSHA.gov',    'rel': '4h ago'},
            {'cat': 'PERMITS',    'ctype': 'permits',    'headline': 'City of Dallas Reduces Permit Processing Time to 5 Days with New Portal',     'source': 'Dallas Biz',  'rel': '6h ago'},
            {'cat': 'LABOR',      'ctype': 'labor',      'headline': 'Skilled Labor Shortage Intensifies — Electrician Wages Up 8% YTD',            'source': 'AGC Report',  'rel': '1d ago'},
        ],
        'goals': [
            {'name': 'On-Time Delivery',    'pct': 73, 'color': 'amber'},
            {'name': 'Budget Adherence',    'pct': 88, 'color': 'green'},
            {'name': 'Safety Record',       'pct': 100,'color': 'blue'},
            {'name': 'Client Satisfaction', 'pct': 91, 'color': 'purple'},
        ],
        'pipeline_label_kpi': 'PROJECTS BY TYPE',
        'pipeline': [
            {'name': 'Commercial', 'pct': 55, 'value': '$4.8M'},
            {'name': 'Residential','pct': 35, 'value': '$2.1M'},
            {'name': 'Civil',      'pct': 20, 'value': '$1.4M'},
            {'name': 'Pending Bid','pct': 10, 'value': '$3.2M est.'},
        ],
        'agents': [
            {'name': 'Permit Watcher',        'status': 'active', 'detail': '3 permits expiring within 30 days'},
            {'name': 'Budget Watchdog',        'status': 'active', 'detail': 'Variance alert: Commerce Park P2'},
            {'name': 'Weather Impact Agent',   'status': 'active', 'detail': 'Rain event: 4 projects affected'},
            {'name': 'RFI Response Agent',     'status': 'active', 'detail': '12 RFI drafts ready for review'},
            {'name': 'Safety Monitor',         'status': 'idle',   'detail': 'Daily log review at 5PM'},
            {'name': 'Subcontractor Comms',    'status': 'active', 'detail': 'Schedule confirmations sent: 14'},
        ],
        'extra_panes': 'construction',
        'project_health': [
            {'name': 'Lakeshore Condos',    'pct': 62, 'budget_var': '+2.1%', 'schedule_var': 'On track',     'risk': 'amber', 'pm': 'Torres'},
            {'name': 'Commerce Park P2',    'pct': 44, 'budget_var': '+7.3%', 'schedule_var': '-3 days',      'risk': 'red',   'pm': 'Johnson'},
            {'name': 'Riverside Homes',     'pct': 88, 'budget_var': '+0.4%', 'schedule_var': 'On track',     'risk': 'green', 'pm': 'Torres'},
            {'name': 'Civic Center Reno',   'pct': 31, 'budget_var': '+1.8%', 'schedule_var': '+2 days ahead','risk': 'green', 'pm': 'Davis'},
            {'name': 'Harbor View Apts',    'pct': 15, 'budget_var': '+3.2%', 'schedule_var': '-6 days',      'risk': 'amber', 'pm': 'Johnson'},
        ],
    },
    'medical': {
        'firm_name': 'SUMMIT MEDICAL GROUP', 'firm_sub': 'PLLC',
        'user_name': 'Dr. Sarah Chen', 'user_title': 'Medical Director', 'greeting_name': 'Dr. Chen',
        'pipeline_label': 'Patient Pipeline',
        'tools': [
            {'key': 'soap',        'title': 'SOAP Notes Drafter',   'icon': '▤'},
            {'key': 'prior-auth',  'title': 'Prior Auth Assistant', 'icon': '◷'},
            {'key': 'denial',      'title': 'Denial Appeal Writer', 'icon': '◈'},
            {'key': 'communicate', 'title': 'Patient Communicator', 'icon': '⚡'},
        ],
        'kpis': [
            {'label': 'PATIENTS SCHEDULED TODAY', 'value': '38',    'sub': '4 openings · 3 overbooked risk'},
            {'label': 'NET COLLECTIONS RATE',      'value': '97.2%', 'sub': 'Target: 98% · 6 claims pending', 'highlight': True},
            {'label': 'PENDING PRIOR AUTHS',       'value': '14',    'sub': '4 expiring before scheduled visit'},
            {'label': 'NO-SHOW RATE (30-DAY)',     'value': '8.3%',  'sub': 'Up 1.2% from last month'},
        ],
        'actions': [
            {'text': 'Prior auth for James H. expires tomorrow — rescheduled for Friday',         'badge': 'URGENT',       'btype': 'urgent',   'dot': 'red'},
            {'text': 'Aetna claim #88412 denied: missing modifier 25 — appeal letter drafted',    'badge': 'APPEAL READY', 'btype': 'due',      'dot': 'amber'},
            {'text': 'Appointment gap 2:00–3:30 PM today — 3 recall patients available',         'badge': '2:00 PM',      'btype': 'time',     'dot': 'blue'},
            {'text': '4 lab results in portal — no provider acknowledgment in 6+ hours',         'badge': 'REVIEW',       'btype': 'risk',     'dot': 'amber'},
            {'text': '47 patients overdue for 6-month recall — automated campaign ready',        'badge': 'TOMORROW',     'btype': 'tomorrow', 'dot': 'gray'},
        ],
        'alerts': [
            {'cat': 'BILLING',     'ctype': 'billing',    'headline': 'Aetna Updates Prior Auth Requirements for Cardiology — Effective June 1',  'source': 'Aetna Portal', 'rel': '1h ago'},
            {'cat': 'COMPLIANCE',  'ctype': 'compliance', 'headline': 'CMS Issues New Guidance on Telehealth Billing Codes Through Dec 2026',     'source': 'CMS.gov',      'rel': '3h ago'},
            {'cat': 'CLINICAL',    'ctype': 'clinical',   'headline': 'FDA Clears New Point-of-Care Diagnostic for Rapid Sepsis Detection',       'source': 'Medscape',     'rel': '5h ago'},
            {'cat': 'REGULATORY',  'ctype': 'regulatory', 'headline': 'HIPAA Security Rule Requires Encryption at Rest for All PHI by Q3 2026',  'source': 'HHS.gov',      'rel': '7h ago'},
        ],
        'goals': [
            {'name': 'Collections Target',  'pct': 97, 'color': 'green'},
            {'name': 'New Patient Goal',     'pct': 63, 'color': 'amber'},
            {'name': 'Patient Satisfaction', 'pct': 88, 'color': 'blue'},
            {'name': 'Auth Approval Rate',   'pct': 72, 'color': 'purple'},
        ],
        'pipeline_label_kpi': 'REVENUE BY PAYER MIX',
        'pipeline': [
            {'name': 'Medicare',   'pct': 45, 'value': '$38,200'},
            {'name': 'Blue Cross', 'pct': 65, 'value': '$24,100'},
            {'name': 'Aetna',      'pct': 30, 'value': '$18,700'},
            {'name': 'Self-Pay',   'pct': 15, 'value': '$6,400'},
        ],
        'agents': [
            {'name': 'Prior Auth Bot',     'status': 'active', 'detail': 'Processing 4 urgent auths · Updated 5 min ago'},
            {'name': 'Claim Scrubber',     'status': 'active', 'detail': '3 claims flagged before submission'},
            {'name': 'Recall Scheduler',   'status': 'active', 'detail': '47 patients queued · campaign ready'},
            {'name': 'Denial Analyzer',    'status': 'active', 'detail': 'Appeal drafted for Aetna #88412'},
            {'name': 'Insurance Verifier', 'status': 'active', 'detail': "Tomorrow's schedule verified"},
            {'name': 'SOAP Notes Agent',   'status': 'idle',   'detail': 'Awaiting provider voice input'},
        ],
        'extra_panes': 'medical',
        'schedule_heatmap': [
            {'time': '8:00 AM',  'slots': ['booked','booked','booked','open']},
            {'time': '9:00 AM',  'slots': ['booked','booked','booked','booked']},
            {'time': '10:00 AM', 'slots': ['booked','booked','open',  'booked']},
            {'time': '11:00 AM', 'slots': ['booked','booked','booked','booked']},
            {'time': '12:00 PM', 'slots': ['lunch', 'lunch', 'lunch', 'lunch']},
            {'time': '1:00 PM',  'slots': ['booked','open',  'booked','booked']},
            {'time': '2:00 PM',  'slots': ['open',  'open',  'open',  'booked']},
            {'time': '3:00 PM',  'slots': ['booked','booked','open',  'booked']},
            {'time': '4:00 PM',  'slots': ['booked','booked','booked','booked']},
        ],
        'ar_aging': [
            {'bucket': '0–30 days',  'amount': '$24,800', 'pct': 48, 'color': 'green'},
            {'bucket': '31–60 days', 'amount': '$12,400', 'pct': 24, 'color': 'amber'},
            {'bucket': '61–90 days', 'amount': '$8,200',  'pct': 16, 'color': 'orange'},
            {'bucket': '90+ days',   'amount': '$6,100',  'pct': 12, 'color': 'red'},
        ],
    },
    'brokerage': {
        'firm_name': 'SUMMIT REALTY GROUP', 'firm_sub': 'LLC',
        'user_name': 'Dana Reeves', 'user_title': 'Broker/Owner', 'greeting_name': 'Dana',
        'pipeline_label': 'Active Listings',
        'tools': [
            {'key': 'listing',  'title': 'Listing Description', 'icon': '▤'},
            {'key': 'cma',      'title': 'CMA Generator',       'icon': '◷'},
            {'key': 'offer',    'title': 'Offer Analyzer',      'icon': '◈'},
            {'key': 'market',   'title': 'Market Report',       'icon': '⚡'},
        ],
        'kpis': [
            {'label': 'ACTIVE LISTINGS',            'value': '63',     'sub': '12 new · 8 price-reduced · 43 active'},
            {'label': 'PIPELINE VALUE (UNDER CTR)', 'value': '$12.4M', 'sub': '18 transactions · avg $689K', 'highlight': True},
            {'label': 'COMMISSION REVENUE MTD',     'value': '$84,200','sub': '73% of monthly target'},
            {'label': 'AGENT PRODUCTIVITY INDEX',   'value': '6.2',    'sub': '22 agents · target: 7.0'},
        ],
        'actions': [
            {'text': 'Listing agreement "4821 Oak Trail" expires in 3 days — renew or release',  'badge': 'URGENT',    'btype': 'urgent',   'dot': 'red'},
            {'text': 'Client Martinez — 11 showings, no offer — price reduction analysis ready', 'badge': 'REVIEW',    'btype': 'due',      'dot': 'amber'},
            {'text': 'New lead Brad Collins — buyer pre-approved $750K — no agent assigned',     'badge': 'ASSIGN',    'btype': 'time',     'dot': 'blue'},
            {'text': 'Offer deadline 5PM on "2200 Ridgewood Dr" — 3 offers received',           'badge': 'DUE TODAY', 'btype': 'risk',     'dot': 'amber'},
            {'text': 'Agent Kim Tran — 0 closings in 45 days — coaching flag triggered',        'badge': 'TOMORROW',  'btype': 'tomorrow', 'dot': 'gray'},
        ],
        'alerts': [
            {'cat': 'MARKET',    'ctype': 'market',    'headline': 'Fed Holds Rates — Mortgage Applications Up 8% Week-Over-Week',              'source': 'MBA Weekly',   'rel': '1h ago'},
            {'cat': 'INVENTORY', 'ctype': 'inventory', 'headline': 'DFW Active Inventory Down 12% YOY — Seller Market Strengthening',          'source': 'MLS Report',   'rel': '3h ago'},
            {'cat': 'TECH',      'ctype': 'tech',      'headline': 'Zillow Launches AI-Powered Listing Recommendations for Buyer Agents',       'source': 'Inman News',   'rel': '5h ago'},
            {'cat': 'REGULATORY','ctype': 'regulatory','headline': 'NAR Settlement Changes Take Full Effect — Agent Commission Transparency',   'source': 'NAR Bulletin', 'rel': '8h ago'},
        ],
        'goals': [
            {'name': 'Commission Target',    'pct': 73, 'color': 'amber'},
            {'name': 'Listing Conversion',   'pct': 68, 'color': 'green'},
            {'name': 'Agent Retention',      'pct': 95, 'color': 'blue'},
            {'name': 'Avg DOM vs. Market',   'pct': 82, 'color': 'purple'},
        ],
        'pipeline_label_kpi': 'SALES PIPELINE BY STAGE',
        'pipeline': [
            {'name': 'Active Leads',     'pct': 40, 'value': '148 leads'},
            {'name': 'Showing Stage',    'pct': 28, 'value': '84 clients'},
            {'name': 'Under Contract',   'pct': 55, 'value': '18 deals'},
            {'name': 'Closing This Mo.', 'pct': 80, 'value': '$9.2M GCI'},
        ],
        'agents': [
            {'name': 'Lead Scorer & Router',   'status': 'active', 'detail': '14 new leads scored today'},
            {'name': 'Listing Optimizer',      'status': 'active', 'detail': 'Price reduction rec: 3 listings'},
            {'name': 'Market Analyst',         'status': 'active', 'detail': 'Weekly report: 8 zip codes'},
            {'name': 'Transaction Coordinator','status': 'active', 'detail': '18 transactions tracked'},
            {'name': 'Showing Scheduler',      'status': 'active', 'detail': '7 showings confirmed today'},
            {'name': 'CMA Bot',                'status': 'idle',   'detail': 'On-demand · 4 CMAs this week'},
        ],
        'extra_panes': 'brokerage',
        'agent_leaderboard': [
            {'name': 'Sarah Mitchell', 'closings': 8,  'gci': '$42,100', 'pipeline': '$1.8M', 'dom': 18},
            {'name': 'Chris Anderson', 'closings': 6,  'gci': '$31,200', 'pipeline': '$2.1M', 'dom': 24},
            {'name': 'Lisa Park',      'closings': 5,  'gci': '$28,400', 'pipeline': '$1.2M', 'dom': 21},
            {'name': 'David Torres',   'closings': 4,  'gci': '$19,800', 'pipeline': '$0.9M', 'dom': 31},
            {'name': 'Kim Tran',       'closings': 0,  'gci': '$0',      'pipeline': '$0.4M', 'dom': None},
        ],
    },
    'hvac': {
        'firm_name': 'CASCADE CLIMATE SYSTEMS', 'firm_sub': 'INC',
        'user_name': 'Tom Bradley', 'user_title': 'Operations Manager', 'greeting_name': 'Tom',
        'pipeline_label': 'Service Calls',
        'tools': [
            {'key': 'estimate',    'title': 'Estimate Builder',     'icon': '▤'},
            {'key': 'dispatch',    'title': 'Dispatch Board',       'icon': '◷'},
            {'key': 'maintenance', 'title': 'Maintenance Planner',  'icon': '◈'},
            {'key': 'invoice',     'title': 'Invoice Generator',    'icon': '⚡'},
        ],
        'kpis': [
            {'label': 'CALLS TODAY',               'value': '28',     'sub': '6 emergency · 14 scheduled · 8 open'},
            {'label': 'MONTHLY REVENUE',            'value': '$84,200','sub': '+12% vs last month', 'highlight': True},
            {'label': 'TECHNICIAN UTILIZATION',     'value': '87%',    'sub': '8 of 9 techs deployed'},
            {'label': 'MAINTENANCE CONTRACTS',      'value': '312',    'sub': '18 renewals due this month'},
        ],
        'actions': [
            {'text': '"Rodriguez" HVAC completely down — 88°F — emergency dispatch needed',           'badge': 'EMERGENCY',  'btype': 'urgent',   'dot': 'red'},
            {'text': 'Martinez running 90 min late on job 4 — next 2 customers auto-notified',       'badge': 'BEHIND',     'btype': 'due',      'dot': 'amber'},
            {'text': '18 maintenance contract renewals due this month — outreach campaign ready',    'badge': 'THIS MONTH', 'btype': 'time',     'dot': 'blue'},
            {'text': 'Carrier 38CKC compressor back-ordered 3 days — job #249 customer at risk',    'badge': 'PARTS',      'btype': 'risk',     'dot': 'amber'},
            {'text': 'Follow-up call due for Johnson install completed Tuesday',                     'badge': 'TOMORROW',   'btype': 'tomorrow', 'dot': 'gray'},
        ],
        'alerts': [
            {'cat': 'WEATHER',     'ctype': 'weather',    'headline': 'Heat Advisory in Effect — Emergency Call Volume Expected 3× Normal Through Weekend',   'source': 'NWS Alert',    'rel': '1h ago'},
            {'cat': 'PARTS',       'ctype': 'parts',      'headline': 'Carrier & Trane Announce 60-Day Lead Times on Residential Units — Order Early',        'source': 'HVAC Supply',  'rel': '3h ago'},
            {'cat': 'INDUSTRY',    'ctype': 'industry',   'headline': 'EPA Refrigerant Phase-Out: R-22 Service Costs Up 40% — Recommend R-410A Retrofits',    'source': 'ACHR News',    'rel': '5h ago'},
            {'cat': 'REGULATORY',  'ctype': 'regulatory', 'headline': 'New SEER2 Efficiency Standards Require Updated Estimate Templates by January 2027',    'source': 'DOE.gov',      'rel': '1d ago'},
        ],
        'goals': [
            {'name': 'Revenue Target',       'pct': 76, 'color': 'amber'},
            {'name': 'Contract Renewals',    'pct': 83, 'color': 'green'},
            {'name': 'First-Call Resolution','pct': 91, 'color': 'blue'},
            {'name': 'Customer Satisfaction','pct': 94, 'color': 'purple'},
        ],
        'pipeline_label_kpi': 'REVENUE BY SERVICE TYPE',
        'pipeline': [
            {'name': 'Emergency Repairs',     'pct': 42, 'value': '$28,100'},
            {'name': 'Scheduled Maintenance', 'pct': 68, 'value': '$31,400'},
            {'name': 'New Installations',     'pct': 55, 'value': '$18,700'},
            {'name': 'Service Contracts',     'pct': 80, 'value': '$6,000'},
        ],
        'agents': [
            {'name': 'Dispatch Optimizer',   'status': 'active', 'detail': '28 jobs assigned · 2 rerouted this AM'},
            {'name': 'Estimate Generator',   'status': 'active', 'detail': '4 estimates sent today · 2 pending approval'},
            {'name': 'Maintenance Reminder', 'status': 'active', 'detail': '18 renewal notices sent this week'},
            {'name': 'Parts Order Monitor',  'status': 'active', 'detail': 'Alert: 38CKC compressor back-ordered — job #249'},
            {'name': 'Follow-up Agent',      'status': 'active', 'detail': '11 post-job follow-ups sent today'},
            {'name': 'Review Request Bot',   'status': 'idle',   'detail': '3 review requests pending send tonight'},
        ],
        'extra_panes': 'hvac',
        'tech_board': [
            {'tech': 'Martinez, J.',   'jobs': 4, 'current_job': 'Rodriguez Repair (Emergency)',     'status': 'en_route',  'eta': '10:45 AM', 'zone': 'North'},
            {'tech': 'Williams, K.',   'jobs': 3, 'current_job': 'Annual Tune-Up — Apex Office',    'status': 'on_job',    'eta': '11:30 AM', 'zone': 'Central'},
            {'tech': 'Chen, L.',       'jobs': 4, 'current_job': 'New Install — Harmon Residence',  'status': 'on_job',    'eta': '1:00 PM',  'zone': 'South'},
            {'tech': 'Davis, R.',      'jobs': 3, 'current_job': 'Compressor Replacement',          'status': 'on_job',    'eta': '12:30 PM', 'zone': 'East'},
            {'tech': 'Thompson, M.',   'jobs': 4, 'current_job': 'System Inspection — Summit Dental','status': 'en_route', 'eta': '10:15 AM', 'zone': 'North'},
            {'tech': 'Garcia, P.',     'jobs': 0, 'current_job': 'Available — Overflow Standby',    'status': 'available', 'eta': '—',        'zone': 'West'},
        ],
    },
    'plumbing': {
        'firm_name': 'APEX FLOW PLUMBING', 'firm_sub': 'LLC',
        'user_name': 'Dave Kowalski', 'user_title': 'Owner / Lead Technician', 'greeting_name': 'Dave',
        'pipeline_label': 'Active Jobs',
        'tools': [
            {'key': 'quote',       'title': 'Quote Builder',    'icon': '▤'},
            {'key': 'job-tracker', 'title': 'Job Tracker',      'icon': '◷'},
            {'key': 'permit',      'title': 'Permit Tracker',   'icon': '◈'},
            {'key': 'invoice',     'title': 'Invoice Generator','icon': '⚡'},
        ],
        'kpis': [
            {'label': 'JOBS TODAY',            'value': '17',     'sub': '4 emergency · 9 scheduled · 4 open'},
            {'label': 'MONTHLY REVENUE',        'value': '$52,400','sub': '+8% vs last month', 'highlight': True},
            {'label': 'OPEN QUOTES',            'value': '23',     'sub': '8 unsent · 11 awaiting approval'},
            {'label': 'AVG REVIEW RATING',      'value': '4.8★',  'sub': '14 new reviews this month'},
        ],
        'actions': [
            {'text': '"Flood at 412 Waverly Ave" — burst pipe — Dave dispatched, ETA 20 min',       'badge': 'EMERGENCY',  'btype': 'urgent',   'dot': 'red'},
            {'text': 'Quote #44 — Riverdale Commercial $8,200 — sent 3 days ago, no response',     'badge': 'FOLLOW UP',  'btype': 'due',      'dot': 'amber'},
            {'text': 'Permit for water heater Job #39 — applied 7 days ago, city still pending',   'badge': 'WAITING',    'btype': 'time',     'dot': 'blue'},
            {'text': 'Jake running 45 min late on Park Dental — customer already notified by AI',  'badge': 'DELAYED',    'btype': 'risk',     'dot': 'amber'},
            {'text': '6 completed jobs this week with no follow-up — review requests pending',     'badge': 'TOMORROW',   'btype': 'tomorrow', 'dot': 'gray'},
        ],
        'alerts': [
            {'cat': 'WEATHER',     'ctype': 'weather',    'headline': 'Freeze Advisory Tonight — Historic Call Volume Expected 8 AM Tomorrow Morning',         'source': 'NWS Alert',       'rel': '2h ago'},
            {'cat': 'PARTS',       'ctype': 'parts',      'headline': 'Copper Prices Up 18% YTD — Lock In Supplier Quotes Before Q3 Re-Pricing',              'source': 'Plumbing Eng.',   'rel': '4h ago'},
            {'cat': 'INDUSTRY',    'ctype': 'industry',   'headline': 'Federal Infrastructure Funds Now Available in 28 States for Lead Pipe Replacement',     'source': 'EPA.gov',         'rel': '6h ago'},
            {'cat': 'REGULATORY',  'ctype': 'regulatory', 'headline': 'New IAPMO Water Heater Efficiency Rules Effective Q2 — Update Estimate Templates',      'source': 'IAPMO',           'rel': '1d ago'},
        ],
        'goals': [
            {'name': 'Revenue Target',         'pct': 71, 'color': 'amber'},
            {'name': 'Quote Conversion',       'pct': 64, 'color': 'green'},
            {'name': 'Emergency Response Time','pct': 88, 'color': 'blue'},
            {'name': 'Customer Reviews (5★)',  'pct': 96, 'color': 'purple'},
        ],
        'pipeline_label_kpi': 'REVENUE BY JOB TYPE',
        'pipeline': [
            {'name': 'Emergency Repairs',  'pct': 48, 'value': '$18,200'},
            {'name': 'Residential Service','pct': 62, 'value': '$16,400'},
            {'name': 'Commercial Service', 'pct': 40, 'value': '$11,800'},
            {'name': 'New Construction',   'pct': 25, 'value': '$6,000'},
        ],
        'agents': [
            {'name': 'Lead Qualifier',     'status': 'active', 'detail': '4 emergency calls triaged today'},
            {'name': 'Quote Generator',    'status': 'active', 'detail': '3 quotes built today · avg $2,400'},
            {'name': 'Dispatch Scheduler', 'status': 'active', 'detail': '17 jobs dispatched · 2 rerouted'},
            {'name': 'Invoice Agent',      'status': 'active', 'detail': '9 invoices sent · $14,200 pending'},
            {'name': 'Review Request Bot', 'status': 'active', 'detail': '6 review requests queued tonight'},
            {'name': 'Permit Tracker',     'status': 'idle',   'detail': '4 active permits · 1 overdue'},
        ],
        'extra_panes': 'plumbing',
        'job_board': [
            {'job': '#P-248', 'customer': '412 Waverly Ave — Burst Pipe',     'tech': 'Kowalski, D.',  'type': 'Emergency',  'status': 'en_route',  'eta': 'ASAP'},
            {'job': '#P-244', 'customer': 'Park Dental — Drain Clearing',      'tech': 'Johnson, S.',   'type': 'Commercial', 'status': 'on_job',    'eta': '11:00 AM'},
            {'job': '#P-241', 'customer': 'Harmon Residence — Water Heater',   'tech': 'Murphy, T.',    'type': 'Residential','status': 'completed', 'eta': 'Done'},
            {'job': '#P-245', 'customer': 'Riverdale Apts — Backflow Test',    'tech': 'Unassigned',    'type': 'Commercial', 'status': 'scheduled', 'eta': '1:00 PM'},
            {'job': '#P-246', 'customer': 'Thompson Home — Sewer Camera',      'tech': 'Rodriguez, M.', 'type': 'Residential','status': 'en_route',  'eta': '12:30 PM'},
            {'job': '#P-247', 'customer': 'City of Riverside — Final Inspect', 'tech': 'Johnson, S.',   'type': 'Permit',     'status': 'scheduled', 'eta': '3:00 PM'},
        ],
    },
    'restaurant': {
        'firm_name': 'HARVEST TABLE RESTAURANT GROUP', 'firm_sub': '',
        'user_name': 'Marco Rossi', 'user_title': 'General Manager', 'greeting_name': 'Marco',
        'pipeline_label': 'Reservations',
        'tools': [
            {'key': 'menu',      'title': 'Menu Performance',  'icon': '▤'},
            {'key': 'staff',     'title': 'Staff Scheduler',   'icon': '◷'},
            {'key': 'inventory', 'title': 'Inventory Manager', 'icon': '◈'},
            {'key': 'review',    'title': 'Review Responder',  'icon': '⚡'},
        ],
        'kpis': [
            {'label': 'COVERS TODAY',             'value': '284',    'sub': '112 lunch · 172 dinner · 18 bar'},
            {'label': 'PROJECTED REVENUE TODAY',   'value': '$14,200','sub': '+$1,800 vs same day last week', 'highlight': True},
            {'label': 'FOOD COST % (MTD)',          'value': '28.4%', 'sub': 'Target: 28% · 0.4% above budget'},
            {'label': 'OPEN REVIEWS TO RESPOND',   'value': '11',    'sub': '3 negative · 8 positive · avg 4.4★'},
        ],
        'actions': [
            {'text': 'Prep team 30 min behind on dinner mise en place — redirect kitchen flow now',  'badge': 'URGENT',       'btype': 'urgent',   'dot': 'red'},
            {'text': '3-star Yelp review posted 2hrs ago — AI response drafted, needs approval',    'badge': 'RESPOND',      'btype': 'due',      'dot': 'amber'},
            {'text': 'TechCorp private dining inquiry — 40 guests May 18, $4,800 est — call at 2PM','badge': '2:00 PM CALL', 'btype': 'time',     'dot': 'blue'},
            {'text': 'Salmon and arugula delivery short 30% — dinner service at risk after 5PM',    'badge': 'INVENTORY',    'btype': 'risk',     'dot': 'amber'},
            {'text': 'Next week staff schedule not approved — 3 shift conflicts unresolved',        'badge': 'TOMORROW',     'btype': 'tomorrow', 'dot': 'gray'},
        ],
        'alerts': [
            {'cat': 'FOOD COSTS', 'ctype': 'food_costs', 'headline': 'USDA: Egg & Dairy Wholesale Prices Down 12% — Renegotiate Supplier Contracts Now',           'source': 'USDA Report',     'rel': '2h ago'},
            {'cat': 'INDUSTRY',   'ctype': 'industry',   'headline': 'OpenTable: "Experience Dining" Bookings Up 22% — Private Event Revenue Opportunity',          'source': 'OpenTable Blog',  'rel': '4h ago'},
            {'cat': 'LABOR',      'ctype': 'labor',      'headline': 'State Minimum Wage Increase to $15.50 Effective July 1 — Update Labor Cost Models',            'source': 'State DOL',       'rel': '6h ago'},
            {'cat': 'REVIEWS',    'ctype': 'reviews',    'headline': 'Google Maps Update Boosts Review Recency Weight — Respond Within 24 Hours for Max Impact',     'source': 'Search Engine J.','rel': '1d ago'},
        ],
        'goals': [
            {'name': 'Revenue Target',      'pct': 84, 'color': 'green'},
            {'name': 'Food Cost Control',   'pct': 71, 'color': 'amber'},
            {'name': 'Review Response Rate','pct': 89, 'color': 'blue'},
            {'name': 'Table Turn Rate',     'pct': 77, 'color': 'purple'},
        ],
        'pipeline_label_kpi': 'REVENUE BY DAYPART',
        'pipeline': [
            {'name': 'Lunch Service',  'pct': 45, 'value': '$4,800'},
            {'name': 'Dinner Service', 'pct': 78, 'value': '$7,400'},
            {'name': 'Bar & Lounge',   'pct': 30, 'value': '$1,200'},
            {'name': 'Private Events', 'pct': 20, 'value': '$800 (today)'},
        ],
        'agents': [
            {'name': 'Reservation Agent',        'status': 'active', 'detail': '284 covers confirmed · 12 waitlisted'},
            {'name': 'Inventory Alert Agent',    'status': 'active', 'detail': '3 items below par — POs drafted'},
            {'name': 'Review Responder',         'status': 'active', 'detail': '3 negative drafts awaiting approval'},
            {'name': 'Menu Performance Analyst', 'status': 'active', 'detail': 'Weekly report: 4 low-margin items flagged'},
            {'name': 'Staff Scheduler',          'status': 'active', 'detail': 'Next week: 2 shift conflicts to resolve'},
            {'name': 'Food Cost Monitor',        'status': 'idle',   'detail': 'Daily report runs at 11 PM'},
        ],
        'extra_panes': 'restaurant',
        'service_timeline': [
            {'time': '11:00 AM', 'service': 'Lunch Open',  'covers': 28,  'status': 'active',   'pct': 62},
            {'time': '12:00 PM', 'service': 'Lunch Peak',   'covers': 84,  'status': 'active',   'pct': 92},
            {'time': '1:00 PM',  'service': 'Lunch Close',  'covers': 41,  'status': 'upcoming', 'pct': 55},
            {'time': '3:00 PM',  'service': 'Prep / Break', 'covers': 0,   'status': 'prep',     'pct': 0},
            {'time': '5:00 PM',  'service': 'Dinner Open',  'covers': 42,  'status': 'upcoming', 'pct': 70},
            {'time': '6:30 PM',  'service': 'Dinner Peak',  'covers': 96,  'status': 'upcoming', 'pct': 100},
            {'time': '8:30 PM',  'service': 'Dinner Close', 'covers': 72,  'status': 'upcoming', 'pct': 88},
            {'time': '10:00 PM', 'service': 'Bar Close',    'covers': 21,  'status': 'upcoming', 'pct': 42},
        ],
    },
}

# ── Sub-page data ─────────────────────────────────────────────────────────────
BRIEF_DATA = {
    'agency': {
        'generated_at': '7:02 AM by AIOS Daily Brief Agent',
        'summary': 'Strong week continuing. MRR is up 4.8% month-over-month. One critical agent outage at Apex Dental requires immediate attention. TechStart Inc shows early churn signals — proactive outreach recommended today.',
        'metrics': [
            {'label': 'MRR',            'value': '$47,200', 'delta': '+$2,100',  'up': True},
            {'label': 'Active Clients', 'value': '24',      'delta': 'stable',    'up': None},
            {'label': 'Agent Uptime',   'value': '91.5%',   'delta': '-0.7%',     'up': False},
            {'label': 'Open Proposals', 'value': '4',       'delta': '+2 new',    'up': True},
        ],
        'highlights': [
            {'type': 'win',   'text': 'Metro HVAC renewed at $1,800/mo — 50% increase over previous contract'},
            {'type': 'risk',  'text': 'TechStart Inc has not logged into their dashboard in 18 days'},
            {'type': 'alert', 'text': 'Apex Dental agent failure at 6:14 AM — 4 automations paused'},
            {'type': 'win',   'text': 'Riviera Realty proposal viewed 3 times in 24hrs — high interest signal'},
        ],
        'calendar': [
            {'time': '9:00 AM',  'event': 'Client check-in — Metro HVAC (monthly)'},
            {'time': '11:00 AM', 'event': 'Proposal review — Riviera Realty (internal)'},
            {'time': '2:00 PM',  'event': 'ROI report delivery — Metro HVAC'},
            {'time': '3:00 PM',  'event': 'Agent audit — Apex Dental recovery'},
        ],
    },
    'legal': {
        'generated_at': '7:15 AM by AIOS Daily Brief Agent',
        'summary': 'Critical SOL deadline in 4 days for Martinez v. Citywide. Opposition brief due today at 5PM — draft is ready for review. 7 deadlines active this week across 5 matters.',
        'metrics': [
            {'label': 'Active Cases',    'value': '18',    'delta': '+1 new',      'up': True},
            {'label': 'Billable Today',  'value': '6.2h',  'delta': 'target: 8h',  'up': False},
            {'label': 'A/R Outstanding', 'value': '$18.4K','delta': '90+ day aged', 'up': False},
            {'label': 'Open Deadlines',  'value': '7',     'delta': '2 critical',   'up': False},
        ],
        'highlights': [
            {'type': 'alert', 'text': 'SOL expires May 4 on Martinez — file complaint today or seek extension'},
            {'type': 'risk',  'text': '$18,400 in A/R over 90 days — collections action recommended'},
            {'type': 'win',   'text': 'Rivera Securities case: favorable ruling on motion to compel'},
            {'type': 'alert', 'text': 'New PACER activity: opposing counsel filed supplemental exhibit in Chen v. Harlow'},
        ],
        'calendar': [
            {'time': '9:00 AM',  'event': 'Team meeting — weekly case review'},
            {'time': '11:00 AM', 'event': 'Deposition prep session — Chen v. Harlow'},
            {'time': '2:00 PM',  'event': 'New client consult — Patterson (employment)'},
            {'time': '4:30 PM',  'event': 'Opposition brief final review + file'},
        ],
    },
    'construction': {
        'generated_at': '6:45 AM by AIOS Daily Brief Agent',
        'summary': 'Weather alert: 3-day rain event starting Monday affects 4 active projects. Commerce Park P2 budget variance at 7.3% — change order review needed. Lakeshore Condos permit expiring in 12 days.',
        'metrics': [
            {'label': 'Active Projects', 'value': '11',   'delta': 'stable',    'up': None},
            {'label': 'Budget Variance', 'value': '+3.2%','delta': 'avg all',   'up': False},
            {'label': 'Open RFIs',       'value': '34',   'delta': '+6 this wk','up': False},
            {'label': 'Safety Days',     'value': '847',  'delta': 'streak',    'up': True},
        ],
        'highlights': [
            {'type': 'alert', 'text': 'Lakeshore Condos permit expires May 12 — renewal package not submitted'},
            {'type': 'risk',  'text': 'Commerce Park P2 variance hit 7.3% — 3 unapproved change orders pending'},
            {'type': 'win',   'text': 'Riverside Homes: final inspection passed — certificate of occupancy received'},
            {'type': 'alert', 'text': 'Rain forecast Mon–Wed — 4 projects need schedule updates'},
        ],
        'calendar': [
            {'time': '7:00 AM',  'event': 'Morning site walk — Lakeshore Condos'},
            {'time': '10:00 AM', 'event': 'Change order review — Commerce Park P2'},
            {'time': '1:00 PM',  'event': 'Sub coordination call — Harmon Carpentry'},
            {'time': '3:30 PM',  'event': 'Permit renewal prep — Lakeshore packet'},
        ],
    },
    'medical': {
        'generated_at': '6:58 AM by AIOS Daily Brief Agent',
        'summary': 'Solid day ahead with 38 patients scheduled across 4 providers. Net collections rate strong at 97.2%. Four prior authorizations expire before scheduled visits — Prior Auth Bot has submitted 3 renewals.',
        'metrics': [
            {'label': 'Patients Today',   'value': '38',    'delta': '+2 from Mon',  'up': True},
            {'label': 'Collections Rate', 'value': '97.2%', 'delta': '-0.8% target', 'up': False},
            {'label': 'Pending Auths',    'value': '14',    'delta': '4 expiring',   'up': False},
            {'label': 'No-Show Rate',     'value': '8.3%',  'delta': '+1.2% MoM',   'up': False},
        ],
        'highlights': [
            {'type': 'alert', 'text': 'Aetna claim #88412 denied — modifier 25 missing. Appeal drafted.'},
            {'type': 'risk',  'text': 'James H. prior auth expires Apr 30 — rescheduled to May 2 pending renewal'},
            {'type': 'win',   'text': '47 recall patients campaign ready — estimated $14,100 in recoverable revenue'},
            {'type': 'alert', 'text': '4 lab results unacknowledged in portal for 6+ hours — review needed'},
        ],
        'calendar': [
            {'time': '8:00 AM',  'event': 'Morning huddle — Dr. Chen, Dr. Patel (daily stand-up)'},
            {'time': '10:30 AM', 'event': 'New patient consult — Maria G. (Dr. Torres)'},
            {'time': '1:00 PM',  'event': 'Prior auth follow-up call — Aetna case manager'},
            {'time': '3:30 PM',  'event': 'Team meeting — recall campaign review'},
        ],
    },
    'brokerage': {
        'generated_at': '7:08 AM by AIOS Daily Brief Agent',
        'summary': 'Busy day: offer deadline at 5PM on Ridgewood Dr with 3 competing offers. New pre-approved buyer needs agent assignment. Listing on Oak Trail expiring in 3 days.',
        'metrics': [
            {'label': 'Active Listings',  'value': '63',     'delta': '+3 new',      'up': True},
            {'label': 'Under Contract',   'value': '18',     'delta': '+2 this wk',  'up': True},
            {'label': 'Commission MTD',   'value': '$84,200','delta': '73% of target','up': None},
            {'label': 'New Leads Today',  'value': '14',     'delta': '+4 vs avg',   'up': True},
        ],
        'highlights': [
            {'type': 'alert', 'text': '4821 Oak Trail listing agreement expires May 3 — contact seller today'},
            {'type': 'win',   'text': '2200 Ridgewood Dr: 3 offers received, multiple offer situation — 5PM deadline'},
            {'type': 'risk',  'text': 'Agent Kim Tran: 0 closings in 45 days — coaching session recommended'},
            {'type': 'win',   'text': 'Brad Collins pre-approved $750K — matched to 8 active listings'},
        ],
        'calendar': [
            {'time': '9:00 AM',  'event': 'Agent meeting — weekly production review'},
            {'time': '11:00 AM', 'event': 'Buyer consult — Brad Collins'},
            {'time': '2:00 PM',  'event': 'Listing presentation — 412 Maple Grove (new)'},
            {'time': '5:00 PM',  'event': 'Offer review — 2200 Ridgewood Dr (3 offers)'},
        ],
    },
    'hvac': {
        'generated_at': '6:30 AM by AIOS Daily Brief Agent',
        'summary': 'Heat advisory in effect — emergency call volume up 3× normal. All 9 techs deployed. 28 jobs on the board today. 18 maintenance contract renewals due this month — outreach campaign ready to launch.',
        'metrics': [
            {'label': 'Calls Today',       'value': '28',     'delta': '+11 vs avg',    'up': False},
            {'label': 'Monthly Revenue',   'value': '$84,200','delta': '+12% MoM',      'up': True},
            {'label': 'Tech Utilization',  'value': '87%',    'delta': '8 of 9 techs',  'up': True},
            {'label': 'Contract Renewals', 'value': '18',     'delta': 'due this month', 'up': False},
        ],
        'highlights': [
            {'type': 'alert', 'text': 'Rodriguez emergency: AC completely down at 88°F — Martinez dispatched, ETA 10:45 AM'},
            {'type': 'risk',  'text': 'Carrier 38CKC compressor back-ordered 3 days — job #249 customer at risk of delay'},
            {'type': 'win',   'text': '18 maintenance contracts renewing this month — outreach campaign pre-built and ready'},
            {'type': 'alert', 'text': 'Martinez running 90 min late on job 4 — next 2 customers auto-notified by AI'},
        ],
        'calendar': [
            {'time': '8:00 AM',  'event': 'Morning dispatch board review — 28 jobs assigned'},
            {'time': '10:00 AM', 'event': 'Parts order review — Carrier back-order status check'},
            {'time': '1:00 PM',  'event': 'Maintenance contract outreach launch — 18 accounts'},
            {'time': '4:00 PM',  'event': 'Daily tech debrief — job completion review'},
        ],
    },
    'plumbing': {
        'generated_at': '6:45 AM by AIOS Daily Brief Agent',
        'summary': 'Active day with 17 jobs on the board including 4 emergencies. Freeze advisory tonight will spike tomorrow morning call volume — system pre-armed for overflow. Quote #44 at $8,200 has gone 3 days without a response.',
        'metrics': [
            {'label': 'Jobs Today',        'value': '17',     'delta': '4 emergency',    'up': False},
            {'label': 'Monthly Revenue',   'value': '$52,400','delta': '+8% MoM',        'up': True},
            {'label': 'Open Quotes',       'value': '23',     'delta': '8 unsent',       'up': False},
            {'label': 'Avg Review Rating', 'value': '4.8★',  'delta': '14 new reviews', 'up': True},
        ],
        'highlights': [
            {'type': 'alert', 'text': 'Burst pipe at 412 Waverly Ave — Dave dispatched, ETA 20 min'},
            {'type': 'risk',  'text': 'Quote #44 ($8,200 — Riverdale Commercial) unanswered 3 days — follow-up queued'},
            {'type': 'win',   'text': 'Freeze advisory tonight — AI pre-armed for 3× emergency call volume tomorrow AM'},
            {'type': 'alert', 'text': 'Permit for water heater Job #39 pending 7 days — city approval follow-up needed'},
        ],
        'calendar': [
            {'time': '8:00 AM',  'event': 'Job board review — 17 active jobs assigned'},
            {'time': '10:00 AM', 'event': 'Quote follow-up — Riverdale Commercial ($8,200)'},
            {'time': '1:00 PM',  'event': 'Permit status call — City permit office Job #39'},
            {'time': '3:00 PM',  'event': 'Tomorrow overflow prep — freeze advisory response plan'},
        ],
    },
    'restaurant': {
        'generated_at': '9:00 AM by AIOS Daily Brief Agent',
        'summary': 'Strong covers today: 284 confirmed across lunch and dinner. Inventory alert on salmon and arugula may affect dinner service. Three negative reviews need responses before 5 PM. TechCorp private dining inquiry at 2 PM.',
        'metrics': [
            {'label': 'Covers Today',      'value': '284',    'delta': '+18 vs avg',     'up': True},
            {'label': 'Proj. Revenue',     'value': '$14,200','delta': '+$1,800 vs wk',  'up': True},
            {'label': 'Food Cost % (MTD)', 'value': '28.4%',  'delta': '+0.4% vs target','up': False},
            {'label': 'Open Reviews',      'value': '11',     'delta': '3 negative',      'up': False},
        ],
        'highlights': [
            {'type': 'alert', 'text': 'Prep team 30 min behind on dinner mise en place — kitchen flow redirect needed'},
            {'type': 'risk',  'text': 'Salmon and arugula delivery short 30% — dinner service at risk after 5 PM'},
            {'type': 'win',   'text': 'TechCorp private dining inquiry — 40 guests May 18, estimated $4,800'},
            {'type': 'alert', 'text': '3 negative Yelp/Google reviews need responses before end of day'},
        ],
        'calendar': [
            {'time': '10:00 AM', 'event': 'Pre-service staff briefing — prep catch-up plan'},
            {'time': '11:00 AM', 'event': 'Lunch service open — 112 covers expected'},
            {'time': '2:00 PM',  'event': 'TechCorp private dining call — 40 guests May 18'},
            {'time': '5:00 PM',  'event': 'Dinner service open — 172 covers expected'},
        ],
    },
}

PIPELINE_DATA = {
    'agency': [
        {'name': 'Apex Dental',    'tier': 'Growth',     'mrr': '$1,800', 'stage': 'at_risk',   'score': 58,  'pm': 'Alex R.',   'next': 'Agent repair',      'due': 'Today'},
        {'name': 'Riviera Realty', 'tier': 'Growth',     'mrr': '$2,200', 'stage': 'active',    'score': 85,  'pm': 'Jordan K.', 'next': 'Send proposal',     'due': 'Today'},
        {'name': 'Metro HVAC',     'tier': 'Enterprise', 'mrr': '$4,200', 'stage': 'active',    'score': 97,  'pm': 'Alex R.',   'next': 'Monthly review',    'due': 'Tomorrow'},
        {'name': 'TechStart Inc',  'tier': 'Starter',    'mrr': '$597',   'stage': 'at_risk',   'score': 41,  'pm': 'Jordan K.', 'next': 'Churn outreach',    'due': 'Today'},
        {'name': 'LakeView Law',   'tier': 'Growth',     'mrr': '$1,800', 'stage': 'active',    'score': 88,  'pm': 'Alex R.',   'next': 'Upsell call',       'due': 'Fri'},
        {'name': 'Summit Clinic',  'tier': 'Growth',     'mrr': '$1,800', 'stage': 'active',    'score': 79,  'pm': 'Jordan K.', 'next': 'QA report',         'due': 'Thu'},
        {'name': 'BlueSky Dental', 'tier': 'Starter',    'mrr': '$597',   'stage': 'onboarding','score': None,'pm': 'Alex R.',   'next': 'Agent setup',       'due': 'May 3'},
        {'name': 'Harbor Fitness', 'tier': 'Growth',     'mrr': '$1,800', 'stage': 'onboarding','score': None,'pm': 'Jordan K.', 'next': 'Discovery call',    'due': 'May 5'},
        {'name': 'Oaks Law Group', 'tier': 'Enterprise', 'mrr': '$4,200', 'stage': 'active',    'score': 92,  'pm': 'Alex R.',   'next': 'Feature expansion', 'due': 'May 8'},
    ],
    'legal': [
        {'name': 'Martinez v. Citywide',  'type': 'PI',           'value': '$420K',  'stage': 'trial',      'attorney': 'Hayes',   'next': 'File complaint',    'due': 'May 4'},
        {'name': 'Chen v. Harlow Mfg',   'type': 'Employment',   'value': '$280K',  'stage': 'discovery',  'attorney': 'Rivera',  'next': 'Deposition prep',   'due': 'Tomorrow'},
        {'name': 'Rivera Securities',     'type': 'Securities',   'value': '$1.8M',  'stage': 'motions',    'attorney': 'Hayes',   'next': 'Suppression motion','due': 'May 10'},
        {'name': 'Oaks Estate Matter',   'type': 'Estate',       'value': '$620K',  'stage': 'negotiation','attorney': 'Torres',  'next': 'Counter-offer',     'due': 'May 6'},
        {'name': 'Patterson Employment', 'type': 'Employment',   'value': '$95K',   'stage': 'intake',     'attorney': 'Rivera',  'next': 'Retainer sign',     'due': 'Today'},
        {'name': 'GlobalTech Contract',  'type': 'Transactional','value': '$340K',  'stage': 'drafting',   'attorney': 'Hayes',   'next': 'Client review',     'due': 'May 8'},
    ],
    'construction': [
        {'name': 'Lakeshore Condos',   'type': 'Residential', 'budget': '$2.4M', 'pct': 62, 'variance': '+2.1%', 'pm': 'Torres',  'next': 'Permit renewal', 'due': 'May 12'},
        {'name': 'Commerce Park P2',   'type': 'Commercial',  'budget': '$3.1M', 'pct': 44, 'variance': '+7.3%', 'pm': 'Johnson', 'next': 'CO review',      'due': 'Today'},
        {'name': 'Riverside Homes',    'type': 'Residential', 'budget': '$0.8M', 'pct': 88, 'variance': '+0.4%', 'pm': 'Torres',  'next': 'Final punch',    'due': 'May 3'},
        {'name': 'Civic Center Reno',  'type': 'Civil',       'budget': '$1.2M', 'pct': 31, 'variance': '+1.8%', 'pm': 'Davis',   'next': 'MEP rough-in',   'due': 'May 15'},
        {'name': 'Harbor View Apts',   'type': 'Residential', 'budget': '$0.8M', 'pct': 15, 'variance': '+3.2%', 'pm': 'Johnson', 'next': 'Foundation pour','due': 'May 6'},
        {'name': 'Sunset Office Bldg', 'type': 'Commercial',  'budget': '$1.8M', 'pct': 5,  'variance': '0.0%',  'pm': 'Torres',  'next': 'Mobilization',   'due': 'May 10'},
    ],
    'medical': [
        {'time': '8:00 AM',  'name': 'Maria Garcia',    'type': 'Annual Physical',   'provider': 'Dr. Chen',   'insurance': 'Blue Cross', 'status': 'checked_in', 'flag': None},
        {'time': '8:30 AM',  'name': 'Robert Kim',      'type': 'Follow-up',         'provider': 'Dr. Patel',  'insurance': 'Medicare',   'status': 'checked_in', 'flag': None},
        {'time': '9:00 AM',  'name': 'Linda Torres',    'type': 'New Patient',       'provider': 'Dr. Torres', 'insurance': 'Aetna',      'status': 'waiting',    'flag': None},
        {'time': '9:30 AM',  'name': 'James Henderson', 'type': 'Pre-op Consult',    'provider': 'Dr. Chen',   'insurance': 'Medicare',   'status': 'scheduled',  'flag': 'Auth expiring'},
        {'time': '10:00 AM', 'name': 'Susan Park',      'type': 'Chronic Care Mgmt', 'provider': 'Dr. Nguyen', 'insurance': 'Blue Cross', 'status': 'scheduled',  'flag': None},
        {'time': '11:00 AM', 'name': 'Karen White',     'type': 'Follow-up',         'provider': 'Dr. Chen',   'insurance': 'Aetna',      'status': 'scheduled',  'flag': None},
        {'time': '1:00 PM',  'name': 'Angela Martinez', 'type': 'Lab Review',        'provider': 'Dr. Nguyen', 'insurance': 'Blue Cross', 'status': 'confirmed',  'flag': 'Unacked labs'},
        {'time': '2:00 PM',  'name': '— Open Slot —',   'type': '',                  'provider': 'Dr. Chen',   'insurance': '',           'status': 'open',       'flag': None},
        {'time': '2:30 PM',  'name': 'Rachel Adams',    'type': 'Follow-up',         'provider': 'Dr. Patel',  'insurance': 'Self-Pay',   'status': 'confirmed',  'flag': None},
    ],
    'brokerage': [
        {'address': '2200 Ridgewood Dr',    'price': '$625,000', 'status': 'under_contract', 'agent': 'S. Mitchell', 'dom': 12, 'offers': 3,  'close': 'May 20'},
        {'address': '4821 Oak Trail',       'price': '$498,000', 'status': 'active',         'agent': 'C. Anderson', 'dom': 87, 'offers': 0,  'close': None},
        {'address': '812 Lakefront Blvd',   'price': '$1.2M',    'status': 'active',         'agent': 'L. Park',     'dom': 24, 'offers': 1,  'close': None},
        {'address': '301 Maple Grove',      'price': '$389,000', 'status': 'under_contract', 'agent': 'D. Torres',   'dom': 8,  'offers': 2,  'close': 'May 15'},
        {'address': '1140 Crestwood Ct',    'price': '$540,000', 'status': 'price_reduced',  'agent': 'S. Mitchell', 'dom': 61, 'offers': 0,  'close': None},
        {'address': '5502 Harbor View',     'price': '$875,000', 'status': 'active',         'agent': 'C. Anderson', 'dom': 18, 'offers': 0,  'close': None},
    ],
    'hvac': [
        {'job': '#H-249', 'customer': 'Rodriguez Residence',   'type': 'Emergency Repair',  'tech': 'Martinez, J.',  'status': 'en_route',    'revenue': '$480',   'due': 'ASAP'},
        {'job': '#H-246', 'customer': 'Apex Office Complex',   'type': 'Annual Tune-Up',    'tech': 'Williams, K.',  'status': 'in_progress', 'revenue': '$320',   'due': '11:30 AM'},
        {'job': '#H-247', 'customer': 'Harmon Residence',      'type': 'New Install',        'tech': 'Chen, L.',      'status': 'in_progress', 'revenue': '$3,800', 'due': '1:00 PM'},
        {'job': '#H-248', 'customer': 'Summit Dental',         'type': 'System Inspection',  'tech': 'Thompson, M.',  'status': 'en_route',    'revenue': '$280',   'due': '10:15 AM'},
        {'job': '#H-244', 'customer': 'Metro HVAC Office',     'type': 'Compressor Repair',  'tech': 'Davis, R.',     'status': 'in_progress', 'revenue': '$1,200', 'due': '12:30 PM'},
        {'job': '#H-250', 'customer': 'Riverside Apartments',  'type': 'Scheduled Maint.',   'tech': 'Unassigned',    'status': 'scheduled',   'revenue': '$240',   'due': '2:00 PM'},
        {'job': '#H-251', 'customer': 'Harbor View Condos',    'type': 'New Install',        'tech': 'Unassigned',    'status': 'scheduled',   'revenue': '$4,200', 'due': 'Tomorrow'},
        {'job': '#H-245', 'customer': 'City Library',          'type': 'Emergency Repair',   'tech': 'Garcia, P.',    'status': 'completed',   'revenue': '$620',   'due': 'Done'},
    ],
    'plumbing': [
        {'job': '#P-248', 'customer': '412 Waverly Ave',        'type': 'Burst Pipe Emergency', 'tech': 'Kowalski, D.',  'status': 'en_route',    'revenue': '$840',   'due': 'ASAP'},
        {'job': '#P-244', 'customer': 'Park Dental',            'type': 'Drain Clearing',       'tech': 'Johnson, S.',   'status': 'in_progress', 'revenue': '$380',   'due': '11:00 AM'},
        {'job': '#P-241', 'customer': 'Harmon Residence',       'type': 'Water Heater Install',  'tech': 'Murphy, T.',    'status': 'completed',   'revenue': '$1,800', 'due': 'Done'},
        {'job': '#P-245', 'customer': 'Riverdale Apts',         'type': 'Backflow Test',         'tech': 'Unassigned',    'status': 'scheduled',   'revenue': '$420',   'due': '1:00 PM'},
        {'job': '#P-246', 'customer': 'Thompson Home',          'type': 'Sewer Camera Inspect',  'tech': 'Rodriguez, M.', 'status': 'en_route',    'revenue': '$280',   'due': '12:30 PM'},
        {'job': '#P-247', 'customer': 'City of Riverside',      'type': 'Permit Final Inspect',   'tech': 'Johnson, S.',   'status': 'scheduled',   'revenue': '$0',     'due': '3:00 PM'},
        {'job': '#P-242', 'customer': 'Harrington Office',      'type': 'Commercial Re-pipe',    'tech': 'Murphy, T.',    'status': 'scheduled',   'revenue': '$6,400', 'due': 'May 5'},
        {'job': '#P-243', 'customer': 'Lakeview Condos',        'type': 'Leak Detection',        'tech': 'Unassigned',    'status': 'pending',     'revenue': '$180',   'due': 'TBD'},
    ],
    'restaurant': [
        {'time': '12:00 PM', 'party': 'Harrison, B.',   'covers': 4, 'type': 'Lunch Walk-in',   'section': 'Main',    'status': 'seated',    'notes': None},
        {'time': '12:15 PM', 'party': 'Martinez, F.',   'covers': 2, 'type': 'Lunch Rsvp',      'section': 'Patio',   'status': 'seated',    'notes': None},
        {'time': '12:30 PM', 'party': 'TechCorp (7)',   'covers': 7, 'type': 'Business Lunch',  'section': 'Private', 'status': 'en_route',  'notes': 'Corp account'},
        {'time': '6:00 PM',  'party': 'Wilson Anniv.',  'covers': 2, 'type': 'Dinner Rsvp',     'section': 'Booth',   'status': 'confirmed', 'notes': 'Anniversary — champagne'},
        {'time': '6:30 PM',  'party': 'Anderson, R.',   'covers': 6, 'type': 'Dinner Rsvp',     'section': 'Main',    'status': 'confirmed', 'notes': None},
        {'time': '7:00 PM',  'party': 'Smith, K.',      'covers': 4, 'type': 'Dinner Rsvp',     'section': 'Patio',   'status': 'confirmed', 'notes': None},
        {'time': '7:30 PM',  'party': 'Waitlist (3)',   'covers': 3, 'type': 'Waitlist',        'section': 'Bar',     'status': 'waitlisted','notes': None},
        {'time': '8:00 PM',  'party': 'Chen, M.',       'covers': 8, 'type': 'Private Event',   'section': 'Private', 'status': 'confirmed', 'notes': 'Birthday dinner'},
    ],
}

AGENTS_DETAIL = {
    'agency': [
        {'name': 'Client Health Monitor', 'type': 'Monitor',   'status': 'active', 'last_run': '3 min ago',  'tasks': 1284, 'errors': 2,  'uptime': '99.8%', 'desc': 'Continuously scans client engagement, agent uptime, delivery, and payment signals. Raises alerts when health score drops below threshold.'},
        {'name': 'Churn Predictor',       'type': 'Predictor', 'status': 'active', 'last_run': '12 min ago', 'tasks': 892,  'errors': 0,  'uptime': '100%',  'desc': 'Analyzes login frequency, feature usage, and support ticket volume to score churn risk for each client.'},
        {'name': 'Proposal Generator',    'type': 'Generator', 'status': 'active', 'last_run': '1 hr ago',   'tasks': 47,   'errors': 1,  'uptime': '97.9%', 'desc': 'Generates customized AI automation proposals from CRM data including ROI projections, timeline, and pricing tiers.'},
        {'name': 'ROI Reporter',          'type': 'Reporter',  'status': 'active', 'last_run': '2 hrs ago',  'tasks': 216,  'errors': 0,  'uptime': '100%',  'desc': 'Compiles monthly ROI reports per client showing automation hours saved, error rates, and revenue impact.'},
        {'name': 'Email Drafter',         'type': 'Composer',  'status': 'active', 'last_run': '45 min ago', 'tasks': 631,  'errors': 4,  'uptime': '99.4%', 'desc': 'Drafts personalized outreach emails, follow-up sequences, and renewal notices matching client communication history.'},
        {'name': 'Lead Intelligence',     'type': 'Scout',     'status': 'idle',   'last_run': '2 hrs ago',  'tasks': 1847, 'errors': 3,  'uptime': '99.8%', 'desc': 'Scans LinkedIn, Google, and industry directories for new agency leads. Scores by industry, revenue range, and automation readiness.'},
    ],
    'legal': [
        {'name': 'Deadline Sentinel',   'type': 'Monitor',   'status': 'active', 'last_run': '1 min ago',  'tasks': 3241, 'errors': 0,  'uptime': '100%',  'desc': 'Tracks all deadlines across every active matter. Sends escalating alerts at 14d/7d/2d/1d before due date.'},
        {'name': 'Legal Research Agent','type': 'Researcher','status': 'active', 'last_run': '20 min ago', 'tasks': 284,  'errors': 2,  'uptime': '99.3%', 'desc': 'Finds relevant case law, statutes, and precedents from Westlaw and Casetext for active matters.'},
        {'name': 'Motion Drafter',      'type': 'Generator', 'status': 'active', 'last_run': '1 hr ago',   'tasks': 62,   'errors': 1,  'uptime': '98.4%', 'desc': 'Drafts motions, briefs, and oppositions from case notes and prior filings using Claude AI.'},
        {'name': 'Billing Agent',       'type': 'Reporter',  'status': 'active', 'last_run': '3 hrs ago',  'tasks': 748,  'errors': 0,  'uptime': '100%',  'desc': 'Auto-generates invoices from time entries, tracks realization rates, and flags overdue balances.'},
        {'name': 'PACER Monitor',       'type': 'Monitor',   'status': 'active', 'last_run': '30 min ago', 'tasks': 1802, 'errors': 4,  'uptime': '99.8%', 'desc': 'Watches federal dockets for new filings and activity. Sends immediate alerts for case updates.'},
        {'name': 'Email Intelligence',  'type': 'Composer',  'status': 'idle',   'last_run': '15 min ago', 'tasks': 2341, 'errors': 3,  'uptime': '99.9%', 'desc': 'Triages incoming emails by urgency, drafts client responses, and identifies follow-up actions.'},
    ],
    'construction': [
        {'name': 'Permit Watcher',       'type': 'Monitor',   'status': 'active', 'last_run': '5 min ago',  'tasks': 892,  'errors': 0,  'uptime': '100%',  'desc': 'Monitors all permit expiration dates and auto-drafts renewal packages 30 days before expiry.'},
        {'name': 'Budget Watchdog',      'type': 'Analyst',   'status': 'active', 'last_run': '10 min ago', 'tasks': 1204, 'errors': 1,  'uptime': '99.9%', 'desc': 'Monitors budget variance per project. Alerts on threshold breaches and identifies root cause from change orders.'},
        {'name': 'Weather Impact Agent', 'type': 'Monitor',   'status': 'active', 'last_run': '1 hr ago',   'tasks': 486,  'errors': 0,  'uptime': '100%',  'desc': 'Pulls 10-day weather forecast and calculates schedule impact per affected project. Generates revised timelines.'},
        {'name': 'RFI Response Agent',   'type': 'Generator', 'status': 'active', 'last_run': '2 hrs ago',  'tasks': 341,  'errors': 2,  'uptime': '99.4%', 'desc': 'Drafts RFI responses from the project spec library and historical project documentation.'},
        {'name': 'Safety Monitor',       'type': 'Monitor',   'status': 'idle',   'last_run': '5 hrs ago',  'tasks': 2841, 'errors': 0,  'uptime': '100%',  'desc': 'Reviews daily site logs for hazard language and safety incidents. Flags near-misses for OSHA reporting.'},
        {'name': 'Subcontractor Comms',  'type': 'Composer',  'status': 'active', 'last_run': '30 min ago', 'tasks': 1547, 'errors': 5,  'uptime': '99.7%', 'desc': 'Sends daily schedule confirmations and follows up on overdue deliverables from subcontractors.'},
    ],
    'medical': [
        {'name': 'Prior Auth Bot',     'type': 'Workflow',  'status': 'active', 'last_run': '5 min ago',  'tasks': 2341, 'errors': 8,  'uptime': '99.6%', 'desc': 'Submits, tracks, and escalates prior authorization requests across all major payers.'},
        {'name': 'Claim Scrubber',     'type': 'Validator', 'status': 'active', 'last_run': '8 min ago',  'tasks': 4892, 'errors': 12, 'uptime': '99.7%', 'desc': 'Reviews outgoing claims for 47 common denial triggers before submission.'},
        {'name': 'Recall Scheduler',   'type': 'Outreach',  'status': 'active', 'last_run': '20 min ago', 'tasks': 883,  'errors': 1,  'uptime': '99.9%', 'desc': 'Identifies patients overdue for recall appointments and sends personalized SMS/email reminders.'},
        {'name': 'Denial Analyzer',    'type': 'Analyst',   'status': 'active', 'last_run': '1 hr ago',   'tasks': 312,  'errors': 0,  'uptime': '100%',  'desc': 'Categorizes denial patterns by payer and reason code. Drafts appeal letters.'},
        {'name': 'Insurance Verifier', 'type': 'Verifier',  'status': 'active', 'last_run': '1 hr ago',   'tasks': 6741, 'errors': 14, 'uptime': '99.8%', 'desc': 'Confirms active insurance coverage and co-pay amounts for all scheduled appointments 24hrs in advance.'},
        {'name': 'SOAP Notes Agent',   'type': 'Composer',  'status': 'idle',   'last_run': '3 hrs ago',  'tasks': 1208, 'errors': 2,  'uptime': '99.8%', 'desc': 'Generates structured SOAP note drafts from provider voice dictation or clinical prompts.'},
    ],
    'brokerage': [
        {'name': 'Lead Scorer & Router',    'type': 'Analyst',   'status': 'active', 'last_run': '4 min ago',  'tasks': 3812, 'errors': 2,  'uptime': '99.9%', 'desc': 'Scores inbound leads by likelihood to transact and routes to the best-matched agent based on history.'},
        {'name': 'Listing Optimizer',       'type': 'Analyst',   'status': 'active', 'last_run': '30 min ago', 'tasks': 1204, 'errors': 1,  'uptime': '99.9%', 'desc': 'Analyzes listing performance and suggests price adjustments, photo changes, and description rewrites.'},
        {'name': 'Market Analyst',          'type': 'Reporter',  'status': 'active', 'last_run': '2 hrs ago',  'tasks': 641,  'errors': 0,  'uptime': '100%',  'desc': 'Produces weekly market condition reports per zip code distributed automatically to all agents.'},
        {'name': 'Transaction Coordinator', 'type': 'Monitor',   'status': 'active', 'last_run': '10 min ago', 'tasks': 5241, 'errors': 3,  'uptime': '99.9%', 'desc': 'Tracks all contingency deadlines per open transaction. Sends reminders to buyers, sellers, and agents.'},
        {'name': 'Showing Scheduler',       'type': 'Workflow',  'status': 'active', 'last_run': '15 min ago', 'tasks': 2847, 'errors': 6,  'uptime': '99.8%', 'desc': 'Coordinates showing requests between buyer agents, listing agents, and sellers automatically.'},
        {'name': 'CMA Bot',                 'type': 'Generator', 'status': 'idle',   'last_run': '3 hrs ago',  'tasks': 312,  'errors': 0,  'uptime': '100%',  'desc': 'Generates comparative market analyses from MLS data on demand in under 90 seconds.'},
    ],
    'hvac': [
        {'name': 'Dispatch Optimizer',    'type': 'Workflow',  'status': 'active', 'last_run': '2 min ago',  'tasks': 3812, 'errors': 1,  'uptime': '99.9%', 'desc': 'Assigns incoming jobs to the best-available technician by skill, zone, and current load. Re-routes automatically when delays or emergencies occur.'},
        {'name': 'Estimate Generator',    'type': 'Generator', 'status': 'active', 'last_run': '30 min ago', 'tasks': 892,  'errors': 2,  'uptime': '99.8%', 'desc': 'Builds itemized repair and installation estimates from job notes and a live parts/labor rate table. Emails to customer within 5 minutes of tech diagnosis.'},
        {'name': 'Maintenance Reminder',  'type': 'Outreach',  'status': 'active', 'last_run': '1 hr ago',   'tasks': 1241, 'errors': 0,  'uptime': '100%',  'desc': 'Identifies maintenance contract renewals due in the next 30 days and sends a personalized outreach sequence — email, SMS, then call prompt.'},
        {'name': 'Parts Order Monitor',   'type': 'Monitor',   'status': 'active', 'last_run': '15 min ago', 'tasks': 604,  'errors': 3,  'uptime': '99.5%', 'desc': 'Tracks part availability, back-order status, and ETA from suppliers. Alerts when a shortage threatens a scheduled job before the tech departs.'},
        {'name': 'Post-Job Follow-up',    'type': 'Outreach',  'status': 'active', 'last_run': '45 min ago', 'tasks': 2841, 'errors': 0,  'uptime': '100%',  'desc': 'Sends a satisfaction check-in 24hrs after job completion. Escalates complaints to the owner and routes happy customers to Google/Yelp review links.'},
        {'name': 'Invoice & Payment Bot', 'type': 'Workflow',  'status': 'idle',   'last_run': '2 hrs ago',  'tasks': 1847, 'errors': 4,  'uptime': '99.8%', 'desc': 'Auto-generates and emails invoices on job close. Sends payment reminders at 3, 7, and 14 days. Flags unpaid balances for collections follow-up.'},
    ],
    'plumbing': [
        {'name': 'Lead Qualifier',       'type': 'Monitor',   'status': 'active', 'last_run': '1 min ago',  'tasks': 2104, 'errors': 0,  'uptime': '100%',  'desc': 'Triages incoming calls and web inquiries by urgency. Classifies emergency vs. scheduled, extracts job details, and creates a dispatch ticket automatically.'},
        {'name': 'Quote Generator',      'type': 'Generator', 'status': 'active', 'last_run': '20 min ago', 'tasks': 741,  'errors': 1,  'uptime': '99.9%', 'desc': 'Builds flat-rate or time-and-material quotes from job notes and pricing tables. Sends via email with a one-click accept link for fast approval.'},
        {'name': 'Dispatch Scheduler',   'type': 'Workflow',  'status': 'active', 'last_run': '5 min ago',  'tasks': 3241, 'errors': 2,  'uptime': '99.9%', 'desc': 'Assigns jobs to the nearest available plumber by skill and location. Sends ETA SMS to customer and job directions to tech on dispatch.'},
        {'name': 'Invoice Agent',        'type': 'Workflow',  'status': 'active', 'last_run': '1 hr ago',   'tasks': 1882, 'errors': 3,  'uptime': '99.8%', 'desc': 'Generates invoices from completed job details and sends them via email or text. Tracks payment status and sends 3, 7, and 14-day reminders.'},
        {'name': 'Review Request Bot',   'type': 'Outreach',  'status': 'active', 'last_run': '3 hrs ago',  'tasks': 1204, 'errors': 0,  'uptime': '100%',  'desc': 'Triggers a review request 2 hours after a positive job close. Monitors Google, Yelp, and HomeAdvisor for new reviews and alerts on negatives.'},
        {'name': 'Permit Tracker',       'type': 'Monitor',   'status': 'idle',   'last_run': '4 hrs ago',  'tasks': 312,  'errors': 1,  'uptime': '99.7%', 'desc': 'Tracks permit application status for water heaters, repiping, and sewer work. Sends follow-up reminders to city offices and notifies team when approved.'},
    ],
    'restaurant': [
        {'name': 'Reservation Agent',        'type': 'Workflow',  'status': 'active', 'last_run': '3 min ago',   'tasks': 8241, 'errors': 1,  'uptime': '99.9%', 'desc': 'Manages all reservations across OpenTable, phone, and web. Confirms, modifies, and manages the waitlist with zero staff effort.'},
        {'name': 'Inventory Alert Agent',    'type': 'Monitor',   'status': 'active', 'last_run': '10 min ago',  'tasks': 1204, 'errors': 2,  'uptime': '99.8%', 'desc': 'Checks daily inventory against par levels and projected covers. Alerts when items are below threshold and drafts purchase orders automatically.'},
        {'name': 'Review Responder',         'type': 'Composer',  'status': 'active', 'last_run': '30 min ago',  'tasks': 892,  'errors': 0,  'uptime': '100%',  'desc': 'Monitors Google, Yelp, and TripAdvisor for new reviews. Drafts branded responses in 10 minutes — manager approves one click before posting.'},
        {'name': 'Menu Performance Analyst', 'type': 'Analyst',   'status': 'active', 'last_run': '2 hrs ago',   'tasks': 641,  'errors': 0,  'uptime': '100%',  'desc': 'Analyzes POS data to rank menu items by contribution margin and velocity. Flags low-margin or slow-moving items weekly for menu engineering review.'},
        {'name': 'Staff Scheduler',          'type': 'Workflow',  'status': 'active', 'last_run': '1 hr ago',    'tasks': 2841, 'errors': 4,  'uptime': '99.9%', 'desc': 'Builds weekly staff schedules against projected covers and labor budget. Resolves conflicts, distributes schedules, and handles shift swap requests.'},
        {'name': 'Food Cost Monitor',        'type': 'Analyst',   'status': 'idle',   'last_run': '11 PM daily', 'tasks': 1547, 'errors': 0,  'uptime': '100%',  'desc': 'Runs end-of-day food cost reconciliation. Compares actual vs. theoretical cost by item and flags deviation above 1%. Weekly trend reports emailed to GM.'},
    ],
}

LOGS_DATA = {
    'agency': [
        {'ts': '11:08 AM', 'agent': 'Client Health Monitor', 'action': 'Health score updated',   'result': 'success', 'detail': 'Apex Dental → 58 (was 71) — alert triggered',        'ms': 142},
        {'ts': '11:04 AM', 'agent': 'Churn Predictor',       'action': 'Risk score computed',     'result': 'success', 'detail': 'TechStart Inc → 74 (HIGH RISK) — outreach triggered', 'ms': 890},
        {'ts': '10:58 AM', 'agent': 'Email Drafter',         'action': 'Draft created',           'result': 'success', 'detail': 'Churn outreach for TechStart Inc — 3 variants',       'ms': 3200},
        {'ts': '10:45 AM', 'agent': 'Client Health Monitor', 'action': 'Batch scan completed',    'result': 'success', 'detail': '24 clients scanned — 2 alerts raised',               'ms': 4800},
        {'ts': '10:30 AM', 'agent': 'Lead Intelligence',     'action': 'Prospect scan',           'result': 'success', 'detail': '12 new leads found — 3 scored >80',                  'ms': 12400},
        {'ts': '9:30 AM',  'agent': 'Client Health Monitor', 'action': 'Apex Dental agent check', 'result': 'error',   'detail': 'Agent offline since 6:14 AM — alert escalated',       'ms': 210},
        {'ts': '9:00 AM',  'agent': 'Proposal Generator',    'action': 'Proposal generated',      'result': 'success', 'detail': 'Riviera Realty — 3 pages, ROI $28,400/yr',           'ms': 8200},
        {'ts': '8:47 AM',  'agent': 'ROI Reporter',          'action': 'Report compiled',         'result': 'success', 'detail': 'Metro HVAC — April 2026 report ready',               'ms': 5600},
        {'ts': '8:00 AM',  'agent': 'Email Drafter',         'action': 'Weekly check-in batch',   'result': 'success', 'detail': '8 check-ins sent — 2 open, 1 reply received',         'ms': 2800},
        {'ts': '7:00 AM',  'agent': 'Client Health Monitor', 'action': 'Morning scan',            'result': 'success', 'detail': '24 clients — all agents checked',                    'ms': 3900},
    ],
    'legal': [
        {'ts': '11:00 AM', 'agent': 'Deadline Sentinel',    'action': 'SOL alert fired',        'result': 'warning', 'detail': 'Martinez: 4 days to SOL — escalated to partner',     'ms': 88},
        {'ts': '10:30 AM', 'agent': 'PACER Monitor',        'action': 'Docket update',          'result': 'success', 'detail': 'Chen v. Harlow: supplemental exhibit filed',          'ms': 1240},
        {'ts': '10:00 AM', 'agent': 'Motion Drafter',       'action': 'Opposition brief draft', 'result': 'success', 'detail': 'Rivera Securities — 22 pages, ready for review',     'ms': 18400},
        {'ts': '9:30 AM',  'agent': 'Legal Research Agent', 'action': 'Precedent search',       'result': 'success', 'detail': '14 cases found — 4 highly relevant',                 'ms': 8200},
        {'ts': '9:00 AM',  'agent': 'Billing Agent',        'action': 'Invoice generated',      'result': 'success', 'detail': 'Patterson Estate — $4,200 invoice created',          'ms': 1100},
        {'ts': '8:30 AM',  'agent': 'Email Intelligence',   'action': 'Inbox triage',           'result': 'success', 'detail': '12 emails classified — 5 urgent, 4 draft replies',   'ms': 4200},
        {'ts': '8:00 AM',  'agent': 'Deadline Sentinel',    'action': 'Morning scan',           'result': 'success', 'detail': '7 deadlines active — 2 within 7 days',               'ms': 240},
        {'ts': '7:30 AM',  'agent': 'PACER Monitor',        'action': 'Overnight docket check', 'result': 'success', 'detail': '3 docket updates across 2 cases',                    'ms': 3800},
    ],
    'construction': [
        {'ts': '11:00 AM', 'agent': 'Budget Watchdog',      'action': 'Variance alert',         'result': 'warning', 'detail': 'Commerce Park P2: 7.3% — threshold exceeded',         'ms': 420},
        {'ts': '10:30 AM', 'agent': 'Weather Impact Agent', 'action': 'Forecast update',        'result': 'warning', 'detail': 'Rain Mon–Wed: 4 projects need schedule update',        'ms': 2100},
        {'ts': '10:00 AM', 'agent': 'Permit Watcher',       'action': 'Expiry scan',            'result': 'warning', 'detail': 'Lakeshore Condos permit expires May 12',              'ms': 880},
        {'ts': '9:30 AM',  'agent': 'RFI Response Agent',   'action': 'Draft batch',            'result': 'success', 'detail': '12 RFI drafts generated from spec library',          'ms': 14200},
        {'ts': '9:00 AM',  'agent': 'Subcontractor Comms',  'action': 'Daily confirmations',    'result': 'success', 'detail': '14 confirmations sent — 12 ack\'d, 2 pending',       'ms': 3400},
        {'ts': '8:00 AM',  'agent': 'Budget Watchdog',      'action': 'Morning sweep',          'result': 'success', 'detail': '11 projects checked — 1 alert, 10 within variance',  'ms': 5600},
        {'ts': '7:00 AM',  'agent': 'Safety Monitor',       'action': 'Daily log review',       'result': 'success', 'detail': 'All site logs reviewed — no incidents found',         'ms': 2800},
        {'ts': '6:45 AM',  'agent': 'Weather Impact Agent', 'action': 'Overnight forecast pull','result': 'success', 'detail': '10-day forecast retrieved — rain event flagged',      'ms': 1100},
    ],
    'medical': [
        {'ts': '11:10 AM', 'agent': 'Prior Auth Bot',     'action': 'Auth status check',      'result': 'success', 'detail': 'James H. — Aetna response pending (submitted 9 AM)',    'ms': 380},
        {'ts': '11:05 AM', 'agent': 'Claim Scrubber',     'action': 'Pre-submission review',  'result': 'warning', 'detail': 'Claim #88420 — modifier 25 missing — flagged',          'ms': 620},
        {'ts': '10:55 AM', 'agent': 'Insurance Verifier', 'action': 'Schedule verify',        'result': 'success', 'detail': '38 appointments — 36 verified, 2 flagged',              'ms': 4200},
        {'ts': '10:40 AM', 'agent': 'Recall Scheduler',   'action': 'SMS batch sent',         'result': 'success', 'detail': '47 recall patients — 41 SMS delivered, 6 bounced',      'ms': 8900},
        {'ts': '10:20 AM', 'agent': 'Denial Analyzer',    'action': 'Appeal letter drafted',  'result': 'success', 'detail': 'Aetna #88412 — appeal with modifier 25 documentation', 'ms': 5400},
        {'ts': '9:00 AM',  'agent': 'Claim Scrubber',     'action': 'Morning batch review',   'result': 'success', 'detail': '12 claims reviewed — 11 clean, 1 flagged',              'ms': 3800},
        {'ts': '8:15 AM',  'agent': 'Prior Auth Bot',     'action': 'Expiry scan',            'result': 'warning', 'detail': '4 auths expiring within 7 days — alerts sent',          'ms': 720},
        {'ts': '7:00 AM',  'agent': 'Recall Scheduler',   'action': 'Weekly recall scan',     'result': 'success', 'detail': '47 patients identified — campaign queued',              'ms': 6400},
    ],
    'brokerage': [
        {'ts': '11:00 AM', 'agent': 'Lead Scorer & Router',    'action': 'Lead scored',          'result': 'success', 'detail': 'Brad Collins — score 94/100 — routed to S. Mitchell',  'ms': 480},
        {'ts': '10:30 AM', 'agent': 'Transaction Coordinator', 'action': 'Deadline check',       'result': 'warning', 'detail': 'Ridgewood Dr: inspection contingency expires May 5',    'ms': 210},
        {'ts': '10:00 AM', 'agent': 'Listing Optimizer',       'action': 'Performance analysis', 'result': 'success', 'detail': '4821 Oak Trail: 87 DOM — price reduction recommended', 'ms': 3200},
        {'ts': '9:30 AM',  'agent': 'Market Analyst',          'action': 'Weekly report gen',    'result': 'success', 'detail': '8 zip codes analyzed — report sent to 22 agents',      'ms': 8400},
        {'ts': '9:00 AM',  'agent': 'Showing Scheduler',       'action': 'Confirmation batch',   'result': 'success', 'detail': '7 showings confirmed for today',                        'ms': 1200},
        {'ts': '8:30 AM',  'agent': 'Lead Scorer & Router',    'action': 'Morning lead batch',   'result': 'success', 'detail': '14 new leads scored and routed',                        'ms': 4800},
        {'ts': '7:00 AM',  'agent': 'Transaction Coordinator', 'action': 'Daily deadline scan',  'result': 'success', 'detail': '18 transactions checked — 2 deadlines this week',       'ms': 1800},
    ],
    'hvac': [
        {'ts': '10:40 AM', 'agent': 'Dispatch Optimizer',   'action': 'Emergency re-route',      'result': 'success', 'detail': 'Rodriguez emergency — Martinez rerouted, 2 downstream jobs auto-notified', 'ms': 280},
        {'ts': '10:30 AM', 'agent': 'Parts Order Monitor',  'action': 'Back-order alert',        'result': 'warning', 'detail': 'Carrier 38CKC: 3-day back-order — job #249 customer at risk',             'ms': 420},
        {'ts': '10:15 AM', 'agent': 'Dispatch Optimizer',   'action': 'Morning board build',     'result': 'success', 'detail': '28 jobs assigned to 8 techs — 2 overflow jobs to Garcia',                 'ms': 2100},
        {'ts': '9:45 AM',  'agent': 'Estimate Generator',   'action': 'Estimate sent',           'result': 'success', 'detail': 'Harmon Residence — new install $3,800 — customer accepted',               'ms': 4800},
        {'ts': '9:20 AM',  'agent': 'Maintenance Reminder', 'action': 'Outreach batch queued',   'result': 'success', 'detail': '18 renewal notices ready — campaign launches at 1 PM',                    'ms': 1800},
        {'ts': '8:30 AM',  'agent': 'Post-Job Follow-up',   'action': 'Follow-up batch sent',    'result': 'success', 'detail': '11 post-job messages sent — 8 opened, 2 review requests clicked',         'ms': 3200},
        {'ts': '8:00 AM',  'agent': 'Invoice & Payment Bot','action': 'Invoice batch',           'result': 'success', 'detail': '6 invoices generated — $8,400 total outstanding',                         'ms': 2400},
        {'ts': '7:00 AM',  'agent': 'Dispatch Optimizer',   'action': 'Pre-day forecast',        'result': 'success', 'detail': 'Heat advisory: 3× volume expected — overflow protocol armed',             'ms': 1100},
    ],
    'plumbing': [
        {'ts': '10:50 AM', 'agent': 'Dispatch Scheduler',  'action': 'Emergency dispatch',      'result': 'success', 'detail': 'Burst pipe 412 Waverly — Kowalski dispatched, ETA SMS sent to customer',   'ms': 140},
        {'ts': '10:35 AM', 'agent': 'Lead Qualifier',      'action': 'Call triage',             'result': 'success', 'detail': '4 emergency calls processed — 2 dispatched, 2 queued',                     'ms': 880},
        {'ts': '10:00 AM', 'agent': 'Quote Generator',     'action': 'Quote built and sent',    'result': 'success', 'detail': 'Harrington Office re-pipe — $6,400 estimate sent with accept link',         'ms': 3800},
        {'ts': '9:45 AM',  'agent': 'Permit Tracker',      'action': 'Follow-up sent',          'result': 'warning', 'detail': 'Job #39 permit pending 7 days — follow-up email sent to city office',      'ms': 640},
        {'ts': '9:15 AM',  'agent': 'Review Request Bot',  'action': 'Review request sent',     'result': 'success', 'detail': 'Harmon Residence job complete — 5★ review request sent via SMS',           'ms': 820},
        {'ts': '8:30 AM',  'agent': 'Invoice Agent',       'action': 'Invoice batch',           'result': 'success', 'detail': '9 invoices generated — $14,200 pending, 3 paid online',                    'ms': 2800},
        {'ts': '8:00 AM',  'agent': 'Lead Qualifier',      'action': 'Overnight inquiry check', 'result': 'success', 'detail': '6 web inquiries processed — 4 quotes queued, 2 emergency callbacks',       'ms': 1800},
        {'ts': '7:30 AM',  'agent': 'Dispatch Scheduler',  'action': 'Daily board build',       'result': 'success', 'detail': '17 jobs assigned — freeze advisory protocol staged for tomorrow AM',       'ms': 2100},
    ],
    'restaurant': [
        {'ts': '11:05 AM', 'agent': 'Reservation Agent',        'action': 'Lunch confirmation batch',  'result': 'success', 'detail': '112 lunch covers confirmed — 3 SMS reminders sent',                'ms': 2400},
        {'ts': '10:50 AM', 'agent': 'Inventory Alert Agent',    'action': 'Inventory check',           'result': 'warning', 'detail': 'Salmon 30% short, arugula out — 2 POs drafted, chef notified',    'ms': 1200},
        {'ts': '10:30 AM', 'agent': 'Review Responder',         'action': 'Review response drafted',   'result': 'success', 'detail': '3-star Yelp review — response drafted, awaiting GM approval',     'ms': 4200},
        {'ts': '10:00 AM', 'agent': 'Food Cost Monitor',        'action': 'Daily cost report',         'result': 'success', 'detail': 'MTD food cost 28.4% — 0.4% over target — 3 items flagged',         'ms': 3800},
        {'ts': '9:30 AM',  'agent': 'Menu Performance Analyst', 'action': 'Weekly item analysis',      'result': 'success', 'detail': '4 low-margin items flagged — prix fixe recommendation generated',  'ms': 8400},
        {'ts': '9:00 AM',  'agent': 'Staff Scheduler',          'action': 'Conflict resolution',       'result': 'warning', 'detail': 'Next week: 3 shift conflicts — 2 resolved, 1 needs manager input', 'ms': 1800},
        {'ts': '8:00 AM',  'agent': 'Reservation Agent',        'action': 'Overnight bookings',        'result': 'success', 'detail': '14 new reservations confirmed for dinner — 2 waitlisted',          'ms': 3200},
        {'ts': '7:30 AM',  'agent': 'Inventory Alert Agent',    'action': 'Morning delivery check',    'result': 'warning', 'detail': 'Salmon order short — escalated to GM and executive chef',           'ms': 840},
    ],
}

USE_CASES_DATA = {
    'agency': [
        {'icon': '📧', 'title': 'Automated Client Reporting',   'desc': 'Monthly ROI reports compiled and emailed to each client automatically. Zero manual effort.',   'status': 'active',    'category': 'Reporting',
         'roi': 'Eliminates 15–20 hrs/month of manual reporting', 'setup': '2–3 days',
         'requirements': ['API access to each client\'s ad/analytics platforms', 'KPI and metric definitions agreed per client', 'Branded report template approved', 'Email distribution list per client'],
         'integrations': ['Google Analytics & Ads API', 'Meta/Facebook Ads API', 'HubSpot or Salesforce CRM', 'Email delivery platform (SendGrid/Mailchimp)']},
        {'icon': '⚠️', 'title': 'Churn Early Warning System',   'desc': 'Detects disengagement signals 30–45 days before churn. Triggers retention sequences.',        'status': 'active',    'category': 'Retention',
         'roi': 'Saves 1 in 5 at-risk clients before cancellation', 'setup': '2–3 days',
         'requirements': ['Login/session activity data per client account', 'Support ticket volume feed', 'Billing and payment history access', 'Contract renewal dates in CRM'],
         'integrations': ['HubSpot or Salesforce CRM', 'Customer portal / client dashboard', 'Billing system (Stripe or QuickBooks)', 'Email automation platform']},
        {'icon': '📝', 'title': 'AI Proposal Generation',       'desc': 'Generates customized proposals from CRM data in under 60 seconds.',                            'status': 'active',    'category': 'Sales',
         'roi': 'Cut proposal creation from 4 hrs to under 10 min', 'setup': '1–2 days',
         'requirements': ['Service catalog with pricing tiers defined', 'CRM contact and company data populated', 'Past proposal library (5–10 approved examples)', 'Proposal template/brand guide'],
         'integrations': ['HubSpot or Salesforce CRM', 'Google Docs or Notion', 'PandaDoc or Proposify', 'E-signature tool (DocuSign)']},
        {'icon': '📊', 'title': 'Agent Performance Dashboard',  'desc': 'Real-time visibility into every deployed agent uptime, task count, and error rate.',           'status': 'active',    'category': 'Operations',
         'roi': 'Detect outages 2× faster; full portfolio visibility', 'setup': '1 day',
         'requirements': ['Deployed agent API endpoints and credentials', 'Uptime and error log access per agent', 'Task completion metric definitions', 'Alert escalation contacts defined'],
         'integrations': ['Internal agent runtime APIs', 'UptimeRobot or DataDog', 'Slack or email for alerts', 'AIOS agent registry']},
        {'icon': '🔍', 'title': 'Lead Intelligence Scanner',    'desc': 'Scans directories for qualified prospects. Scores and routes to pipeline.',                    'status': 'active',    'category': 'Sales',
         'roi': '3–5 qualified leads per day without manual research', 'setup': '1–2 days',
         'requirements': ['Target industry, geography, and revenue criteria defined', 'ICP (Ideal Customer Profile) documented', 'Lead scoring rubric approved', 'CRM pipeline stage structure ready'],
         'integrations': ['LinkedIn Sales Navigator or Apollo.io', 'ZoomInfo or Clearbit enrichment', 'CRM for lead injection (HubSpot/Salesforce)', 'Email sequence tool']},
        {'icon': '📅', 'title': 'Contract Renewal Reminders',   'desc': 'Alerts 60/30/14 days before renewals. Drafts renewal emails automatically.',                  'status': 'available', 'category': 'Retention',
         'roi': 'Reduce missed renewals to zero; 100% pipeline visibility', 'setup': '1 day',
         'requirements': ['Contract database with start and end dates', 'Client contact info current in CRM', 'Renewal email templates approved', 'Escalation path for non-responsive clients'],
         'integrations': ['CRM (HubSpot/Salesforce)', 'PandaDoc or DocuSign for contract delivery', 'Google Calendar or Outlook for reminders', 'Email automation platform']},
        {'icon': '💬', 'title': 'Client Onboarding Automation', 'desc': 'Guides new clients through setup with automated tasks and welcome sequences.',                 'status': 'available', 'category': 'Operations',
         'roi': 'Reduce onboarding time from 2 weeks to 3 days', 'setup': '2–3 days',
         'requirements': ['Onboarding checklist and workflow documented', 'Client intake form built and tested', 'Welcome email and resource library ready', 'Success milestones and checkpoints defined'],
         'integrations': ['CRM (HubSpot/Salesforce)', 'Monday.com, Asana, or ClickUp', 'Email automation platform', 'Client portal or knowledge base']},
        {'icon': '📈', 'title': 'Upsell Opportunity Detector',  'desc': 'Monitors plan usage and recommends upsell conversations when clients hit capacity.',           'status': 'available', 'category': 'Sales',
         'roi': 'Increase average contract value by 18–25%', 'setup': '2 days',
         'requirements': ['Usage/capacity metrics per client account', 'Plan tier limits and overage rules defined', 'Upsell email and pitch deck templates ready', 'Sales owner per client assigned in CRM'],
         'integrations': ['CRM (HubSpot/Salesforce)', 'Client portal/dashboard data feed', 'Email automation platform', 'Billing system (Stripe/QuickBooks)']},
    ],
    'legal': [
        {'icon': '⏰', 'title': 'Deadline Sentinel',             'desc': 'Never miss a statute of limitations, filing deadline, or response due date.',                 'status': 'active',    'category': 'Compliance',
         'roi': 'Eliminates malpractice risk from missed deadlines', 'setup': '1–2 days',
         'requirements': ['Active matter list with jurisdiction codes', 'Docket and calendar system API or export access', 'Attorney assignment per matter in practice management system', 'Deadline calculation rules per jurisdiction loaded'],
         'integrations': ['Clio, MyCase, or PracticePanther', 'Court-specific deadline calculators (CourtDrive)', 'Outlook or Google Calendar', 'SMS/email alert system']},
        {'icon': '📝', 'title': 'AI Motion Drafting',            'desc': 'Drafts motions and briefs from case notes in minutes, not hours.',                           'status': 'active',    'category': 'Litigation',
         'roi': 'Cut drafting time by 70%; associates handle 40% more matters', 'setup': '2–3 days',
         'requirements': ['Case notes and fact chronology in structured format', 'Jurisdiction-specific motion templates (10–15 examples)', 'Court local rules and formatting requirements loaded', 'Attorney review workflow defined'],
         'integrations': ['Clio or MyCase matter management', 'Westlaw or LexisNexis API', 'Microsoft Word or Google Docs', 'Practice management document storage']},
        {'icon': '🔍', 'title': 'Legal Research Automation',     'desc': 'Finds precedents and statutes across Westlaw and Casetext automatically.',                    'status': 'active',    'category': 'Research',
         'roi': '4-hour research tasks completed in under 45 minutes', 'setup': '1 day',
         'requirements': ['Active Westlaw or LexisNexis credentials with API access', 'Research query templates or issue checklist per practice area', 'Matter-specific jurisdiction list', 'Memo output format/template approved'],
         'integrations': ['Westlaw Edge API or LexisNexis API', 'Clio or MyCase matter management', 'Document management (NetDocuments/iManage)', 'Word/Google Docs for memo output']},
        {'icon': '💰', 'title': 'Automated Billing',             'desc': 'Converts time entries to invoices. Tracks realization rates and collections aging.',         'status': 'active',    'category': 'Billing',
         'roi': '100% billing capture; reduce A/R days by 35%', 'setup': '2 days',
         'requirements': ['Time entry data feed from timekeeping system', 'Billing rate table per attorney, matter type, and client', 'Client billing preferences (LEDES, flat-fee, retainer) configured', 'Invoice approval workflow defined'],
         'integrations': ['Clio, TimeSolv, or Bill4Time', 'QuickBooks or Xero', 'Client payment portal (LawPay)', 'Email delivery for invoice distribution']},
        {'icon': '📡', 'title': 'PACER Docket Monitoring',       'desc': 'Instant alerts on docket activity across all active federal matters.',                       'status': 'active',    'category': 'Litigation',
         'roi': 'Real-time alerts vs. manual PACER checks 1–2×/week', 'setup': '1 day',
         'requirements': ['PACER account credentials with API access', 'List of active federal matter case numbers', 'Attorney and paralegal alert contact list', 'Docket event classification rules (motions, orders, deadlines)'],
         'integrations': ['PACER API or CourtAlert', 'Clio or MyCase for matter linking', 'Email and SMS notification system', 'Outlook or Google Calendar for deadline creation']},
        {'icon': '✉️', 'title': 'Client Communication AI',       'desc': 'Triages incoming client emails and drafts replies maintaining consistent tone.',              'status': 'active',    'category': 'Client Service',
         'roi': 'Saves 3 hrs/day per attorney on email triage', 'setup': '1–2 days',
         'requirements': ['Email account access (read and draft permissions)', 'Active matter-to-client mapping in CRM', 'Communication tone and style guidelines documented', 'Response urgency classification rules defined'],
         'integrations': ['Outlook or Gmail API', 'Clio or MyCase CRM', 'Practice management matter lookup', 'SMS platform for urgent escalations']},
        {'icon': '📋', 'title': 'Conflict Check Automation',     'desc': 'AI-powered conflict search on new matters against all client and opposing party history.',   'status': 'available', 'category': 'Compliance',
         'roi': 'Conflict checks in seconds vs. 30–45 min manual process', 'setup': '2–3 days',
         'requirements': ['Full client and opposing party database export', 'New matter intake form with all party names collected', 'Historical matter archive (minimum 3 years)', 'State ethics rules and conflict standards reference loaded'],
         'integrations': ['Clio or MyCase conflict module', 'CRM contact database', 'State bar ethics database', 'New matter intake form system']},
        {'icon': '📊', 'title': 'Matter Profitability Tracker',  'desc': 'Real-time P&L by matter. Identifies write-off risk before it happens.',                      'status': 'available', 'category': 'Billing',
         'roi': 'Identify unprofitable matters early; improve firm-wide realization rate by 12%', 'setup': '2–3 days',
         'requirements': ['Time and billing data per matter with write-off history', 'Fixed-fee vs. hourly matter type designation', 'Overhead allocation model approved by firm management', 'Profitability threshold alerts defined per practice area'],
         'integrations': ['Clio or TimeSolv billing data', 'QuickBooks or Xero financials', 'Practice management system', 'Reporting dashboard (Power BI or custom)']},
    ],
    'construction': [
        {'icon': '📋', 'title': 'Permit Expiry Automation',      'desc': 'Auto-tracks permit expiry dates and drafts renewal packages 30 days early.',                 'status': 'active',    'category': 'Compliance',
         'roi': 'Eliminates stop-work orders from expired permits', 'setup': '1 day',
         'requirements': ['Active permit list with permit numbers and expiry dates', 'City/county permit portal login credentials per jurisdiction', 'Email and fax contacts at each permit office', 'Renewal document templates per permit type'],
         'integrations': ['Procore or Buildertrend compliance module', 'Email/fax platform', 'County permit portal API or web access', 'Calendar system for renewal milestones']},
        {'icon': '💰', 'title': 'Budget Variance Monitoring',    'desc': 'Monitors budget variance per project. Alerts the moment threshold is crossed.',              'status': 'active',    'category': 'Finance',
         'roi': 'Catch cost overruns 2 weeks earlier than manual review', 'setup': '2–3 days',
         'requirements': ['Project cost codes and budget baseline per project', 'Daily or weekly expense feed from accounting system', 'Variance threshold policy defined per project tier', 'Project manager alert contacts per project'],
         'integrations': ['Sage 300 CRE, Viewpoint, or QuickBooks', 'Procore cost management module', 'Email and SMS alert system', 'Power BI or Procore analytics dashboard']},
        {'icon': '⛅', 'title': 'Weather Schedule Impact',       'desc': 'Pulls 10-day forecasts, calculates project delay impact, generates revised schedules.',       'status': 'active',    'category': 'Operations',
         'roi': 'Reduce weather-related schedule surprises by 80%', 'setup': '1 day',
         'requirements': ['Project schedule with all outdoor activities flagged', 'Site GPS coordinates per active project', 'Crew and equipment calendar access', 'Weather impact thresholds per activity type defined (rain >0.25", wind >25mph, temp <32°F)'],
         'integrations': ['OpenWeatherMap or Weather.gov API', 'Procore or MS Project schedule', 'Email/SMS notification system', 'Google Calendar for revised schedule distribution']},
        {'icon': '📝', 'title': 'Automated RFI Drafting',        'desc': 'Generates RFI responses from spec library, reducing response time from days to hours.',      'status': 'active',    'category': 'Documentation',
         'roi': 'Reduce RFI response time from 3 days to 4 hours', 'setup': '2–3 days',
         'requirements': ['Current project specs and drawings uploaded (PDF format)', 'Historical RFI library with at least 20 resolved examples', 'Architect and engineer contact directory', 'RFI numbering and log system access'],
         'integrations': ['Procore RFI module', 'SharePoint, Dropbox, or Box for drawing storage', 'Email platform for distribution', 'PDF processing and spec parsing']},
        {'icon': '🔧', 'title': 'Subcontractor Coordination',    'desc': 'Daily schedule confirmations, follow-ups on late deliverables, performance scoring.',        'status': 'active',    'category': 'Operations',
         'roi': '90% reduction in missed schedule confirmations', 'setup': '1–2 days',
         'requirements': ['Subcontractor contact list with trade and schedule assignments', 'Baseline project schedule with sub milestones', 'Delivery and milestone log access', 'Performance scoring criteria defined (on-time %, quality, communication)'],
         'integrations': ['Procore or Buildertrend subcontractor module', 'Email and SMS communication system', 'Project scheduling tool (MS Project/Procore)', 'Performance tracking dashboard']},
        {'icon': '⚠️', 'title': 'Safety Incident Monitor',       'desc': 'Reviews site logs for hazard language. Identifies near-misses before they become incidents.', 'status': 'active',    'category': 'Safety',
         'roi': '40% reduction in recordable incidents; OSHA compliance assured', 'setup': '1 day',
         'requirements': ['Daily site log or daily report feed (text or PDF)', 'OSHA hazard language and classification reference loaded', 'Field staff and safety officer alert contacts', 'Incident severity escalation matrix defined'],
         'integrations': ['Procore Daily Logs', 'iAuditor or SafetyCulture', 'Email and SMS alert system', 'OSHA incident reporting system']},
        {'icon': '📊', 'title': 'Change Order Analytics',        'desc': 'Tracks all change orders, approvals, and budget impact across every project.',               'status': 'available', 'category': 'Finance',
         'roi': 'Full change order visibility across all projects in real time', 'setup': '2 days',
         'requirements': ['All executed change orders with approval dates and signatories', 'Original contract value per project', 'Budget cost codes affected by each change order', 'CO approval workflow and authority limits defined'],
         'integrations': ['Procore Change Events module', 'Sage 300 or Viewpoint financials', 'DocuSign for approval tracking', 'Reporting dashboard (Power BI or Procore Analytics)']},
        {'icon': '🗓️', 'title': 'Draw Schedule Tracker',         'desc': 'Monitors payment milestones, tracks amounts drawn, and projects cash flow.',                 'status': 'available', 'category': 'Finance',
         'roi': 'Project cash flow 90 days out with >95% accuracy', 'setup': '2 days',
         'requirements': ['Draw schedule per project with milestone and percentage triggers', 'Lender and owner contact information', 'Payment history log with dates and amounts', 'Retainage and lien waiver requirements per contract'],
         'integrations': ['Procore or Buildertrend draw module', 'Banking or accounting system (Sage/QuickBooks)', 'DocuSign for lien waiver execution', 'Cash flow forecasting dashboard']},
    ],
    'medical': [
        {'icon': '📋', 'title': 'Prior Authorization Automation', 'desc': 'Submits, tracks, and re-submits prior auth requests across all major payers.',             'status': 'active',    'category': 'Revenue Cycle',
         'roi': 'Reduce auth denial rate by 40%; save 2 hrs/day per coordinator', 'setup': '3–5 days',
         'requirements': ['Active payer portal credentials (Availity + payer-specific logins)', 'Diagnosis and procedure codes per patient encounter', 'Provider NPI and group NPI numbers', 'Auth submission criteria per payer and procedure type'],
         'integrations': ['Epic, Athena, or eClinicalWorks EHR', 'Availity and payer-specific portals', 'Practice management system', 'Fax platform for payers without portal access']},
        {'icon': '🔍', 'title': 'Pre-Claim Scrubbing',            'desc': 'Reviews every claim for 47 denial triggers before submission. Reduces denials ~35%.',       'status': 'active',    'category': 'Revenue Cycle',
         'roi': '35% reduction in first-pass denials; accelerated payment cycle', 'setup': '2–3 days',
         'requirements': ['Clearinghouse API credentials (Availity or Change Healthcare)', 'Current CPT and ICD-10 code set with payer-specific edits', 'Payer LCD and NCD coverage policy library', 'Denial reason code mapping from prior 6 months'],
         'integrations': ['Availity or Change Healthcare clearinghouse', 'EHR billing module', 'CMS payer LCD/NCD database', 'Practice management system']},
        {'icon': '📣', 'title': 'Patient Recall Campaign',        'desc': 'Identifies overdue patients and sends personalized reminders with booking links.',           'status': 'active',    'category': 'Patient Engagement',
         'roi': '22% increase in recall appointment bookings', 'setup': '2 days',
         'requirements': ['Patient appointment history in EHR with last-seen dates', 'Preventive and recall schedule defined per service type and patient profile', 'Patient contact preferences (SMS or email opt-in status)', 'Online booking link or scheduling system access'],
         'integrations': ['Epic, Athena, or eClinicalWorks EHR', 'Twilio or Klara for SMS', 'Email marketing platform', 'Online scheduling tool (Zocdoc/Phreesia)']},
        {'icon': '📝', 'title': 'Denial Appeal Generator',        'desc': 'Drafts appeal letters with supporting documentation based on denial reason codes.',         'status': 'active',    'category': 'Revenue Cycle',
         'roi': 'Overturn 45–60% of appealable denials vs. 20% manual average', 'setup': '2–3 days',
         'requirements': ['EOB and remittance data feed with denial reason codes', 'Clinical documentation access for medical necessity support', 'Payer appeal address, fax, and deadline directory', 'Appeal letter templates by denial category (medical necessity, coding, auth)'],
         'integrations': ['EHR for clinical documentation retrieval', 'Practice management or billing system', 'Fax and certified mail platform', 'Clearinghouse for electronic appeal submission']},
        {'icon': '✅', 'title': 'Insurance Pre-Verification',     'desc': 'Confirms coverage and co-pay 24hrs before each appointment.',                               'status': 'active',    'category': 'Operations',
         'roi': 'Eliminate day-of insurance surprises; reduce no-auth denials by 70%', 'setup': '1–2 days',
         'requirements': ['Scheduled appointment feed (minimum 48 hrs in advance)', 'Patient insurance ID and payer information in EHR', 'Eligibility API access or portal credentials', 'Co-pay and deductible communication workflow defined'],
         'integrations': ['Availity or Change Healthcare eligibility API', 'EHR appointment scheduler', 'Patient communication platform (Klara/Luma Health)', 'Practice management system']},
        {'icon': '🩺', 'title': 'SOAP Notes Drafting',            'desc': 'Generates clinical note drafts from voice input. Saves 6–8 minutes per encounter.',        'status': 'active',    'category': 'Clinical',
         'roi': 'Save 6–8 min per encounter; cut documentation backlog by 90%', 'setup': '3–5 days',
         'requirements': ['Voice recording capability or real-time transcription input at point of care', 'Provider-specific SOAP note template per specialty', 'EHR note entry API or direct integration', 'Provider review and sign-off workflow defined'],
         'integrations': ['Epic, Athena, or eClinicalWorks EHR API', 'Nuance DAX or OpenAI Whisper transcription', 'Clinical note template library', 'Provider mobile or desktop interface']},
        {'icon': '📊', 'title': 'A/R Aging Monitor',              'desc': 'Tracks receivables daily. Escalates accounts approaching write-off thresholds.',            'status': 'available', 'category': 'Revenue Cycle',
         'roi': 'Reduce days in A/R from 45 to under 30; recover 15–20% more revenue', 'setup': '1–2 days',
         'requirements': ['Billing system A/R aging report API or scheduled export', 'Write-off threshold policy by payer and amount tier', 'Collection escalation contact list and workflow', 'Payment plan and settlement authority rules defined'],
         'integrations': ['Kareo, AdvancedMD, or Athena billing', 'Collection agency API', 'Email and phone alert system', 'Practice management dashboard']},
        {'icon': '💬', 'title': 'Patient Satisfaction Surveys',   'desc': 'Sends post-visit surveys automatically. Aggregates scores and flags negatives.',           'status': 'available', 'category': 'Patient Engagement',
         'roi': '3× more reviews; flag dissatisfaction before public complaints', 'setup': '1 day',
         'requirements': ['Post-appointment trigger from EHR scheduler (discharge event)', 'Patient contact info with SMS and email consent status', 'Survey questions approved by practice leadership', 'Negative response escalation threshold and routing defined'],
         'integrations': ['EHR appointment scheduler', 'Qualtrics, SurveyMonkey, or Press Ganey', 'Google Business and Healthgrades review prompts', 'Email and SMS delivery platform']},
    ],
    'brokerage': [
        {'icon': '🎯', 'title': 'Lead Scoring & Routing',         'desc': 'Scores inbound leads by conversion likelihood and routes to the best-fit agent.',           'status': 'active',    'category': 'Lead Management',
         'roi': '35% increase in lead-to-showing conversion rate', 'setup': '1–2 days',
         'requirements': ['Inbound lead source API or webhook from all portals', 'Agent profile data (specialty, zip coverage, capacity, conversion history)', 'Lead scoring criteria and ICP defined', 'CRM pipeline stage structure configured'],
         'integrations': ['Follow Up Boss, kvCORE, or BoomTown CRM', 'Zillow Premier Agent, Realtor.com, and website lead capture', 'Twilio or Dialpad for instant lead response', 'MLS for property match alerts']},
        {'icon': '📊', 'title': 'Listing Performance Optimizer',  'desc': 'Analyzes DOM, views, and showings. Recommends price changes and description rewrites.',      'status': 'active',    'category': 'Listings',
         'roi': 'Reduce average DOM by 22%; increase list-price-to-sale ratio', 'setup': '2 days',
         'requirements': ['MLS data API access (showing count, portal views, DOM, saves)', 'Active listing inventory with listing agent assignment', 'Comparable sales data by zip and price band', 'Price reduction approval workflow and agent contact'],
         'integrations': ['NTREIS or local MLS API', 'ShowingTime for showing data', 'CRM for listing management', 'Zillow/Realtor.com listing analytics feed']},
        {'icon': '📈', 'title': 'Market Report Automation',       'desc': 'Weekly market condition reports per zip code, auto-distributed to all agents.',              'status': 'active',    'category': 'Market Intel',
         'roi': 'Agents deliver branded market intel with zero manual prep', 'setup': '1–2 days',
         'requirements': ['MLS data access (sold, active, pending by zip and price range)', 'Agent email distribution list by territory/specialty', 'Report branding template and logo assets', 'Frequency and delivery schedule approved by broker'],
         'integrations': ['MLS data API (NTREIS/CRMLS/MFRMLS)', 'Email marketing platform (Mailchimp/Constant Contact)', 'CRM for audience segmentation', 'PDF generation for client-facing versions']},
        {'icon': '✅', 'title': 'Transaction Deadline Tracking',  'desc': 'Monitors all contingency deadlines. Never miss an inspection or appraisal date.',           'status': 'active',    'category': 'Transactions',
         'roi': 'Zero missed contingency deadlines; eliminate deal-killing errors', 'setup': '1–2 days',
         'requirements': ['Executed purchase contract with all contingency dates extracted', 'Transaction coordinator assignment per file', 'All party contact info (agents, lender, title, TC)', 'Escalation rules for approaching deadlines (72hr, 24hr, same-day alerts)'],
         'integrations': ['DocuSign or Dotloop for contract data extraction', 'Dotloop, SkySlope, or Brokermint TC platform', 'Google Calendar or Outlook for deadline sync', 'Email and SMS notification system']},
        {'icon': '📅', 'title': 'Showing Coordination',           'desc': 'Automates showing requests between all parties. Confirms and reschedules automatically.',   'status': 'active',    'category': 'Operations',
         'roi': '90% of showings confirmed without agent involvement', 'setup': '1 day',
         'requirements': ['Listing access instructions and lockbox codes per property', 'Owner or occupant contact preferences and blackout times', 'Available showing windows per listing in ShowingTime', 'Feedback request templates approved'],
         'integrations': ['ShowingTime API', 'Supra or SentriLock lockbox system', 'CRM for showing log', 'Email and SMS for confirmation and feedback']},
        {'icon': '📝', 'title': 'Listing Description AI',         'desc': 'Generates compelling MLS listing descriptions in under 30 seconds.',                        'status': 'active',    'category': 'Listings',
         'roi': 'Cut listing prep time by 2 hrs; improve search ranking with keyword optimization', 'setup': '1 day',
         'requirements': ['Property data input (beds, baths, sq ft, features, upgrades)', 'Photo set available for visual feature extraction', 'Brand voice and style guide documented', 'MLS character limits and compliance rules by board'],
         'integrations': ['MLS listing entry platform (Matrix/Paragon/Flexmls)', 'Google Drive or Dropbox for photo storage', 'CRM for listing record', 'Listing management tool (Canva for social distribution)']},
        {'icon': '📉', 'title': 'Expired Listing Recovery',       'desc': 'Identifies expired competitor listings as prospecting opportunities.',                       'status': 'available', 'category': 'Lead Management',
         'roi': '2–4 listing appointments per month from automated outreach', 'setup': '2 days',
         'requirements': ['MLS expired listing feed by target zip code and radius', 'Agent capacity list for outreach assignment', 'Expired listing outreach sequence templates (call, text, letter)', 'DNC list cross-reference for compliance'],
         'integrations': ['MLS API with expired filter', 'CRM for prospect tracking (Follow Up Boss/kvCORE)', 'Dialpad or Ring Central for power dialing queue', 'Direct mail platform for letter campaigns']},
        {'icon': '💰', 'title': 'Commission Forecasting',         'desc': 'Projects forward commission revenue from pipeline. Tracks against monthly targets.',        'status': 'available', 'category': 'Finance',
         'roi': '90-day forward revenue visibility; eliminate month-end surprises', 'setup': '2–3 days',
         'requirements': ['Pipeline transaction list with close probability and projected close date', 'Agent roster with commission split schedules per transaction type', 'Monthly and quarterly revenue targets by agent and brokerage', 'Historical close rate by pipeline stage for probability calibration'],
         'integrations': ['CRM pipeline (Follow Up Boss/kvCORE)', 'TC platform for close date confirmation (SkySlope/Dotloop)', 'QuickBooks or accounting system for actuals', 'Reporting dashboard (custom or Power BI)']},
    ],
    'hvac': [
        {'icon': '🚨', 'title': 'Emergency Dispatch Automation',    'desc': 'Triages emergency HVAC calls, assigns the nearest available technician, and notifies the customer — all within 90 seconds.',           'status': 'active',    'category': 'Operations',
         'roi': 'Reduce response time from 15 min to under 3 min; capture every emergency call', 'setup': '1 day',
         'requirements': ['Technician roster with live zone assignment', 'Job type classification rules (emergency vs. scheduled)', 'Customer contact database with SMS opt-in', 'Dispatch software API or manual fallback'],
         'integrations': ['ServiceTitan or Jobber for dispatch', 'Google Maps API for routing', 'Twilio for SMS notifications', 'Phone system (call routing or IVR)']},
        {'icon': '📋', 'title': 'Smart Estimate Generator',          'desc': 'Builds itemized repair and installation estimates from tech job notes in under 5 minutes and emails them to the customer automatically.', 'status': 'active',    'category': 'Sales',
         'roi': 'Close 30% more estimates with same-day delivery; eliminate 1 hr/job in admin', 'setup': '2–3 days',
         'requirements': ['Flat-rate or T&M pricing book', 'Parts and labor cost database', 'Branded estimate template', 'Tech mobile app to submit job notes'],
         'integrations': ['ServiceTitan or Jobber', 'Parts supplier catalog (Carrier, Trane API)', 'Email delivery (SendGrid or Gmail)', 'E-signature for estimate acceptance (DocuSign)']},
        {'icon': '🔄', 'title': 'Maintenance Contract Renewal',      'desc': 'Identifies contracts expiring in 30 days and sends a multi-step personalized outreach campaign — email, SMS, then phone prompt.',         'status': 'active',    'category': 'Retention',
         'roi': 'Recover 25–40% of at-risk renewals; protect $8K–$15K/month in recurring revenue', 'setup': '2 days',
         'requirements': ['Maintenance contract database with renewal dates', 'Customer contact info (email + mobile)', 'Renewal pricing and offer details', 'Outreach sequence templates approved'],
         'integrations': ['ServiceTitan or Jobber for contract records', 'Twilio for SMS outreach', 'Email platform (Mailchimp or SendGrid)', 'CRM for response tracking (HubSpot or Zoho)']},
        {'icon': '🔧', 'title': 'Parts Inventory & Alert System',    'desc': 'Monitors part stock and supplier back-orders. Alerts the team when a shortage threatens a scheduled job before the technician leaves.',  'status': 'available', 'category': 'Procurement',
         'roi': 'Eliminate 70% of same-day part shortages; reduce wasted truck rolls', 'setup': '3–4 days',
         'requirements': ['Parts inventory system or spreadsheet', 'Supplier contact list with lead times', 'Job schedule with required parts per job', 'Reorder level thresholds per SKU'],
         'integrations': ['ServiceTitan parts inventory module', 'Supplier portals (Carrier, Johnstone Supply)', 'Email/SMS for alerts (Twilio + SendGrid)', 'Purchase order generation (QuickBooks)']},
        {'icon': '⭐', 'title': 'Post-Job Follow-up & Reviews',      'desc': 'Sends a satisfaction check-in 24hrs after job close. Routes happy customers to Google/Yelp review links; escalates complaints to the owner.', 'status': 'active',  'category': 'Reputation',
         'roi': '2–5 new 5-star reviews per week; catch issues before they become public', 'setup': '1 day',
         'requirements': ['Completed job list with customer contact info', 'Job completion trigger from dispatch software', 'Google Business Profile and Yelp links', 'Owner mobile for negative response escalation'],
         'integrations': ['ServiceTitan or Jobber for job completion trigger', 'Twilio SMS', 'Google Business Profile API', 'Email delivery platform']},
        {'icon': '🗺️', 'title': 'Technician Route Optimizer',       'desc': 'Calculates the most efficient daily route for each technician given their assigned jobs, traffic, and job duration estimates.',             'status': 'available', 'category': 'Operations',
         'roi': 'Save 45–60 min/tech/day in drive time; fit 1 extra job per tech daily', 'setup': '2 days',
         'requirements': ['Daily job schedule with customer addresses', 'Technician starting location', 'Estimated job duration by job type', 'Mobile app or SMS to deliver optimized route'],
         'integrations': ['Google Maps Routes API or Route4Me', 'ServiceTitan or Jobber job schedule', 'Twilio or email for route delivery to tech', 'GPS fleet tracking (Samsara, optional)']},
        {'icon': '💰', 'title': 'Invoice & Payment Automation',      'desc': 'Auto-generates invoices on job close and sends them via email or text. Tracks payment and sends reminders at 3, 7, and 14 days.',            'status': 'active',    'category': 'Finance',
         'roi': 'Cut average payment time from 18 days to 6 days; zero manual AR follow-up', 'setup': '1–2 days',
         'requirements': ['Job completion trigger from dispatch software', 'Invoice template', 'Payment gateway account (Stripe or Square)', 'Customer email or mobile for delivery'],
         'integrations': ['ServiceTitan or Jobber for job data', 'QuickBooks for accounting sync', 'Stripe or Square for payment', 'Email/SMS for invoice delivery and reminders']},
        {'icon': '📈', 'title': 'Seasonal Demand Forecasting',       'desc': 'Predicts call volume by week for the next 90 days using historical job data and weather forecasts to optimize staffing and parts.',         'status': 'available', 'category': 'Planning',
         'roi': 'Reduce stockouts by 60%; optimize tech staffing to capture peak demand', 'setup': '3–5 days',
         'requirements': ['2+ years of historical job data by type and date', 'Local weather forecast API integration', 'Staffing availability and on-call list', 'Supplier lead times for high-demand parts'],
         'integrations': ['ServiceTitan historical reporting export', 'NOAA or Weather API for local forecasts', 'Google Sheets or BI tool for forecast display', 'Supplier ordering portals']},
    ],
    'plumbing': [
        {'icon': '🚨', 'title': 'Emergency Call Triage',             'desc': 'Classifies incoming calls as emergency or scheduled, extracts job details, and dispatches the nearest plumber within 2 minutes — any time of day.', 'status': 'active',    'category': 'Operations',
         'roi': 'Capture 100% of after-hours emergencies; $800–$2,000 per job vs. missed call', 'setup': '1 day',
         'requirements': ['Plumber on-call schedule with mobile numbers', 'Job type rules (burst pipe, sewer, routine)', 'Customer SMS opt-in or emergency-nature auto-permission', 'Call forwarding or web chat intake form'],
         'integrations': ['Jobber or ServiceTitan for dispatch', 'Twilio for SMS dispatch and ETA', 'Google Maps for nearest-plumber routing', 'Phone system (IVR or forwarding)']},
        {'icon': '📝', 'title': 'Instant Quote Generator',           'desc': 'Builds flat-rate quotes from job descriptions and emails them with a one-click accept link — close jobs the same day they call.',               'status': 'active',    'category': 'Sales',
         'roi': 'Increase quote-to-job conversion by 35%; eliminate 1–2 hrs/day in quote prep', 'setup': '2 days',
         'requirements': ['Flat-rate price book for common job types', 'Parts cost database or supplier price list', 'Branded quote template', 'E-signature or accept link for approval'],
         'integrations': ['Jobber or Housecall Pro for quote delivery', 'Email delivery (Gmail or SendGrid)', 'E-signature (DocuSign or jSign)', 'Accounting sync (QuickBooks)']},
        {'icon': '🔔', 'title': 'Customer ETA & Status Alerts',      'desc': 'Automatically texts the customer when the plumber is dispatched (with ETA), when they are 10 minutes away, and when the job is complete.',      'status': 'active',    'category': 'Customer Service',
         'roi': 'Eliminate 80% of "where is my plumber?" calls; increase 5-star review rate by 40%', 'setup': '1 day',
         'requirements': ['Dispatch software with job status updates', 'Customer mobile number', 'SMS templates for each status milestone', 'Job completion trigger from tech mobile app'],
         'integrations': ['Jobber or ServiceTitan for job status', 'Twilio SMS', 'Google Maps ETA API', 'CRM for customer contact management']},
        {'icon': '📋', 'title': 'Permit Application & Tracking',     'desc': 'Prepares permit application documents from job details and tracks approval status with city offices — follow-ups sent automatically.',         'status': 'available', 'category': 'Compliance',
         'roi': 'Reduce permit turnaround by 3–5 days; eliminate manual follow-up calls to city', 'setup': '3–4 days',
         'requirements': ['Job details: scope, address, materials, license number', 'City permit portal login or API access', 'Standard permit forms by work type', 'Notification contact list (tech, customer, office)'],
         'integrations': ['City permit portal (varies by municipality)', 'DocuSign for signed permit applications', 'Email/SMS for status notifications', 'Job management software for permit linking']},
        {'icon': '⭐', 'title': 'Review Collection Automation',      'desc': 'Triggers a review request via SMS 2 hours after positive job close. Monitors Google, Yelp, and HomeAdvisor for new reviews.',                 'status': 'active',    'category': 'Reputation',
         'roi': '4–8 new 5-star reviews per week; real-time negative review alerts within 30 minutes', 'setup': '1 day',
         'requirements': ['Job completion trigger from dispatch software', 'Customer mobile number', 'Google Business Profile and Yelp review links', 'Owner mobile for negative review escalation'],
         'integrations': ['Jobber or ServiceTitan for job close trigger', 'Twilio SMS', 'Google Business Profile API', 'Yelp Business API (or web monitoring)']},
        {'icon': '💰', 'title': 'Invoice & Payment Automation',      'desc': 'Generates invoices immediately on job close and delivers them via email or text with a payment link. Automatic reminders at 3, 7, and 14 days.', 'status': 'active',    'category': 'Finance',
         'roi': 'Cut average collection time from 21 days to 5 days; zero AR manual follow-up', 'setup': '1–2 days',
         'requirements': ['Job completion trigger and pricing from dispatch software', 'Payment gateway (Stripe or Square)', 'Invoice template with company branding', 'Customer email or mobile for delivery'],
         'integrations': ['Jobber or Housecall Pro for job data', 'Stripe or Square for payment', 'QuickBooks for accounting sync', 'Email/SMS for delivery and reminders']},
        {'icon': '📊', 'title': 'Job Profitability Tracker',        'desc': 'Calculates actual vs. estimated profit per job type, technician, and season — identifies where money is made and where it leaks.',              'status': 'available', 'category': 'Finance',
         'roi': 'Identify top and bottom 20% of job types; increase overall margin by 4–8%', 'setup': '3–4 days',
         'requirements': ['Job cost data: labor hours, parts used, technician rate', 'Invoice amount per completed job', 'Job type and technician categorization', 'Minimum 3 months of historical job data'],
         'integrations': ['Jobber or ServiceTitan reporting export', 'QuickBooks for actual costs', 'Google Sheets or Power BI for profitability dashboard', 'Email for weekly margin report']},
        {'icon': '📣', 'title': 'Referral & Loyalty Program',       'desc': 'Identifies happy customers (5-star reviews or repeat jobs) and enrolls them in an automated referral reward program with tracked codes.',     'status': 'available', 'category': 'Marketing',
         'roi': '15–25% of new jobs from referrals; $0 ad cost per referral job', 'setup': '3 days',
         'requirements': ['Customer database with job history', 'Referral code generation and tracking system', 'Reward fulfillment method (bill credit, gift card)', 'Email or SMS referral invite templates approved'],
         'integrations': ['Jobber or Housecall Pro CRM', 'Email platform (Mailchimp or Klaviyo)', 'Referral tracking (ReferralHero or custom)', 'Twilio SMS for referral invites']},
    ],
    'restaurant': [
        {'icon': '📅', 'title': 'Reservation Management Agent',     'desc': 'Handles reservations across phone, OpenTable, and web simultaneously. Confirms, modifies, and manages the waitlist with zero staff effort.',   'status': 'active',    'category': 'Front of House',
         'roi': 'Handle 100% of reservation requests with 0 extra staff; reduce no-shows by 30%', 'setup': '1–2 days',
         'requirements': ['OpenTable or Resy account credentials', 'Reservation policy (party sizes, time slots, blackout dates)', 'Customer phone number for confirmation SMS', 'VIP and special occasion handling rules'],
         'integrations': ['OpenTable or Resy API', 'Twilio for SMS confirmations and reminders', 'Google Business Profile for reservation link', 'Restaurant management system (Toast or Aloha)']},
        {'icon': '📦', 'title': 'Inventory Alert & Auto-Order',     'desc': 'Checks daily inventory against par levels and projected covers. Drafts purchase orders for items below threshold before the AM delivery window.', 'status': 'active',    'category': 'Back of House',
         'roi': "Eliminate 85% of 86'd items; reduce over-ordering waste by $800–$2,000/month", 'setup': '2–3 days',
         'requirements': ['Current par levels for all inventory items', 'Projected covers by daypart for the next 3 days', 'Supplier contact list and order portals/emails', 'Inventory log from POS end-of-day reports'],
         'integrations': ['Toast or Square POS for sales depletion data', 'Sysco, US Foods, or local supplier order portals', 'Email for automated PO delivery', 'Google Sheets or restaurant management system']},
        {'icon': '⭐', 'title': 'Review Response Automation',       'desc': 'Monitors Google, Yelp, and TripAdvisor for new reviews. Drafts branded responses in 10 minutes — manager approves one click before posting.',   'status': 'active',    'category': 'Reputation',
         'roi': 'Respond to 100% of reviews within 24 hrs; 22% increase in new bookings from review activity', 'setup': '1 day',
         'requirements': ['Google Business Profile and Yelp business account access', 'Brand voice guide and response tone approved', 'Manager email or mobile for draft approval notifications', 'Escalation rules for severe complaints'],
         'integrations': ['Google Business Profile API', 'Yelp Business API', 'TripAdvisor management portal', 'Email or Slack for draft approval workflow']},
        {'icon': '📊', 'title': 'Menu Performance & Engineering',   'desc': 'Analyzes POS sales by item — margin, velocity, and contribution. Flags underperformers and generates a weekly recommendations report.',         'status': 'active',    'category': 'Revenue',
         'roi': 'Increase overall menu margin by 2–4%; reduce food cost variance below 0.5%', 'setup': '2 days',
         'requirements': ['POS sales data by menu item with revenue and quantity', 'Recipe costing data (ingredients + labor)', 'Menu categorization (appetizer, entree, dessert)', 'Chef and GM email for weekly report'],
         'integrations': ['Toast, Square, or Lightspeed POS API', 'Recipe management platform (MarketMan or Compeat)', 'Google Sheets or Power BI for dashboard', 'Email for weekly report distribution']},
        {'icon': '👥', 'title': 'Smart Staff Scheduling',            'desc': 'Builds weekly schedules from projected covers and labor budget. Resolves conflicts, distributes via app or SMS, and manages shift swaps.',       'status': 'active',    'category': 'Labor',
         'roi': 'Reduce scheduling time from 3 hrs to 20 min; keep labor cost within 28–32% of revenue', 'setup': '2–3 days',
         'requirements': ['Staff roster with availability preferences and roles', 'Projected covers by day and daypart for the week', 'Labor budget as % of projected revenue', 'Shift swap approval rules and escalation contacts'],
         'integrations': ['7shifts, HotSchedules, or Deputy for schedule distribution', 'POS for projected covers data (Toast or Square)', 'Twilio SMS for schedule notifications', 'Payroll system sync (Gusto or ADP)']},
        {'icon': '💰', 'title': 'Food Cost Monitoring',             'desc': 'Runs end-of-day food cost reconciliation against theoretical cost. Flags deviations above 1% per item and sends a daily cost report to the GM.', 'status': 'available', 'category': 'Finance',
         'roi': 'Catch variances within 24 hrs instead of weekly; save $1,500–$4,000/month in undetected waste', 'setup': '3 days',
         'requirements': ['POS sales data with item quantities sold', 'Recipe cost cards with ingredient weights and costs', 'Daily inventory count method (physical or POS depletion)', 'GM email for daily cost report'],
         'integrations': ['Toast or Square POS for sales data', 'MarketMan or Compeat for theoretical cost', 'Supplier invoices for actual cost (email parsing)', 'Restaurant management system dashboard']},
        {'icon': '🎉', 'title': 'Private Event & Catering Pipeline', 'desc': 'Qualifies private dining and catering inquiries, sends a customized proposal in under 1 hour, and tracks follow-up through close.',           'status': 'available', 'category': 'Revenue',
         'roi': '2–4 private events per month from faster follow-up; avg $3,000–$8,000 per event', 'setup': '2 days',
         'requirements': ['Private event menu and pricing packages', 'Availability calendar for private dining space', 'Event inquiry intake form (web or phone)', 'Contract and deposit terms approved'],
         'integrations': ['OpenTable or Tripleseat for event CRM', 'DocuSign for event contract signing', 'Email/SMS for inquiry follow-up automation', 'Stripe for deposit collection']},
        {'icon': '📣', 'title': 'Guest Loyalty & Re-engagement',    'desc': 'Identifies lapsed guests from POS data and sends personalized re-engagement offers. Tracks redemption and feeds back into the reservation system.', 'status': 'available', 'category': 'Marketing',
         'roi': '15–20% of lapsed guests return within 30 days; $40–$80 recovered revenue per guest', 'setup': '2–3 days',
         'requirements': ['Guest contact database from POS or reservation system', 'Lapsed guest definition (60, 90, 180 days since last visit)', 'Offer or incentive approved (complimentary appetizer, birthday offer)', 'Email or SMS marketing opt-in consent'],
         'integrations': ['Toast, Square, or Lightspeed POS for guest visit data', 'OpenTable or Resy for reservation history', 'Mailchimp or Klaviyo for email campaigns', 'Twilio SMS for text re-engagement']},
    ],
}

EMAILS_DATA = {
    'agency': [
        {'id':1, 'from': 'Sarah Mitchell',  'company': 'Apex Dental',    'subject': 'Automation stopped working again',    'preview': 'Hi, our booking bot has been offline since 6 AM and we have 14 patients scheduled...',  'time': '8:14 AM',   'priority': 'urgent',      'ai_action': 'Open support ticket', 'read': False},
        {'id':2, 'from': 'John Kowalski',   'company': 'Riviera Realty', 'subject': 'Re: Proposal — a few questions',      'preview': 'Thanks for sending this. I had a few questions about the implementation timeline...',    'time': '7:52 AM',   'priority': 'respond',     'ai_action': 'Draft reply',         'read': False},
        {'id':3, 'from': 'Mike Torres',     'company': 'Metro HVAC',     'subject': 'ROI report — looks great!',           'preview': 'Team loved the numbers. Can we get one of these monthly going forward?...',             'time': '7:30 AM',   'priority': 'low',         'ai_action': 'Log + reply',         'read': False},
        {'id':4, 'from': 'Dana Patel',      'company': 'TechStart Inc',  'subject': 'Quick question about our plan',       'preview': "We haven't been using the dashboard much lately. Is there a simpler option?...",        'time': 'Yesterday', 'priority': 'respond',     'ai_action': 'Retention call offer','read': True},
        {'id':5, 'from': 'Greg Anderson',   'company': 'LakeView Law',   'subject': 'Capacity warning — 80% of plan used', 'preview': 'Just got the notification. What does upgrading to Enterprise look like?...',            'time': 'Yesterday', 'priority': 'opportunity', 'ai_action': 'Send upgrade deck',   'read': True},
        {'id':6, 'from': 'New Lead',        'company': 'Harbor Fitness', 'subject': 'Inquiry: AI automation for our gyms', 'preview': 'Hi, I found you through a referral. We operate 6 locations and are looking...',         'time': 'Apr 28',    'priority': 'respond',     'ai_action': 'Discovery call email','read': True},
    ],
    'legal': [
        {'id':1, 'from': 'Client: J. Martinez',     'company': 'Martinez',     'subject': 'Update on my case — very worried',      'preview': 'Hi Jordan, I keep thinking about the deadline. Can we please talk today?...',        'time': '9:02 AM',   'priority': 'urgent',      'ai_action': 'Call client today',   'read': False},
        {'id':2, 'from': 'Opposing Counsel',         'company': 'Harlow LLC',   'subject': 'Chen v. Harlow — discovery responses',  'preview': 'Please find attached our responses to your first set of interrogatories...',        'time': '8:30 AM',   'priority': 'respond',     'ai_action': 'Review + calendar',  'read': False},
        {'id':3, 'from': 'PACER Notification',       'company': 'Federal Court','subject': 'New docket activity — Case 24-cv-1184', 'preview': 'A new filing has been entered in the above-captioned matter...',                   'time': '7:45 AM',   'priority': 'respond',     'ai_action': 'Review docket entry', 'read': False},
        {'id':4, 'from': 'Client: M. Rivera',        'company': 'Rivera',       'subject': 'Securities case — positive news?',      'preview': 'I heard from a colleague that there was a ruling in our favor...',                  'time': 'Yesterday', 'priority': 'respond',     'ai_action': 'Draft update letter', 'read': True},
        {'id':5, 'from': 'Billing Dept',             'company': 'Internal',     'subject': 'Overdue A/R — 6 clients, $18,400',      'preview': 'The following matters have balances over 90 days outstanding...',                  'time': 'Yesterday', 'priority': 'low',         'ai_action': 'Send collection notice','read': True},
        {'id':6, 'from': 'New Consult Request',      'company': 'Patterson LLC','subject': 'Employment matter — referral from Kim', 'preview': 'Hi, Kim at Summit Dental referred me. I have a wrongful termination situation...',  'time': 'Apr 28',    'priority': 'respond',     'ai_action': 'Schedule consult',    'read': True},
    ],
    'construction': [
        {'id':1, 'from': 'City Permit Office',   'company': 'City of Dallas', 'subject': 'Permit P-2024-8841 — renewal required',   'preview': 'Your commercial building permit for Lakeshore Condos is due to expire...',         'time': '8:45 AM',   'priority': 'urgent',      'ai_action': 'Initiate renewal package','read': False},
        {'id':2, 'from': 'Project Owner',        'company': 'Commerce Park',  'subject': 'Budget concern — need explanation',       'preview': 'We noticed the variance is now over 7%. Can we schedule a call to review...',       'time': '8:15 AM',   'priority': 'urgent',      'ai_action': 'Schedule review call',    'read': False},
        {'id':3, 'from': 'Harmon Carpentry',     'company': 'Sub - Framing',  'subject': 'Block C delay — material shortage',       'preview': 'Just wanted to give you a heads up that our lumber delivery is delayed...',         'time': '7:30 AM',   'priority': 'respond',     'ai_action': 'Update schedule + RFI',   'read': False},
        {'id':4, 'from': 'Architect - Rivera',   'company': 'Rivera Design',  'subject': 'RFI #118 — clarification needed',         'preview': 'We need additional information before we can provide a response to RFI #118...',   'time': 'Yesterday', 'priority': 'respond',     'ai_action': 'Request escalation',     'read': True},
        {'id':5, 'from': 'OSHA Compliance',      'company': 'OSHA',           'subject': 'New fall protection standards — July 2026','preview': 'Please be advised that updated fall protection requirements take effect...',       'time': 'Yesterday', 'priority': 'low',         'ai_action': 'Schedule safety training','read': True},
        {'id':6, 'from': 'Insurance Broker',     'company': 'AmTrust',        'subject': 'GL insurance renewal — due June 1',       'preview': 'Your general liability policy comes up for renewal on June 1, 2026...',            'time': 'Apr 28',    'priority': 'low',         'ai_action': 'Log + remind May 15',    'read': True},
    ],
    'medical': [
        {'id':1, 'from': 'Aetna Provider Relations','company': 'Aetna',     'subject': 'Claim #88412 — Action Required',          'preview': 'Your claim has been denied. Reason: Missing modifier 25. To appeal...',          'time': '8:30 AM',   'priority': 'urgent',      'ai_action': 'Review denial + appeal', 'read': False},
        {'id':2, 'from': 'James Henderson',          'company': 'Patient',  'subject': 'Prior auth question — appointment',       'preview': "Hi Dr. Chen's office, I got a message that my auth might expire...",             'time': '8:05 AM',   'priority': 'urgent',      'ai_action': 'Call patient today',     'read': False},
        {'id':3, 'from': 'Quest Diagnostics',        'company': 'Lab',      'subject': 'Lab results uploaded — 4 patients',       'preview': 'Results for Garcia M., Torres L., Park S., Adams A. are now available...',      'time': '7:48 AM',   'priority': 'respond',     'ai_action': 'Flag for providers',     'read': False},
        {'id':4, 'from': 'Blue Cross Provider',      'company': 'BCBS',     'subject': 'Credentialing renewal — Dr. Torres',      'preview': "Dr. Torres' credentialing renewal is due May 15, 2026...",                     'time': 'Yesterday', 'priority': 'respond',     'ai_action': 'Submit renewal docs',    'read': True},
        {'id':5, 'from': 'Maria Garcia',             'company': 'Patient',  'subject': 'Thank you — excellent care today',        'preview': 'I just wanted to say how much I appreciated the team...',                       'time': 'Yesterday', 'priority': 'low',         'ai_action': 'Send review request',    'read': True},
        {'id':6, 'from': 'Medicare Admin',           'company': 'Medicare', 'subject': 'Telehealth billing code update',          'preview': 'Please review the updated billing codes for telehealth services effective...',  'time': 'Apr 28',    'priority': 'low',         'ai_action': 'Update billing templates','read': True},
    ],
    'brokerage': [
        {'id':1, 'from': 'Brad Collins',      'company': 'Buyer Lead',   'subject': 'Interested in properties — pre-approved $750K', 'preview': 'Hi, I was referred by a colleague. I have pre-approval and am ready to move...',    'time': '9:15 AM',   'priority': 'urgent',      'ai_action': 'Assign agent + schedule',  'read': False},
        {'id':2, 'from': 'Client: Martinez',  'company': 'Seller',       'subject': 'Any offers on Oak Street yet?',                 'preview': 'It has been 11 showings now and no offers. I am getting worried about...',          'time': '8:40 AM',   'priority': 'respond',     'ai_action': 'Send price reduction CMA',  'read': False},
        {'id':3, 'from': 'Buyer Agent - Kim', 'company': 'Allied RE',    'subject': 'Offer on 2200 Ridgewood Dr',                    'preview': 'Please find attached an offer for your listing at the above address...',             'time': '8:00 AM',   'priority': 'respond',     'ai_action': 'Log offer + notify seller', 'read': False},
        {'id':4, 'from': 'MLS Alert',         'company': 'NTREIS MLS',   'subject': 'Price reduction: competitor listing nearby',    'preview': 'A comparable listing at 2318 Ridgewood has reduced price by $25,000...',            'time': 'Yesterday', 'priority': 'low',         'ai_action': 'Flag for agent awareness',  'read': True},
        {'id':5, 'from': 'Kim Tran',          'company': 'Agent - Internal', 'subject': 'Struggling with leads — need support',     'preview': 'Hi Dana, I am having trouble converting leads lately. Can we chat about...',        'time': 'Yesterday', 'priority': 'respond',     'ai_action': 'Schedule coaching session', 'read': True},
        {'id':6, 'from': 'Title Company',     'company': 'First American','subject': 'Closing scheduled — 301 Maple Grove',          'preview': 'This confirms the closing for 301 Maple Grove is set for May 15 at 10AM...',         'time': 'Apr 28',    'priority': 'low',         'ai_action': 'Log + notify agent',        'read': True},
    ],
    'hvac': [
        {'id':1, 'from': 'Rodriguez, M.',      'company': 'Emergency Customer',   'subject': 'AC completely down — 88 degrees inside',      'preview': 'Hi, I called and left a message. Our AC has been out since 6 AM and it is extremely hot...',       'time': '9:45 AM',   'priority': 'urgent',      'ai_action': 'Dispatched — confirm ETA',   'read': False},
        {'id':2, 'from': 'Harmon, B.',         'company': 'Residential Customer', 'subject': 'Install quote accepted — when can you start?', 'preview': 'Team, we approved the $3,800 estimate. When is your earliest availability for the install?...',   'time': '9:30 AM',   'priority': 'respond',     'ai_action': 'Schedule install date',      'read': False},
        {'id':3, 'from': 'Parts Supplier',     'company': 'Johnstone Supply',     'subject': 'Your order #4412 — back-order update',        'preview': 'This is an update on your Carrier 38CKC order. Current ETA is now May 4 due to supply...',       'time': '8:30 AM',   'priority': 'respond',     'ai_action': 'Find alternative supplier',  'read': False},
        {'id':4, 'from': 'Metro HVAC Mgmt.',   'company': 'Service Contract',     'subject': 'Annual maintenance contract renewal',         'preview': 'Hi, our service contract is up in June. Can you send renewal pricing and any new options?...',    'time': 'Yesterday', 'priority': 'opportunity', 'ai_action': 'Send renewal proposal',      'read': True},
        {'id':5, 'from': 'Google Alerts',      'company': 'Review Monitor',       'subject': 'New 2-star Google review posted',             'preview': 'A customer left a 2-star review: "Technician was rude and left the area dirty..."...',           'time': 'Yesterday', 'priority': 'respond',     'ai_action': 'Draft response + escalate',  'read': True},
        {'id':6, 'from': 'New Inquiry',        'company': 'Commercial Prospect',  'subject': 'HVAC service contract — 8 units, 2 locations', 'preview': 'Hi, we manage two office buildings with 8 HVAC units. We are looking for a service partner...',  'time': 'Apr 28',    'priority': 'opportunity', 'ai_action': 'Send commercial package',    'read': True},
    ],
    'plumbing': [
        {'id':1, 'from': 'Customer — 412 Waverly', 'company': 'Emergency Call',    'subject': 'EMERGENCY — water flooding my hallway',       'preview': 'There is water coming from under our hallway. We cannot find the shutoff. Please help...',       'time': '10:40 AM',  'priority': 'urgent',      'ai_action': 'Dispatched — ETA 20 min',    'read': False},
        {'id':2, 'from': 'Riverdale Comml. Mgmt', 'company': 'Quote Follow-up',   'subject': 'Re: Quote #44 — we have a few questions',     'preview': 'Thanks for sending the quote. Before we approve the $8,200 we wanted to ask about timeline...',  'time': '9:00 AM',   'priority': 'respond',     'ai_action': 'Call to clarify + close',    'read': False},
        {'id':3, 'from': 'City Permit Office',    'company': 'City of Riverside', 'subject': 'Permit P-PLB-4491 — additional docs needed',  'preview': 'Your water heater permit application is incomplete. Please provide the following items...',      'time': '8:30 AM',   'priority': 'respond',     'ai_action': 'Submit missing docs today',  'read': False},
        {'id':4, 'from': 'Harmon Residence',      'company': 'Completed Job',     'subject': '5-star review left — thank you!',             'preview': 'Hi Dave, just left you a 5-star review on Google. Murphy did an incredible job on the...',       'time': 'Yesterday', 'priority': 'low',         'ai_action': 'Thank you reply',            'read': True},
        {'id':5, 'from': 'Supplier — Ferguson',   'company': 'Parts Supply',      'subject': 'Copper price increase — effective June 1',    'preview': 'We are writing to inform you that copper fittings and piping will increase 12% starting...',     'time': 'Yesterday', 'priority': 'low',         'ai_action': 'Update price book + order',  'read': True},
        {'id':6, 'from': 'New Lead',              'company': 'Harrington Mgmt.',  'subject': 'Commercial re-pipe — 4-story building',       'preview': 'Hi, we manage an older building and need a full re-pipe quote. About 40 units total...',          'time': 'Apr 28',    'priority': 'respond',     'ai_action': 'Schedule site assessment',   'read': True},
    ],
    'restaurant': [
        {'id':1, 'from': 'TechCorp — Events',   'company': 'Private Dining',    'subject': 'Private event inquiry — 40 guests, May 18',   'preview': 'Hi, I am the event coordinator at TechCorp. We would like to host a client dinner for 40...',   'time': '9:15 AM',   'priority': 'opportunity', 'ai_action': 'Send event proposal',          'read': False},
        {'id':2, 'from': 'Sysco Distribution',  'company': 'Food Supplier',     'subject': 'Delivery adjustment — salmon allocation cut', 'preview': 'Due to current supply constraints, your salmon allocation has been reduced by 30% for...',       'time': '8:45 AM',   'priority': 'urgent',      'ai_action': 'Source alternate + alert chef','read': False},
        {'id':3, 'from': 'Yelp Notification',   'company': 'Review Alert',      'subject': '3-star review posted — response needed',      'preview': 'A guest left a 3-star review: "Food was good but wait time was completely unacceptable..."...',  'time': '8:00 AM',   'priority': 'respond',     'ai_action': 'Draft response for approval',  'read': False},
        {'id':4, 'from': 'Wilson, J.',          'company': 'Reservation',       'subject': 'Anniversary dinner — special request',        'preview': 'We have a reservation tonight at 6 PM. Could you arrange champagne on arrival for my wife...',   'time': 'Yesterday', 'priority': 'respond',     'ai_action': 'Confirm + note for FOH',       'read': True},
        {'id':5, 'from': 'State Dept. of Labor','company': 'Compliance',        'subject': 'Minimum wage increase — effective July 1',    'preview': 'This is official notice that the state minimum wage will increase to $15.50 on July 1...',       'time': 'Yesterday', 'priority': 'low',         'ai_action': 'Update labor cost models',     'read': True},
        {'id':6, 'from': 'Google Alerts',       'company': 'Review Monitor',    'subject': 'New 5-star Google review posted',             'preview': 'Your restaurant received a new 5-star review: "Best pasta I have had in years..."...',           'time': 'Apr 28',    'priority': 'low',         'ai_action': 'Respond + share with team',    'read': True},
    ],
}

# ── User Guide Content ───────────────────────────────────────────────────────
GUIDE_CONTENT = {
    'agency': {
        'headline': 'AIOS — AI Automation Agency Command Center',
        'tagline': 'Manage every client account, agent deployment, and MRR signal from one AI-powered platform.',
        'quick_start': [
            'Connect your CRM (HubSpot or Salesforce) via Settings → Integrations',
            'Import your client roster via Data Import → upload CSV (firm name, contact, MRR tier)',
            'Open the Dashboard → review the Client Health Scorecard and AI Actions panel',
            'Run your first Daily Brief — AI generates a morning summary of all client signals at 7 AM',
            'Open Agent Overview — confirm all 6 agents show green / active status',
            'Send your first AI-drafted check-in email from Email Intelligence → Draft Reply',
        ],
        'sections': [
            {'icon': '◎', 'title': 'Dashboard',      'tips': [
                'AI Actions panel — check this first each morning; items are ranked by urgency',
                'Client Health Scorecard — red/amber dots identify clients needing attention today',
                'Goals & Pipeline bar — tracks MRR progress against month target in real time',
                'Agent Status widget — all 6 agents should show active; investigate any idle agents',
            ]},
            {'icon': '≡', 'title': 'Daily Brief',    'tips': [
                'Auto-generated at 7 AM from overnight agent activity — no manual steps needed',
                'Highlights surface wins, risks, and alerts in urgency order',
                'Metrics block shows MRR, client count, uptime, and open proposals day-over-day',
                'Connect Google Calendar via Integrations to populate the Calendar section automatically',
            ]},
            {'icon': '⬡', 'title': 'Client Pipeline','tips': [
                'Use stage filters (Active, At Risk, Onboarding) to focus your day',
                'Health Score below 60 triggers automatic churn outreach from the Churn Predictor',
                'Next Action and Due columns are agent-populated — review and override any as needed',
                'Import new clients via Data Import or sync automatically from your connected CRM',
            ]},
            {'icon': '✉', 'title': 'Email Intelligence','tips': [
                'AI Action column shows the recommended next step for every message',
                'Click "Draft Reply" to have the Email Drafter compose a response in seconds',
                '"Retention call offer" items should be actioned within 24 hours to prevent churn',
                'Opportunity badges (green) represent upsell moments — prioritize same-day response',
            ]},
            {'icon': '◷', 'title': 'Integrations',   'tips': [
                'Connect HubSpot or Salesforce first — it powers the Client Health Monitor',
                'Google Analytics + Meta Ads APIs enable automated ROI report generation per client',
                'SendGrid or Mailchimp is required for Email Drafter agent outbound delivery',
                'All credentials are AES-256 encrypted at rest — safe to store API keys here',
            ]},
        ],
        'faqs': [
            {'q': 'How do I add a new client?', 'a': 'Use Data Import to upload a client CSV, or sync automatically from HubSpot/Salesforce once connected. Each new client is scored by the Client Health Monitor within 15 minutes of appearing.'},
            {'q': 'What triggers a churn alert?', 'a': 'The Churn Predictor fires when login frequency drops below threshold, agent uptime falls below 95%, or a support ticket is opened. Scores update every 15 minutes; below 60 triggers an alert.'},
            {'q': 'How do I generate an ROI report?', 'a': 'The ROI Reporter runs automatically at month-end. For on-demand reports, go to Agent Overview → ROI Reporter → Run Now. The report is emailed to the client automatically.'},
            {'q': 'Can I customize the proposal template?', 'a': 'Upload your branded proposal template as a PDF to Documents. The Proposal Generator uses it as a base and populates it with client-specific CRM data.'},
        ],
    },
    'legal': {
        'headline': 'AIOS — Legal Practice Intelligence Platform',
        'tagline': 'Never miss a deadline. Track every matter, billing target, and court docket from one command center.',
        'quick_start': [
            'Connect your practice management system (Clio or MyCase) via Integrations',
            'Import active matters via Data Import → CSV with matter name, SOL date, attorney, type',
            'Review the SOL Watchlist on the Dashboard — any matter under 14 days needs immediate action',
            'Open Email Intelligence → review urgent client emails flagged by the AI triage agent',
            'Confirm the Deadline Sentinel agent is active in Agent Overview',
            'Enable PACER Monitor integration for automatic federal docket alerts',
        ],
        'sections': [
            {'icon': '◎', 'title': 'Dashboard',          'tips': [
                'SOL Watchlist — red items are critical; the Deadline Sentinel fires alerts at 14/7/2/1 days',
                'AI Actions are sorted by urgency — case-critical items appear first',
                'Billable Hours KPI tracks today\'s target — update time entries in your billing system',
                'Agent Status — Deadline Sentinel should always show active; alert if it goes idle',
            ]},
            {'icon': '≡', 'title': 'Daily Brief',        'tips': [
                'Generated at 7:15 AM — includes all new docket activity from overnight PACER scans',
                'A/R Outstanding metric tracks overdue invoices — flag anything over 90 days for collections',
                'Highlights surface opposing counsel filings, upcoming deadlines, and new case activity',
                'Calendar entries are pulled from your connected calendar — sync Outlook or Google Calendar',
            ]},
            {'icon': '⬡', 'title': 'Matter Pipeline',    'tips': [
                'Stage column shows current workflow status (Intake, Discovery, Motions, Trial, etc.)',
                'Due column is agent-populated from your matter management system — verify against PACER',
                'Est. Value tracks matter pipeline by case type for revenue forecasting',
                'Click a matter row to view full AI-generated case summary and next steps',
            ]},
            {'icon': '✉', 'title': 'Email Intelligence', 'tips': [
                'Client emails are triaged by urgency — urgent items appear at the top every morning',
                'Draft Reply uses the client\'s prior communication style for tone-matched responses',
                'PACER Notification emails are auto-classified — review docket entries immediately',
                'Billing and collections emails are auto-tagged with AI Action for faster processing',
            ]},
            {'icon': '◷', 'title': 'Integrations',       'tips': [
                'PACER API is required for automated federal docket monitoring',
                'Westlaw or Casetext API unlocks the Legal Research Agent for live precedent search',
                'Clio or MyCase integration populates the Pipeline and Billing Agent automatically',
                'DocuSign integration enables AI-drafted engagement letters to be sent for e-signature',
            ]},
        ],
        'faqs': [
            {'q': 'How does the Deadline Sentinel prevent missed deadlines?', 'a': 'It scans all active matters every 30 minutes and sends escalating alerts at 14, 7, 2, and 1 day before any deadline. Alerts are sent via email and appear in the Dashboard AI Actions panel.'},
            {'q': 'Can AIOS draft motions and briefs?', 'a': 'Yes — the Motion Drafter agent generates draft documents from case notes and prior filings. Upload relevant documents to the Document Vault first for best results. Always have an attorney review before filing.'},
            {'q': 'How do I handle a PACER docket alert?', 'a': 'PACER Monitor sends an alert within 15 minutes of new activity. The Email Intelligence page flags these as "Review docket entry." Click to see the filing summary, then calendar any new deadlines.'},
            {'q': 'How are invoices generated?', 'a': 'The Billing Agent pulls time entries from your connected practice management system (Clio/MyCase) and generates invoices automatically. Configure billing rates in your PM system — they sync to AIOS automatically.'},
        ],
    },
    'construction': {
        'headline': 'AIOS — Construction Project Intelligence Platform',
        'tagline': 'Monitor every project, permit, RFI, and subcontractor across your entire portfolio in real time.',
        'quick_start': [
            'Connect your project management system (Procore or Buildertrend) via Integrations',
            'Import active projects via Data Import → CSV with project name, budget, PM, start/end dates',
            'Review the Project Health Matrix on the Dashboard — any red risk dots need same-day attention',
            'Open Email Intelligence → action any permit or owner emails flagged urgent by the AI',
            'Confirm Permit Watcher and Budget Watchdog agents are active in Agent Overview',
            'Connect the Weather API (OpenWeatherMap) to enable automatic weather impact forecasting',
        ],
        'sections': [
            {'icon': '◎', 'title': 'Dashboard',          'tips': [
                'Project Health Matrix — budget variance above 5% and red risk dots require immediate review',
                'AI Actions panel — permit expiry alerts and weather warnings are time-critical',
                'Pipeline bar shows budget consumption vs. % complete for all active projects',
                'Safety Days counter resets on any reported incident — maintain a clean log',
            ]},
            {'icon': '≡', 'title': 'Daily Brief',        'tips': [
                'Generated at 6:45 AM — includes overnight weather forecast and schedule impacts',
                'Budget Variance metric shows average across all projects — drill in on the Pipeline page',
                'RFI count tracks open items — anything over 30 days unresolved should be escalated',
                'Weather alert highlights affect multiple projects simultaneously — review before site walks',
            ]},
            {'icon': '⬡', 'title': 'Project Pipeline',   'tips': [
                'Budget Var. column turns amber at +3%, red at +7% — investigate root cause via change orders',
                '% Complete tracks physical progress from your PM system — keep it synced weekly',
                'PM column shows the responsible project manager for each job — use for routing issues',
                'Next Action and Due are agent-populated — override as conditions change on site',
            ]},
            {'icon': '✉', 'title': 'Email Intelligence', 'tips': [
                'Permit office emails are auto-tagged "Initiate renewal package" — action within 24 hrs',
                'Owner budget concern emails should be escalated via "Schedule review call" same day',
                'Subcontractor delay emails trigger automatic RFI draft by the RFI Response Agent',
                'OSHA and insurance renewal emails are tagged low priority but should be calendared',
            ]},
            {'icon': '◷', 'title': 'Integrations',       'tips': [
                'Procore integration populates the Project Pipeline and syncs RFI logs automatically',
                'Buildertrend integration is available for residential-focused builders',
                'OpenWeatherMap API powers the Weather Impact Agent — connect for automatic schedule alerts',
                'Sage 300 or QuickBooks integration enables real-time budget variance tracking',
            ]},
        ],
        'faqs': [
            {'q': 'How does the Permit Watcher prevent permit lapses?', 'a': 'Permit Watcher scans expiry dates daily and sends alerts at 30, 14, and 7 days before expiry. At 14 days it auto-drafts the renewal package from project details — review and submit before the deadline.'},
            {'q': 'What causes a budget variance alert?', 'a': 'Budget Watchdog fires when variance exceeds your configured threshold (default 5%). Root cause analysis pulls from the change order log — connect Procore for automatic CO tracking.'},
            {'q': 'How do I handle a weather impact?', 'a': 'The Weather Impact Agent generates a revised schedule automatically when a multi-day weather event is forecast. Review the impact report in the Daily Brief and update affected subcontractors via the Subcontractor Comms agent.'},
            {'q': 'How are RFI responses drafted?', 'a': 'The RFI Response Agent pulls from your uploaded spec library and historical project documentation. Upload project specs as PDFs to the Document Vault — the agent indexes them within 10 minutes of upload.'},
        ],
    },
    'medical': {
        'headline': 'AIOS — Medical Practice Intelligence Platform',
        'tagline': 'Keep prior authorizations current, claims clean, and patients recalled — on autopilot.',
        'quick_start': [
            'Connect your EHR/PM system (Availity or Change Healthcare) via Integrations',
            'Import today\'s schedule via Data Import → CSV export from your scheduling system',
            'Review the Dashboard — check Pending Auths count and any claims flagged by Claim Scrubber',
            'Open Email Intelligence → action any payer denials or credentialing emails flagged urgent',
            'Confirm Prior Auth Bot and Claim Scrubber are active in Agent Overview',
            'Launch the Recall Scheduler campaign — identify patients overdue for recall under Use Cases',
        ],
        'sections': [
            {'icon': '◎', 'title': 'Dashboard',           'tips': [
                'Pending Auths widget — anything expiring within 7 days needs same-day action',
                'Collections Rate KPI — below 96% indicates claim submission or follow-up issues',
                'Schedule Utilization shows today\'s fill rate — open slots should trigger recall outreach',
                'AI Actions panel — denial and auth alerts are time-sensitive; act same day',
            ]},
            {'icon': '≡', 'title': 'Daily Brief',         'tips': [
                'Generated at 6:58 AM — includes overnight auth status and lab result alerts',
                'Patients Today metric matches your scheduling system — sync EHR for live count',
                'Highlights surface claim denials, expiring auths, and unacknowledged lab results',
                'Calendar entries show provider schedules — link to your Google/Outlook calendar',
            ]},
            {'icon': '⬡', 'title': 'Patient Schedule',    'tips': [
                'Status column: Checked In → Waiting → Confirmed tracks real-time patient flow',
                'Flag column shows Auth Expiring and Unacked Labs — clear before the visit starts',
                'Open slots are highlighted — the Recall Scheduler auto-fills from overdue patient list',
                'Insurance column is verified 24 hrs in advance by the Insurance Verifier agent',
            ]},
            {'icon': '✉', 'title': 'Email Intelligence',  'tips': [
                'Payer denial emails should be actioned immediately — use "Review denial + appeal" workflow',
                'Patient emails about auths/appointments should be called back same day',
                'Lab result emails trigger "Flag for providers" — route to the correct provider inbox',
                'Credentialing renewal emails have long lead times — calendar 90 days before due',
            ]},
            {'icon': '◷', 'title': 'Integrations',        'tips': [
                'Availity integration is required for Prior Auth Bot to submit and track authorizations',
                'Change Healthcare connects for real-time eligibility verification and claim status',
                'AthenaHealth integration enables direct EHR chart sync for SOAP Note drafting',
                'Quest Diagnostics integration auto-routes incoming lab results to the correct provider',
            ]},
        ],
        'faqs': [
            {'q': 'How does the Prior Auth Bot submit authorizations?', 'a': 'Connect Availity via Integrations — the bot reads the appointment schedule, identifies patients needing auth, and submits electronically. It also monitors status and sends alerts at 14 and 7 days before auth expiry.'},
            {'q': 'How does the Claim Scrubber work?', 'a': 'It reviews every claim before submission against 47 common denial triggers including missing modifiers, diagnosis-procedure mismatches, and credentialing gaps. Claims with issues are flagged for review before they leave the practice.'},
            {'q': 'How do I run a recall campaign?', 'a': 'Go to Use Cases → Recall Scheduling → Activate. The Recall Scheduler identifies patients overdue for their next visit and sends a personalized SMS/email sequence automatically. Review the patient list before launching for the first time.'},
            {'q': 'What happens when a claim is denied?', 'a': 'The Denial Analyzer categorizes the denial by payer and reason code, then drafts an appeal letter. Go to Email Intelligence → find the denial email → click "Review denial + appeal" to review and submit.'},
        ],
    },
    'brokerage': {
        'headline': 'AIOS — Real Estate Brokerage Intelligence Platform',
        'tagline': 'Route every lead, optimize every listing, and close every transaction on schedule.',
        'quick_start': [
            'Connect your CRM (Follow Up Boss or kvCORE) via Integrations to sync lead flow',
            'Connect your TC platform (SkySlope or Dotloop) for live transaction deadline tracking',
            'Import your active listings via Data Import → CSV from MLS (address, price, agent, DOM)',
            'Review the Dashboard — check the Agent Leaderboard and any listing optimization alerts',
            'Confirm Lead Scorer & Router and Transaction Coordinator agents are active',
            'Review open listings with DOM > 30 days — the Listing Optimizer flags price reduction candidates',
        ],
        'sections': [
            {'icon': '◎', 'title': 'Dashboard',           'tips': [
                'Agent Leaderboard — agents with 0 closings in 45+ days need coaching intervention',
                'AI Actions panel — offer deadlines and listing expiry alerts are time-critical',
                'Under Contract KPI tracks pipeline momentum — should be 25-30% of active listings',
                'New Leads Today compares to your daily average — spikes indicate marketing activity',
            ]},
            {'icon': '≡', 'title': 'Daily Brief',         'tips': [
                'Generated at 7:08 AM — includes overnight lead arrivals and transaction deadline alerts',
                'Highlights surface offer deadlines, listing expiry, and agent performance signals',
                'Commission MTD tracks against monthly target — use to pace the team',
                'Calendar entries show pending offer reviews, listing appointments, and buyer consults',
            ]},
            {'icon': '⬡', 'title': 'Listing Pipeline',    'tips': [
                'DOM > 60 turns amber — Listing Optimizer will suggest price, photo, or copy changes',
                'Under Contract listings should be monitored daily for contingency deadlines',
                'Price Reduced status is auto-set when a reduction is entered in MLS',
                'Offers column is populated from your TC platform — keep SkySlope/Dotloop synced',
            ]},
            {'icon': '✉', 'title': 'Email Intelligence',  'tips': [
                'Pre-approved buyer emails should be actioned within 30 minutes — route to matched agent',
                'Seller "any offers?" emails trigger "Send price reduction CMA" workflow',
                'Offer submission emails are auto-tagged "Log offer + notify seller" — action immediately',
                'Agent support emails should route to broker for coaching follow-up within 24 hours',
            ]},
            {'icon': '◷', 'title': 'Integrations',        'tips': [
                'Follow Up Boss or kvCORE CRM integration is required for Lead Scorer routing to work',
                'SkySlope or Dotloop integration powers the Transaction Coordinator deadline tracking',
                'MLS API integration enables Listing Optimizer to pull real-time comparable data',
                'ShowingTime integration automates showing coordination and feedback collection',
            ]},
        ],
        'faqs': [
            {'q': 'How does Lead Scorer & Router assign leads?', 'a': 'It scores each lead 0-100 based on engagement, pre-approval status, and search behavior, then routes to the agent with the best matching history and current capacity. Configure routing rules in Integrations → Follow Up Boss.'},
            {'q': 'How does the Listing Optimizer decide what to recommend?', 'a': 'It analyzes DOM, showing count, offer count, and comparable active listings. When DOM exceeds your threshold (default 30 days) without offers, it generates a report with specific price, photo, and copy recommendations.'},
            {'q': 'How are transaction deadlines tracked?', 'a': 'Connect SkySlope or Dotloop via Integrations. The Transaction Coordinator agent reads all open contracts, extracts contingency dates, and sends alerts at 7, 3, and 1 day before each deadline to buyer, seller, and agent.'},
            {'q': 'How do I run a CMA?', 'a': 'Go to Use Cases → CMA Bot → Run. Enter the subject property address and the bot pulls MLS comparables and generates a full CMA in under 90 seconds. Output is a formatted PDF ready for client presentation.'},
        ],
    },
    'hvac': {
        'headline': 'AIOS — HVAC & Climate Services Command Center',
        'tagline': 'Dispatch faster, estimate smarter, and never lose a maintenance contract renewal.',
        'quick_start': [
            'Connect ServiceTitan or Jobber via Integrations to sync your job and customer data',
            'Import your technician roster via Data Import → CSV with name, zone, skills, and mobile number',
            'Review the Dashboard Dispatch Board — confirm all techs are assigned and on route',
            'Open Email Intelligence → action any emergency customer emails first',
            'Confirm Dispatch Optimizer and Maintenance Reminder agents are active in Agent Overview',
            'Review upcoming maintenance contract renewals in the Daily Brief and launch outreach campaign',
        ],
        'sections': [
            {'icon': '◎', 'title': 'Dashboard',              'tips': [
                'Technician Dispatch Board — red "EMERGENCY" AI Actions require immediate dispatch',
                'Maintenance Contracts KPI shows renewals due this month — launch outreach from here',
                'Monthly Revenue bar tracks progress to target — Emergency Repairs drive the fastest growth',
                'Tech Utilization should stay between 80-90%; above 95% risks burnout and missed SLAs',
            ]},
            {'icon': '≡', 'title': 'Daily Brief',            'tips': [
                'Generated at 6:30 AM — includes weather advisory and emergency call forecast for the day',
                'Calls Today metric is compared to your rolling average — spikes signal need to call in overflow',
                'Contract Renewals due this month are counted here — use the link to launch outreach',
                'Parts Order alerts surface back-orders that could delay today\'s scheduled jobs',
            ]},
            {'icon': '⬡', 'title': 'Service Call Pipeline',  'tips': [
                'ASAP ETAs are emergency jobs — confirm dispatch before reviewing any other items',
                'Revenue column shows estimated job value — prioritize high-value and emergency calls',
                'Unassigned jobs need a tech before the end of the day — use the Dispatch Board to assign',
                'Completed jobs trigger the Post-Job Follow-up and Invoice agents automatically',
            ]},
            {'icon': '✉', 'title': 'Email Intelligence',     'tips': [
                'Emergency customer emails appear at the top — confirm dispatch ETA immediately',
                'Parts supplier back-order emails should trigger "Find alternative supplier" search',
                'Maintenance contract renewal inquiries should get a proposal back within 2 hours',
                'Commercial service contract opportunities should be escalated to a senior tech or owner',
            ]},
            {'icon': '◷', 'title': 'Integrations',           'tips': [
                'ServiceTitan integration powers the Dispatch Optimizer and Estimate Generator agents',
                'Jobber is the alternative field service platform — connect one or the other, not both',
                'Twilio SMS integration enables customer ETA notifications and review request delivery',
                'Yelp Business integration monitors incoming reviews and alerts within 30 minutes of posting',
            ]},
        ],
        'faqs': [
            {'q': 'How does the Dispatch Optimizer assign jobs?', 'a': 'It assigns each incoming job to the best-available technician by matching skill set, current zone, and current job load. Emergency jobs override the queue automatically. Connect ServiceTitan or Jobber for live job data.'},
            {'q': 'How do I manage maintenance contract renewals?', 'a': 'The Maintenance Reminder agent identifies contracts expiring within 30 days and launches a personalized outreach sequence (email → SMS → call prompt). Review the renewal list in the Daily Brief and click to launch the campaign.'},
            {'q': 'How are estimates generated and sent?', 'a': 'The Estimate Generator builds itemized estimates from tech job notes against your flat-rate price book. Connect ServiceTitan/Jobber and upload your price book via Data Import. Estimates are emailed to the customer within 5 minutes of tech diagnosis.'},
            {'q': 'What happens after a job is completed?', 'a': 'Three agents fire automatically on job close: Post-Job Follow-up (sends satisfaction check-in 24 hrs later), Invoice & Payment Bot (sends invoice immediately), and Review Request Bot (sends 5-star review request 2 hrs later for satisfied customers).'},
        ],
    },
    'plumbing': {
        'headline': 'AIOS — Plumbing Services Command Center',
        'tagline': 'Triage every emergency, close every quote, and collect every invoice — without lifting a finger.',
        'quick_start': [
            'Connect Jobber or Housecall Pro via Integrations to sync jobs and customers',
            'Import your plumber roster via Data Import → CSV with name, mobile number, and current zone',
            'Review the Dashboard Job Board — confirm all active emergency jobs are dispatched',
            'Open Email Intelligence → action any burst pipe or flooding emergency emails first',
            'Confirm Lead Qualifier and Dispatch Scheduler agents are active in Agent Overview',
            'Review open quotes over 2 days old in the Pipeline — trigger follow-up from Email Intelligence',
        ],
        'sections': [
            {'icon': '◎', 'title': 'Dashboard',              'tips': [
                'Job Board — ASAP / emergency jobs require dispatch confirmation before anything else',
                'Open Quotes KPI — more than 15 open quotes indicates a follow-up backlog',
                'Monthly Revenue bar shows progress to target — Emergency Repairs are the highest margin',
                'Avg Review Rating tracks customer satisfaction — below 4.5 signals service quality issues',
            ]},
            {'icon': '≡', 'title': 'Daily Brief',            'tips': [
                'Generated at 6:45 AM — includes weather freeze advisory and tomorrow\'s volume forecast',
                'Jobs Today metric breaks down emergency vs. scheduled — use for staffing decisions',
                'Open Quotes count tracks unconverted estimates — review daily to close revenue gaps',
                'Permit Pending items are listed here — follow up on any over 5 days old',
            ]},
            {'icon': '⬡', 'title': 'Job Pipeline',           'tips': [
                'ASAP ETAs are burst pipe or flooding emergencies — verify dispatch is in progress',
                'Revenue column shows est. job value — $0 permit inspections still drive future work',
                'Pending jobs need customer confirmation before dispatching — call to verify',
                'Completed jobs trigger the Invoice Agent and Review Request Bot automatically',
            ]},
            {'icon': '✉', 'title': 'Email Intelligence',     'tips': [
                'Emergency flooding emails should be actioned within 5 minutes — dispatch immediately',
                'Quote follow-up emails with questions should get a callback same day to close the job',
                'City permit office emails requesting additional docs should be actioned same day',
                'Supplier price increase emails should trigger a price book update before the effective date',
            ]},
            {'icon': '◷', 'title': 'Integrations',           'tips': [
                'Jobber integration powers the Lead Qualifier, Dispatch Scheduler, and Invoice Agent',
                'Housecall Pro is an alternative field service platform — use one or the other',
                'Twilio SMS integration enables customer ETA alerts and review request delivery',
                'Google Business Profile integration enables the Review Request Bot to direct customers to your listing',
            ]},
        ],
        'faqs': [
            {'q': 'How does the emergency call triage work?', 'a': 'The Lead Qualifier agent processes incoming calls and web inquiries, classifies them as emergency or routine, and creates a dispatch ticket automatically. Emergency jobs are flagged immediately and routed to the nearest available plumber.'},
            {'q': 'How are quotes built and delivered?', 'a': 'The Quote Generator builds flat-rate quotes from job notes and your uploaded price book. Quotes are emailed with a one-click accept link — when the customer clicks Accept, the job is scheduled automatically and a deposit request is sent.'},
            {'q': 'How does permit tracking work?', 'a': 'The Permit Tracker logs applications and monitors approval status. It sends automated follow-up emails to city offices after 5 days with no response, and notifies your team immediately when a permit is approved.'},
            {'q': 'How do I get more 5-star reviews?', 'a': 'The Review Request Bot sends a review request 2 hours after a satisfied job close. Connect Twilio SMS for highest response rates. Negative responses are routed to the owner for immediate follow-up before they become public reviews.'},
        ],
    },
    'restaurant': {
        'headline': 'AIOS — Restaurant & Food Service Command Center',
        'tagline': 'Fill every table, manage every review, and control food cost — all on autopilot.',
        'quick_start': [
            'Connect OpenTable or Resy via Integrations to sync reservations and guest history',
            'Connect Toast or Square POS via Integrations to enable menu analytics and food cost tracking',
            'Review the Dashboard Service Timeline — confirm lunch prep is on schedule',
            'Open Email Intelligence → action any negative review alerts and supplier emails first',
            'Confirm Reservation Agent and Inventory Alert Agent are active in Agent Overview',
            'Review today\'s inventory against par levels in the Daily Brief — order any below-threshold items',
        ],
        'sections': [
            {'icon': '◎', 'title': 'Dashboard',              'tips': [
                'Service Timeline shows live daypart status — prep delays need immediate kitchen intervention',
                'Open Reviews KPI — negative reviews should be responded to within 2 hours',
                'Food Cost % (MTD) — above target triggers the Food Cost Monitor alert automatically',
                'AI Actions panel — inventory shortages before dinner service are the highest urgency item',
            ]},
            {'icon': '≡', 'title': 'Daily Brief',            'tips': [
                'Generated at 9:00 AM — includes last night\'s food cost reconciliation and cover count',
                'Covers Today metric breaks down lunch, dinner, and bar — compare to last week',
                'Projected Revenue vs. last week shows momentum — use for daily specials and upsell focus',
                'Review Alerts section shows any new negative reviews posted overnight',
            ]},
            {'icon': '⬡', 'title': 'Reservations',          'tips': [
                'Status filters (Seated, Confirmed, En Route, Waitlisted) show real-time floor status',
                'VIP and special occasion notes appear in the Notes column — brief FOH team before service',
                'Waitlisted parties should receive an ETA SMS — configure via Twilio in Integrations',
                'Private event reservations should be confirmed 48 hours in advance with a detailed BEO',
            ]},
            {'icon': '✉', 'title': 'Email Intelligence',     'tips': [
                'Private event inquiries are high-value — send a proposal back within 1 hour',
                'Supplier delivery adjustment emails should trigger an immediate inventory check',
                'Yelp/Google review alerts should be responded to within 2 hours — use the AI draft',
                'Reservation special request emails should be confirmed and logged for FOH before service',
            ]},
            {'icon': '◷', 'title': 'Integrations',           'tips': [
                'OpenTable or Resy integration is required for the Reservation Agent to manage bookings',
                'Toast or Square POS powers the Menu Performance Analyst and Food Cost Monitor',
                'Sysco or US Foods portal integration enables the Inventory Alert Agent to auto-generate POs',
                'Yelp Business and Google Business Profile APIs enable real-time review response drafting',
            ]},
        ],
        'faqs': [
            {'q': 'How does the Reservation Agent handle incoming bookings?', 'a': 'Connect OpenTable or Resy via Integrations. The agent handles phone, web, and OpenTable reservations simultaneously, sends SMS confirmations, manages the waitlist, and alerts FOH staff of VIP arrivals and special occasions.'},
            {'q': 'How does inventory auto-ordering work?', 'a': 'Connect your POS for depletion data and configure par levels via Data Import. The Inventory Alert Agent checks inventory against projected covers each morning and drafts purchase orders for items below threshold — you review and approve before sending.'},
            {'q': 'How does review response work?', 'a': 'Connect Google Business Profile and Yelp Business via Integrations. The Review Responder monitors for new reviews and drafts a branded response within 10 minutes. You receive an email with a one-click approval link — approved responses are posted automatically.'},
            {'q': 'How do I use the Menu Performance Analyst?', 'a': 'Connect your POS (Toast or Square) and upload recipe cost cards via Data Import. The analyst runs weekly and flags items with below-target contribution margins or low velocity. The report is emailed to the GM every Monday at 8 AM.'},
        ],
    },
}

# ── Auth Routes ───────────────────────────────────────────────────────────────
def _complete_login(email: str, method: str = 'email_otp'):
    """Finalize session after any successful authentication method."""
    now = _time.time()
    if email in ALLOWED_EMAILS:
        session['aios_auth']     = True
        session['aios_email']    = email
        session['aios_login_ts'] = now
        audit('login', f'/{method}', 'success', f'admin={email} method={method}')
        return redirect(url_for('index'))
    user = TenantUser.query.filter_by(email=email, active=True).first()
    if user:
        user.last_login = datetime.utcnow()
        db.commit()
        session['tenant_auth']     = True
        session['tenant_email']    = email
        session['tenant_id']       = user.tenant_id
        session['tenant_role']     = user.role
        session['tenant_industry'] = user.tenant.industry
        session['tenant_login_ts'] = now
        audit('login', f'/{method}', 'success', f'tenant_user={email} method={method}')
        return redirect(url_for('dashboard', industry=user.tenant.industry))
    return redirect(url_for('login'))


@app.route('/login', methods=['GET', 'POST'])
def login():
    if session.get('aios_auth') or session.get('tenant_auth'):
        return redirect(url_for('index'))
    error   = None
    prefill = request.args.get('email', '')
    if request.method == 'POST':
        email = request.form.get('email', '').strip().lower()
        ok, msg = check_authorized(email)
        if not ok:
            error = msg
        elif totp_enabled(email):
            session['aios_pending_email'] = email
            return redirect(url_for('totp_verify'))
        else:
            ok2, msg2 = request_otp(email)
            if ok2:
                session['aios_pending_email'] = email
                return redirect(url_for('otp_page'))
            error = msg2
    return render_template('login.html', error=error, prefill=prefill)


@app.route('/otp', methods=['GET', 'POST'])
def otp_page():
    email = session.get('aios_pending_email')
    # Fallback: form submits a hidden email field — use it if session dropped it
    if not email and request.method == 'POST':
        email = request.form.get('email', '').strip().lower()
    if not email:
        return redirect(url_for('login'))
    error = None
    if request.method == 'POST':
        submitted = request.form.get('code', '').strip()
        ok, msg = verify_otp(email, submitted)
        if ok:
            session.pop('aios_pending_email', None)
            return _complete_login(email, 'otp')
        error = msg
    has_totp = totp_enabled(email)
    return render_template('otp.html', email=email, masked_email=mask_email(email),
                           error=error, has_totp=has_totp)


@app.route('/totp/verify', methods=['GET', 'POST'])
def totp_verify():
    email = session.get('aios_pending_email')
    if not email and request.method == 'POST':
        email = request.form.get('email', '').strip().lower()
    if not email:
        return redirect(url_for('login'))
    error = None
    if request.method == 'POST':
        code = request.form.get('code', '').replace(' ', '').strip()
        ok, msg = verify_totp_code(email, code)
        if ok:
            session.pop('aios_pending_email', None)
            return _complete_login(email, 'totp')
        error = msg
    return render_template('totp_verify.html', email=email,
                           masked_email=mask_email(email), error=error)


@app.route('/totp/email-fallback')
def totp_email_fallback():
    """Fallback: send email OTP from the TOTP verify page."""
    email = session.get('aios_pending_email')
    if not email:
        return redirect(url_for('login'))
    ok, _ = request_otp(email)
    if ok:
        return redirect(url_for('otp_page'))
    return redirect(url_for('login'))

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

# ── Index ─────────────────────────────────────────────────────────────────────
@app.route('/')
@require_auth
def index():
    return render_template('index.html')

# ── Industry dashboard ────────────────────────────────────────────────────────
@app.route('/<industry>')
@require_auth
def dashboard(industry):
    cfg = INDUSTRIES.get(industry)
    if not cfg:
        return redirect('/')
    d = {**cfg, 'industry': industry,
         'nav': _nav(industry, 'dashboard', cfg['pipeline_label'], cfg['tools'])}
    return render_template('dashboard.html', data=d, **_ctx(d))

# ── Sub-pages (shared pattern) ────────────────────────────────────────────────
def _page(industry, active_key, template, **extra):
    cfg = INDUSTRIES.get(industry)
    if not cfg:
        return redirect('/')
    d = {**cfg, 'industry': industry,
         'nav': _nav(industry, active_key, cfg['pipeline_label'], cfg['tools'])}
    return render_template(template, data=d, **_ctx(d), **extra)

@app.route('/<industry>/brief')
@require_auth
def brief(industry):
    return _page(industry, 'brief', 'pages/brief.html',
                 brief=BRIEF_DATA.get(industry, {}))

@app.route('/<industry>/pipeline')
@require_auth
def pipeline(industry):
    return _page(industry, 'pipeline', 'pages/pipeline.html',
                 rows=PIPELINE_DATA.get(industry, []))

@app.route('/<industry>/email')
@require_auth
def email_intel(industry):
    return _page(industry, 'email', 'pages/email_intel.html',
                 emails=EMAILS_DATA.get(industry, []))

@app.route('/<industry>/goals')
@require_auth
def goals(industry):
    return _page(industry, 'goals', 'pages/goals_page.html')

@app.route('/<industry>/agents')
@require_auth
def agents(industry):
    return _page(industry, 'agents', 'pages/agents_page.html',
                 agents_detail=AGENTS_DETAIL.get(industry, []))

@app.route('/<industry>/use-cases')
@require_auth
def use_cases(industry):
    return _page(industry, 'use_cases', 'pages/use_cases.html',
                 use_cases=USE_CASES_DATA.get(industry, []))


# ── Integrations ──────────────────────────────────────────────────────────────

@app.route('/<industry>/integrations')
@require_auth
def integrations_page(industry):
    from integration_connectors import IntegrationAgent
    cfg = INDUSTRIES.get(industry)
    if not cfg:
        return redirect('/')
    tenant_id = session.get('tenant_id', '_admin')
    agent = IntegrationAgent(tenant_id)
    platforms = agent.get_status_list(industry=industry)
    categories = sorted({p['category'] for p in platforms})
    return _page(industry, 'integrations', 'pages/integrations.html',
                 platforms=platforms, categories=categories)


@app.route('/api/integrations/<platform_key>/connect', methods=['POST'])
@require_auth
def api_integration_connect(platform_key):
    from integration_connectors import IntegrationAgent, PLATFORMS
    if platform_key not in PLATFORMS:
        return jsonify({'ok': False, 'msg': f'Unknown platform: {platform_key}'}), 404
    tenant_id = session.get('tenant_id', '_admin')
    creds = {k: v for k, v in request.form.items() if k != 'csrf_token'}
    agent = IntegrationAgent(tenant_id)
    email = session.get('aios_email') or session.get('tenant_email', '')
    result = agent.connect(platform_key, creds, connected_by=email)
    return jsonify(result)


@app.route('/api/integrations/<platform_key>/test', methods=['POST'])
@require_auth
def api_integration_test(platform_key):
    from integration_connectors import IntegrationAgent, PLATFORMS
    if platform_key not in PLATFORMS:
        return jsonify({'ok': False, 'msg': f'Unknown platform: {platform_key}'}), 404
    tenant_id = session.get('tenant_id', '_admin')
    agent = IntegrationAgent(tenant_id)
    result = agent.test(platform_key)
    return jsonify(result)


@app.route('/api/integrations/<platform_key>/disconnect', methods=['POST'])
@require_auth
def api_integration_disconnect(platform_key):
    from integration_connectors import IntegrationAgent
    tenant_id = session.get('tenant_id', '_admin')
    IntegrationAgent(tenant_id).disconnect(platform_key)
    return jsonify({'ok': True})


@app.route('/api/integrations/<platform_key>/oauth/start')
@require_auth
def api_integration_oauth_start(platform_key):
    from integration_connectors import IntegrationAgent, PLATFORMS, oauth_authorize_url
    p = PLATFORMS.get(platform_key)
    if not p or 'oauth' not in p:
        return jsonify({'ok': False, 'msg': 'Platform does not support OAuth2'}), 400
    tenant_id = session.get('tenant_id', '_admin')
    agent = IntegrationAgent(tenant_id)
    rec = agent._load(platform_key)
    stored_creds = agent._creds(rec)
    redirect_uri = url_for('api_integration_oauth_callback', platform_key=platform_key, _external=True)
    state = secrets.token_hex(16)
    session[f'oauth_state_{platform_key}'] = state
    auth_url = oauth_authorize_url(platform_key, redirect_uri, state, stored_creds=stored_creds)
    if not auth_url:
        return jsonify({'ok': False, 'msg': 'Client ID not configured — save credentials first'}), 400
    return redirect(auth_url)


@app.route('/api/integrations/<platform_key>/oauth/callback')
@require_auth
def api_integration_oauth_callback(platform_key):
    from integration_connectors import IntegrationAgent, PLATFORMS, oauth_exchange_code
    code  = request.args.get('code', '')
    state = request.args.get('state', '')
    if not code:
        return '<h2 style="color:red">OAuth error — no code returned.</h2>', 400
    expected_state = session.pop(f'oauth_state_{platform_key}', '')
    if state and expected_state and state != expected_state:
        return '<h2 style="color:red">OAuth state mismatch — possible CSRF.</h2>', 400
    tenant_id = session.get('tenant_id', '_admin')
    agent = IntegrationAgent(tenant_id)
    rec = agent._load(platform_key)
    stored_creds = agent._creds(rec)
    redirect_uri = url_for('api_integration_oauth_callback', platform_key=platform_key, _external=True)
    tokens = oauth_exchange_code(platform_key, code, redirect_uri, stored_creds=stored_creds)
    if tokens.get('error'):
        return (f'<html><body style="background:#0a0e14;color:#e6edf3;padding:32px">'
                f'<h2 style="color:red">Token exchange failed: {tokens["error"]}</h2></body></html>'), 500
    agent.store_oauth_tokens(platform_key, tokens, base_creds=stored_creds)
    p = PLATFORMS.get(platform_key, {})
    industry = session.get('tenant_industry', 'agency')
    return (f'<html><head><meta http-equiv="refresh" content="2;url=/{industry}/integrations"></head>'
            f'<body style="background:#0a0e14;color:#e6edf3;font-family:sans-serif;padding:32px;text-align:center">'
            f'<div style="font-size:40px;margin-bottom:16px">✅</div>'
            f'<h2 style="color:#3fb950">{p.get("name","Platform")} connected successfully!</h2>'
            f'<p style="color:#8b949e">Redirecting back to Integrations…</p>'
            f'</body></html>')


@app.route('/<industry>/deploy')
@require_auth
def deploy(industry):
    return _page(industry, 'deploy', 'pages/deploy.html')

@app.route('/<industry>/logs')
@require_auth
def logs(industry):
    return _page(industry, 'logs', 'pages/logs_page.html',
                 logs=LOGS_DATA.get(industry, []))

@app.route('/<industry>/guide')
@require_auth
def guide(industry):
    g = GUIDE_CONTENT.get(industry)
    if not g:
        return redirect(f'/{industry}')
    return _page(industry, 'guide', 'pages/guide.html', guide=g)

@app.route('/<industry>/import')
@require_auth
def data_import(industry):
    return _page(industry, 'import', 'pages/data_import.html')

@app.route('/<industry>/team')
@require_auth
def team(industry):
    return _page(industry, 'team', 'pages/settings.html', setting='team')

@app.route('/<industry>/tool/<tool_key>')
@require_auth
def tool_page(industry, tool_key):
    cfg = INDUSTRIES.get(industry)
    if not cfg:
        return redirect('/')
    tool = next((t for t in cfg['tools'] if t['key'] == tool_key), None)
    if not tool:
        return redirect(f'/{industry}')
    active = f'tool_{tool_key.replace("-","_")}'
    d = {**cfg, 'industry': industry,
         'nav': _nav(industry, active, cfg['pipeline_label'], cfg['tools'])}
    return render_template('pages/tool_page.html', data=d, tool=tool, **_ctx(d))

# ── Documents ─────────────────────────────────────────────────────────────────
@app.route('/<industry>/documents')
@require_auth
def documents(industry):
    tenant_id = session.get('tenant_id')
    if tenant_id:
        docs = (Document.query.filter_by(tenant_id=tenant_id)
                .order_by(Document.uploaded_at.desc()).all())
    else:
        docs = []
    return _page(industry, 'documents', 'pages/documents.html', docs=docs)


@app.route('/<industry>/documents/upload', methods=['POST'])
@require_auth
def documents_upload(industry):
    from document_processor import process_upload, allowed_file, MAX_UPLOAD_BYTES
    import werkzeug.utils as wz
    tenant_id = session.get('tenant_id')
    if not tenant_id:
        return jsonify({'ok': False, 'error': 'No tenant context. Super-admins upload via /admin.'}), 400

    f = request.files.get('file')
    if not f or not f.filename:
        return jsonify({'ok': False, 'error': 'No file selected'}), 400

    filename = wz.secure_filename(f.filename)
    if not allowed_file(filename):
        return jsonify({'ok': False, 'error': 'File type not allowed'}), 400

    file_bytes = f.read()
    if len(file_bytes) > MAX_UPLOAD_BYTES:
        return jsonify({'ok': False, 'error': 'File exceeds 25 MB limit'}), 400

    email  = session.get('tenant_email', '')
    result = process_upload(file_bytes, filename, tenant_id, industry, email)

    doc = Document(
        tenant_id      = tenant_id,
        filename       = filename,
        content_type   = result['content_type'],
        encrypted_blob = result['encrypted_blob'],
        size_bytes     = result['size_bytes'],
        classification = result['classification'],
        summary_enc    = result['summary_enc'],
        uploaded_by    = email,
        status         = 'pending',
    )
    db.add(doc)
    db.commit()
    audit('document_upload', f'doc:{doc.id}', 'success',
          f'file={filename} class={result["classification"]}')

    return jsonify({
        'ok':            True,
        'doc_id':        doc.id,
        'classification':result['classification'],
        'confidence':    result['confidence'],
        'summary':       result['summary'],
    })


@app.route('/<industry>/documents/<doc_id>/assign', methods=['POST'])
@require_auth
def document_assign(industry, doc_id):
    tenant_id = session.get('tenant_id')
    query = Document.query.filter_by(id=doc_id)
    if tenant_id:
        query = query.filter_by(tenant_id=tenant_id)
    doc = query.first_or_404()
    doc.assigned_to = request.form.get('assigned_to', '').strip()[:200]
    doc.status      = 'reviewed'
    db.commit()
    return jsonify({'ok': True})


# ── Domain management (per-industry) ─────────────────────────────────────────
@app.route('/<industry>/domain')
@require_auth
def domain_page(industry):
    tenant_id = session.get('tenant_id')
    tenant    = Tenant.query.get(tenant_id) if tenant_id else None
    domains   = Domain.query.filter_by(tenant_id=tenant_id).all() if tenant_id else []
    cname_target = os.getenv('APP_HOSTNAME', 'aios-platform.railway.app')
    return _page(industry, 'domain', 'pages/domains.html',
                 tenant=tenant, domains=domains, cname_target=cname_target)


@app.route('/<industry>/domain/add', methods=['POST'])
@require_auth
def domain_add(industry):
    from security import validate_domain
    tenant_id = session.get('tenant_id')
    if not tenant_id:
        return jsonify({'ok': False, 'error': 'No tenant context'}), 400

    domain_str = request.form.get('domain', '').strip().lower().lstrip('www.')
    if not validate_domain(domain_str):
        return jsonify({'ok': False, 'error': 'Invalid domain name'}), 400
    if Domain.query.filter_by(domain=domain_str).first():
        return jsonify({'ok': False, 'error': 'Domain already registered'}), 400

    cname_target = os.getenv('APP_HOSTNAME', 'aios-platform.railway.app')
    dom = Domain(
        tenant_id          = tenant_id,
        domain             = domain_str,
        verification_token = secrets.token_hex(24),
        cname_target       = cname_target,
    )
    db.add(dom)
    db.commit()
    audit('domain_added', f'tenant:{tenant_id}', 'success', f'domain={domain_str}')
    return jsonify({
        'ok':                True,
        'domain_id':         dom.id,
        'verification_token': dom.verification_token,
        'cname_target':      cname_target,
    })


@app.route('/<industry>/domain/<domain_id>/verify', methods=['POST'])
@require_auth
def domain_verify(industry, domain_id):
    from admin_bp import _check_dns_txt
    tenant_id = session.get('tenant_id')
    dom = Domain.query.filter_by(id=domain_id, tenant_id=tenant_id).first_or_404()
    verified = _check_dns_txt(dom.domain, dom.verification_token)
    if verified:
        dom.verified    = True
        dom.ssl_status  = 'active'
        dom.verified_at = datetime.utcnow()
        db.commit()
    return jsonify({'ok': True, 'verified': verified})


# ── Health check ──────────────────────────────────────────────────────────────
@app.route('/health')
def health():
    return jsonify({'status': 'ok', 'version': 'v3.1.0'})


# ── Offline fallback page ─────────────────────────────────────────────────────
@app.route('/offline')
def offline_page():
    return render_template('offline.html'), 200


# ── Service Worker — must be served from root scope ───────────────────────────
@app.route('/sw.js')
def service_worker():
    from flask import send_from_directory, make_response
    resp = make_response(send_from_directory('static', 'sw.js'))
    resp.headers['Content-Type']          = 'application/javascript'
    resp.headers['Service-Worker-Allowed'] = '/'
    resp.headers['Cache-Control']          = 'no-cache'
    return resp


# ── Email diagnostics (temporary — remove after email confirmed working) ───────
@app.route('/admin/test-email')
@require_admin
def test_email():
    import os as _os
    from notify import send as _send
    to = session.get('aios_email', 'roger@aievolutionservices.com')
    try:
        _send(to, 'AIOS Email Test', '<h2>It works!</h2><p>AIOS email delivery is working correctly.</p>')
        result = f'OK — test email sent to {to}'
    except Exception as e:
        result = f'ERROR: {e}'
    diag = {
        'RESEND_API_KEY': 'set (' + (_os.getenv('RESEND_API_KEY','')[:8] + '…)') if _os.getenv('RESEND_API_KEY') else 'NOT SET',
        'RESEND_FROM':    _os.getenv('RESEND_FROM', 'NOT SET'),
        'SMTP_HOST':      _os.getenv('SMTP_HOST', 'NOT SET'),
        'result':         result,
    }
    rows = ''.join(f'<tr><td style="padding:8px 16px;color:#8b949e">{k}</td><td style="padding:8px 16px;color:#e3b341">{v}</td></tr>' for k,v in diag.items())
    return f'<html><body style="background:#0a0e14;color:#e6edf3;font-family:monospace;padding:32px"><h2 style="color:#e3b341">AIOS Email Diagnostics</h2><table style="border-collapse:collapse;background:#0d1117;border:1px solid #30363d;border-radius:8px">{rows}</table></body></html>'


if __name__ == '__main__':
    app.run(debug=True, port=5000)
