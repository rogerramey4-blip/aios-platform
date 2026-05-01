"""
AIOS Integration Connector Agents
26 platform connectors — autonomous credential management, OAuth flows, and connection health.
Each connector defines required fields, step-by-step setup instructions, and a live test_connection.
"""
import os, json, logging, urllib.request, urllib.parse, urllib.error
from datetime import datetime, timedelta
from base64 import b64encode

log = logging.getLogger(__name__)

PLATFORMS = {}   # platform_key -> platform dict


def _reg(d):
    PLATFORMS[d['key']] = d
    return d


# ── HTTP helpers ───────────────────────────────────────────────────────────────

def _get(url, headers=None, timeout=12):
    req = urllib.request.Request(url, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            body = r.read().decode()
            try:    return r.status, json.loads(body)
            except: return r.status, body
    except urllib.error.HTTPError as e:
        return e.code, (e.read().decode() if hasattr(e, 'read') else '')
    except Exception as exc:
        return 0, str(exc)


def _post(url, data, headers=None, timeout=12):
    if isinstance(data, dict):
        data = urllib.parse.urlencode(data).encode()
    h = {'Content-Type': 'application/x-www-form-urlencoded', **(headers or {})}
    req = urllib.request.Request(url, data=data, headers=h, method='POST')
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            body = r.read().decode()
            try:    return r.status, json.loads(body)
            except: return r.status, body
    except urllib.error.HTTPError as e:
        return e.code, (e.read().decode() if hasattr(e, 'read') else '')
    except Exception as exc:
        return 0, str(exc)


def _basic(user, pwd):
    return {'Authorization': 'Basic ' + b64encode(f'{user}:{pwd}'.encode()).decode()}


def _bearer(token):
    return {'Authorization': f'Bearer {token}'}


def _ok(msg):   return {'ok': True,  'msg': msg}
def _err(msg):  return {'ok': False, 'msg': msg}


# ══════════════════════════════════════════════════════════════════════════════
# CRM
# ══════════════════════════════════════════════════════════════════════════════

_reg({'key': 'hubspot', 'name': 'HubSpot CRM', 'logo': '🟠', 'category': 'CRM',
      'auth_type': 'api_key', 'industries': ['agency', 'legal', 'construction', 'medical', 'brokerage'],
      'fields': [
          {'key': 'api_key', 'label': 'Private App Token', 'type': 'password',
           'placeholder': 'pat-na1-xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx',
           'help': 'HubSpot → Settings → Integrations → Private Apps → Create'},
      ],
      'setup_steps': [
          'HubSpot → Settings (gear icon) → Integrations → Private Apps',
          'Create a private app named "AIOS" — enable scopes: crm.objects.contacts.read, crm.objects.deals.read',
          'Copy the Access Token and paste it above',
      ],
      'test': lambda c: (
          _ok('Connected — HubSpot CRM accessible') if
          _get('https://api.hubapi.com/crm/v3/objects/contacts?limit=1',
               headers=_bearer(c.get('api_key','')))[0] == 200
          else _err('Invalid token — check your Private App Token')
          if _get('https://api.hubapi.com/crm/v3/objects/contacts?limit=1',
                  headers=_bearer(c.get('api_key','')))[0] == 401
          else _err(f'HubSpot returned HTTP {_get("https://api.hubapi.com/crm/v3/objects/contacts?limit=1", headers=_bearer(c.get("api_key","")))[0]}')
      )})


def _test_hubspot(c):
    if not c.get('api_key'): return _err('No API key provided')
    s, _ = _get('https://api.hubapi.com/crm/v3/objects/contacts?limit=1', headers=_bearer(c['api_key']))
    if s == 200: return _ok('Connected — HubSpot CRM accessible')
    if s == 401: return _err('Invalid token — check your Private App Token')
    return _err(f'HubSpot returned HTTP {s}')

PLATFORMS['hubspot']['test'] = _test_hubspot


_reg({'key': 'salesforce', 'name': 'Salesforce CRM', 'logo': '☁️', 'category': 'CRM',
      'auth_type': 'api_key', 'industries': ['agency', 'legal', 'medical'],
      'fields': [
          {'key': 'instance_url', 'label': 'Instance URL', 'type': 'url',
           'placeholder': 'https://yourorg.salesforce.com', 'help': 'Your Salesforce org URL'},
          {'key': 'access_token', 'label': 'Access Token', 'type': 'password',
           'placeholder': '00Dxx...', 'help': 'From Salesforce Workbench or Connected App OAuth'},
      ],
      'setup_steps': [
          'In Salesforce: Setup → Users → your user → enable "API Enabled"',
          'Use Workbench (workbench.developerforce.com) → Login → REST Explorer to get a token',
          'Or create a Connected App: Setup → App Manager → New Connected App',
          'Paste your Instance URL and Access Token above',
      ],
      'test': None})

def _test_salesforce(c):
    url = c.get('instance_url', '').rstrip('/')
    token = c.get('access_token', '')
    if not url or not token: return _err('Instance URL and Access Token required')
    s, _ = _get(f'{url}/services/data/v60.0/limits', headers=_bearer(token))
    if s == 200: return _ok('Connected — Salesforce org accessible')
    if s == 401: return _err('Invalid token — re-authenticate in Salesforce')
    return _err(f'Salesforce returned HTTP {s}')

PLATFORMS['salesforce']['test'] = _test_salesforce


_reg({'key': 'follow_up_boss', 'name': 'Follow Up Boss', 'logo': '🎯', 'category': 'CRM',
      'auth_type': 'api_key', 'industries': ['brokerage'],
      'fields': [
          {'key': 'api_key', 'label': 'API Key', 'type': 'password',
           'placeholder': 'fub_...', 'help': 'Follow Up Boss Admin → Settings → API → Generate Key'},
      ],
      'setup_steps': [
          'Follow Up Boss: Admin → Settings → API → Generate API Key',
          'Copy the key and paste it above',
      ],
      'test': None})

def _test_fub(c):
    if not c.get('api_key'): return _err('No API key provided')
    s, _ = _get('https://api.followupboss.com/v1/users?limit=1',
                headers={**_basic(c['api_key'], ''), 'Accept': 'application/json'})
    if s == 200: return _ok('Connected — Follow Up Boss accessible')
    if s == 401: return _err('Invalid API key')
    return _err(f'Follow Up Boss returned HTTP {s}')

PLATFORMS['follow_up_boss']['test'] = _test_fub


_reg({'key': 'kvcore', 'name': 'kvCORE', 'logo': '🏠', 'category': 'CRM',
      'auth_type': 'api_key', 'industries': ['brokerage'],
      'fields': [
          {'key': 'api_key', 'label': 'API Key', 'type': 'password',
           'placeholder': '', 'help': 'kvCORE: Settings → Integrations → API Key'},
      ],
      'setup_steps': [
          'kvCORE → Settings → Integrations → API Key',
          'Copy and paste above (contact brokerage admin if not visible)',
      ],
      'test': None})

def _test_kvcore(c):
    if not c.get('api_key'): return _err('No API key provided')
    s, _ = _get('https://api.kvcore.com/v2/public/leads?per_page=1',
                headers={**_bearer(c['api_key']), 'Accept': 'application/json'})
    if s == 200: return _ok('Connected — kvCORE accessible')
    if s == 401: return _err('Invalid API key')
    return _err(f'kvCORE returned HTTP {s}')

PLATFORMS['kvcore']['test'] = _test_kvcore


_reg({'key': 'clio', 'name': 'Clio (Legal)', 'logo': '⚖️', 'category': 'CRM',
      'auth_type': 'oauth2', 'industries': ['legal'],
      'fields': [
          {'key': 'client_id',     'label': 'Client ID',     'type': 'text',     'placeholder': '', 'help': 'Clio → Settings → Developer Apps → Client ID'},
          {'key': 'client_secret', 'label': 'Client Secret', 'type': 'password', 'placeholder': '', 'help': 'Clio → Settings → Developer Apps → Client Secret'},
          {'key': 'access_token',  'label': 'Access Token',  'type': 'password', 'placeholder': '', 'help': 'Auto-filled after clicking Authorize'},
      ],
      'setup_steps': [
          'app.clio.com → Settings → Developer → Create Developer App',
          'Set redirect URI to: {base_url}/api/integrations/clio/oauth/callback',
          'Copy Client ID and Client Secret into the fields above',
          'Click "Authorize with Clio" to complete the OAuth flow',
      ],
      'oauth': {'authorize_url': 'https://app.clio.com/oauth/authorize',
                'token_url': 'https://app.clio.com/oauth/token',
                'scope': 'contacts:read matters:read bills:read',
                'client_id_field': 'client_id', 'client_secret_field': 'client_secret'},
      'test': None})

def _test_clio(c):
    if not c.get('access_token'): return _err('Not connected — use the Authorize button')
    s, _ = _get('https://app.clio.com/api/v4/users/who_am_i.json', headers=_bearer(c['access_token']))
    if s == 200: return _ok('Connected — Clio accessible')
    if s == 401: return _err('Token expired — reconnect')
    return _err(f'Clio returned HTTP {s}')

PLATFORMS['clio']['test'] = _test_clio


_reg({'key': 'mycase', 'name': 'MyCase', 'logo': '📋', 'category': 'CRM',
      'auth_type': 'api_key', 'industries': ['legal'],
      'fields': [
          {'key': 'api_key', 'label': 'API Key', 'type': 'password',
           'placeholder': '', 'help': 'MyCase → Settings → Integrations → API Keys → Create New'},
      ],
      'setup_steps': [
          'MyCase → Settings → Integrations → API Keys → Create New API Key',
          'Copy and paste above',
      ],
      'test': None})

def _test_mycase(c):
    if not c.get('api_key'): return _err('No API key provided')
    s, _ = _get('https://api.mycase.com/v1/cases?per_page=1',
                headers={'Authorization': f'Token {c["api_key"]}', 'Accept': 'application/json'})
    if s == 200: return _ok('Connected — MyCase accessible')
    if s == 401: return _err('Invalid API key')
    return _err(f'MyCase returned HTTP {s}')

PLATFORMS['mycase']['test'] = _test_mycase


# ══════════════════════════════════════════════════════════════════════════════
# Analytics / Ads
# ══════════════════════════════════════════════════════════════════════════════

_reg({'key': 'google_analytics', 'name': 'Google Analytics & Ads', 'logo': '📊', 'category': 'Analytics',
      'auth_type': 'oauth2', 'industries': ['agency'],
      'fields': [
          {'key': 'access_token', 'label': 'Access Token',    'type': 'password', 'placeholder': 'ya29...', 'help': 'Obtained via Google OAuth'},
          {'key': 'property_id',  'label': 'GA4 Property ID', 'type': 'text',     'placeholder': '123456789', 'help': 'Analytics → Admin → Property Settings'},
      ],
      'setup_steps': [
          'Enable Google Analytics Data API in Google Cloud Console',
          'Click "Authorize with Google Analytics" — uses the same Google OAuth project as Gmail',
          'Paste your GA4 Property ID from Analytics → Admin → Property Settings',
      ],
      'oauth': {'authorize_url': 'https://accounts.google.com/o/oauth2/auth',
                'token_url': 'https://oauth2.googleapis.com/token',
                'scope': 'https://www.googleapis.com/auth/analytics.readonly',
                'client_id_env': 'GOOGLE_CLIENT_ID', 'client_secret_env': 'GOOGLE_CLIENT_SECRET'},
      'test': None})

def _test_ga(c):
    token = c.get('access_token', '')
    if not token: return _err('Not connected — paste Access Token above')
    s, body = _get(f'https://www.googleapis.com/oauth2/v1/tokeninfo?access_token={token}')
    if s == 200: return _ok('Connected — Google Analytics API accessible')
    return _err('Token invalid or expired — re-authorize')

PLATFORMS['google_analytics']['test'] = _test_ga


_reg({'key': 'meta_ads', 'name': 'Meta / Facebook Ads', 'logo': '🔵', 'category': 'Analytics',
      'auth_type': 'api_key', 'industries': ['agency'],
      'fields': [
          {'key': 'access_token',  'label': 'Page Access Token', 'type': 'password',
           'placeholder': 'EAAxx...', 'help': 'Facebook Developers → Graph API Explorer → Generate Token (ads_read scope)'},
          {'key': 'ad_account_id', 'label': 'Ad Account ID',     'type': 'text',
           'placeholder': 'act_1234567890', 'help': 'Meta Ads Manager → Account Settings (starts with act_)'},
      ],
      'setup_steps': [
          'developers.facebook.com → Graph API Explorer → Generate Access Token',
          'Add permissions: ads_read, ads_management, business_management',
          'For a long-lived token (60 days): exchange via /oauth/access_token?grant_type=fb_exchange_token',
          'Find Ad Account ID in Meta Ads Manager → Account Settings (starts with act_)',
      ],
      'test': None})

def _test_meta(c):
    if not c.get('access_token'): return _err('No access token provided')
    s, body = _get(f'https://graph.facebook.com/v20.0/me?access_token={c["access_token"]}')
    if s == 200: return _ok(f'Connected — Meta API accessible')
    return _err('Invalid or expired token')

PLATFORMS['meta_ads']['test'] = _test_meta


# ══════════════════════════════════════════════════════════════════════════════
# Communication
# ══════════════════════════════════════════════════════════════════════════════

_reg({'key': 'twilio', 'name': 'Twilio SMS', 'logo': '📱', 'category': 'Communication',
      'auth_type': 'basic_auth', 'industries': ['medical', 'agency', 'brokerage', 'legal', 'construction'],
      'fields': [
          {'key': 'account_sid', 'label': 'Account SID',    'type': 'text',     'placeholder': 'ACxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx', 'help': 'console.twilio.com → Account Info'},
          {'key': 'auth_token',  'label': 'Auth Token',     'type': 'password', 'placeholder': '',                                    'help': 'console.twilio.com → Account Info'},
          {'key': 'from_number', 'label': 'From Number',    'type': 'text',     'placeholder': '+12015551234',                        'help': 'Your Twilio phone number in E.164 format'},
      ],
      'setup_steps': [
          'console.twilio.com → copy Account SID and Auth Token from the dashboard',
          'Buy or use an existing Twilio phone number',
          'Paste all three values above',
      ],
      'test': None})

def _test_twilio(c):
    sid = c.get('account_sid', '')
    token = c.get('auth_token', '')
    if not sid or not token: return _err('Account SID and Auth Token required')
    s, _ = _get(f'https://api.twilio.com/2010-04-01/Accounts/{sid}.json', headers=_basic(sid, token))
    if s == 200: return _ok('Connected — Twilio account active')
    if s == 401: return _err('Invalid credentials — check Account SID / Auth Token')
    return _err(f'Twilio returned HTTP {s}')

PLATFORMS['twilio']['test'] = _test_twilio


_reg({'key': 'slack', 'name': 'Slack Alerts', 'logo': '💬', 'category': 'Communication',
      'auth_type': 'webhook', 'industries': ['agency', 'legal', 'construction', 'medical', 'brokerage'],
      'fields': [
          {'key': 'webhook_url', 'label': 'Incoming Webhook URL', 'type': 'url',
           'placeholder': 'https://hooks.slack.com/services/T.../B.../..',
           'help': 'api.slack.com/apps → Incoming Webhooks → Add Webhook to Workspace'},
      ],
      'setup_steps': [
          'api.slack.com/apps → Create New App → From Scratch',
          'Add "Incoming Webhooks" feature and activate it',
          'Add New Webhook to Workspace → select channel → Authorize',
          'Copy the Webhook URL and paste above',
      ],
      'test': None})

def _test_slack(c):
    url = c.get('webhook_url', '')
    if not url: return _err('No webhook URL provided')
    payload = json.dumps({'text': '✅ AIOS integration test — Slack connected!'}).encode()
    req = urllib.request.Request(url, data=payload,
                                  headers={'Content-Type': 'application/json'}, method='POST')
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            body = r.read().decode()
            return _ok('Connected — test message sent to Slack') if body == 'ok' else _err(f'Slack returned: {body}')
    except Exception as exc:
        return _err(f'Request failed: {exc}')

PLATFORMS['slack']['test'] = _test_slack


# ══════════════════════════════════════════════════════════════════════════════
# Construction
# ══════════════════════════════════════════════════════════════════════════════

_reg({'key': 'procore', 'name': 'Procore', 'logo': '🏗️', 'category': 'Construction',
      'auth_type': 'oauth2', 'industries': ['construction'],
      'fields': [
          {'key': 'client_id',     'label': 'Client ID',     'type': 'text',     'placeholder': '', 'help': 'developers.procore.com → App Management'},
          {'key': 'client_secret', 'label': 'Client Secret', 'type': 'password', 'placeholder': '', 'help': 'developers.procore.com → App Management'},
          {'key': 'access_token',  'label': 'Access Token',  'type': 'password', 'placeholder': '', 'help': 'Auto-filled after clicking Authorize'},
          {'key': 'company_id',    'label': 'Company ID',    'type': 'text',     'placeholder': '1234567', 'help': 'Visible in the Procore app URL'},
      ],
      'setup_steps': [
          'developers.procore.com → Create an App',
          'Set Redirect URI to: {base_url}/api/integrations/procore/oauth/callback',
          'Copy Client ID and Client Secret → paste above',
          'Click "Authorize with Procore"',
      ],
      'oauth': {'authorize_url': 'https://login.procore.com/oauth/authorize',
                'token_url': 'https://login.procore.com/oauth/token',
                'scope': '',
                'client_id_field': 'client_id', 'client_secret_field': 'client_secret'},
      'test': None})

def _test_procore(c):
    if not c.get('access_token'): return _err('Not connected — authorize with Procore first')
    s, _ = _get('https://api.procore.com/rest/v1.0/me', headers=_bearer(c['access_token']))
    if s == 200: return _ok('Connected — Procore accessible')
    if s == 401: return _err('Token expired — reconnect')
    return _err(f'Procore returned HTTP {s}')

PLATFORMS['procore']['test'] = _test_procore


_reg({'key': 'buildertrend', 'name': 'Buildertrend', 'logo': '🔨', 'category': 'Construction',
      'auth_type': 'api_key', 'industries': ['construction'],
      'fields': [
          {'key': 'api_key', 'label': 'API Key', 'type': 'password',
           'placeholder': '', 'help': 'Buildertrend Admin → Company Settings → API Integration'},
      ],
      'setup_steps': [
          'Buildertrend → Admin → Company Settings → API Integration',
          'Generate an API key and paste it above',
      ],
      'test': None})

def _test_buildertrend(c):
    if not c.get('api_key'): return _err('No API key provided')
    s, _ = _get('https://buildertrend.net/api/v1/jobs?pageSize=1',
                headers={'Authorization': f'Bearer {c["api_key"]}',
                          'buildertrend-api-key': c['api_key']})
    if s == 200: return _ok('Connected — Buildertrend accessible')
    if s == 401: return _err('Invalid API key')
    return _err(f'Buildertrend returned HTTP {s}')

PLATFORMS['buildertrend']['test'] = _test_buildertrend


_reg({'key': 'openweathermap', 'name': 'OpenWeatherMap', 'logo': '⛅', 'category': 'Construction',
      'auth_type': 'api_key', 'industries': ['construction'],
      'fields': [
          {'key': 'api_key', 'label': 'API Key', 'type': 'password',
           'placeholder': 'xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx',
           'help': 'openweathermap.org → My Profile → My API Keys → Generate'},
      ],
      'setup_steps': [
          'Register free at openweathermap.org (free tier: 60 calls/min)',
          'My Profile → My API Keys → Generate Key',
          'Paste the key above',
      ],
      'test': None})

def _test_owm(c):
    if not c.get('api_key'): return _err('No API key provided')
    s, body = _get(f'https://api.openweathermap.org/data/2.5/weather?q=Dallas&appid={c["api_key"]}')
    if s == 200: return _ok('Connected — weather data accessible')
    if s == 401: return _err('Invalid API key — check at openweathermap.org')
    return _err(f'OpenWeatherMap returned HTTP {s}')

PLATFORMS['openweathermap']['test'] = _test_owm


_reg({'key': 'sage300', 'name': 'Sage 300 CRE', 'logo': '💰', 'category': 'Construction',
      'auth_type': 'basic_auth', 'industries': ['construction'],
      'fields': [
          {'key': 'api_url',  'label': 'Sage API URL', 'type': 'url',      'placeholder': 'https://your-server/sage300/v1', 'help': 'Your Sage 300 CRE server URL with API path'},
          {'key': 'username', 'label': 'Username',      'type': 'text',     'placeholder': '', 'help': 'Sage 300 CRE API user'},
          {'key': 'password', 'label': 'Password',      'type': 'password', 'placeholder': '', 'help': 'Sage 300 CRE API password'},
      ],
      'setup_steps': [
          'Enable Sage 300 CRE Web API from the Server Manager',
          'Create an API user or use your existing admin credentials',
          'Enter the API server URL, username, and password above',
      ],
      'test': None})

def _test_sage(c):
    url = c.get('api_url', '').rstrip('/')
    if not url or not c.get('username'): return _err('API URL and credentials required')
    s, _ = _get(f'{url}/companies', headers=_basic(c.get('username',''), c.get('password','')))
    if s == 200: return _ok('Connected — Sage 300 CRE accessible')
    if s == 401: return _err('Invalid credentials')
    return _err(f'Sage 300 returned HTTP {s}')

PLATFORMS['sage300']['test'] = _test_sage


# ══════════════════════════════════════════════════════════════════════════════
# Healthcare
# ══════════════════════════════════════════════════════════════════════════════

_reg({'key': 'availity', 'name': 'Availity Clearinghouse', 'logo': '🏥', 'category': 'Healthcare',
      'auth_type': 'api_key', 'industries': ['medical'],
      'fields': [
          {'key': 'client_id',     'label': 'Client ID',     'type': 'text',     'placeholder': '', 'help': 'developer.availity.com → Applications'},
          {'key': 'client_secret', 'label': 'Client Secret', 'type': 'password', 'placeholder': '', 'help': 'developer.availity.com → Applications'},
      ],
      'setup_steps': [
          'Register at developer.availity.com → Create Application',
          'Request access to Eligibility 270/271 and Claims 837 transactions',
          'Copy Client ID and Client Secret → paste above',
      ],
      'test': None})

def _test_availity(c):
    if not c.get('client_id') or not c.get('client_secret'): return _err('Client ID and Secret required')
    s, body = _post('https://api.availity.com/availity/v1/token',
                    {'grant_type': 'client_credentials', 'scope': 'hipaa'},
                    headers=_basic(c['client_id'], c['client_secret']))
    if s == 200 and isinstance(body, dict) and body.get('access_token'):
        return _ok('Connected — Availity clearinghouse accessible')
    return _err(f'Availity auth failed (HTTP {s}) — verify credentials')

PLATFORMS['availity']['test'] = _test_availity


_reg({'key': 'change_healthcare', 'name': 'Change Healthcare', 'logo': '⚕️', 'category': 'Healthcare',
      'auth_type': 'api_key', 'industries': ['medical'],
      'fields': [
          {'key': 'client_id',     'label': 'Client ID',     'type': 'text',     'placeholder': '', 'help': 'developers.changehealthcare.com → Applications'},
          {'key': 'client_secret', 'label': 'Client Secret', 'type': 'password', 'placeholder': '', 'help': 'developers.changehealthcare.com → Applications'},
      ],
      'setup_steps': [
          'Register at developers.changehealthcare.com',
          'Create a Sandbox or Production Application',
          'Copy Client ID and Client Secret → paste above',
      ],
      'test': None})

def _test_chc(c):
    if not c.get('client_id') or not c.get('client_secret'): return _err('Client ID and Secret required')
    s, body = _post('https://sandbox.apis.changehealthcare.com/apip/auth/v2/token',
                    {'grant_type': 'client_credentials'},
                    headers=_basic(c['client_id'], c['client_secret']))
    if s == 200 and isinstance(body, dict) and body.get('access_token'):
        return _ok('Connected — Change Healthcare sandbox accessible')
    return _err(f'Change Healthcare auth failed (HTTP {s})')

PLATFORMS['change_healthcare']['test'] = _test_chc


_reg({'key': 'athenahealth', 'name': 'athenahealth EHR', 'logo': '🩺', 'category': 'Healthcare',
      'auth_type': 'oauth2', 'industries': ['medical'],
      'fields': [
          {'key': 'client_id',     'label': 'Client ID',     'type': 'text',     'placeholder': '', 'help': 'developer.athenahealth.com → Create Application'},
          {'key': 'client_secret', 'label': 'Client Secret', 'type': 'password', 'placeholder': '', 'help': 'developer.athenahealth.com → Create Application'},
          {'key': 'access_token',  'label': 'Access Token',  'type': 'password', 'placeholder': '', 'help': 'Auto-filled after clicking Authorize'},
          {'key': 'practice_id',   'label': 'Practice ID',   'type': 'text',     'placeholder': '195900', 'help': 'Your athenahealth Practice ID'},
      ],
      'setup_steps': [
          'developer.athenahealth.com → Create Application',
          'Set redirect URI to: {base_url}/api/integrations/athenahealth/oauth/callback',
          'Copy Client ID and Client Secret → paste above',
          'Click "Authorize with athenahealth"',
      ],
      'oauth': {'authorize_url': 'https://api.platform.athenahealth.com/oauth2/v1/authorize',
                'token_url': 'https://api.platform.athenahealth.com/oauth2/v1/token',
                'scope': 'system/Patient.read system/Appointment.read',
                'client_id_field': 'client_id', 'client_secret_field': 'client_secret'},
      'test': None})

def _test_athena(c):
    if not c.get('access_token'): return _err('Not connected — authorize with athenahealth first')
    pid = c.get('practice_id', '195900')
    s, _ = _get(f'https://api.platform.athenahealth.com/v1/{pid}/practitioners/1',
                headers=_bearer(c['access_token']))
    if s in (200, 404): return _ok('Connected — athenahealth API accessible')
    if s == 401: return _err('Token expired — reconnect')
    return _err(f'athenahealth returned HTTP {s}')

PLATFORMS['athenahealth']['test'] = _test_athena


# ══════════════════════════════════════════════════════════════════════════════
# Legal Research
# ══════════════════════════════════════════════════════════════════════════════

_reg({'key': 'westlaw', 'name': 'Westlaw Edge API', 'logo': '📚', 'category': 'Legal',
      'auth_type': 'api_key', 'industries': ['legal'],
      'fields': [
          {'key': 'api_key',   'label': 'API Key',   'type': 'password', 'placeholder': '', 'help': 'developer.thomsonreuters.com → My Apps → API Key — requires Westlaw Edge subscription'},
          {'key': 'client_id', 'label': 'Client ID', 'type': 'text',     'placeholder': '', 'help': 'Thomson Reuters API Client ID'},
      ],
      'setup_steps': [
          'Contact your Westlaw Edge account rep to enable API access',
          'developer.thomsonreuters.com → My Apps → Create Application',
          'Copy Client ID and API Key → paste above',
      ],
      'test': None})

def _test_westlaw(c):
    if not c.get('api_key'): return _err('API Key required')
    s, _ = _get('https://api.westlaw.com/v1/search?q=contract&db=ALLCASES&num=1',
                headers={**_bearer(c['api_key']), 'x-client-id': c.get('client_id', '')})
    if s == 200: return _ok('Connected — Westlaw Edge API accessible')
    if s == 401: return _err('Invalid credentials — verify with your Thomson Reuters account rep')
    if s == 403: return _err('API access not enabled on this subscription')
    return _err(f'Westlaw returned HTTP {s}')

PLATFORMS['westlaw']['test'] = _test_westlaw


_reg({'key': 'pacer', 'name': 'PACER (Federal Courts)', 'logo': '🏛️', 'category': 'Legal',
      'auth_type': 'basic_auth', 'industries': ['legal'],
      'fields': [
          {'key': 'username', 'label': 'PACER Username', 'type': 'text',     'placeholder': '', 'help': 'Your PACER account username (pacer.uscourts.gov)'},
          {'key': 'password', 'label': 'PACER Password', 'type': 'password', 'placeholder': '', 'help': 'Your PACER account password'},
      ],
      'setup_steps': [
          'Register at pacer.uscourts.gov/register if needed',
          'Confirm credentials work at pacer.login.uscourts.gov',
          'Enter your PACER username and password above',
          'Note: PACER may charge $0.10/page for some document queries',
      ],
      'test': None})

def _test_pacer(c):
    if not c.get('username') or not c.get('password'): return _err('Username and password required')
    data = urllib.parse.urlencode({'loginid': c['username'], 'password': c['password'],
                                    'apptype': 'B', 'clientCode': '', 'c': ''}).encode()
    req = urllib.request.Request(
        'https://pacer.login.uscourts.gov/services/cso-auth', data=data,
        headers={'Content-Type': 'application/x-www-form-urlencoded', 'Accept': 'application/json'},
        method='POST')
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            body = json.loads(r.read().decode())
            if body.get('nextGenCSO') or body.get('loginResult') == '0':
                return _ok('Connected — PACER credentials valid')
            return _err(f'PACER login failed: {body.get("errorDescription", "unknown")}')
    except urllib.error.HTTPError as e:
        return _err(f'PACER returned HTTP {e.code}')
    except Exception as exc:
        return _err(f'Connection error: {exc}')

PLATFORMS['pacer']['test'] = _test_pacer


# ══════════════════════════════════════════════════════════════════════════════
# Finance & Payments
# ══════════════════════════════════════════════════════════════════════════════

_reg({'key': 'stripe', 'name': 'Stripe Payments', 'logo': '💳', 'category': 'Finance',
      'auth_type': 'api_key', 'industries': ['agency', 'legal', 'medical', 'construction', 'brokerage'],
      'fields': [
          {'key': 'secret_key', 'label': 'Secret Key', 'type': 'password',
           'placeholder': 'sk_live_... or sk_test_...',
           'help': 'Stripe Dashboard → Developers → API Keys → Secret key'},
      ],
      'setup_steps': [
          'dashboard.stripe.com → Developers → API Keys',
          'Copy the Secret Key (sk_live_ for production, sk_test_ for testing)',
          'Paste it above',
      ],
      'test': None})

def _test_stripe(c):
    if not c.get('secret_key'): return _err('No secret key provided')
    s, _ = _get('https://api.stripe.com/v1/balance', headers=_bearer(c['secret_key']))
    if s == 200: return _ok('Connected — Stripe balance accessible')
    if s == 401: return _err('Invalid API key')
    return _err(f'Stripe returned HTTP {s}')

PLATFORMS['stripe']['test'] = _test_stripe


_reg({'key': 'quickbooks', 'name': 'QuickBooks', 'logo': '📗', 'category': 'Finance',
      'auth_type': 'oauth2', 'industries': ['agency', 'legal', 'construction', 'medical', 'brokerage'],
      'fields': [
          {'key': 'client_id',     'label': 'Client ID',       'type': 'text',     'placeholder': '', 'help': 'developer.intuit.com → My Apps → Keys & Credentials'},
          {'key': 'client_secret', 'label': 'Client Secret',   'type': 'password', 'placeholder': '', 'help': 'developer.intuit.com → My Apps → Keys & Credentials'},
          {'key': 'access_token',  'label': 'Access Token',    'type': 'password', 'placeholder': '', 'help': 'Auto-filled after clicking Authorize'},
          {'key': 'realm_id',      'label': 'Company (Realm) ID', 'type': 'text',  'placeholder': '1234567890', 'help': 'Shown in your QuickBooks URL after login'},
      ],
      'setup_steps': [
          'developer.intuit.com → Create an App',
          'Set redirect URI to: {base_url}/api/integrations/quickbooks/oauth/callback',
          'Copy Client ID and Client Secret → paste above',
          'Click "Authorize with QuickBooks"',
      ],
      'oauth': {'authorize_url': 'https://appcenter.intuit.com/connect/oauth2',
                'token_url': 'https://oauth.platform.intuit.com/oauth2/v1/tokens/bearer',
                'scope': 'com.intuit.quickbooks.accounting',
                'client_id_field': 'client_id', 'client_secret_field': 'client_secret'},
      'test': None})

def _test_quickbooks(c):
    if not c.get('access_token') or not c.get('realm_id'): return _err('Access Token and Company ID required')
    rid = c['realm_id']
    s, _ = _get(f'https://sandbox-quickbooks.api.intuit.com/v3/company/{rid}/companyinfo/{rid}',
                headers={**_bearer(c['access_token']), 'Accept': 'application/json'})
    if s == 200: return _ok('Connected — QuickBooks accessible')
    if s == 401: return _err('Token expired — reconnect')
    return _err(f'QuickBooks returned HTTP {s}')

PLATFORMS['quickbooks']['test'] = _test_quickbooks


_reg({'key': 'docusign', 'name': 'DocuSign', 'logo': '✍️', 'category': 'Finance',
      'auth_type': 'oauth2', 'industries': ['agency', 'legal', 'construction', 'brokerage'],
      'fields': [
          {'key': 'integration_key', 'label': 'Integration Key (Client ID)', 'type': 'text',     'placeholder': '', 'help': 'DocuSign Admin → API and Keys → Integration Key'},
          {'key': 'client_secret',   'label': 'Client Secret',               'type': 'password', 'placeholder': '', 'help': 'DocuSign Admin → API and Keys → Client Secret'},
          {'key': 'access_token',    'label': 'Access Token',                'type': 'password', 'placeholder': '', 'help': 'Auto-filled after clicking Authorize'},
          {'key': 'account_id',      'label': 'Account ID',                  'type': 'text',     'placeholder': '', 'help': 'DocuSign Admin → API and Keys'},
      ],
      'setup_steps': [
          'admin.docusign.com → API and Keys',
          'Create or select an App → copy Integration Key',
          'Add redirect URI: {base_url}/api/integrations/docusign/oauth/callback',
          'Click "Authorize with DocuSign"',
      ],
      'oauth': {'authorize_url': 'https://account.docusign.com/oauth/auth',
                'token_url': 'https://account.docusign.com/oauth/token',
                'scope': 'signature',
                'client_id_field': 'integration_key', 'client_secret_field': 'client_secret'},
      'test': None})

def _test_docusign(c):
    if not c.get('access_token'): return _err('Not connected — authorize with DocuSign first')
    s, _ = _get('https://account.docusign.com/oauth/userinfo', headers=_bearer(c['access_token']))
    if s == 200: return _ok('Connected — DocuSign accessible')
    if s == 401: return _err('Token expired — reconnect')
    return _err(f'DocuSign returned HTTP {s}')

PLATFORMS['docusign']['test'] = _test_docusign


# ══════════════════════════════════════════════════════════════════════════════
# Real Estate
# ══════════════════════════════════════════════════════════════════════════════

_reg({'key': 'mls_api', 'name': 'MLS / NTREIS API', 'logo': '🏡', 'category': 'Real Estate',
      'auth_type': 'api_key', 'industries': ['brokerage'],
      'fields': [
          {'key': 'api_key',  'label': 'API Key / RETS Password', 'type': 'password', 'placeholder': '', 'help': 'Provided by your MLS board after API access approval'},
          {'key': 'mls_user', 'label': 'MLS Username',            'type': 'text',     'placeholder': '', 'help': 'Your MLS RETS or API username'},
          {'key': 'board',    'label': 'MLS Board',                'type': 'text',     'placeholder': 'NTREIS', 'help': 'Your MLS board (e.g. NTREIS, CRMLS, MFRMLS)'},
      ],
      'setup_steps': [
          'Submit an API access application to your MLS board',
          'For NTREIS: ntreis.net → Technology → RETS/IDX application',
          'Once approved you will receive RETS/API credentials',
          'Enter your credentials and board name above',
      ],
      'test': None})

def _test_mls(c):
    if not c.get('mls_user') or not c.get('api_key'): return _err('MLS username and API key required')
    board = c.get('board', 'NTREIS').upper()
    s, _ = _get('https://sparkapi.com/v1/listings?_limit=1',
                headers={**_basic(c['api_key'], ''), 'Accept': 'application/json'})
    if s == 200:   return _ok(f'Connected — {board} MLS API accessible')
    if s == 401:   return _err('Invalid credentials — check with your MLS board')
    if s in (403, 422): return _ok(f'Credentials accepted — {board} RETS configured')
    return _err(f'MLS API returned HTTP {s}')

PLATFORMS['mls_api']['test'] = _test_mls


_reg({'key': 'showingtime', 'name': 'ShowingTime', 'logo': '📅', 'category': 'Real Estate',
      'auth_type': 'api_key', 'industries': ['brokerage'],
      'fields': [
          {'key': 'api_key', 'label': 'API Key', 'type': 'password',
           'placeholder': '', 'help': 'Request API access from your ShowingTime account manager'},
      ],
      'setup_steps': [
          'Contact ShowingTime support to enable API access for your account',
          'They will provide an API key — paste it above',
      ],
      'test': None})

def _test_showingtime(c):
    if not c.get('api_key'): return _err('No API key provided')
    s, _ = _get('https://api.showingtime.com/v1/appointments?limit=1',
                headers={'x-api-key': c['api_key'], 'Accept': 'application/json'})
    if s == 200: return _ok('Connected — ShowingTime API accessible')
    if s == 401: return _err('Invalid API key')
    return _err(f'ShowingTime returned HTTP {s}')

PLATFORMS['showingtime']['test'] = _test_showingtime


_reg({'key': 'zillow', 'name': 'Zillow Bridge', 'logo': '🏘️', 'category': 'Real Estate',
      'auth_type': 'api_key', 'industries': ['brokerage'],
      'fields': [
          {'key': 'api_key', 'label': 'API Key', 'type': 'password',
           'placeholder': '', 'help': 'Apply at zillow.com/partner for Zillow Bridge Interactive access'},
      ],
      'setup_steps': [
          'Apply for Zillow Bridge Interactive access at zillow.com/partner',
          'Once approved you will receive API credentials',
          'Paste your API key above (requires partner approval)',
      ],
      'test': None})

def _test_zillow(c):
    if not c.get('api_key'): return _err('No API key provided')
    s, _ = _get(f'https://api.bridgedataoutput.com/api/v2/zestimates?access_token={c["api_key"]}&limit=1')
    if s == 200: return _ok('Connected — Zillow Bridge accessible')
    if s == 401: return _err('Invalid API key')
    return _err(f'Zillow API returned HTTP {s}')

PLATFORMS['zillow']['test'] = _test_zillow


# ══════════════════════════════════════════════════════════════════════════════
# Project Management
# ══════════════════════════════════════════════════════════════════════════════

_reg({'key': 'monday', 'name': 'Monday.com', 'logo': '📋', 'category': 'Project Management',
      'auth_type': 'api_key', 'industries': ['agency', 'construction'],
      'fields': [
          {'key': 'api_key', 'label': 'API Token', 'type': 'password',
           'placeholder': 'eyJhbG...', 'help': 'Monday.com → Profile → Admin → API → Personal API Key'},
      ],
      'setup_steps': [
          'Monday.com → click profile picture (top right) → Admin → API',
          'Copy the Personal API Key (long token starting with eyJhb...)',
          'Paste it above',
      ],
      'test': None})

def _test_monday(c):
    if not c.get('api_key'): return _err('No API token provided')
    payload = json.dumps({'query': '{ me { name email } }'}).encode()
    req = urllib.request.Request('https://api.monday.com/v2', data=payload,
                                  headers={'Content-Type': 'application/json',
                                            'Authorization': c['api_key']}, method='POST')
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            body = json.loads(r.read().decode())
            if body.get('data', {}).get('me'):
                name = body['data']['me'].get('name', '')
                return _ok(f'Connected — Monday.com ({name})')
            return _err(f'Monday.com auth failed: {body.get("errors", "")}')
    except Exception as exc:
        return _err(f'Connection error: {exc}')

PLATFORMS['monday']['test'] = _test_monday


# ══════════════════════════════════════════════════════════════════════════════
# OAuth2 helpers
# ══════════════════════════════════════════════════════════════════════════════

def oauth_authorize_url(platform_key: str, redirect_uri: str, state: str,
                        stored_creds: dict = None) -> str | None:
    """Build the OAuth2 authorization URL for the given platform."""
    p = PLATFORMS.get(platform_key)
    if not p or 'oauth' not in p:
        return None
    oauth = p['oauth']
    creds = stored_creds or {}
    cid_field = oauth.get('client_id_field', 'client_id')
    client_id = creds.get(cid_field) or os.getenv(oauth.get('client_id_env', ''), '')
    if not client_id:
        return None
    params = {'client_id': client_id, 'redirect_uri': redirect_uri,
               'response_type': 'code', 'state': state}
    if oauth.get('scope'):
        params['scope'] = oauth['scope']
    if platform_key == 'google_analytics':
        params['access_type'] = 'offline'
        params['prompt'] = 'consent'
    return f"{oauth['authorize_url']}?{urllib.parse.urlencode(params)}"


def oauth_exchange_code(platform_key: str, code: str, redirect_uri: str,
                        stored_creds: dict = None) -> dict:
    """Exchange an authorization code for access + refresh tokens."""
    p = PLATFORMS.get(platform_key)
    if not p or 'oauth' not in p:
        return {'error': f'Platform {platform_key} does not support OAuth2'}
    oauth = p['oauth']
    creds = stored_creds or {}
    cid_field = oauth.get('client_id_field', 'client_id')
    sec_field = oauth.get('client_secret_field', 'client_secret')
    client_id     = creds.get(cid_field) or os.getenv(oauth.get('client_id_env', ''), '')
    client_secret = creds.get(sec_field) or os.getenv(oauth.get('client_secret_env', ''), '')
    if not client_id or not client_secret:
        return {'error': 'Client ID and Secret not configured'}
    s, body = _post(oauth['token_url'], {
        'code': code, 'client_id': client_id, 'client_secret': client_secret,
        'redirect_uri': redirect_uri, 'grant_type': 'authorization_code',
    })
    if s == 200 and isinstance(body, dict):
        return body
    return {'error': f'Token exchange failed (HTTP {s}): {body}'}


def oauth_refresh(platform_key: str, refresh_token_val: str, stored_creds: dict = None) -> dict:
    """Refresh an OAuth2 access token."""
    p = PLATFORMS.get(platform_key)
    if not p or 'oauth' not in p:
        return {'error': 'Platform does not support OAuth2'}
    oauth = p['oauth']
    creds = stored_creds or {}
    cid_field = oauth.get('client_id_field', 'client_id')
    sec_field = oauth.get('client_secret_field', 'client_secret')
    client_id     = creds.get(cid_field) or os.getenv(oauth.get('client_id_env', ''), '')
    client_secret = creds.get(sec_field) or os.getenv(oauth.get('client_secret_env', ''), '')
    s, body = _post(oauth['token_url'], {
        'refresh_token': refresh_token_val, 'client_id': client_id,
        'client_secret': client_secret, 'grant_type': 'refresh_token',
    })
    if s == 200 and isinstance(body, dict):
        return body
    return {'error': f'Token refresh failed (HTTP {s})'}


# ══════════════════════════════════════════════════════════════════════════════
# Integration Agent
# ══════════════════════════════════════════════════════════════════════════════

class IntegrationAgent:
    """
    Autonomous agent that manages all platform connections for a single tenant.
    Handles credential storage (encrypted), connection testing, OAuth lifecycle,
    and token refresh.
    """

    def __init__(self, tenant_id: str):
        self.tenant_id = tenant_id

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _load(self, platform_key: str):
        from models import TenantIntegration
        return TenantIntegration.query.filter_by(
            tenant_id=self.tenant_id, platform_key=platform_key).first()

    def _save(self, platform_key: str, **kwargs):
        from models import TenantIntegration, db
        rec = self._load(platform_key)
        if not rec:
            rec = TenantIntegration(tenant_id=self.tenant_id, platform_key=platform_key)
            db.add(rec)
        for k, v in kwargs.items():
            setattr(rec, k, v)
        db.commit()
        return rec

    def _creds(self, rec) -> dict:
        if not rec or not rec.creds_enc:
            return {}
        from encryption import decrypt_str
        try:
            return json.loads(decrypt_str(self.tenant_id, rec.creds_enc))
        except Exception:
            return {}

    def _enc(self, creds: dict) -> str:
        from encryption import encrypt_str
        return encrypt_str(self.tenant_id, json.dumps(creds))

    # ── Public API ────────────────────────────────────────────────────────────

    def connect(self, platform_key: str, creds: dict, connected_by: str = '') -> dict:
        """Save credentials and run a live connection test."""
        p = PLATFORMS.get(platform_key)
        if not p:
            return _err(f'Unknown platform: {platform_key}')
        self._save(platform_key, creds_enc=self._enc(creds))
        result = p['test'](creds)
        self._save(platform_key,
                   status='connected' if result['ok'] else 'error',
                   last_tested=datetime.utcnow(),
                   last_test_ok=result['ok'],
                   last_test_msg=result['msg'][:500],
                   connected_at=datetime.utcnow() if result['ok'] else None,
                   connected_by=connected_by)
        return result

    def test(self, platform_key: str) -> dict:
        """Re-test an existing connection with stored credentials."""
        p = PLATFORMS.get(platform_key)
        if not p:
            return _err(f'Unknown platform: {platform_key}')
        rec = self._load(platform_key)
        creds = self._creds(rec)
        if not creds:
            return _err('No credentials stored — connect first')
        result = p['test'](creds)
        self._save(platform_key,
                   status='connected' if result['ok'] else 'error',
                   last_tested=datetime.utcnow(),
                   last_test_ok=result['ok'],
                   last_test_msg=result['msg'][:500])
        return result

    def disconnect(self, platform_key: str):
        """Clear stored credentials and mark disconnected."""
        self._save(platform_key, creds_enc='', status='disconnected',
                   last_test_ok=False, last_test_msg='',
                   connected_at=None, connected_by='', token_expires_at=None)

    def store_oauth_tokens(self, platform_key: str, token_response: dict,
                           base_creds: dict = None) -> dict:
        """
        Persist OAuth2 tokens after authorization code exchange.
        Merges new tokens into existing credential set so previously entered
        client_id / client_secret are preserved.
        """
        rec = self._load(platform_key)
        creds = self._creds(rec) if rec else {}
        if base_creds:
            creds.update(base_creds)
        if token_response.get('access_token'):
            creds['access_token'] = token_response['access_token']
        if token_response.get('refresh_token'):
            creds['refresh_token'] = token_response['refresh_token']
        if token_response.get('instance_url'):     # Salesforce
            creds['instance_url'] = token_response['instance_url']
        if token_response.get('realmId'):          # QuickBooks
            creds['realm_id'] = token_response['realmId']
        expires_at = None
        if token_response.get('expires_in'):
            expires_at = datetime.utcnow() + timedelta(seconds=int(token_response['expires_in']) - 60)
        self._save(platform_key,
                   creds_enc=self._enc(creds),
                   status='connected',
                   token_expires_at=expires_at,
                   last_tested=datetime.utcnow(),
                   last_test_ok=True,
                   last_test_msg='OAuth authorization complete',
                   connected_at=datetime.utcnow())
        return creds

    def maybe_refresh_token(self, platform_key: str) -> bool:
        """
        If the stored OAuth token is expired (or close to expiry), refresh it automatically.
        Returns True if a refresh was performed.
        """
        rec = self._load(platform_key)
        if not rec or rec.status != 'connected':
            return False
        if rec.token_expires_at and datetime.utcnow() < rec.token_expires_at:
            return False   # still valid
        creds = self._creds(rec)
        refresh_token_val = creds.get('refresh_token', '')
        if not refresh_token_val:
            return False
        result = oauth_refresh(platform_key, refresh_token_val, stored_creds=creds)
        if result.get('access_token'):
            self.store_oauth_tokens(platform_key, result, base_creds=creds)
            log.info('[Integration] Auto-refreshed token for %s / %s', self.tenant_id, platform_key)
            return True
        log.warning('[Integration] Token refresh failed for %s / %s: %s',
                    self.tenant_id, platform_key, result.get('error'))
        return False

    def get_status_list(self, industry: str = None) -> list:
        """Return connection status for all platforms (optionally filtered by industry)."""
        from models import TenantIntegration
        recs = {r.platform_key: r for r in
                TenantIntegration.query.filter_by(tenant_id=self.tenant_id).all()}
        result = []
        for key, p in PLATFORMS.items():
            if industry and industry not in p.get('industries', []):
                continue
            rec = recs.get(key)
            result.append({
                'key':           key,
                'name':          p['name'],
                'logo':          p['logo'],
                'category':      p['category'],
                'auth_type':     p['auth_type'],
                'industries':    p['industries'],
                'fields':        p['fields'],
                'setup_steps':   p.get('setup_steps', []),
                'has_oauth':     'oauth' in p,
                'status':        rec.status if rec else 'disconnected',
                'last_tested':   rec.last_tested.isoformat() if rec and rec.last_tested else None,
                'last_test_ok':  rec.last_test_ok if rec else False,
                'last_test_msg': rec.last_test_msg if rec else '',
                'connected_at':  rec.connected_at.isoformat() if rec and rec.connected_at else None,
                'connected_by':  rec.connected_by if rec else '',
            })
        return result
