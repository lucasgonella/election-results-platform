<?php
declare(strict_types=1);

/**
 * Staging-only HTTPS receiver. Does NOT publish anything under public_html/data.
 * Install at public_html/api/election-publish.php; secrets live outside docroot.
 */
header('Content-Type: application/json; charset=utf-8');
header('Cache-Control: no-store');
header('X-Content-Type-Options: nosniff');

function reply(int $code, string $status, array $extra = []): never {
    http_response_code($code);
    echo json_encode(['status' => $status] + $extra, JSON_UNESCAPED_SLASHES);
    exit;
}
function safeId(mixed $v): bool {
    return is_string($v) && preg_match('/^[a-f0-9]{32}$/D', $v) === 1;
}
function safePath(mixed $v): bool {
    return is_string($v)
        && strlen($v) <= 120
        && preg_match('#^(?:[a-z]{2}/[a-z0-9-]+\.json|manifest\.json|version\.json|alerts\.json)$#D', $v) === 1;
}
if (($_SERVER['REQUEST_METHOD'] ?? '') !== 'POST') {
    header('Allow: POST');
    reply(405, 'method_not_allowed');
}
if (($_SERVER['HTTPS'] ?? '') !== 'on') {
    reply(403, 'https_required');
}
$max = 1048576;
if (isset($_SERVER['CONTENT_LENGTH']) && (int) $_SERVER['CONTENT_LENGTH'] > $max) {
    reply(413, 'payload_too_large');
}
$base = dirname(__DIR__, 2) . '/.election-publisher';
$keyHex = trim((string) @file_get_contents($base . '/hmac.key'));
if (!preg_match('/^[a-f0-9]{64}$/D', $keyHex)) {
    reply(503, 'server_not_ready');
}
$ts = $_SERVER['HTTP_X_TIMESTAMP'] ?? '';
$nonce = $_SERVER['HTTP_X_NONCE'] ?? '';
$sig = $_SERVER['HTTP_X_SIGNATURE'] ?? '';
if (!is_string($ts) || !preg_match('/^[0-9]{10}$/D', $ts) ||
    abs(time() - (int) $ts) > 60 || !safeId($nonce) ||
    !is_string($sig) || !preg_match('/^[a-f0-9]{64}$/D', $sig)) {
    reply(401, 'invalid_auth');
}
$raw = @file_get_contents('php://input', false, null, 0, $max + 1);
if ($raw === false || strlen($raw) > $max) {
    reply(413, 'payload_too_large');
}
$expected = hash_hmac('sha256', $ts . "\n" . $nonce . "\n" . $raw, hex2bin($keyHex));
if (!hash_equals($expected, $sig)) {
    reply(401, 'invalid_signature');
}
$nonceDir = $base . '/nonces';
$batchDir = $base . '/batches';
if ((!is_dir($nonceDir) && !@mkdir($nonceDir, 0700, true)) ||
    (!is_dir($batchDir) && !@mkdir($batchDir, 0700, true))) {
    reply(503, 'storage_unavailable');
}
// Bound stale nonce cleanup: executed only after a valid HMAC. A nonce is never
// removed while its timestamp could still pass the 60-second window.
foreach (glob($nonceDir . '/nonce-*') ?: [] as $p) {
    if (is_file($p) && filemtime($p) < time() - 180) {
        @unlink($p);
    }
}
$nonceFile = $nonceDir . '/nonce-' . $nonce;
$fh = @fopen($nonceFile, 'x');
if ($fh === false) reply(409, 'replay_detected');
@chmod($nonceFile, 0600);
fclose($fh);

