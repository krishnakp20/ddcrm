<?php
/**
 * DialDesk CRM - lead loader for Vicidial.
 *
 * Runs on a Vicidial server (cron, every minute). It asks the CRM for the leads waiting for this server and adds each one to its
 * Vicidial list with Vicidial's own add_lead API (on this same server), then tells the CRM what happened to every lead.
 * Nothing is ever removed from the dialer. The Vicidial API login stays in this server's config file; the CRM never sees it.
 *
 *   php vicidial_leads.php             normal run (cron)
 *   php vicidial_leads.php --check     test the CRM key and the Vicidial API login, load nothing
 *
 * Settings: the same vicidial_push.config.php as the pusher, plus the three 'vici_api_*' lines (see the sample).
 */

if (PHP_SAPI !== 'cli') { exit("Run this from the command line.\n"); }

$cfgFile = __DIR__ . '/vicidial_push.config.php';
if (!is_file($cfgFile)) { fwrite(STDERR, "Missing $cfgFile (copy vicidial_push.config.sample.php and fill it in)\n"); exit(2); }
$cfg = require $cfgFile;
foreach (['vici_api_user', 'vici_api_pass'] as $k) {
    if (empty($cfg[$k])) { fwrite(STDERR, "Set '$k' in $cfgFile (a Vicidial API user with 'add_lead' permission)\n"); exit(2); }
}
$apiUrl = opt($cfg, 'vici_api_url', 'http://127.0.0.1/vicidial/non_agent_api.php');
$maxSeconds = (int)(opt($cfg, 'max_seconds', 50));
$check = isset(getopt('', ['check'])['check']);

// works on old PHP too (Vicibox ships PHP 5.x): no "??", no [$a, $b] = ..., no arrow functions
function opt($a, $k, $d = null) { return (is_array($a) && isset($a[$k])) ? $a[$k] : $d; }
function utf8ize($v) {
    if (is_array($v)) { foreach ($v as $k => $x) { $v[$k] = utf8ize($x); } return $v; }
    return is_string($v) ? @iconv('UTF-8', 'UTF-8//IGNORE', $v) : $v;
}
function to_json($v) {
    $flags = (defined('JSON_PARTIAL_OUTPUT_ON_ERROR') ? JSON_PARTIAL_OUTPUT_ON_ERROR : 0);
    if (defined('JSON_INVALID_UTF8_SUBSTITUTE')) { $flags |= JSON_INVALID_UTF8_SUBSTITUTE; } else { $v = utf8ize($v); }
    return json_encode($v, $flags);
}

function logline($m) { echo '[' . date('Y-m-d H:i:s') . "] $m\n"; }

$lock = fopen(sys_get_temp_dir() . '/dialdesk_leads.lock', 'c');
if (!$lock || !flock($lock, LOCK_EX | LOCK_NB)) { logline('Another run is still going, stopping.'); exit(0); }

function crm($cfg, $path, $body = null) {
    $url = rtrim($cfg['crm_url'], '/') . $path;
    for ($try = 1; $try <= 4; $try++) {
        $ch = curl_init($url);
        curl_setopt_array($ch, [CURLOPT_RETURNTRANSFER => true, CURLOPT_POST => true, CURLOPT_TIMEOUT => 60, CURLOPT_CONNECTTIMEOUT => 15,
            CURLOPT_HTTPHEADER => ['Authorization: Bearer ' . $cfg['server_key'], 'Content-Type: application/json', 'Accept: application/json'],
            CURLOPT_POSTFIELDS => to_json($body === null ? new stdClass() : $body),
            CURLOPT_SSL_VERIFYPEER => opt($cfg, 'verify_ssl', true), CURLOPT_SSL_VERIFYHOST => (opt($cfg, 'verify_ssl', true)) ? 2 : 0]);
        $res = curl_exec($ch);
        $code = (int)curl_getinfo($ch, CURLINFO_HTTP_CODE);
        $err = curl_error($ch);
        curl_close($ch);
        if ($res !== false && $code > 0 && $code < 500) { return [$code, json_decode($res, true)]; }
        logline("CRM not reachable or busy (try $try, HTTP $code $err)");
        sleep(2 * $try);
    }
    return [0, null];
}

