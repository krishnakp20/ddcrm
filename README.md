# DialDesk CRM

Multi-client call-centre CRM. FastAPI + PostgreSQL backend, React (Vite) frontend.
Built step by step; the scope is in the PRD "DialDesk CRM – Product Requirements Document".
Earlier experimental code (calls, campaigns, tag forms) is kept in `_archive/` and is not part of the running app.

## What works now

- **Login** with the DialDesk branding (logo and colours).
- **Dashboard and menu** for the DialDesk admin: clients waiting for review, active clients, quick actions.
- **Client onboarding (two steps)**
  1. **Basic registration.** On the login page a company clicks "Register your company" and gives only the basics: company name, GSTIN, one contact person (name, mobile, email), and accepts the terms. GSTIN is checked (format and check digit), and duplicate GSTIN / PAN / login email are blocked. A hidden field and a limit of 5 registrations per hour per connection reduce spam. The admin can also **Add client** directly (optionally activating at once).
  2. **Admin activates.** The admin sees the registration on the dashboard, opens it and clicks **Activate** (or Reject with a reason). Activation creates the client's administrator login and sends the welcome message (email, SMS, WhatsApp) with a link to set a password. No password is typed on the registration form.
  3. **The client completes the profile after login** under *Company profile*: address (state and PAN are derived from the GSTIN), billing address, more contact persons, services, documents (PDF/JPG/PNG up to 5 MB, stored privately) and a company logo. A checklist shows how complete the profile is. Company name, GSTIN, PAN and the login email are locked for the client; only DialDesk can change them. Documents wait for the admin to approve or reject them.
  - The admin can suspend / re-activate a client, and edit any client's details on their behalf.
- **Plans and billing setup**
  - **Plans** (menu): create a price plan with the full field list (plan type and period, setup fee, subscription, credit and top-up rules, inbound day/night, outbound and multi-language call charges with pulse and a calculated rate per pulse, miss call, IVR, VFO, SMS, email, WhatsApp, users, seats and remote users). Amounts are exact decimals; rates per pulse are calculated, not typed.
  - **Approval:** a new plan waits for approval. Rejected plans can be edited and sent again. An approved plan is locked so billing never changes under a client; to change prices, clone it into a new plan. With more than one admin, a plan must be approved by someone other than its creator. Approved plans can be retired (not given to new clients; existing clients keep them).
  - **Give a plan to a client** (client page, *Plan & billing* tab) with an **effective date**. To change plans later, add a new plan with a later date; the earlier plan automatically ends the day before. A change that has not started yet can be cancelled; plans that started are never edited or deleted. The very first plan may start up to 90 days in the past.
  - **Users we do not bill:** tick users (for example your own support agents) that the client must not be charged for. The page shows billable users, free users in the plan and the extra user charge.
- **Users, departments, roles and permissions** (menu: Access)
  - **Three kinds of user:** DialDesk admin users, client users (belong to one client company) and agents (DialDesk's shared agents, or one client's own). Adding a user sends them an invitation by email, SMS and WhatsApp with a link to set their own password; no one types a password for someone else. A "Send password link" button also resets a forgotten password.
  - **Departments:** a department master for DialDesk and one for each client. A user is placed in a department of their own company. Departments with users cannot be deleted; switch them off instead.
  - **Roles:** built-in roles (Super admin, Operations, Accounts, Support, Client admin, Client manager, Agent) plus custom roles you create. A role is a set of permissions for one kind of user. The Super admin role is locked.
  - **Permissions per user:** on top of the role, tick or untick individual permissions for one person; the screen shows what was added or removed for that user.
  - **Safety rules:** nobody can give access they do not have themselves; client users only see and manage their own company's users and departments; you cannot change your own role or switch yourself off; only a super admin can touch a super admin; a user's type, company and (after sign-up) login email cannot be changed.
  - Every screen and API call is checked against permissions, so what a person sees in the menu is exactly what the server lets them do.