$req = json_decode($raw, true);
if (!is_array($req)) reply(400, 'invalid_json');
$action = $req['action'] ?? '';
if ($action === 'health') reply(200, 'ok', ['mode' => 'staging_only']);
$id = $req['batch_id'] ?? null;
if (!safeId($id)) reply(400, 'invalid_batch_id');
$dir = $batchDir . '/' . $id;
if ($action === 'begin') {
    $paths = $req['paths'] ?? null;
    if (!is_array($paths) || count($paths) < 4 || count($paths) > 140 ||
        count(array_unique($paths)) !== count($paths)) {
        reply(400, 'invalid_paths');
    }
    foreach ($paths as $p) if (!safePath($p)) reply(400, 'invalid_path');
    foreach (['manifest.json', 'version.json', 'alerts.json'] as $required) {
        if (!in_array($required, $paths, true)) reply(400, 'missing_metadata');
    }
    if (!@mkdir($dir, 0700)) reply(409, 'batch_exists');
    $meta = json_encode(['paths' => $paths], JSON_THROW_ON_ERROR);
    if (file_put_contents($dir . '/batch.json', $meta, LOCK_EX) === false) {
        reply(500, 'storage_error');
    }
    @chmod($dir . '/batch.json', 0600);
    reply(200, 'prepared', ['batch_id' => $id, 'mode' => 'staging_only']);
}
$metaPath = $dir . '/batch.json';
if (!is_file($metaPath)) reply(404, 'batch_not_found');
$meta = json_decode((string) file_get_contents($metaPath), true);
if (!is_array($meta) || !is_array($meta['paths'] ?? null)) reply(500, 'invalid_batch_state');
if ($action === 'publish_official') {
    require_once __DIR__ . '/publish-official-snapshot.php';
    try {
        $result = publishOfficialSnapshot($base, $id);
        reply(200, $result['status'], array_diff_key($result, ['status' => 1]));
    } catch (RuntimeException $e) {
        reply(409, $e->getMessage(), ['mode' => 'official']);
    }
}
if ($action === 'activate_test') {
    // Authenticated operation. Strictly private; no public data writes.
    require_once __DIR__ . '/activate-private-batch.php';
    try {
        $result = activatePrivateBatch($base, $id);
        reply(200, $result['status'], array_diff_key($result, ['status' => 1]));
    } catch (RuntimeException $e) {
        $status = $e->getMessage();
        $code = in_array($status, ['activation_busy','stale_version'], true) ? 409 : 422;
        reply($code, $status, ['mode' => 'sandbox']);
    }
}
if ($action === 'build_snapshot_test') {
    require_once __DIR__ . '/build-private-snapshot.php';
    try {
        $result = buildPrivateSnapshot($base, $id);
        reply(200, $result['status'], array_diff_key($result, ['status' => 1]));
    } catch (RuntimeException $e) {
        $code = $e->getMessage() === 'snapshot_busy' ? 409 : 422;
        reply($code, $e->getMessage(), ['mode' => 'sandbox']);
    }
}
if ($action === 'promote_snapshot_test' || $action === 'rollback_snapshot_test') {
    require_once __DIR__ . '/promote-private-snapshot.php';
    try {
        $snapshotId = $req['snapshot_id'] ?? '';
        if (!is_string($snapshotId)) reply(400, 'invalid_snapshot_id');
        $result = promotePrivateSnapshot($base, $snapshotId, $action === 'rollback_snapshot_test');
        reply(200, $result['status'], array_diff_key($result, ['status' => 1]));
    } catch (RuntimeException $e) {
        reply(409, $e->getMessage(), ['mode' => 'sandbox']);
    }
}
if ($action === 'inspect') {
    $present = [];
    foreach ($meta['paths'] as $p) {
        if (is_file($dir . '/files/' . $p)) $present[] = $p;
    }
    reply(200, 'inspected', [
        'batch_id' => $id,
        'expected' => count($meta['paths']),
        'received' => count($present),
        'present' => $present,
        'complete' => count($present) === count($meta['paths']),
        'mode' => 'staging_only',
    ]);
}
if ($action !== 'upload') reply(400, 'unknown_action');
$path = $req['path'] ?? null;
$hash = $req['sha256'] ?? null;
$encoded = $req['content_b64'] ?? null;
$encoding = $req['content_encoding'] ?? 'identity';
if (!safePath($path) || !in_array($path, $meta['paths'], true) ||
    !is_string($hash) || !preg_match('/^[a-f0-9]{64}$/D', $hash) ||
    !is_string($encoded) || !in_array($encoding, ['identity','gzip'], true)) reply(400, 'invalid_upload');
$bytes = base64_decode($encoded, true);
if ($bytes === false || strlen($bytes) > 700000) reply(422, 'payload_limit');
if ($encoding === 'gzip') {
    $decoded = @gzdecode($bytes, 6291456);
    if ($decoded === false) reply(422, 'invalid_gzip');
    $bytes = $decoded;
}
if (strlen($bytes) > 6291456 || !hash_equals($hash, hash('sha256', $bytes))) {
    reply(422, 'checksum_mismatch');
}
try {
    json_decode($bytes, true, 512, JSON_THROW_ON_ERROR);
} catch (JsonException $e) {
    reply(422, 'invalid_file_json');
}
$target = $dir . '/files/' . $path;
$parent = dirname($target);
if (!is_dir($parent) && !@mkdir($parent, 0700, true)) reply(500, 'storage_error');
// Atomic replacement of a single staged file, never a public file.
$tmp = @tempnam($parent, '.upload-');
if ($tmp === false || file_put_contents($tmp, $bytes) !== strlen($bytes)) {
    if ($tmp !== false) @unlink($tmp);
    reply(500, 'storage_error');
}
@chmod($tmp, 0600);
if (!@rename($tmp, $target)) {
    @unlink($tmp);
    reply(500, 'storage_error');
}
reply(200, 'stored', ['path' => $path, 'sha256' => $hash, 'mode' => 'staging_only']);