/** Adds one lead through Vicidial's add_lead. Returns [status, vicidial lead id|null, message]. */
function add_lead($cfg, $apiUrl, $it) {
    $p = [
        'source' => opt($cfg, 'vici_api_source', 'dialdesk'), 'user' => $cfg['vici_api_user'], 'pass' => $cfg['vici_api_pass'], 'function' => 'add_lead',
        'phone_number' => $it['phone_number'], 'phone_code' => $it['phone_code'], 'list_id' => $it['list_id'],
        'vendor_lead_code' => $it['vendor_lead_code'], 'duplicate_check' => $it['dup_check'] === 'NONE' ? '' : $it['dup_check'],
    ];
    $custom = [];
    foreach ($it['fields'] as $to => $value) {
        if (strpos($to, 'custom:') === 0) { $custom[substr($to, 7)] = $value; } else { $p[$to] = $value; }
    }
    if ($custom) { $p['custom_fields'] = 'Y'; $p = array_merge($p, $custom); }
    $p = array_filter($p, function ($v) { return $v !== ''; });
    $ch = curl_init($apiUrl);
    curl_setopt_array($ch, [CURLOPT_RETURNTRANSFER => true, CURLOPT_POST => true, CURLOPT_POSTFIELDS => http_build_query($p), CURLOPT_TIMEOUT => 20,
        CURLOPT_CONNECTTIMEOUT => 5, CURLOPT_SSL_VERIFYPEER => opt($cfg, 'vici_api_verify_ssl', true), CURLOPT_SSL_VERIFYHOST => (opt($cfg, 'vici_api_verify_ssl', true)) ? 2 : 0]);
    $res = curl_exec($ch);
    $err = curl_error($ch);
    curl_close($ch);
    if ($res === false) { return ['failed', null, "Vicidial API not reachable: $err"]; }
    $res = trim(preg_replace('/\s+/', ' ', strip_tags($res)));
    if (stripos($res, 'SUCCESS') === 0) {
        // "SUCCESS: add_lead LEAD HAS BEEN ADDED - phone|list_id|lead_id|api user"
        $tail = strpos($res, ' - ') !== false ? substr($res, strpos($res, ' - ') + 3) : $res;
        $parts = explode('|', $tail);
        $id = (isset($parts[2]) && ctype_digit(trim($parts[2]))) ? (int)trim($parts[2]) : null;
        return ['sent', $id, ''];
    }
    if (stripos($res, 'DUPLICATE') !== false) { return ['duplicate', null, substr($res, 0, 250)]; }
    return ['failed', null, substr($res, 0, 250)];
}

if ($check) {
    list($code, $r) = crm($cfg, '/api/dialer/leads/claim', null);
    logline($code === 200 ? 'CRM key: OK (note: this check may have claimed waiting leads; they return to the queue in 10 minutes)' : "CRM key: FAILED (HTTP $code " . json_encode($r) . ')');
    $probe = http_build_query(['source' => opt($cfg, 'vici_api_source', 'dialdesk'), 'user' => $cfg['vici_api_user'], 'pass' => $cfg['vici_api_pass'], 'function' => 'version']);
    $res = @file_get_contents($apiUrl . '?' . $probe);
    logline('Vicidial API: ' . ($res === false ? 'NOT REACHABLE' : trim(substr(strip_tags($res), 0, 200))));
    exit($code === 200 && $res !== false ? 0 : 1);
}

$started = time();
$total = ['sent' => 0, 'duplicate' => 0, 'failed' => 0];
while (time() - $started < $maxSeconds) {
    list($code, $r) = crm($cfg, '/api/dialer/leads/claim', null);
    if ($code !== 200) { logline("CRM refused (HTTP $code " . json_encode($r) . ')'); exit(1); }
    $items = opt($r, 'leads', array());
    if (!$items) { break; }
    $results = [];
    foreach ($items as $it) {
        list($status, $leadId, $msg) = add_lead($cfg, $apiUrl, $it);
        $total[$status]++;
        $results[] = ['delivery_id' => $it['delivery_id'], 'status' => $status, 'lead_id' => $leadId, 'error' => $msg];
        if ($status === 'failed' && stripos($msg, 'not reachable') !== false) { break; }  // do not hammer a dead API
    }
    list($rc) = crm($cfg, '/api/dialer/leads/result', ['results' => $results]);
    if ($rc !== 200) { logline("Could not report results to the CRM (HTTP $rc); they will be offered again."); exit(1); }
    if (count($results) < count($items)) { break; }
}
if (array_sum($total)) { logline("Loaded: {$total['sent']}, already there: {$total['duplicate']}, failed: {$total['failed']}"); }
exit($total['failed'] ? 1 : 0);
