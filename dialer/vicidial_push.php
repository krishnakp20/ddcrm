<?php
/**
 * DialDesk CRM - Vicidial pusher.
 *
 * Runs on a Vicidial server (cron, every minute). It asks the CRM where it stopped, reads the new rows of
 *   vicidial_closer_log  (inbound calls)      vicidial_log   (outbound calls)
 *   recording_log        (recording paths)    vicidial_agent_log (agent time, for the APR)
 * and sends them to the CRM over HTTPS in batches. The CRM remembers what it has, so a repeat is harmless.
 * It keeps no state of its own and never writes to the Vicidial database (read-only user is enough).
 *
 *   php vicidial_push.php                       normal run (cron)
 *   php vicidial_push.php --since=2025-10-23    first run: start from this date (default: 12 months back)
 *   php vicidial_push.php --table=agent_log     one table only (closer_log, log, recording_log, agent_log)
 *   php vicidial_push.php --dry-run             show what would be sent, send nothing
 *
 * Settings: copy vicidial_push.config.sample.php to vicidial_push.config.php next to this file and fill it in.
 */

if (PHP_SAPI !== 'cli') { exit("Run this from the command line.\n"); }

$cfgFile = __DIR__ . '/vicidial_push.config.php';
if (!is_file($cfgFile)) { fwrite(STDERR, "Missing $cfgFile (copy vicidial_push.config.sample.php and fill it in)\n"); exit(2); }
$cfg = require $cfgFile;

$opts = getopt('', ['since::', 'table::', 'dry-run', 'batch::']);
$dry = isset($opts['dry-run']);
$batch = max(50, min(1000, (int)opt($opts, 'batch', opt($cfg, 'batch', 500))));
$maxSeconds = (int)(opt($cfg, 'max_seconds', 50));       // stop before the next cron start
$monthsBack = (int)(opt($cfg, 'months_back', 12));
$since = isset($opts['since']) ? $opts['since'] : date('Y-m-d', strtotime("-$monthsBack months"));
if (!preg_match('/^\d{4}-\d{2}-\d{2}$/', $since)) { fwrite(STDERR, "--since must look like 2026-10-31\n"); exit(2); }
$only = opt($opts, 'table');

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

// one run at a time
$lock = fopen(sys_get_temp_dir() . '/dialdesk_push.lock', 'c');
if (!$lock || !flock($lock, LOCK_EX | LOCK_NB)) { logline('Another run is still going, stopping.'); exit(0); }

$started = time();
try {
    $pdo = new PDO("mysql:host={$cfg['db_host']};port=" . opt($cfg, 'db_port', 3306) . ";dbname={$cfg['db_name']};charset=utf8mb4",
        $cfg['db_user'], $cfg['db_pass'], [PDO::ATTR_ERRMODE => PDO::ERRMODE_EXCEPTION, PDO::ATTR_DEFAULT_FETCH_MODE => PDO::FETCH_ASSOC]);
} catch (Exception $e) { logline('Cannot connect to the Vicidial database: ' . $e->getMessage()); exit(1); }

/** Calls the CRM. Retries network errors and 5xx; returns [httpCode, decodedJson|null]. */
function crm($cfg, $method, $path, $body = null) {
    $url = rtrim($cfg['crm_url'], '/') . $path;
    for ($try = 1; $try <= 4; $try++) {
        $ch = curl_init($url);
        $headers = ['Authorization: Bearer ' . $cfg['server_key'], 'Content-Type: application/json', 'Accept: application/json'];
        curl_setopt_array($ch, [CURLOPT_RETURNTRANSFER => true, CURLOPT_HTTPHEADER => $headers, CURLOPT_TIMEOUT => 90, CURLOPT_CONNECTTIMEOUT => 15,
            CURLOPT_SSL_VERIFYPEER => opt($cfg, 'verify_ssl', true), CURLOPT_SSL_VERIFYHOST => (opt($cfg, 'verify_ssl', true)) ? 2 : 0]);
        if ($method === 'POST') {
            curl_setopt($ch, CURLOPT_POST, true);
            curl_setopt($ch, CURLOPT_POSTFIELDS, to_json($body));
        }
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

// How to read the next rows of each table. 'key' is what the CRM reports as "last".
$tables = [
    'closer_log' => ['sql' => 'SELECT * FROM vicidial_closer_log WHERE closecallid > :last ORDER BY closecallid LIMIT %d',
                     'first' => 'SELECT * FROM vicidial_closer_log WHERE call_date >= :since ORDER BY closecallid LIMIT %d', 'key' => 'closecallid'],
    'log'        => ['sql' => 'SELECT * FROM vicidial_log WHERE start_epoch >= :last ORDER BY start_epoch, uniqueid LIMIT %d',
                     'first' => 'SELECT * FROM vicidial_log WHERE call_date >= :since ORDER BY start_epoch, uniqueid LIMIT %d', 'key' => 'start_epoch', 'overlap' => 300],
    'recording_log' => ['sql' => 'SELECT * FROM recording_log WHERE recording_id > :last ORDER BY recording_id LIMIT %d',
                     'first' => 'SELECT * FROM recording_log WHERE start_time >= :since ORDER BY recording_id LIMIT %d', 'key' => 'recording_id'],
    'agent_log'  => ['sql' => 'SELECT * FROM vicidial_agent_log WHERE agent_log_id > :last ORDER BY agent_log_id LIMIT %d',
                     'first' => 'SELECT * FROM vicidial_agent_log WHERE event_time >= :since ORDER BY agent_log_id LIMIT %d', 'key' => 'agent_log_id'],
];
$exit = 0;
foreach ($tables as $name => $t) {
    if ($only && $only !== $name) { continue; }
    if (time() - $started > $maxSeconds) { logline('Time is up, the rest continues in the next run.'); break; }
    list($code, $state) = crm($cfg, 'GET', "/api/dialer/ingest/state/$name");
    if ($code !== 200) { logline("$name: cannot read the CRM state (HTTP $code) " . json_encode($state)); $exit = 1; continue; }
    $last = $state['last'];                     // null on the very first run
    $cursor = $last === null ? null : (int)$last - (opt($t, 'overlap', 0));
    $sent = $added = 0;
    while (time() - $started <= $maxSeconds) {
        $stmt = $pdo->prepare(sprintf($cursor === null ? $t['first'] : $t['sql'], $batch));
        $cursor === null ? $stmt->execute([':since' => $since . ' 00:00:00']) : $stmt->execute([':last' => $cursor]);
        $rows = $stmt->fetchAll();
        if (!$rows) { break; }
        $top = max(array_map(function ($r) use ($t) { return (int)$r[$t['key']]; }, $rows));
        if ($dry) { logline("$name: would send " . count($rows) . " row(s), up to {$t['key']} $top"); break; }
        list($code, $res) = crm($cfg, 'POST', "/api/dialer/ingest/$name", ['rows' => $rows]);
        if ($code !== 200) { logline("$name: the CRM refused the batch (HTTP $code) " . json_encode($res)); $exit = 1; break; }
        $sent += count($rows);
        $added += (int)$res['added'];
        if ($res['rejected'] > 0) { logline("$name: {$res['rejected']} row(s) were rejected by the CRM"); }
        $next = $t['key'] === 'start_epoch' ? ($top > $cursor ? $top : $top + 1) : $top;   // always move forward
        $cursor = $next;
        if (count($rows) < $batch) { break; }
    }
    if (!$dry) { logline("$name: sent $sent row(s), new in the CRM: $added"); }
}
exit($exit);
