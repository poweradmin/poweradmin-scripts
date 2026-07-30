<?php

declare(strict_types=1);

require __DIR__ . '/../../vendor/autoload.php';

use Poweradmin\Infrastructure\Network\ProxyContext;

$url = $argv[1] ?? '';
if ($url === '') {
    fwrite(STDERR, "usage: proxy_harness.php <url>\n");
    exit(2);
}

$httpOptions = ProxyContext::httpOptionsFor($url);
$httpOptions['timeout'] = 5;
$httpOptions['ignore_errors'] = true;

$ctx = stream_context_create(['http' => $httpOptions]);
$body = @file_get_contents($url, false, $ctx);

fwrite(STDOUT, "OPTIONS:" . json_encode($httpOptions) . "\n");
fwrite(STDOUT, "BODY:" . ($body === false ? '<error>' : trim((string) $body)) . "\n");
