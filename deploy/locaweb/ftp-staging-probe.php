<?php
declare(strict_types=1);
// TEST TOOL ONLY. Not included in any application artifact or production deploy.
// Install only inside a separately authorized ftp-staging-* fixture namespace.
ini_set('display_errors', '0');
header('Content-Type: application/json');
header('Cache-Control: no-store');
header('X-Content-Type-Options: nosniff');
$authenticated = PHP_SAPI === 'cli';
try {
    // Reject unauthenticated web traffic before consulting private configuration.
    if (PHP_SAPI !== 'cli' && (($_SERVER['HTTPS'] ?? '') !== 'on' || ($_SERVER['REQUEST_METHOD'] ?? '') !== 'POST'
            || !preg_match('/^[0-9]{10}$/D', $_SERVER['HTTP_X_TIMESTAMP'] ?? '')
            || !preg_match('/^[a-f0-9]{64}$/D', $_SERVER['HTTP_X_SIGNATURE'] ?? ''))) throw new RuntimeException('invalid_fixture_auth');
    $public = realpath(__DIR__);
    $normalize = static fn(string|false $path): string => str_replace('\\', '/', (string)$path);
    $root = realpath(dirname(__DIR__));
    $split = false;
    if (basename(__DIR__) === '__staging_pr75' && basename(dirname(__DIR__)) === 'eleicoes'
            && basename(dirname(__DIR__, 2)) === 'public_html') {
        $home = realpath(dirname(__DIR__, 3));
        $root = realpath($home . '/ftp-staging-pr75');
        if ($normalize($public) !== $normalize($home) . '/public_html/eleicoes/__staging_pr75' || $normalize($root) !== $normalize($home) . '/ftp-staging-pr75') throw new RuntimeException('fixture_namespace_required');
        $split = true;
    }
    if (!$root || !str_starts_with(basename($root), 'ftp-staging-')) throw new RuntimeException('fixture_namespace_required');
    if (is_link($root . '/private') || $normalize(realpath($root . '/private')) !== $normalize($root) . '/private') throw new RuntimeException('fixture_namespace_required');
    foreach (['staging-config.json', 'ftp-publication.php', 'probe.lock'] as $leaf) {
        if (is_link($root . '/private/' . $leaf)) throw new RuntimeException('fixture_namespace_required');
    }
    if (is_link($public . '/probe-marker.json') || !is_file($public . '/probe-marker.json')) throw new RuntimeException('fixture_namespace_required');
    $cfg = json_decode((string)file_get_contents($root . '/private/staging-config.json'), true, 32, JSON_THROW_ON_ERROR);
    if (($cfg['fixture_only'] ?? false) !== true || ($cfg['environment'] ?? '') !== 'fixture' || realpath($cfg['root'] ?? '') !== $root) throw new RuntimeException('fixture_configuration_required');
    if (!preg_match('/^[a-f0-9]{64}$/D', $cfg['fixture_key'] ?? '')) throw new RuntimeException('fixture_configuration_required');
    $readActions = ['runtime', 'read'];
    $testActions = ['runtime', 'read', 'lock', 'replace_a', 'replace_b'];
    if ($split && (($cfg['public_root'] ?? '') !== $public || !in_array($cfg['allowed_actions'] ?? null, [$readActions, $testActions], true))) throw new RuntimeException('fixture_configuration_required');
    if (!$split && $normalize($public) !== $normalize($root) . '/public') throw new RuntimeException('fixture_namespace_required');
    if (PHP_SAPI === 'cli') {
        $action = $argv[1] ?? 'runtime';
    } else {
        if (($_SERVER['HTTPS'] ?? '') !== 'on' || ($_SERVER['REQUEST_METHOD'] ?? '') !== 'POST') throw new RuntimeException('https_post_required');
        $raw = file_get_contents('php://input', false, null, 0, 1025);
        $ts = $_SERVER['HTTP_X_TIMESTAMP'] ?? '';
        $sig = $_SERVER['HTTP_X_SIGNATURE'] ?? '';
        if ($raw === false || strlen($raw) > 1024 || !preg_match('/^[0-9]{10}$/D', $ts) || abs(time()-(int)$ts)>30 || !hash_equals(hash_hmac('sha256', $ts . "\n" . $raw, hex2bin($cfg['fixture_key'])), $sig)) throw new RuntimeException('invalid_fixture_auth');
        $authenticated = true;
        $request = json_decode($raw, true, 8, JSON_THROW_ON_ERROR);
        if (array_keys($request) !== ['action']) throw new RuntimeException('invalid_request');
        $action = $request['action'];
    }
    if ($split && !in_array($action, $cfg['allowed_actions'], true)) throw new RuntimeException('fixture_action_not_approved');
    require $root . '/private/ftp-publication.php';
    // Reads can observe nodes; mutations must stay on the explicitly pinned host.
    // This does not certify NFS/multi-host locking or provider confinement.
    if (in_array($action, ['lock', 'replace_a', 'replace_b'], true)) {
        if (!is_string($cfg['activation_host'] ?? null) || $cfg['activation_host'] === '') throw new RuntimeException('unverified_lock_scope');
        if ($cfg['activation_host'] !== gethostname()) throw new RuntimeException('activation_host_mismatch');
    }
    $value = ['host'=>gethostname(), 'pid'=>getmypid(), 'sapi'=>PHP_SAPI, 'php'=>PHP_VERSION, 'probe_version'=>2];
    if ($action === 'runtime') {
        $value += ['effective_uid'=>function_exists('posix_geteuid') ? posix_geteuid() : null,
                   'effective_gid'=>function_exists('posix_getegid') ? posix_getegid() : null,
                   'fixture_root'=>$root, 'fixture_public_root'=>$public, 'process_root'=>@readlink('/proc/self/root') ?: null,
                   'flock'=>function_exists('flock'),'fsync'=>function_exists('fsync'),'rename'=>function_exists('rename'),
                   'opcache'=>ini_get('opcache.enable'),'validate_timestamps'=>ini_get('opcache.validate_timestamps'),
                   'revalidate_freq'=>ini_get('opcache.revalidate_freq')];
        $value['helper_revision'] = defined('FTP_PUBLICATION_HELPER_VERSION') ? FTP_PUBLICATION_HELPER_VERSION : 1;
    } elseif (in_array($action, ['lock', 'replace_a', 'replace_b'], true)) {
        $lock = $root . '/private/probe.lock';
        if (file_exists($lock) && (!is_file($lock) || (fileperms($lock) & 0777) !== 0600)) throw new RuntimeException('fixture_lock_invalid');
        $mask = umask(0077);
        try { $handle = fopen($lock, 'c'); } finally { umask($mask); }
        if (!$handle) throw new RuntimeException('fixture_lock_invalid');
        try {
            if (!flock($handle, LOCK_EX | LOCK_NB)) throw new RuntimeException('publication_busy');
            if ($action === 'lock') {
                usleep(2000000); // Exactly two clients, bounded overlap window.
                $value['status'] = 'lock_acquired';
            } else {
                if (!function_exists('fsync')) throw new RuntimeException('fixture_fsync_required');
                fp_write($public . '/probe-marker.json', ['fixture'=>$action]);
                $value['status'] = 'replaced';
            }
        } finally { flock($handle, LOCK_UN); fclose($handle); }
    } elseif ($action === 'read') {
        $marker = fp_read($public, 'probe-marker.json');
        $value['marker'] = json_decode($marker, true, 8, JSON_THROW_ON_ERROR);
        if (!in_array($value['marker'], [['fixture'=>'replace_a'], ['fixture'=>'replace_b']], true)) throw new RuntimeException('invalid_fixture_marker');
        $value['marker_sha256'] = hash('sha256', $marker);
        $value['marker_bytes'] = strlen($marker);
    } else throw new RuntimeException('invalid_action');
    echo json_encode($value, JSON_THROW_ON_ERROR);
} catch (Throwable $error) {
    http_response_code($authenticated ? 409 : 401);
    $safe = !$authenticated ? 'invalid_fixture_auth' : ($error instanceof RuntimeException && preg_match('/^[a-z_]+$/D', $error->getMessage()) ? $error->getMessage() : 'probe_failed');
    echo json_encode(['error'=>$safe]);
    if (PHP_SAPI === 'cli') exit(1);
}
