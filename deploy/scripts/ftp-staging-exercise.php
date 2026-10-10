<?php
declare(strict_types=1);
/** Fixture CLI client. Execute on the server; never install as a web endpoint. */
const FX_HOME = '/home/storage/4/b7/e0/afgnet1';
const FX_ROOT = FX_HOME . '/ftp-staging-pr75';
const FX_PUBLIC = FX_HOME . '/public_html/eleicoes/__staging_pr75';
const FX_PRIVATE = FX_ROOT . '/private';
const FX_BACKUP = FX_PRIVATE . '/etapa15-backup';
const FX_URL = 'https://afgnet.com.br/eleicoes/__staging_pr75/';
const FX_READ = ['runtime', 'read'];
const FX_TEST = ['runtime', 'read', 'lock', 'replace_a', 'replace_b'];

function fx_fail(string $code): never { throw new RuntimeException($code); }
function fx_raw(string $path, int $limit=65536): string {
    if (is_link($path) || !is_file($path)) fx_fail('fixture_file_invalid');
    $raw=file_get_contents($path, false, null, 0, $limit+1);
    if ($raw===false || strlen($raw)>$limit) fx_fail('fixture_read_failed');
    return $raw;
}
function fx_atomic(string $path, string $raw, int $mode): void {
    if (is_link($path)) fx_fail('fixture_file_invalid');
    $temp=$path.'.'.bin2hex(random_bytes(8)).'.tmp';
    $mask=umask(0077);
    try { $stream=fopen($temp,'x'); } finally { umask($mask); }
    if (!$stream) fx_fail('fixture_write_failed');
    try {
        try {
            if (!chmod($temp,$mode) || fwrite($stream,$raw)!==strlen($raw) || !fflush($stream)
                || !function_exists('fsync') || !fsync($stream)) fx_fail('fixture_write_failed');
        } finally { fclose($stream); }
        if (!rename($temp,$path)) fx_fail('fixture_write_failed');
    } finally { if (is_file($temp)) unlink($temp); }
}
function fx_template(string $raw, string $key): array {
    if (!preg_match('/^[a-f0-9]{64}$/D',$key) || substr_count($raw,$key)!==1) fx_fail('fixture_template_invalid');
    $offset=strpos($raw,$key);
    return ['prefix'=>substr($raw,0,$offset),'suffix'=>substr($raw,$offset+64),'sha256'=>hash('sha256',$raw)];
}
function fx_rebuild(array $template, string $key): string {
    $raw=$template['prefix'].$key.$template['suffix'];
    if (!hash_equals($template['sha256'],hash('sha256',$raw))) fx_fail('fixture_config_recovery_invalid');
    return $raw;
}
function fx_restore_pair(string $configPath, string $markerPath, array $template, string $key, string $marker, ?callable $beforeMarker=null): void {
    $config=fx_rebuild($template,$key);$original=json_decode($config,true,32,JSON_THROW_ON_ERROR);
    if (($original['allowed_actions']??null)!==FX_READ || ($original['activation_host']??null)!=='') fx_fail('fixture_recovery_config_invalid');
    fx_atomic($configPath,$config,0600);
    if ($beforeMarker!==null) $beforeMarker();
    fx_atomic($markerPath,$marker,0644);
    if (hash('sha256',fx_raw($configPath))!==$template['sha256'] || fx_raw($markerPath)!==$marker) fx_fail('fixture_recovery_verification_failed');
}
function fx_cfg(): array {
    foreach ([FX_ROOT,FX_PRIVATE,FX_PUBLIC] as $path) {
        if (is_link($path) || realpath($path)!==$path) fx_fail('fixture_namespace_invalid');
    }
    if ((fileperms(FX_ROOT)&0777)!==0700 || (fileperms(FX_PRIVATE)&0777)!==0700
        || (fileperms(FX_PRIVATE.'/staging-config.json')&0777)!==0600) fx_fail('fixture_permissions_invalid');
    $cfg=json_decode(fx_raw(FX_PRIVATE.'/staging-config.json'),true,32,JSON_THROW_ON_ERROR);
    if (array_diff(array_keys($cfg),['fixture_only','environment','root','public_root','fixture_key','allowed_actions','activation_host'])) fx_fail('fixture_configuration_invalid');
    if (($cfg['fixture_only']??false)!==true || ($cfg['environment']??'')!=='fixture'
        || ($cfg['root']??'')!==FX_ROOT || ($cfg['public_root']??'')!==FX_PUBLIC
        || !in_array($cfg['allowed_actions']??null,[FX_READ,FX_TEST],true)
        || !in_array($cfg['activation_host']??null,['',gethostname()],true)
        || !preg_match('/^[a-f0-9]{64}$/D',$cfg['fixture_key']??'')) fx_fail('fixture_configuration_invalid');
    return $cfg;
}
function fx_response(int $status, string $raw, array $headers, ?string $action, string $host): array {
    if ($status!==200 && $status!==409) fx_fail('fixture_http_status_invalid');
    if ($action!==null && ($headers['cache-control']??'')!=='no-store') fx_fail('fixture_http_cacheable');
    $value=json_decode($raw,true,32,JSON_THROW_ON_ERROR);
    if (!is_array($value)) fx_fail('fixture_http_body_invalid');
    if ($status===409) {
        if (array_keys($value)!==['error'] || !in_array($value['error'],['publication_busy','fixture_action_not_approved'],true)) fx_fail('fixture_http_error_unexpected');
    } else {
        if ($action===null) {
            if (!in_array($value,[['fixture'=>'replace_a'],['fixture'=>'replace_b']],true)) fx_fail('fixture_marker_invalid');
        } else {
            $allowed=['host','pid','sapi','php','probe_version','effective_uid','effective_gid','fixture_root','fixture_public_root','process_root',
                'flock','fsync','rename','opcache','validate_timestamps','revalidate_freq','marker','marker_sha256','marker_bytes','status','helper_revision'];
            if (array_diff(array_keys($value),$allowed) || ($value['host']??null)!==$host
                || ($value['sapi']??null)!=='fpm-fcgi' || ($value['probe_version']??null)!==2) fx_fail('fixture_web_runtime_invalid');
            if ($action==='runtime' && (($value['fixture_root']??null)!==FX_ROOT || ($value['fixture_public_root']??null)!==FX_PUBLIC
                || ($value['fsync']??false)!==true || ($value['helper_revision']??null)!==2)) fx_fail('fixture_web_namespace_invalid');
        }
    }
    return ['status'=>$status,'result'=>$value,'sha256'=>hash('sha256',$raw),'bytes'=>strlen($raw),'headers'=>$headers];
}
function fx_handle(?string $action, string $key, bool $bust=false): array {
    if (isset($GLOBALS['fx_deadline']) && microtime(true)>$GLOBALS['fx_deadline']) fx_fail('fixture_operation_timeout');
    if ($action!==null && !in_array($action,FX_TEST,true)) fx_fail('fixture_action_invalid');
    $state=(object)['raw'=>'','headers'=>[],'started'=>hrtime(true)];
    $handle=curl_init(FX_URL.($action===null?'probe-marker.json'.($bust?'?etapa15='.bin2hex(random_bytes(4)):''):'probe.php'));
    $headers=['Cache-Control: no-cache'];
    $options=[CURLOPT_FOLLOWLOCATION=>false,CURLOPT_CONNECTTIMEOUT=>5,CURLOPT_TIMEOUT=>10,
        CURLOPT_SSL_VERIFYPEER=>true,CURLOPT_SSL_VERIFYHOST=>2,
        CURLOPT_WRITEFUNCTION=>static function($ch,string $chunk) use ($state): int {
            if (strlen($state->raw)+strlen($chunk)>16384) return 0;
            $state->raw.=$chunk;return strlen($chunk);
        },CURLOPT_HEADERFUNCTION=>static function($ch,string $line) use ($state):int {
            $parts=explode(':',$line,2);$name=strtolower(trim($parts[0]));
            if (count($parts)===2 && in_array($name,['server','cache-control','age','etag','last-modified','content-type','x-content-type-options'],true)) $state->headers[$name]=trim($parts[1]);
            return strlen($line);
        }];
    if ($action!==null) {
        $body=json_encode(['action'=>$action],JSON_THROW_ON_ERROR);$stamp=(string)time();
        $headers=array_merge($headers,['Content-Type: application/json','X-Timestamp: '.$stamp,
            'X-Signature: '.hash_hmac('sha256',$stamp."\n".$body,hex2bin($key))]);
        $options+= [CURLOPT_POST=>true,CURLOPT_POSTFIELDS=>$body];
    }
    $options[CURLOPT_HTTPHEADER]=$headers;curl_setopt_array($handle,$options);
    return [$handle,$state,$action];
}
function fx_finished(array $request, string $host): array {
    [$handle,$state,$action]=$request;
    if (curl_errno($handle)!==0) fx_fail('fixture_https_failed');
    $result=fx_response((int)curl_getinfo($handle,CURLINFO_RESPONSE_CODE),$state->raw,$state->headers,$action,$host);
    $result['elapsed_ms']=round((hrtime(true)-$state->started)/1000000,2);
    return $result;
}
function fx_post(?string $action, string $key, string $host, bool $bust=false): array {
    $request=fx_handle($action,$key,$bust);
    try {
        if (curl_exec($request[0])===false) fx_fail('fixture_https_failed');
        return fx_finished($request,$host);
    } finally { curl_close($request[0]); }
}
function fx_pair(array $actions, string $key, string $host): array {
    if (count($actions)!==2) fx_fail('fixture_concurrency_invalid');
    $multi=curl_multi_init();$requests=[];
    try {
        foreach ($actions as $action) { $request=fx_handle($action,$key);$requests[]=$request;curl_multi_add_handle($multi,$request[0]); }
        $deadline=min(microtime(true)+12,$GLOBALS['fx_deadline']??INF);
        do {
            $code=curl_multi_exec($multi,$running);
            if ($code!==CURLM_OK || microtime(true)>$deadline) fx_fail('fixture_concurrency_timeout');
            if ($running) { if (curl_multi_select($multi,0.1)===-1) usleep(10000); }
        } while ($running);
        return array_map(static fn($request)=>fx_finished($request,$host),$requests);
    } finally {
        foreach ($requests as $request) {curl_multi_remove_handle($multi,$request[0]);curl_close($request[0]);}
        curl_multi_close($multi);
    }
}
function fx_visible(string $hash, string $key, string $host): array {
    $read=fx_post('read',$key,$host);
    if ($read['status']!==200 || ($read['result']['marker_sha256']??null)!==$hash) fx_fail('fixture_marker_visibility_failed');
    $normal=fx_post(null,$key,$host);$busted=fx_post(null,$key,$host,true);
    if ($normal['sha256']!==$hash || $busted['sha256']!==$hash) fx_fail('fixture_marker_visibility_failed');
    return ['read'=>$read,'normal'=>$normal,'cache_busted'=>$busted];
}
function fx_monitored(): array {
    $paths=['data/version.json','eleicoes/index.html','eleicoes/app.js','eleicoes/favorites.js',
        'eleicoes/composition.js','eleicoes/goias/raio-x/index.html'];$result=[];
    foreach ($paths as $path) $result[$path]=hash('sha256',fx_raw(FX_HOME.'/public_html/'.$path,2000000));
    return $result;
}
function fx_recover(string $host): array {
    if ($host!==gethostname() || is_link(FX_BACKUP) || realpath(FX_BACKUP)!==FX_BACKUP) fx_fail('fixture_recovery_namespace_invalid');
    $cfg=fx_cfg();$key=$cfg['fixture_key'];
    $manifest=json_decode(fx_raw(FX_BACKUP.'/manifest.json'),true,16,JSON_THROW_ON_ERROR);
    $template=json_decode(fx_raw(FX_BACKUP.'/config-template.json'),true,16,JSON_THROW_ON_ERROR);
    $marker=fx_raw(FX_BACKUP.'/marker.original');
    if ($manifest['host']!==$host || hash('sha256',$marker)!==$manifest['marker_sha256']) fx_fail('fixture_backup_invalid');
    // Disable new mutations first. A persistent key-free template permits this
    // exact restoration even after SSH disconnect or termination of the client.
    $lock=null;
    try {
        fx_restore_pair(FX_PRIVATE.'/staging-config.json',FX_PUBLIC.'/probe-marker.json',$template,$key,$marker,static function() use (&$lock): void {
        if (file_exists(FX_PRIVATE.'/probe.lock') || is_link(FX_PRIVATE.'/probe.lock')) {
            if (is_link(FX_PRIVATE.'/probe.lock') || !is_file(FX_PRIVATE.'/probe.lock') || (fileperms(FX_PRIVATE.'/probe.lock')&0777)!==0600) fx_fail('fixture_recovery_lock_invalid');
            $lock=fopen(FX_PRIVATE.'/probe.lock','r+');$deadline=microtime(true)+6;
            while (!flock($lock,LOCK_EX|LOCK_NB)) {
                if (microtime(true)>$deadline) fx_fail('fixture_recovery_lock_busy');
                usleep(100000);
            }
        }
        });
    } finally { if ($lock!==null) {flock($lock,LOCK_UN);fclose($lock);} }
    if (hash('sha256',fx_raw(FX_PRIVATE.'/staging-config.json'))!==$template['sha256']
        || hash('sha256',fx_raw(FX_PUBLIC.'/probe-marker.json'))!==$manifest['marker_sha256']
        || fx_monitored()!==$manifest['public_hashes']) fx_fail('fixture_recovery_verification_failed');
    $visibility=fx_visible($manifest['marker_sha256'],$key,$host);
    $denied=[];
    foreach (['lock','replace_a','replace_b'] as $action) {
        $response=fx_post($action,$key,$host);
        if ($response['status']!==409 || $response['result']!==['error'=>'fixture_action_not_approved']) fx_fail('fixture_mutations_not_disabled');
        $denied[$action]=409;
    }
    return ['status'=>'restored','config_exact'=>true,'marker_exact'=>true,'public_preserved'=>true,'mutations_denied'=>$denied,'visibility'=>$visibility];
}
function fx_main(array $args): array {
    $operation=$args[1]??'plan';
    if ($operation==='plan') return ['namespace'=>FX_ROOT,'url'=>FX_URL.'probe.php','backup'=>FX_BACKUP,'remote_writes_authorized'=>false,
        'actions'=>FX_TEST,'max_concurrency'=>2,'multi_host_validated'=>false,'key_exported'=>false];
    if (PHP_SAPI!=='cli' || !in_array($operation,['run','recover'],true) || ($args[2]??'')!==FX_ROOT
        || ($args[3]??'')!==gethostname()) fx_fail('fixture_specific_approval_required');
    $host=$args[3];
    $GLOBALS['fx_deadline']=microtime(true)+90;
    if ($operation==='recover') return fx_recover($host);
    $cfg=fx_cfg();$key=$cfg['fixture_key'];
    if ($cfg['allowed_actions']!==FX_READ || $cfg['activation_host']!=='') fx_fail('fixture_read_only_baseline_required');
    foreach ([FX_PUBLIC.'/probe.php'=>$args[4]??'',FX_PRIVATE.'/ftp-publication.php'=>$args[5]??''] as $path=>$hash) {
        if (!preg_match('/^[a-f0-9]{64}$/D',$hash) || hash('sha256',fx_raw($path))!==$hash) fx_fail('fixture_artifact_hash_invalid');
    }
    $runtime=fx_post('runtime',$key,$host);
    if ($runtime['status']!==200) fx_fail('fixture_runtime_failed');
    $marker=fx_raw(FX_PUBLIC.'/probe-marker.json');
    if (!in_array(json_decode($marker,true),[['fixture'=>'replace_a'],['fixture'=>'replace_b']],true)) fx_fail('fixture_marker_invalid');
    $baseline=fx_monitored();$original=fx_raw(FX_PRIVATE.'/staging-config.json');
    if (hash('sha256',$marker)!==($args[6]??'') || hash('sha256',$original)!==($args[7]??'')
        || hash('sha256',json_encode($baseline,JSON_THROW_ON_ERROR|JSON_UNESCAPED_SLASHES))!==($args[8]??'')) fx_fail('fixture_approved_baseline_changed');
    if (file_exists(FX_BACKUP) || is_link(FX_BACKUP) || !mkdir(FX_BACKUP,0700)) fx_fail('fixture_backup_collision');
    fx_atomic(FX_BACKUP.'/marker.original',$marker,0600);
    fx_atomic(FX_BACKUP.'/config-template.json',json_encode(fx_template($original,$key),JSON_THROW_ON_ERROR),0600);
    fx_atomic(FX_BACKUP.'/manifest.json',json_encode(['host'=>$host,'marker_sha256'=>hash('sha256',$marker),'public_hashes'=>$baseline],JSON_THROW_ON_ERROR),0600);
    if (fx_raw(FX_BACKUP.'/marker.original')!==$marker
        || fx_rebuild(json_decode(fx_raw(FX_BACKUP.'/config-template.json'),true,16,JSON_THROW_ON_ERROR),$key)!==$original) fx_fail('fixture_backup_verification_failed');
    $report=['runtime'=>$runtime,'multi_host_validated'=>false,'key_exported'=>false];
    try {
        $cfg['allowed_actions']=FX_TEST;$cfg['activation_host']=$host;
        fx_atomic(FX_PRIVATE.'/staging-config.json',json_encode($cfg,JSON_THROW_ON_ERROR),0600);
        $locks=fx_pair(['lock','lock'],$key,$host);
        if (count(array_filter($locks,static fn($r)=>$r['status']===200 && ($r['result']['status']??'')==='lock_acquired'))!==1
            || count(array_filter($locks,static fn($r)=>$r['status']===409 && ($r['result']['error']??'')==='publication_busy'))!==1) fx_fail('fixture_lock_exclusion_failed');
        $report['locks']=$locks;$report['transitions']=[];
        $allowed=[hash('sha256',$marker),hash('sha256','{"fixture":"replace_a"}'),hash('sha256','{"fixture":"replace_b"}')];
        foreach (['replace_b','replace_a'] as $action) {
            $pair=fx_pair([$action,null],$key,$host);
            if ($pair[0]['status']!==200 || ($pair[0]['result']['status']??'')!=='replaced'
                || !in_array($pair[1]['sha256'],$allowed,true)) fx_fail('fixture_atomic_observation_failed');
            $hash=hash('sha256',json_encode(['fixture'=>$action],JSON_THROW_ON_ERROR));
            $report['transitions'][$action]=['overlapping_get'=>$pair[1],'verified'=>fx_visible($hash,$key,$host)];
        }
        $report['status']='single_host_exercise_passed';
    } catch (Throwable $error) {
        $report['status']='exercise_failed';$report['reason']=$error instanceof RuntimeException?$error->getMessage():'fixture_exercise_failed';
    } finally {
        $GLOBALS['fx_deadline']=microtime(true)+60;
        try { $report['recovery']=fx_recover($host); }
        catch (Throwable $error) { $report['recovery']=['status'=>'required','reason'=>$error instanceof RuntimeException?$error->getMessage():'fixture_recovery_failed']; }
    }
    // Persistent recovery files and the lock inode are retained until the
    // separately approved, hash-checked cleanup; never unlink a live lock inode.
    return $report;
}
if (!defined('FTP_STAGING_CLIENT_LIBRARY')) {
    ini_set('display_errors','0');error_reporting(0);
    try {
        $result=fx_main($argv);echo json_encode($result,JSON_THROW_ON_ERROR)."\n";
        if (($result['status']??null)==='exercise_failed' || ($result['recovery']['status']??null)==='required') exit(1);
    }
    catch (Throwable $error) {
        $code=$error instanceof RuntimeException && preg_match('/^[a-z_]+$/D',$error->getMessage())?$error->getMessage():'fixture_client_failed';
        echo json_encode(['status'=>'failed','reason'=>$code,'key_exported'=>false])."\n";exit(1);
    }
}
