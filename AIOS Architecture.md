 AIOS — AI Operating System

  Full Design Specification v1.0

  ---
  Part 1: Core Architecture

  The AIOS is built as a multi-tenant, industry-vertical platform. Every tenant is a firm (law firm, construction company, medical practice, etc.). Each
  tenant gets their own isolated agent runtime, data namespace, and tailored dashboard configuration.

  Kernel Layers (based on published AIOS research + multi-tenant SaaS patterns)

  ┌─────────────────────────────────────────────────────────────────┐
  │                    PRESENTATION LAYER                           │
  │  Dashboard UI  │  Daily Brief  │  Agent Activity  │  Alerts    │
  ├─────────────────────────────────────────────────────────────────┤
  │                    ORCHESTRATION LAYER                          │
  │  Task Scheduler  │  Priority Engine  │  Goal Tracker           │
  ├──────────────┬──────────────┬──────────────┬───────────────────┤
  │  AGENT       │  MEMORY      │  TOOL        │  LEARNING         │
  │  RUNTIME     │  MANAGER     │  REGISTRY    │  ENGINE           │
  │  (per tenant)│  Short+Long  │  Per industry│  Feedback loops   │
  ├──────────────┴──────────────┴──────────────┴───────────────────┤
  │                    DATA LAYER                                   │
  │  PostgreSQL (tenant_id isolation)  │  Vector DB (pgvector)     │
  │  Imported Tables  │  Agent Logs  │  KPI History                │
  ├─────────────────────────────────────────────────────────────────┤
  │                    INTEGRATION LAYER                            │
  │  Email (IMAP/SMTP)  │  APIs (per industry)  │  DB Import (CSV/SQL) │
  └─────────────────────────────────────────────────────────────────┘

  Core Database Schema

  tenants          (id, name, industry, plan, branding_json, created_at)
  users            (id, tenant_id, name, role, email, title)
  agents           (id, tenant_id, type, status, config_json, last_run, error_count)
  agent_logs       (id, agent_id, tenant_id, action, result, duration_ms, timestamp)
  priority_actions (id, tenant_id, title, urgency, due_at, source_agent, dismissed)
  kpi_snapshots    (id, tenant_id, metric_key, value, captured_at)
  goals            (id, tenant_id, name, target, current, period, unit)
  alerts           (id, tenant_id, category, headline, source, body, relevance, created_at)
  data_tables      (id, tenant_id, table_name, schema_json, row_count, imported_at)
  imported_rows    (id, table_id, tenant_id, row_json)  -- partitioned by tenant_id

  ---
  Part 2: Universal Dashboard Shell

  Every industry shares the same shell. What changes is the content inside each pane.

  Header Bar

  [FIRM NAME + LOGO]  [AIOS Command Center badge]  [User Name + Role badge]
                                           [HH:MM AM/PM]  [☀ Light / 🌙 Dark]

  Left Sidebar Navigation Structure

  COMMAND CENTER
    ○ Dashboard          ← main landing (industry-specific content)
    ○ Daily Brief        ← AI-generated morning summary
    ○ [Industry Pipeline]← case/project/patient/listing pipeline
    ○ Email Intelligence ← inbox triage + draft suggestions
    ○ Goals & Strategy   ← goal setting + progress

  AI TOOLS              ← generative tools specific to industry
    ○ [Tool 1]
    ○ [Tool 2]
    ○ [Tool 3]

  AI AGENTS             ← live agent management
    ○ Agent Overview  [N badge = active]
    ○ Use Cases
    ○ Deploy New Agent
    ○ Agent Logs

  SETTINGS
    ○ Data Import
    ○ Integrations
    ○ Team & Roles
    ○ Billing

  Main Content Layout

  Good [Morning/Afternoon], [First Name]
  [Day], [Month] [Date], [Year]

  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐
  │  KPI 1   │ │  KPI 2   │ │  KPI 3   │ │  KPI 4   │
  │ (primary)│ │(financial)│ │(comms)   │ │(deadline)│
  └──────────┘ └──────────┘ └──────────┘ └──────────┘

  ┌────────────────────────────┐ ┌────────────────────────┐
  │  ⚡ TODAY'S PRIORITY        │ │  📡 INDUSTRY INTEL     │
  │  ACTIONS                   │ │  ALERTS                │
  │  [AI-ranked task list]     │ │  [Curated news feed]   │
  └────────────────────────────┘ └────────────────────────┘

  ┌─────────────┐ ┌────────────────────┐ ┌──────────────────┐
  │ 🎯 GOALS    │ │ 📊 PIPELINE BY     │ │ 🤖 AI AGENT      │
  │ PROGRESS    │ │ [INDUSTRY SEGMENT] │ │ ACTIVITY         │
  └─────────────┘ └────────────────────┘ └──────────────────┘

  ┌────────────────────────────────────────────────────────┐
  │  📋 ADDITIONAL INDUSTRY-SPECIFIC PANE (row 3)          │
  └────────────────────────────────────────────────────────┘

  ---
  Part 3: Industry Modules

  ---
  🏢 Industry 1: AI Automation Agency

  KPI Cards:

  ┌────────────────────────────┬─────────┬───────────────────────────────────────┐
  │            Card            │ Metric  │              Sub-detail               │
  ├────────────────────────────┼─────────┼───────────────────────────────────────┤
  │ Active Client Projects     │ 24      │ 6 onboarding · 14 running · 4 at risk │
  ├────────────────────────────┼─────────┼───────────────────────────────────────┤
  │ Monthly Recurring Revenue  │ $47,200 │ +$3,100 from last month               │
  ├────────────────────────────┼─────────┼───────────────────────────────────────┤
  │ Agents Deployed & Live     │ 142     │ 12 erroring · 4 paused                │
  ├────────────────────────────┼─────────┼───────────────────────────────────────┤
  │ Deliverables Due This Week │ 9       │ 3 overdue · 2 awaiting approval       │
  └────────────────────────────┴─────────┴───────────────────────────────────────┘

  Left Nav (AI Tools): Proposal Writer, SOW Generator, ROI Report Builder, Upsell Deck Creator

  Priority Actions (AI-generated):
  - Client "Apex Dental" agent down 4hrs — intervention needed URGENT
  - Proposal for "Riviera Realty" due by 3PM — draft ready DUE TODAY
  - Monthly ROI report for "Metro HVAC" — agent compiled data READY
  - Churn signal: "TechStart Inc" last logged in 18 days ago AT RISK
  - Upsell opportunity: "LakeView Law" hits 80% of base plan capacity OPPORTUNITY

  Intelligence Panel: AI industry news, new model releases, competitor agency moves, automation tool updates

  Additional Panes (Row 2-3):
  - Client Health Scorecard — traffic-light grid: each client scored on engagement, agent uptime, deliverable cadence, payment status
  - Agent Performance Matrix — table: agent name, client, uptime %, tasks completed, error rate, last success
  - MRR Waterfall — bar chart: new MRR, expansion, contraction, churn, net new
  - Automation ROI Tracker — per client: hours automated/month, dollar value saved, efficiency score
  - Proposal Pipeline — funnel: prospects → proposals sent → in negotiation → closed/won/lost

  ---
  ⚖️ Industry 2: Legal (as shown in screenshot — expanded)

  KPI Cards:

  ┌────────────────────────┬────────┬───────────────────────────────────────┐
  │          Card          │ Metric │              Sub-detail               │
  ├────────────────────────┼────────┼───────────────────────────────────────┤
  │ Active Cases           │ 18     │ 6 securities · 7 PI · 5 transactional │
  ├────────────────────────┼────────┼───────────────────────────────────────┤
  │ Pending Recovery Value │ $4.2M  │ 3 cases at trial stage                │
  ├────────────────────────┼────────┼───────────────────────────────────────┤
  │ Emails to Review       │ 12     │ 5 urgent · 4 drafts ready             │
  ├────────────────────────┼────────┼───────────────────────────────────────┤
  │ Deadlines This Week    │ 7      │ 2 filing deadlines · 5 responses      │
  └────────────────────────┴────────┴───────────────────────────────────────┘

  Left Nav (AI Tools): Motion Drafter, Legal Research, Contract Analyzer, Deposition Prep, Demand Letter Writer

  Additional Panes (expanded beyond screenshot):
  - Billable Hours Tracker — today vs. target, by attorney, realization rate (billed vs. collected)
  - Statute of Limitations Watchlist — countdown timers per case, color-coded by urgency
  - Client Intake Pipeline — leads → consult scheduled → retained → active
  - A/R & Collections — invoiced, outstanding, overdue by age bucket
  - Conflict Check Log — AI-powered new matter conflict scan results
  - Court Filing Calendar — synced deadlines, court dates, docket entries

  AI Agents specific:
  - PACER Monitor — watches federal dockets for case activity
  - Legal Research Agent — cites relevant precedents for active matters
  - Deadline Sentinel — cross-references all deadlines, sends escalating alerts at 14d/7d/2d/1d
  - Motion Drafter Agent — drafts motions from case notes using Claude
  - Billing Agent — auto-generates invoices from time entries

  ---
  🏗️ Industry 3: Construction

  KPI Cards:

  ┌───────────────────────────────┬────────┬─────────────────────────────────────────────┐
  │             Card              │ Metric │                 Sub-detail                  │
  ├───────────────────────────────┼────────┼─────────────────────────────────────────────┤
  │ Active Projects               │ 11     │ 4 commercial · 5 residential · 2 civil      │
  ├───────────────────────────────┼────────┼─────────────────────────────────────────────┤
  │ Total Budget Under Management │ $8.3M  │ 2 projects > 5% variance                    │
  ├───────────────────────────────┼────────┼─────────────────────────────────────────────┤
  │ Open RFIs & Submittals        │ 34     │ 8 overdue response · 12 awaiting approval   │
  ├───────────────────────────────┼────────┼─────────────────────────────────────────────┤
  │ Safety Incidents (30-day)     │ 0      │ 847 incident-free days · 1 near-miss logged │
  └───────────────────────────────┴────────┴─────────────────────────────────────────────┘

  Left Nav (AI Tools): Estimate Builder, RFI Drafter, Spec Analyzer, Change Order Generator, Permit Tracker

  Priority Actions (AI-generated):
  - Permit for "Lakeshore Condos" expires in 12 days — renewal package not submitted URGENT
  - Framing sub "Harmon Carpentry" is 6 days behind on Block C BEHIND SCHEDULE
  - Budget variance 7.3% on "Commerce Park Phase 2" — review change orders REVIEW
  - RFI #118 unanswered 4 days — architect unresponsive FOLLOW UP
  - Weather forecast: 3-day rain event starts Monday — update schedule for 4 affected projects TOMORROW

  Intelligence Panel: Material price indices (lumber, steel, concrete), local permit office news, OSHA updates, subcontractor availability alerts, code
  amendment feeds

  Additional Panes:
  - Project Health Matrix — grid: project name, % complete, budget variance, schedule variance, risk level (red/yellow/green), PM assigned
  - Subcontractor Scorecard — by sub: on-time rate, quality score, RFI response time, bid win rate, insurance expiration
  - Change Order Log — pending, approved, rejected — dollar impact waterfall
  - Daily Manpower Report — total workers on site today vs. planned, by trade, by project
  - Equipment Utilization — fleet assets, location, utilization %, maintenance due
  - Punch List Tracker — items by project, by trade, days open, % complete
  - Permit & Inspection Calendar — scheduled inspections, permit expiration countdowns
  - Draw Schedule — payment milestones, amounts drawn, amounts remaining per project

  AI Agents specific:
  - Permit Watcher — monitors permit expiration dates, auto-drafts renewal packages
  - RFI Response Agent — drafts RFI responses from spec library + project docs
  - Budget Watchdog — alerts on variance thresholds, identifies root cause from change orders
  - Safety Monitor — reviews daily site logs for hazard language, flags incidents
  - Weather Impact Agent — pulls 10-day forecast, calculates schedule impact per project
  - Subcontractor Comms Agent — sends daily schedule confirmations, follow-ups on overdue items

  ---
  🏥 Industry 4: Medical / Dental / Specialist

  This vertical has sub-profiles that auto-configure on onboarding (General Practice, Dental, Cardiology, Orthopedics, Dermatology, etc.).

  KPI Cards:

  ┌──────────────────────────────┬────────┬───────────────────────────────────┐
  │             Card             │ Metric │            Sub-detail             │
  ├──────────────────────────────┼────────┼───────────────────────────────────┤
  │ Patients Scheduled Today     │ 38     │ 4 openings · 3 overbooked risk    │
  ├──────────────────────────────┼────────┼───────────────────────────────────┤
  │ Net Collections Rate         │ 97.2%  │ Target: 98% · 6 claims pending    │
  ├──────────────────────────────┼────────┼───────────────────────────────────┤
  │ Pending Prior Authorizations │ 14     │ 4 expiring before scheduled visit │
  ├──────────────────────────────┼────────┼───────────────────────────────────┤
  │ No-Show Rate (30-day)        │ 8.3%   │ Up 1.2% from last month           │
  └──────────────────────────────┴────────┴───────────────────────────────────┘

  Left Nav (AI Tools): Clinical Notes Drafter (SOAP), Prior Auth Assistant, Insurance Verifier, Patient Recall Communicator, Denial Appeal Writer

  Priority Actions (AI-generated):
  - Prior auth for patient James H. expires tomorrow — rescheduled for Friday URGENT
  - Insurance claim #88412 (Aetna) denied — reason: missing modifier 25 APPEAL READY
  - Appointment gap 2:00–3:30 PM — 3 recall patients available to fill OPPORTUNITY
  - Lab results for 4 patients in portal — no provider acknowledgment yet REVIEW
  - Patient recall: 47 patients overdue for 6-month hygiene appointment CAMPAIGN READY

  Intelligence Panel: CMS/payer policy changes, ICD/CPT code updates, specialty clinical news, state licensing board alerts, malpractice case summaries
  (specialty-filtered)

  Additional Panes:
  - Schedule Utilization Heatmap — hourly grid: green = booked, yellow = open, red = overbooked. By provider.
  - A/R Aging Buckets — 0-30 / 31-60 / 61-90 / 90+ days by payer and self-pay
  - Insurance Denial Dashboard — denial count by payer, by denial reason, appeal success rate, write-off risk
  - Provider Productivity — RVUs, patients seen, avg visit time, production per hour
  - Case/Treatment Acceptance Rate (Dental/Specialist) — proposals presented vs. accepted by treatment type
  - Referral Source Tracker — referring physicians, patient source breakdown, referral volume trend
  - Patient Lifetime Value — average revenue per patient, retention cohorts, at-risk patients (no visit >18 months)
  - Payer Mix Chart — % Medicare / Medicaid / Commercial / Self-Pay

  Specialty sub-modules:
  - Dental specific: Hygiene chair fill rate, treatment plan completion rate, fluoride/sealant acceptance
  - Cardiology/Specialist: Procedure scheduling lead time, diagnostic wait times, hospital referral outcome tracking
  - Primary Care: Chronic disease registry (diabetic panel, hypertension), preventive care gap list, wellness visit compliance

  AI Agents specific:
  - Prior Auth Bot — auto-submits auth requests, tracks status, escalates expiring auths
  - Claim Scrubber — reviews outgoing claims for common denial triggers before submission
  - Recall Scheduler — identifies overdue patients, drafts personalized outreach (text/email)
  - Denial Analyzer — categorizes denials, identifies patterns, drafts appeal letters
  - Insurance Verifier — confirms active coverage + copay before appointments
  - SOAP Notes Agent — generates draft clinical notes from provider voice input

  ---
  🏠 Industry 5: Real Estate Brokerage

  KPI Cards:

  ┌─────────────────────────────────┬─────────┬──────────────────────────────────────┐
  │              Card               │ Metric  │              Sub-detail              │
  ├─────────────────────────────────┼─────────┼──────────────────────────────────────┤
  │ Active Listings                 │ 63      │ 12 new · 8 price-reduced · 43 active │
  ├─────────────────────────────────┼─────────┼──────────────────────────────────────┤
  │ Pipeline Value (Under Contract) │ $12.4M  │ 18 transactions · avg $689K          │
  ├─────────────────────────────────┼─────────┼──────────────────────────────────────┤
  │ Commission Revenue MTD          │ $84,200 │ 73% of monthly target                │
  ├─────────────────────────────────┼─────────┼──────────────────────────────────────┤
  │ Agent Productivity Index        │ 6.2     │ 22 agents · target: 7.0              │
  └─────────────────────────────────┴─────────┴──────────────────────────────────────┘

  Left Nav (AI Tools): Listing Description Writer, CMA Generator, Offer Analyzer, Client Communicator, Market Report Builder

  Priority Actions (AI-generated):
  - Listing agreement for "4821 Oak Trail" expires in 3 days — renew or release URGENT
  - Client Martinez — 11 showings, no offer — price reduction analysis ready REVIEW
  - New lead "Brad Collins" — buyer pre-approved $750K — no agent assigned yet ASSIGN
  - Offer deadline 5:00 PM today on "2200 Ridgewood Dr" — 3 offers received DUE TODAY
  - Agent Kim Tran — 0 closings in 45 days — coaching flag triggered TOMORROW

  Intelligence Panel: MLS daily stats, Fed rate announcements, local market inventory shifts, competitor brokerage moves, new construction announcements

  Additional Panes:
  - Sales Pipeline Funnel — lead → showing → offer → under contract → closed. Count + $ value at each stage.
  - Agent Leaderboard — ranked by closings, GCI, active pipeline, days since last close
  - Days on Market Tracker — listings sorted by DOM, benchmark vs. market average, price reduction history
  - Commission Forecast — projected closings × expected commission = forward revenue by week/month
  - Lead Source Attribution — Zillow / Realtor.com / Referral / Open House / Social / Direct — conversion rates by source
  - Expired & Withdrawn Recovery List — AI-identified listings that expired from competitors — prospecting opportunities
  - Market Trend Charts — median list price, median sale price, list-to-sale ratio, months of inventory — by zip code
  - Transaction Checklist Tracker — per active deal: contingency deadlines, inspection scheduled, title ordered, closing date countdown

  AI Agents specific:
  - Listing Optimizer — analyzes listing performance, suggests price adjustments, photo improvements, description rewrites
  - Lead Scorer & Router — scores inbound leads by likelihood to transact, routes to best-fit agent
  - Showing Scheduler — coordinates showing requests with sellers, buyers, agents
  - CMA Bot — generates comparative market analyses from MLS data on demand
  - Market Analyst — weekly market condition report per zip code, auto-distributed to agents
  - Transaction Coordinator Agent — tracks all deadlines per open transaction, sends reminders to all parties

  ---
  Part 4: Universal AI Agents (All Industries)

  ┌─────────────────────┬─────────────────────────────────────────────────────────────────┬─────────────────────────────────────────────────────────────┐
  │        Agent        │                            Function                             │                      Learns Over Time                       │
  ├─────────────────────┼─────────────────────────────────────────────────────────────────┼─────────────────────────────────────────────────────────────┤
  │ Daily Brief         │ AI morning briefing: overnight events, today's priorities,      │ Learns user's reading preferences, what they act on         │
  │                     │ anomalies                                                       │                                                             │
  ├─────────────────────┼─────────────────────────────────────────────────────────────────┼─────────────────────────────────────────────────────────────┤
  │ Email Intelligence  │ Inbox triage: classify urgency, draft replies, identify         │ Learns communication patterns, preferred tone               │
  │                     │ follow-ups                                                      │                                                             │
  ├─────────────────────┼─────────────────────────────────────────────────────────────────┼─────────────────────────────────────────────────────────────┤
  │ Deadline Sentinel   │ Tracks all time-sensitive items across all sources              │ Learns which deadlines the user tends to miss; escalates    │
  │                     │                                                                 │ earlier                                                     │
  ├─────────────────────┼─────────────────────────────────────────────────────────────────┼─────────────────────────────────────────────────────────────┤
  │ Anomaly Detector    │ Flags unusual patterns vs. 90-day baseline                      │ Learns normal operating range per tenant                    │
  ├─────────────────────┼─────────────────────────────────────────────────────────────────┼─────────────────────────────────────────────────────────────┤
  │ Intelligence        │ Industry news, filtered to active cases/projects                │ Learns which sources and topics the user finds valuable     │
  │ Curator             │                                                                 │                                                             │
  ├─────────────────────┼─────────────────────────────────────────────────────────────────┼─────────────────────────────────────────────────────────────┤
  │ Data Sync Agent     │ Keeps imported tables fresh from connected sources              │ Learns ingestion patterns, self-heals on schema drift       │
  ├─────────────────────┼─────────────────────────────────────────────────────────────────┼─────────────────────────────────────────────────────────────┤
  │ Goal Coach          │ Tracks goal progress, sends nudges, identifies blockers         │ Learns motivation cadence from what drives action           │
  ├─────────────────────┼─────────────────────────────────────────────────────────────────┼─────────────────────────────────────────────────────────────┤
  │ Report Generator    │ Produces weekly/monthly performance reports                     │ Learns preferred report format and distribution list        │
  └─────────────────────┴─────────────────────────────────────────────────────────────────┴─────────────────────────────────────────────────────────────┘

  ---
  Part 5: Database Import System

  IMPORT SOURCES
  ├── CSV / Excel upload       → drag-and-drop, column mapping UI
  ├── Direct SQL connection    → PostgreSQL / MySQL / MSSQL / SQLite
  ├── REST API webhook         → push data from any source
  ├── Google Sheets sync       → live-linked, auto-refresh
  └── Practice/Case Mgmt APIs  → Clio, Procore, Dentrix, MLS, QuickBooks
       (via pre-built connectors per industry)

  COLUMN MAPPING ENGINE
    1. AI auto-maps uploaded columns to AIOS schema fields
    2. User confirms or corrects
    3. Mapping saved as template for future imports
    4. Agents immediately begin working against new data

  DATA TABLE BROWSER
    → View all imported tables
    → Row count, schema, last sync time
    → Query builder (natural language → SQL)
    → "Ask AIOS about this table" chat interface

  ---
  Part 6: Self-Learning & Autonomous Improvement

  ┌────────────────────────┬───────────────────────────────────────────────────────────────────────────────────────────────────────────┐
  │       Mechanism        │                                               What It Does                                                │
  ├────────────────────────┼───────────────────────────────────────────────────────────────────────────────────────────────────────────┤
  │ Feedback Loops         │ Every Priority Action has thumbs up/down. Agent learns which action types get acted on.                   │
  ├────────────────────────┼───────────────────────────────────────────────────────────────────────────────────────────────────────────┤
  │ Pattern Memory         │ Long-term vector store records: what alerts triggered responses, what was dismissed.                      │
  ├────────────────────────┼───────────────────────────────────────────────────────────────────────────────────────────────────────────┤
  │ Agent Health Monitor   │ Watches all agents for error rate spikes, timeout patterns, hallucinations. Auto-restarts failing agents. │
  ├────────────────────────┼───────────────────────────────────────────────────────────────────────────────────────────────────────────┤
  │ Prompt Evolution       │ Over time, agent system prompts are auto-tuned based on output quality scores.                            │
  ├────────────────────────┼───────────────────────────────────────────────────────────────────────────────────────────────────────────┤
  │ Onboarding Calibration │ First 30 days: AIOS asks 3 feedback questions per week to calibrate priorities.                           │
  ├────────────────────────┼───────────────────────────────────────────────────────────────────────────────────────────────────────────┤
  │ Anomaly Learning       │ After each anomaly is reviewed, the user labels it: real issue / false positive. Model updates threshold. │
  └────────────────────────┴───────────────────────────────────────────────────────────────────────────────────────────────────────────┘

  ---
  Part 7: Technical Stack

  ┌────────────────┬──────────────────────────────────────────────────────────────────────────────────┐
  │     Layer      │                                    Technology                                    │
  ├────────────────┼──────────────────────────────────────────────────────────────────────────────────┤
  │ Backend        │ Python / FastAPI                                                                 │
  ├────────────────┼──────────────────────────────────────────────────────────────────────────────────┤
  │ Frontend       │ HTML/CSS/JS (dark-mode-first, matches existing codebase pattern)                 │
  ├────────────────┼──────────────────────────────────────────────────────────────────────────────────┤
  │ LLM / Agents   │ Anthropic Claude Sonnet 4.6 (tool use + extended thinking for complex reasoning) │
  ├────────────────┼──────────────────────────────────────────────────────────────────────────────────┤
  │ Database       │ PostgreSQL + pgvector (tenant_id on every table)                                 │
  ├────────────────┼──────────────────────────────────────────────────────────────────────────────────┤
  │ Real-time      │ Server-Sent Events (SSE) for live agent activity panel                           │
  ├────────────────┼──────────────────────────────────────────────────────────────────────────────────┤
  │ Auth           │ JWT per tenant, TOTP (matches existing auth.py)                                  │
  ├────────────────┼──────────────────────────────────────────────────────────────────────────────────┤
  │ Job Scheduling │ APScheduler (matches existing) — one scheduler per agent per tenant              │
  ├────────────────┼──────────────────────────────────────────────────────────────────────────────────┤
  │ Vector Memory  │ pgvector extension — per-tenant namespace                                        │
  ├────────────────┼──────────────────────────────────────────────────────────────────────────────────┤
  │ File Import    │ pandas (CSV/Excel), SQLAlchemy (SQL), requests (API)                             │
  ├────────────────┼──────────────────────────────────────────────────────────────────────────────────┤
  │ Deployment     │ Railway (matches existing pipeline)                                              │
  └────────────────┴──────────────────────────────────────────────────────────────────────────────────┘

  ---
  Part 8: Industry Scaling Template

  To add a new industry beyond the 5 initial verticals:

  1. Create industry_config/<industry>.json — defines KPI card labels, nav items, agent list, tool list, alert categories, import schema hints
  2. Register agents in agents/ directory — each agent is a Python class inheriting BaseAgent
  3. Define data model extensions — any industry-specific tables added to data_tables registry
  4. Map to dashboard template — the universal shell auto-populates from the config JSON

  Industries that can be added with minimal effort given this architecture: Accounting/CPA firms, Insurance agencies, Restaurants/Hospitality,
  Retail/eCommerce, Property Management, Financial Advisory, Staffing Agencies, Marketing Agencies.

  ---
  Part 9: Implementation Phases

  ┌──────────────────┬──────────────────────────────────────────────────────────────────────────────────────┬─────────────────────────────────────────┐
  │      Phase       │                                        Scope                                         │                 Outcome                 │
  ├──────────────────┼──────────────────────────────────────────────────────────────────────────────────────┼─────────────────────────────────────────┤
  │ 1 — Shell        │ Universal dashboard shell, auth, dark/light, left nav, KPI cards, SSE agent activity │ Working UI skeleton with live data feed │
  ├──────────────────┼──────────────────────────────────────────────────────────────────────────────────────┼─────────────────────────────────────────┤
  │ 2 — Legal        │ Full legal module (existing codebase head start from GBP work)                       │ First fully-functional industry         │
  ├──────────────────┼──────────────────────────────────────────────────────────────────────────────────────┼─────────────────────────────────────────┤
  │ 3 — Core Agents  │ Daily Brief, Deadline Sentinel, Email Intelligence, Intelligence Curator             │ Universal agent layer live              │
  ├──────────────────┼──────────────────────────────────────────────────────────────────────────────────────┼─────────────────────────────────────────┤
  │ 4 — Data Import  │ CSV/Excel, column mapper, table browser, natural language query                      │ Database import system live             │
  ├──────────────────┼──────────────────────────────────────────────────────────────────────────────────────┼─────────────────────────────────────────┤
  │ 5 — Medical      │ Medical/Dental module, Prior Auth agent, Denial Analyzer                             │ Second industry live                    │
  ├──────────────────┼──────────────────────────────────────────────────────────────────────────────────────┼─────────────────────────────────────────┤
  │ 6 — Construction │ Construction module, Permit Watcher, RFI Agent                                       │ Third industry live                     │
  ├──────────────────┼──────────────────────────────────────────────────────────────────────────────────────┼─────────────────────────────────────────┤
  │ 7 — Brokerage    │ Real estate module, Listing Optimizer, Lead Router                                   │ Fourth industry live                    │
  ├──────────────────┼──────────────────────────────────────────────────────────────────────────────────────┼─────────────────────────────────────────┤
  │ 8 — AI Agency    │ AI agency module, Client Health Monitor, Agent Matrix                                │ Fifth industry live                     │
  ├──────────────────┼──────────────────────────────────────────────────────────────────────────────────────┼─────────────────────────────────────────┤
  │ 9 — Learning     │ Feedback loops, pattern memory, prompt evolution, anomaly calibration                │ Self-improving layer live               │
  ├──────────────────┼──────────────────────────────────────────────────────────────────────────────────────┼─────────────────────────────────────────┤
  │ 10 — Scale       │ Multi-tenant onboarding, billing metering, white-label config                        │ SaaS-ready                              │
  └──────────────────┴──────────────────────────────────────────────────────────────────────────────────────┴─────────────────────────────────────────┘