- **Call & ticket forms** (menu: Call & ticket forms; DialDesk admin, or a client admin who is given the right *Change form setup*)
  - **Inbound:** one form per client (menu: *Inbound & ticket form*). It also opens when an agent creates a ticket for the client.
  - **Outbound:** every campaign has its own tagging form (see Campaigns below). Fields, scenarios and the rest work the same way.
  - **Fields:** text, text area, whole number, decimal, date, date and time, time, dropdown, multi-select, radio, tick box, mobile number, email. Validation (letters and numbers, letters, digits, custom pattern, length, minimum and maximum), mandatory, help text, order. A field is shown always or only for chosen scenarios.
  - **Value lists with levels** (for example Country > State > City, up to 5 levels): a dropdown can depend on another one, so choosing a country shows only its states. Edit values column by column, or import a CSV/Excel file. A shared "India states" list is provided; a dropdown can also have its own simple values (the *Values* button).
  - **Scenario tree** (call disposition): up to 5 levels, each option can have an outcome (connected, not connected, call back, converted, closed, do not call) and can bring its own fields and make some of them mandatory.
  - **Preview** shows the form exactly as an agent will see it (scenario levels, dependent dropdowns, fields that change with the scenario) and checks the answers with the same rules the call screen and tickets will use.
  - **Copy:** a campaign form can be copied from another campaign (of the same client, or by DialDesk staff from any client). The copy is independent afterwards. Value lists of the client are shared between its campaigns; a field's own values are copied. The inbound form can be copied from another client by DialDesk staff. Client users only ever see and change their own company's forms.
- **Campaigns** (menu: Campaigns; rights *See campaigns* / *Create and change campaigns* can be given to client users)
  - A client can have any number of outbound campaigns: name, code (generated if empty), dates, description. Status: Draft → Active → Paused → Closed (a closed campaign can be reopened as paused). A campaign can only be activated once its tagging form is set up, and only a draft can be deleted.
  - Open a campaign and use its **Tagging form** tab to build the form, or copy it from another campaign. Changing one campaign's form never changes another's.
  - **Campaign data** (campaign > *Data* tab; rights *See campaigns* / *Create and change campaigns*):
    - **Upload** a CSV or Excel file (up to 50,000 rows, 10 MB). The first row is the column names; the CRM guesses which column is name, mobile, email, city and reference, and you can change it. Name and mobile number are mandatory for every row; other columns you tick are shown to the agent on the call screen (for example premium due). Invalid rows and numbers already in the campaign are skipped and listed.
    - **Share the data**: leave everyone unticked for a *shared queue* that any allocated agent can take from, or tick agents to split the data evenly between them. *Share with agents* can redo this later for leads not yet called. A mistaken upload can be removed (leads nobody called stay out of harm: only uncalled leads are deleted).
  - **Manual dialing queue** (agent menu *Work queue*): each campaign shows what is waiting (yours, shared, call backs due). *Take next lead* gives due call backs first, then the agent's own data, then the shared queue, and locks that lead to the agent; the call screen opens with the customer, the uploaded details, a *Dial* link (`tel:`) and the campaign's tagging form. The agent can also pick a lead from their own list. The wrap-up lock still applies: no new lead until the call is tagged or skipped.
  - **After each call the lead is updated:** call back (with an optional date and time; default 4 hours; the agent who spoke follows up), done (connected, converted, closed), do not call (never offered again), not connected (retried after 2 hours, retired after 3 tries). A skipped lead returns after 15 minutes. A lead is locked to an agent for up to 2 hours.
  - **Predictive calls** for a number that is in the campaign data are linked to that lead automatically, so the agent sees the uploaded details and the lead is updated when the call is tagged.
