import os, secrets
import time as _time
from datetime import datetime
from flask import Flask, render_template, request, session, redirect, url_for

try:
    from dotenv import load_dotenv; load_dotenv()
except ImportError:
    pass

from auth import request_otp, verify_otp, require_auth, mask_email

app = Flask(__name__)
app.secret_key = os.getenv('SECRET_KEY') or secrets.token_hex(32)

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
}

USE_CASES_DATA = {
    'agency': [
        {'icon': '📧', 'title': 'Automated Client Reporting',  'desc': 'Monthly ROI reports compiled and emailed to each client automatically. Zero manual effort.',   'status': 'active',    'category': 'Reporting'},
        {'icon': '⚠️', 'title': 'Churn Early Warning System',  'desc': 'Detects disengagement signals 30–45 days before churn. Triggers retention sequences.',        'status': 'active',    'category': 'Retention'},
        {'icon': '📝', 'title': 'AI Proposal Generation',      'desc': 'Generates customized proposals from CRM data in under 60 seconds.',                            'status': 'active',    'category': 'Sales'},
        {'icon': '📊', 'title': 'Agent Performance Dashboard', 'desc': 'Real-time visibility into every deployed agent uptime, task count, and error rate.',           'status': 'active',    'category': 'Operations'},
        {'icon': '🔍', 'title': 'Lead Intelligence Scanner',   'desc': 'Scans directories for qualified prospects. Scores and routes to pipeline.',                    'status': 'active',    'category': 'Sales'},
        {'icon': '📅', 'title': 'Contract Renewal Reminders',  'desc': 'Alerts 60/30/14 days before renewals. Drafts renewal emails automatically.',                  'status': 'available', 'category': 'Retention'},
        {'icon': '💬', 'title': 'Client Onboarding Automation','desc': 'Guides new clients through setup with automated tasks and welcome sequences.',                 'status': 'available', 'category': 'Operations'},
        {'icon': '📈', 'title': 'Upsell Opportunity Detector', 'desc': 'Monitors plan usage and recommends upsell conversations when clients hit capacity.',           'status': 'available', 'category': 'Sales'},
    ],
    'legal': [
        {'icon': '⏰', 'title': 'Deadline Sentinel',            'desc': 'Never miss a statute of limitations, filing deadline, or response due date.',                 'status': 'active',    'category': 'Compliance'},
        {'icon': '📝', 'title': 'AI Motion Drafting',           'desc': 'Drafts motions and briefs from case notes in minutes, not hours.',                           'status': 'active',    'category': 'Litigation'},
        {'icon': '🔍', 'title': 'Legal Research Automation',    'desc': 'Finds precedents and statutes across Westlaw and Casetext automatically.',                    'status': 'active',    'category': 'Research'},
        {'icon': '💰', 'title': 'Automated Billing',            'desc': 'Converts time entries to invoices. Tracks realization rates and collections aging.',         'status': 'active',    'category': 'Billing'},
        {'icon': '📡', 'title': 'PACER Docket Monitoring',      'desc': 'Instant alerts on docket activity across all active federal matters.',                       'status': 'active',    'category': 'Litigation'},
        {'icon': '✉️', 'title': 'Client Communication AI',      'desc': 'Triages incoming client emails and drafts replies maintaining consistent tone.',              'status': 'active',    'category': 'Client Service'},
        {'icon': '📋', 'title': 'Conflict Check Automation',    'desc': 'AI-powered conflict search on new matters against all client and opposing party history.',   'status': 'available', 'category': 'Compliance'},
        {'icon': '📊', 'title': 'Matter Profitability Tracker', 'desc': 'Real-time P&L by matter. Identifies write-off risk before it happens.',                      'status': 'available', 'category': 'Billing'},
    ],
    'construction': [
        {'icon': '📋', 'title': 'Permit Expiry Automation',     'desc': 'Auto-tracks permit expiry dates and drafts renewal packages 30 days early.',                 'status': 'active',    'category': 'Compliance'},
        {'icon': '💰', 'title': 'Budget Variance Monitoring',   'desc': 'Monitors budget variance per project. Alerts the moment threshold is crossed.',              'status': 'active',    'category': 'Finance'},
        {'icon': '⛅', 'title': 'Weather Schedule Impact',      'desc': 'Pulls 10-day forecasts, calculates project delay impact, generates revised schedules.',       'status': 'active',    'category': 'Operations'},
        {'icon': '📝', 'title': 'Automated RFI Drafting',       'desc': 'Generates RFI responses from spec library, reducing response time from days to hours.',      'status': 'active',    'category': 'Documentation'},
        {'icon': '🔧', 'title': 'Subcontractor Coordination',   'desc': 'Daily schedule confirmations, follow-ups on late deliverables, performance scoring.',        'status': 'active',    'category': 'Operations'},
        {'icon': '⚠️', 'title': 'Safety Incident Monitor',      'desc': 'Reviews site logs for hazard language. Identifies near-misses before they become incidents.', 'status': 'active',    'category': 'Safety'},
        {'icon': '📊', 'title': 'Change Order Analytics',       'desc': 'Tracks all change orders, approvals, and budget impact across every project.',               'status': 'available', 'category': 'Finance'},
        {'icon': '🗓️', 'title': 'Draw Schedule Tracker',        'desc': 'Monitors payment milestones, tracks amounts drawn, and projects cash flow.',                 'status': 'available', 'category': 'Finance'},
    ],
    'medical': [
        {'icon': '📋', 'title': 'Prior Authorization Automation','desc': 'Submits, tracks, and re-submits prior auth requests across all major payers.',             'status': 'active',    'category': 'Revenue Cycle'},
        {'icon': '🔍', 'title': 'Pre-Claim Scrubbing',           'desc': 'Reviews every claim for 47 denial triggers before submission. Reduces denials ~35%.',       'status': 'active',    'category': 'Revenue Cycle'},
        {'icon': '📣', 'title': 'Patient Recall Campaign',       'desc': 'Identifies overdue patients and sends personalized reminders with booking links.',           'status': 'active',    'category': 'Patient Engagement'},
        {'icon': '📝', 'title': 'Denial Appeal Generator',       'desc': 'Drafts appeal letters with supporting documentation based on denial reason codes.',         'status': 'active',    'category': 'Revenue Cycle'},
        {'icon': '✅', 'title': 'Insurance Pre-Verification',    'desc': 'Confirms coverage and co-pay 24hrs before each appointment.',                               'status': 'active',    'category': 'Operations'},
        {'icon': '🩺', 'title': 'SOAP Notes Drafting',           'desc': 'Generates clinical note drafts from voice input. Saves 6–8 minutes per encounter.',        'status': 'active',    'category': 'Clinical'},
        {'icon': '📊', 'title': 'A/R Aging Monitor',             'desc': 'Tracks receivables daily. Escalates accounts approaching write-off thresholds.',            'status': 'available', 'category': 'Revenue Cycle'},
        {'icon': '💬', 'title': 'Patient Satisfaction Surveys',  'desc': 'Sends post-visit surveys automatically. Aggregates scores and flags negatives.',           'status': 'available', 'category': 'Patient Engagement'},
    ],
    'brokerage': [
        {'icon': '🎯', 'title': 'Lead Scoring & Routing',        'desc': 'Scores inbound leads by conversion likelihood and routes to the best-fit agent.',           'status': 'active',    'category': 'Lead Management'},
        {'icon': '📊', 'title': 'Listing Performance Optimizer', 'desc': 'Analyzes DOM, views, and showings. Recommends price changes and description rewrites.',      'status': 'active',    'category': 'Listings'},
        {'icon': '📈', 'title': 'Market Report Automation',      'desc': 'Weekly market condition reports per zip code, auto-distributed to all agents.',              'status': 'active',    'category': 'Market Intel'},
        {'icon': '✅', 'title': 'Transaction Deadline Tracking', 'desc': 'Monitors all contingency deadlines. Never miss an inspection or appraisal date.',           'status': 'active',    'category': 'Transactions'},
        {'icon': '📅', 'title': 'Showing Coordination',          'desc': 'Automates showing requests between all parties. Confirms and reschedules automatically.',   'status': 'active',    'category': 'Operations'},
        {'icon': '📝', 'title': 'Listing Description AI',        'desc': 'Generates compelling MLS listing descriptions in under 30 seconds.',                        'status': 'active',    'category': 'Listings'},
        {'icon': '📉', 'title': 'Expired Listing Recovery',      'desc': 'Identifies expired competitor listings as prospecting opportunities.',                       'status': 'available', 'category': 'Lead Management'},
        {'icon': '💰', 'title': 'Commission Forecasting',        'desc': 'Projects forward commission revenue from pipeline. Tracks against monthly targets.',        'status': 'available', 'category': 'Finance'},
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
}

# ── Auth Routes ───────────────────────────────────────────────────────────────
@app.route('/login', methods=['GET', 'POST'])
def login():
    if session.get('aios_auth'):
        return redirect(url_for('index'))
    error   = None
    prefill = request.args.get('email', '')
    if request.method == 'POST':
        email = request.form.get('email', '').strip().lower()
        ok, msg = request_otp(email)
        if ok:
            session['aios_pending_email'] = email
            return redirect(url_for('otp_page'))
        error = msg
    return render_template('login.html', error=error, prefill=prefill)

@app.route('/otp', methods=['GET', 'POST'])
def otp_page():
    email = session.get('aios_pending_email')
    if not email:
        return redirect(url_for('login'))
    error = None
    if request.method == 'POST':
        submitted = request.form.get('code', '').strip()
        ok, msg = verify_otp(email, submitted)
        if ok:
            session.pop('aios_pending_email', None)
            session['aios_auth']     = True
            session['aios_email']    = email
            session['aios_login_ts'] = _time.time()
            return redirect(url_for('index'))
        error = msg
    return render_template('otp.html', email=email, masked_email=mask_email(email), error=error)

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

@app.route('/<industry>/deploy')
@require_auth
def deploy(industry):
    return _page(industry, 'deploy', 'pages/deploy.html')

@app.route('/<industry>/logs')
@require_auth
def logs(industry):
    return _page(industry, 'logs', 'pages/logs_page.html',
                 logs=LOGS_DATA.get(industry, []))

@app.route('/<industry>/import')
@require_auth
def data_import(industry):
    return _page(industry, 'import', 'pages/data_import.html')

@app.route('/<industry>/integrations')
@require_auth
def integrations(industry):
    return _page(industry, 'integrations', 'pages/settings.html', setting='integrations')

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

if __name__ == '__main__':
    app.run(debug=True, port=5000)
