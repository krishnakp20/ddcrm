# Vicidial to CRM: call records (CDR), recordings and agent log (APR)

Each Vicidial server runs a small PHP script from cron. It reads the new rows of four standard tables and posts them to the CRM over HTTPS.
The CRM never connects to your dialers and nothing connects to the CRM database.

| Vicidial table | In the CRM |
|---|---|
| `vicidial_closer_log` | inbound calls (CDR) |
| `vicidial_log` | outbound calls (CDR) |
| `recording_log` | recording path, joined to its call; played through the CRM |
| `vicidial_agent_log` | the APR (agent performance), one row per agent per day |

## 1. In the CRM (once per server)

1. **Dialer servers > Add server.** Give a name, the server's time zone, **every IP address it will post from** (one per line), and the address the recordings are served from (for example `https://rec.example.com`).
   If a server is used by one client only, choose that client: calls that match no ID then go to it.
2. Copy the **key** that is shown (once). A new key can be made later; the old one stops working at once.
3. For each client, on the client's page > **Dialer IDs**, make sure the **ingroup IDs** (inbound) and **campaign IDs** (outbound) are listed. They are how a call is matched to its client.
   The same name on two servers can belong to different clients: choose the **Dialer server** next to the ID.
   Rows that arrive before their ID exists are kept as "not matched" and get their client the moment the ID is added.

## 2. On each Vicidial server

Needs PHP 7.4+ with `curl` and `pdo_mysql`, and a **read-only** MySQL user on the Vicidial database.

```
mkdir -p /opt/dialdesk && cp vicidial_push.php vicidial_push.config.sample.php /opt/dialdesk/
cd /opt/dialdesk && cp vicidial_push.config.sample.php vicidial_push.config.php && chmod 600 vicidial_push.config.php
# edit vicidial_push.config.php: crm_url, server_key, database user
php vicidial_push.php --dry-run        # shows what would be sent
php vicidial_push.php                  # first run: starts 12 months back (use --since=2026-01-01 to change)
```

Cron (every minute; a run that is still busy blocks the next, so runs never pile up):

```
* * * * * php /opt/dialdesk/vicidial_push.php >> /var/log/dialdesk_push.log 2>&1
```

The first run sends 12 months of history in batches of 500 and carries on in the following minutes until it has caught up.
The script keeps no state: each time it asks the CRM where it stopped. If a run fails, the next run continues from the same place.

## 3. How it is kept safe

- **HTTPS only**, a **secret key per server** (stored hashed in the CRM), and the key only works from the **IP addresses listed** for that server.
- **Nothing is trusted from the dialer except the rows.** The client of a call is decided by the CRM from the Dialer IDs, never from what the dialer says. Two clients with one name on the same server means "not matched", never a guess.
- **Repeats are harmless.** Every row has a unique key per server and table, so a resend, a retry or a re-run changes nothing.
- **Limits:** at most 1000 rows and about 6 MB per request, and a rate limit per server. Only the standard Vicidial columns are read; anything else is ignored; bad rows are counted as rejected, not stored.
- **Recordings** are stored as a path. They are played through the CRM with a permission check and a 10-minute link, from the address you set for the server. The dialer server is never shown to clients, and every playback is written to the audit log.
- **Who sees what:** DialDesk staff see all calls and the APR. A client's users see their company's calls and recordings. An agent sees only the calls taken with their own dialer ID (set on the user), for clients they work for.
- **Behind your own reverse proxy** set `TRUST_FORWARDED_FOR=true` in `backend/.env` so the dialer's real IP is read from `X-Forwarded-For`. Leave it off otherwise.
- **Check the feed:** *Dialer servers* shows when each table last arrived (Receiving, Late after 10 minutes, Silent after an hour) and the calls per day for the last 7 days, to compare with Vicidial.

## 4. APR (agent performance)

Built from `vicidial_agent_log`: **login** = pause + wait + talk + wrap-up + dead time; **productive login** = login minus all pause time; **utilization** = talk time / login; **ACHT** = (talk + wrap-up) / calls; **calls** = agent-log rows with talk time.
Pause codes are counted as lunch, tea, bio, operation, quality, refresher, training or other. Codes are guessed from their names; check them under *Dialer servers > Details & pause codes* and press *Rebuild the APR* after changing one.
Shared agents' time is split by client through the campaign they worked on.

## 5. Housekeeping

- `python purge_dialer_data.py --months 24 --commit` (in `backend`) deletes older call records, recordings, agent log and APR days. Run monthly if you want a rolling window.
- To rehearse everything without a real dialer, `make_test_vicidial_db.py` builds a small Vicidial-like database in MySQL.

## 6. Leads to the dialer (predictive / progressive lists)

Leads uploaded in the CRM (file) or posted by a client (campaign webhook, one record or a batch) are added to the campaign's Vicidial list automatically.
The CRM never logs in to the dialer: the script on the Vicidial server fetches its waiting leads and adds them with Vicidial's own `add_lead` API on the same machine.

1. **Vicidial:** make an API user (Admin > Users: user level 8 or 9, "Modify Leads" on, API access on) and a list (Admin > Lists) under the campaign that dials it.
2. **This server:** add the three `vici_api_*` lines of `vicidial_push.config.sample.php` to `vicidial_push.config.php`, copy `vicidial_leads.php` next to `vicidial_push.php`, then test: `php vicidial_leads.php --check`.
3. **Cron** (every minute): `* * * * * php /opt/dialdesk/vicidial_leads.php >> /var/log/dialdesk_leads.log 2>&1`
4. **CRM:** open the campaign > **Data** > **Send to the dialer** > Connect a dialer list: choose the server, the list ID, and what is sent with the number (name, email, city, or any other column of the client's data, to a Vicidial field or `custom:FIELDNAME`).

Rules: add only (nothing is ever deleted in Vicidial); a number already in Vicidial is reported as "already in dialer" (Vicidial's duplicate check: same list, campaign or system); a failed lead is retried every 5 minutes, up to 5 times, then shown as Failed with the reason (use "Try failed again" after fixing it, for example a wrong list ID).
Each lead is sent with `vendor_lead_code` = `CRM<lead id>`. The Vicidial lead id is stored with the delivery.
