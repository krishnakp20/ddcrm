<?php
// Copy this file to vicidial_push.config.php (same folder) and fill it in. Keep the copy readable by the cron user only (chmod 600).
return [
    'crm_url'    => 'https://crm.example.com',   // the public address of the CRM (no trailing slash)
    'server_key' => 'PASTE-THE-KEY-FROM-THE-CRM', // CRM > Dialer servers > this server > New key (shown once)
    'verify_ssl' => true,                         // leave true; false only for a test server with a self-signed certificate

    // the Vicidial database on THIS server: a read-only user is enough
    'db_host' => '127.0.0.1',
    'db_port' => 3306,
    'db_name' => 'asterisk',
    'db_user' => 'cron_readonly',
    'db_pass' => 'change-me',

    // only for vicidial_leads.php (loads the CRM's leads into the dialer). Vicidial: Admin > Users > an API user with
    // "Modify Leads" = 1 and API access ("Vdc Agent API Access" = 1, user level 8 or 9). The login stays on this server.
    'vici_api_url'  => 'http://127.0.0.1/vicidial/non_agent_api.php',
    'vici_api_user' => 'crmapi',
    'vici_api_pass' => 'change-me',

    'batch'       => 500,   // rows per request (50 to 1000)
    'max_seconds' => 50,    // stop a run after this long so runs never pile up
    'months_back' => 12,    // first run only: how far back to start
];
