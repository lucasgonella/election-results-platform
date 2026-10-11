<?php
declare(strict_types=1);
ini_set('display_errors', '0');
require_once __DIR__ . '/ftp-publication.php';
header('Content-Type: application/json; charset=utf-8');
header('Cache-Control: no-store');
header('X-Content-Type-Options: nosniff');
function fc_reply(int $code, array $value): never {
    http_response_code($code); echo json_encode($value, JSON_UNESCAPED_SLASHES); exit;
}
if (($_SERVER['REQUEST_METHOD'] ?? '') !== 'POST' || ($_SERVER['HTTPS'] ?? '') !== 'on') fc_reply(403, ['status'=>'https_post_required']);
try {
    $base = dirname(__DIR__, 2) . '/.election-publisher';
    $cfg = fp_json($base . '/ftp-config.json');
    fp_assert_runtime($cfg);
    if (realpath($cfg['public_root'] ?? '') !== realpath(dirname(__DIR__))) fp_fail('invalid_configuration');
    $keyHex = trim((string)file_get_contents($base . '/hmac.key'));
    if (!preg_match('/^[a-f0-9]{64}$/D', $keyHex)) fp_fail('server_not_ready');
    $cfg['key'] = hex2bin($keyHex);
    $raw = file_get_contents('php://input', false, null, 0, 2049);
    $ts = $_SERVER['HTTP_X_TIMESTAMP'] ?? ''; $nonce = $_SERVER['HTTP_X_NONCE'] ?? ''; $sig = $_SERVER['HTTP_X_SIGNATURE'] ?? '';
    if ($raw === false || strlen($raw) > 2048 || !preg_match('/^[0-9]{10}$/D', $ts) || abs(time() - (int)$ts) > 60 || !preg_match('/^[a-f0-9]{32}$/D', $nonce) || !hash_equals(hash_hmac('sha256', $ts . "\n" . $nonce . "\n" . $raw, $cfg['key']), $sig)) fc_reply(401, ['status'=>'invalid_auth']);
    $nonceDir = $base . '/ftp-nonces';
    if (!is_dir($nonceDir) && !mkdir($nonceDir, 0700)) fp_fail('storage_error');
    foreach (glob($nonceDir . '/*') ?: [] as $path) if (is_file($path) && filemtime($path) < time() - 180) unlink($path);
    $handle = fopen($nonceDir . '/' . $nonce, 'x');
    if (!$handle) fc_reply(409, ['status'=>'replay_detected']);
    fclose($handle);
    $request = json_decode($raw, true, 8, JSON_THROW_ON_ERROR);
    if (!is_array($request) || array_diff(array_keys($request), ['action','delivery_id'])) fp_fail('invalid_request');
    $result = fp_run($cfg, $request['action'] ?? '', $request['delivery_id'] ?? '');
    error_log('election_ftp action=' . ($request['action'] ?? '') . ' status=' . $result['status']);
    fc_reply(200, $result);
} catch (Throwable $error) {
    // Never return paths, request bodies, credentials or arbitrary exception messages.
    $safe = $error instanceof RuntimeException && preg_match('/^[a-z_]+$/D', $error->getMessage()) ? $error->getMessage() : 'operation_failed';
    error_log('election_ftp error=' . $safe);
    fc_reply(409, ['status'=>'error', 'error'=>$safe]);
}