- **Agent panel and tagging page** (menu: Agent panel)
  - The dialer opens a link in the agent's browser:
    - Inbound: `/agent/call?phonenumber=2312312&vendor_id=1234&ingroup_id=pms`
    - Predictive (PD): `/agent/call?phonenumber=2312312&vendor_id=1234&campaign_id=CAMP01`
    - Optional but recommended: `call_id` (stops the same call opening twice) and `agent_id` (warns when the wrong agent is signed in).
  - If the agent is not signed in, they sign in and land on the same call.
  - **Dialer IDs** (Client page > Dialer IDs; DialDesk staff): a *vendor ID* belongs to exactly one client (a client can have several); *ingroup IDs* belong to a client (the same name may exist for two clients); *campaign IDs* belong to a campaign (a campaign can have several). The page shows ready-to-copy links for the dialer team.
  - **Who may work what:** a client's own agents work their own client; shared DialDesk agents are allocated to clients on their user page; every agent must also be allocated to a campaign (Campaign > Agents) for predictive calls. A wrong or unmapped id shows a clear message saying what to ask the admin for. Paused, draft and closed campaigns cannot take calls.
  - The page shows the client, mode, phone number, a timer, the customer (found by phone number, or a new caller to add: name and mobile are mandatory), the previous calls of that customer, and the tagging form (inbound form, or the campaign's form for PD). An existing number keeps its saved name; the agent cannot overwrite it by typing a different name.
  - **Create a ticket while tagging:** on the tagging form, tick *Also create a ticket for this call* and add a subject (empty = the last scenario), priority, who gets it and what must be done. The ticket is saved together with the tag, with the same customer, scenario and answers, and is linked to the call; if the ticket has a problem (for example a bad assignee) nothing is saved and the call stays open. This works for inbound, predictive and manual calls (agents need the right *Create tickets, comment, change status and assign*). The *Create ticket* button on the call bar still opens the full ticket page.
  - **Wrap-up lock:** the next call cannot open until the current one is tagged, or skipped with a reason. Unfinished calls older than 4 hours are skipped automatically.
  - - **Tickets** (menu: Tickets; rights *See tickets*, *Create tickets, comment, change status and assign*, *Set the SLA*)
  - **Raising a ticket:** *New ticket* (offline: choose the client, then the customer by mobile number: a known number keeps its saved name) or *Create ticket* on the call screen (the call's client and customer are filled in and the call is linked). The ticket fills in the client's own **inbound form** (scenario levels, dependent dropdowns, mandatory fields), plus subject, priority and description. Agents can only raise tickets for the clients they work for; client users only for their own company.
  - **Status:** Open → In progress → Pending → Resolved → Closed (can be reopened). Resolving or closing needs a note. Assigning a ticket to a person moves an open ticket to In progress.
  - **Assignment:** to a person (DialDesk staff, the client's users and agents, or a shared agent allocated to that client) and/or to a department (DialDesk's or the client's).
  - **SLA:** hours to resolve per priority per client (standard: urgent 4, high 24, medium 48, low 72; change them under *Tickets > SLA settings*). The clock runs from creation to resolution; the list shows time left, overdue, or SLA met. Changing the priority recalculates the due time.
  - **Comments and history:** every status change, assignment and priority change is recorded with who did it, together with the comments.
  - Lists: Open, Mine, Unassigned, Overdue, All, with search and priority filter; DialDesk staff follow the client picked in the top bar. The red number on the menu is overdue tickets.
  - Not built yet for tickets: escalation, attachments, business-hours SLA, 
- **Alerts** (menu: Alerts; right *Set up alerts, and the data webhook of campaigns*; DialDesk staff pick the client in the top bar, client users manage their own company's)
  - A rule says **when** (new ticket, ticket assigned, ticket resolved or closed, ticket due soon (2 hours before), SLA missed, call tagged), **only when** (optional: ticket priority, call outcome, scenario name contains, or a tagging field equals a value, for example Country = UAE), **who is told** (the assignee, the agent of the call, chosen users, up to 5 extra emails and 5 mobile numbers) and **on which channels** (email, SMS, WhatsApp), with an optional custom message using placeholders such as `{number}`, `{subject}`, `{customer}`, `{due}`, `{link}`.
  - *Add standard alerts* creates: tell the assignee on assignment, warn before the SLA is missed, tell when it is missed. *Test* sends a sample to the people the rule names. *Recent alerts* shows what fired.
  - **The customer can be told too** (SMS / WhatsApp to the mobile number on the call or ticket). Messages can also use the answers on the form: the name of a form field in lower case with underscores, for example `{model_no}` or `{remarks}`.
  - SLA alerts are checked once a minute by the server and each ticket is alerted only once per kind; only tickets that became late in the last 24 hours are alerted.
  - Messages go through the same sender as the welcome messages: until SMTP / SMS / WhatsApp settings exist in `.env` they are only recorded in *Settings > Notification log*.
- **Client webhook for campaign data** (campaign > *Data* tab > *Data webhook*)
  - Create a key; the address `POST /api/hooks/leads/<key>` is shown once. The client posts one record, a list, or `{"leads": [...]}` (up to 500 per call, 60 calls a minute) with at least `name` and `mobile` (aliases such as `customer_name` and `phone` work). Other fields are kept and shown to the agent. The reply says for each record whether it was accepted, a duplicate or invalid. A new key replaces the old one at once; the webhook can be switched off.
  - **Copy to the dialer:** DialDesk staff can set a dialer address (and an Authorization header). New data from the webhook and from file uploads is then also posted there as JSON (`campaign`, `campaign_ids`, `leads` with name and mobile), after the data is safely saved here. The outcome of each delivery is shown under *Recent deliveries*. Only DialDesk staff can set the address, so a client cannot point the server at any address.
- **Intake channels** (menu: Intake channels; right *Set up alerts, and the data webhook of campaigns*; DialDesk staff pick the client in the top bar)
  - Three ways for a client's customers to write in. Each has its own key (shown once, can be replaced, can be switched off), a default **priority** (which sets the SLA) and an optional default **person / department** to give new tickets to. Every message becomes a ticket with a **source** (Website, WhatsApp, Email) shown in the ticket list, the ticket and the Tickets report (filter by channel with the *mode* filter of that report). The customer's words appear in the conversation as "Customer (channel)". Alerts for *new ticket* and *ticket assigned* fire as for any ticket.
  - **Website form:** `POST /api/intake/<key>/website`. Drop an HTML form on the client's site (the page shows the exact snippet); a normal form post shows a thank-you page with the ticket reference, JSON or `FormData` posts get `{"ok": true, "reference": "T-000123"}`. Name, a message and a mobile or email are required; extra fields are kept in the message. A hidden field catches robots and a limit of 10 posts a minute per visitor address stops floods.
  - **WhatsApp bot:** `POST /api/intake/<key>/whatsapp`. Works directly as the WhatsApp Cloud API webhook (the callback URL, with the key as the verify token), or with any bot that posts `{from, name, message, message_id}`. A new number opens a ticket; later messages from the same number go into its open ticket (a resolved ticket opens again); a repeated `message_id` is ignored; the number becomes a customer record.
  - **Email:** `POST /api/intake/<key>/email`, for a mail provider's inbound webhook (SendGrid, Mailgun, Postmark or your own relay), JSON or form post (`from`, `subject`, `text`, `message_id`, `in_reply_to`). A reply joins its ticket when the subject has the ticket number (for example `[T-000123]`) or `in_reply_to` matches an earlier message; automatic replies and repeats are ignored. A sender with no known customer is kept on the ticket as name and email.
  - *Recent messages* lists what each channel received: ticket created, added to a ticket, repeat ignored, or rejected (with the reason). Set `APP_BASE_URL` to the public address so the addresses shown are the ones to give out.
  - Not built yet for intake: sending the agent's replies back out to the customer on WhatsApp / email (replies are written in the ticket; alerts can notify staff), attachments, and connecting a mailbox directly (IMAP).
- **Reports** (menu: Reports; right *See and download reports*; DialDesk staff follow the client picked in the top bar, client users see only their own company)
  - Four reports with a date range (Today, Yesterday, Last 7 / 30 days, This month, or any dates up to one year; dates are in the server time zone):
    - **Calls:** every call with client, campaign, mode (inbound / predictive / manual), agent, customer, scenario, outcome, status, minutes and notes; totals for tagged, skipped, not tagged, tag rate and average time. Filters: mode, status, outcome, campaign.
    - **Tickets:** every ticket with priority, status, owner, department, due, resolved, hours to resolve and SLA result; totals for open, resolved, overdue, SLA met % and average hours. Filters: status, priority.
    - **Agents:** per agent, calls, tagged, skipped, converted, call backs, average minutes, tickets raised and tickets resolved.
    - **Campaigns:** per campaign, leads loaded and their state (not called, call back, done, do not call), leads called, and calls, tagged and converted in the range.
  - **Download CSV** gives the whole table for the chosen range and filters (not just the page on screen), with a header row, opens correctly in Excel (UTF-8), and text that starts with `=`, `+`, `-` or `@` is neutralised so it cannot run as a formula.
- **Dialer data: CDR, recordings and APR** (menus: Call records (CDR), Agent performance (APR); System > Dialer servers; install guide in `dialer/README.md`)
  - Each of your Vicidial servers runs `dialer/vicidial_push.php` from cron and posts new rows of `vicidial_closer_log` (inbound calls), `vicidial_log` (outbound calls), `recording_log` (recording paths) and `vicidial_agent_log` (agent time) to the CRM over HTTPS. Each server has its own key and a list of allowed IP addresses. The first run goes 12 months back.
  - **Dialer servers** page (DialDesk staff): add a server, its IPs, time zone and recording address; see when data last arrived; calls per day; the campaign / ingroup names not matched to a client yet (with *Match now*); the pause-code meanings; *Rebuild the APR*.
  - A call is matched to its client by the **ingroup ID** (inbound) or **campaign ID** (outbound) in the client's Dialer IDs, optionally tagged with the dialer server (the same name on two servers can be two clients). Unmatched calls are kept and matched the moment the ID is added.
  - **Call records (CDR):** filters by date, direction, status, agent, phone number, recording, server and (staff) unmatched; a summary (calls, recordings, abandoned, average talk and queue); open a call to see it with the CRM tag and **play the recording** (played through the CRM with a permission check). Clients see their own company; agents see only calls taken with their own dialer ID. CSV download.
  - **Agent performance (APR):** per agent per day (or per agent): calls, ACHT, talk, wait, wrap-up, net and productive login, lunch / tea / bio / operation / quality / refresher / training / other pause, utilization (talk / login), first and last activity. DialDesk staff only. CSV download.
  - Housekeeping: `python purge_dialer_data.py --months 24 --commit` keeps a rolling window.
- **Allocations and download** (campaign > Data): every upload has a **name**; the agent's Work queue lets them choose the campaign and then an allocation (yours / shared counts) and take its numbers one at a time. **Download** gives the numbers as a file for a dialer that is not connected: CRM columns, or Vicidial *Load Leads* layout (you type the list ID; Do-not-call numbers are never included; each download is audited). Numbers stay in the CRM, so the agent screen still opens when that dialer connects the call.
- **Leads to the dialer** (campaign > Data > *Send to the dialer*; `dialer/vicidial_leads.php`): leads from a file upload or from the client's webhook (one record or a batch) are lined up for the campaign's Vicidial list and added by the script on that server through Vicidial's `add_lead` API. Add only, never deleted; duplicates reported; failed leads retried; field mapping per list (name, email, city, any data column, custom fields). Setup in `dialer/README.md` section 6.
- After login, client users see their **company logo** in the top bar.
- **Settings**: edit the acknowledgement and welcome message texts, and see every message sent in the **Notification log**.

## Setup

### 1. Database

```powershell
& "C:\Program Files\PostgreSQL\16\bin\psql.exe" -U postgres -h localhost -c "CREATE DATABASE ddcrm;"
```

### 2. Backend

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env      # then edit DATABASE_URL password and SECRET_KEY
python -m app.seed          # creates the DialDesk admin
uvicorn app.main:app --reload --port 8000
```

When the schema changes during development, start from an empty database: `python -m app.seed --reset`. New columns on existing tables are added on start by `ensure_columns()` in `backend/app/database.py`.
API docs: http://localhost:8000/docs

### 3. Frontend

```powershell
cd frontend
npm install
npm run dev
```

Open http://localhost:5173 and sign in as `admin@dialdesk.in` / `admin123` (change it before real use).

## Connecting email, SMS and WhatsApp

Until these are set in `backend/.env`, every message is only **recorded** (Settings → Notification log) so the whole flow can be tested.

- **Email:** fill `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_FROM`.
- **SMS / WhatsApp:** set `SMS_API_URL` / `SMS_API_KEY` and `WHATSAPP_API_URL` / `WHATSAPP_API_KEY`. The CRM sends `POST {"to": "+91...", "message": "..."}` with `Authorization: Bearer <key>`. Your provider's real request format may differ; the sender is one small function in `backend/app/services/notify.py` to adapt.
- Set `APP_BASE_URL` to the public address of the frontend so links in messages are correct.

## Migrating from the old CRM

`backend/migrate_old.py` reads the old MySQL database (`db_dialdesk`; set `OLD_DB_HOST`, `OLD_DB_PORT`, `OLD_DB_USER`, `OLD_DB_PASSWORD` if it is not on 127.0.0.1:3307 as root) and moves **active clients** (`registration_master.status = 'A'`).

```powershell
cd backend
.\.venv\Scripts\python.exe migrate_old.py                 # dry run: reads, checks and reports; writes nothing
.\.venv\Scripts\python.exe migrate_old.py --commit        # really write
.\.venv\Scripts\python.exe migrate_old.py --commit --only clients,users --client 605
```

- **Moved now:** clients (company, GSTIN, addresses, contacts), client users, agents (dedicated agents become the client's own agents; the rest are shared agents allocated to their clients), dialer ids (the old client number as vendor id, plus ingroup ids), the inbound form (fields, dropdown values) and the scenario tree.
- **Safe to repeat:** every moved row is remembered in `legacy_map`; a second run skips it.
- **Passwords are never copied.** The old tables hold plain-text passwords. Moved users get an unusable password: send each a set-password link from the Users page. Agents without a valid email in the old data get `agentNN@legacy.invalid`; correct it before inviting.
- **Moved by the second part** (`--only plans,campaigns,calls,outcalls,leads`; `--months 12`, `--leads active|all|none`):
  - **Plans** used by the moved clients (all come in as approved; check the rates) and each client's plan with its start date.
  - **Outbound campaigns** with their forms, dropdown values, scenario trees and the campaign id the dialer knows. Campaigns that were active come in **paused**; activate them when the dialer is ready.
  - **Inbound call history** of the last 12 months as tagged calls (scenario names and the answers on the form), the **customers** found in them (name, email and city are taken from the form field called Name / Email / City when there is one), and **tickets** for calls that were in the old close-loop (open, in progress, closed; due time; the closing remarks as a comment). Calls that were only opened and never tagged are not moved.
  - **Outbound call history** of the last 12 months, and the **campaign data (leads)** of campaigns that are still active (rows without a valid number and repeats are skipped; one old upload of a million "NA" rows is skipped this way).
  - Agents who only appear in old history are created switched off.
- **Run it on a copy first.** Dump the new database, restore it as another database, set `DATABASE_URL` to that copy and run with `--commit` for one or two small clients (`--client 499 --client 641`). Run it twice: the second run must write nothing.
- **Alert matrix** (`--only alertmatrix`): the old matrix tables become alert rules, for incoming and outbound campaigns. `tbl_matrix` / `tbl_obmatrix` (who is told, on email / SMS / WhatsApp) become *call tagged* alerts for the scenario they name, or *ticket still open after N hours* for the escalation levels (N is the old TAT; escalation 1, 2 and 3 without a TAT use 48, 72 and 96 hours). `tbl_sms` / `tbl_template` (and the outbound versions) give the message: those marked to the customer (send type 0) become alerts that text the customer; those for the people in the matrix (send type 1) become the message of their alerts. Old placeholders such as `:Name:`, `:Category1:`, `:SrNo:` become `{customer}`, `{category1}`, `{number}`; form fields become `{field_name}`. People are merged into one rule per scenario, channel and message (at most 5 addresses per rule). An alert only applies to tickets raised after it was created, so old tickets never trigger the moved escalations.
  - Not moved: the TAT per scenario in `tbl_time` (the new SLA is per priority), provider template ids and API keys (set the SMS / WhatsApp provider in `backend/.env` and check the message text against its approved templates), message templates that no one was assigned to receive, and people whose address does not fit their channel.
  - **Review before connecting a provider.** Many moved alerts send to customers on every tagged call exactly as the old CRM did; when SMS / WhatsApp go live they will really send.
- **Alerts** (`--only alerts`): the old per-client alert rules become alert rules here. A scenario alert to a person becomes *call tagged* (scenario contains the old scenario name) with the same email / mobile and message (the old `:Name:`, `:Contact No:`, `:Remarks:` placeholders become `{customer}`, `{mobile}`, `{remarks}`); a close-loop alert to a person and the SMS to the customer on closing become *ticket resolved* (or *assigned*). Not moved: the SMS to callers of **abandoned** calls (needs abandoned-call events from the dialer), DialDesk's own internal digests (`alert_mechanism`), scheduled report emails (`scenario_automate`), and the alert queue and send logs.
- **Not moved:** billing history and invoices, old reports, recordings, SMS / email logs.
- **Looking at the old call data:** *Reports > Calls* (inbound, predictive and manual calls together; use the *mode* filter to separate them). Pick a client in the top bar and the table gets one column per question of that client's form (the old Field1, Field2 … with their real names), plus Category 1 to 5; the CSV has the same columns. Click any call to open every answer, the customer, their other calls and tickets.
- **Garbled text:** the old latin1 columns held UTF-8 text, so dashes and accents came across garbled. The migration now repairs this as it reads; `python fix_mojibake.py --commit` repairs data that was moved earlier (run once after the first migration; safe to repeat).

## Not built yet

Billing and invoices (plans are stored; usage is not yet charged), escalation chains and follow-up groups, sending replies back to customers, scheduled and emailed reports, Alembic migrations, automated tests.
