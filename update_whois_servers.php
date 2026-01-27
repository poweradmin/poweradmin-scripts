#!/usr/bin/env php
<?php

/*  Poweradmin, a friendly web-based admin tool for PowerDNS.
 *  See <https://www.poweradmin.org> for more details.
 *
 *  Copyright 2007-2010 Rejo Zenger <rejo@zenger.nl>
 *  Copyright 2010-2025 Poweradmin Development Team
 *
 *  This program is free software: you can redistribute it and/or modify
 *  it under the terms of the GNU General Public License as published by
 *  the Free Software Foundation, either version 3 of the License, or
 *  (at your option) any later version.
 *
 *  This program is distributed in the hope that it will be useful,
 *  but WITHOUT ANY WARRANTY; without even the implied warranty of
 *  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
 *  GNU General Public License for more details.
 *
 *  You should have received a copy of the GNU General Public License
 *  along with this program.  If not, see <https://www.gnu.org/licenses/>.
 */

/**
 * Script to update WHOIS servers from IANA database
 *
 * This script fetches the official WHOIS server information from IANA
 * for all TLDs and updates the whois_servers.json file.
 *
 * Usage:
 *   php scripts/update_whois_servers.php [options]
 *
 * Options:
 *   --dry-run     Show changes without writing to file
 *   --verbose     Show detailed progress
 *   --help        Show this help message
 */

define('IANA_ROOT_DB_URL', 'https://www.iana.org/domains/root/db');
define('IANA_WHOIS_SERVER', 'whois.iana.org');
define('WHOIS_SERVERS_FILE', __DIR__ . '/../data/whois_servers.php');
define('SOCKET_TIMEOUT', 5);
define('REQUEST_DELAY_MS', 150); // Delay between IANA queries to avoid rate limiting

// Parse command line options
$options = getopt('', ['dry-run', 'verbose', 'help']);
$dryRun = isset($options['dry-run']);
$verbose = isset($options['verbose']);
$showHelp = isset($options['help']);

if ($showHelp) {
    echo <<<HELP
Update WHOIS servers from IANA database

Usage:
  php scripts/update_whois_servers.php [options]

Options:
  --dry-run     Show changes without writing to file
  --verbose     Show detailed progress
  --help        Show this help message

Examples:
  php scripts/update_whois_servers.php --dry-run --verbose
  php scripts/update_whois_servers.php

HELP;
    exit(0);
}

/**
 * Fetch URL content using curl
 */
function fetchUrl(string $url): string
{
    $ch = curl_init();
    curl_setopt_array($ch, [
        CURLOPT_URL => $url,
        CURLOPT_RETURNTRANSFER => true,
        CURLOPT_FOLLOWLOCATION => true,
        CURLOPT_TIMEOUT => 30,
        CURLOPT_USERAGENT => 'Mozilla/5.0 (compatible; Poweradmin WHOIS Updater/1.0)',
        CURLOPT_SSL_VERIFYPEER => true,
    ]);

    $response = curl_exec($ch);
    $httpCode = curl_getinfo($ch, CURLINFO_HTTP_CODE);
    $error = curl_error($ch);
    curl_close($ch);

    if ($response === false || $httpCode !== 200) {
        throw new RuntimeException("HTTP request failed: $error (HTTP $httpCode)");
    }

    return $response;
}

/**
 * Fetch the list of all TLDs from IANA root database
 */
function fetchTldList(): array
{
    echo "Fetching TLD list from IANA...\n";

    $html = fetchUrl(IANA_ROOT_DB_URL);

    // Parse the HTML to extract TLD links
    // TLDs are in links like /domains/root/db/com.html
    preg_match_all('/<a href="\/domains\/root\/db\/([^"]+)\.html"/', $html, $matches);

    $tlds = array_unique($matches[1]);
    sort($tlds);

    echo "Found " . count($tlds) . " TLDs\n";

    return $tlds;
}

/**
 * Query IANA WHOIS server for TLD information
 */
function queryIanaWhois(string $tld): ?string
{
    $socket = @fsockopen(IANA_WHOIS_SERVER, 43, $errno, $errstr, SOCKET_TIMEOUT);
    if (!$socket) {
        return null;
    }

    stream_set_timeout($socket, SOCKET_TIMEOUT);
    fwrite($socket, $tld . "\r\n");

    $response = '';
    while (!feof($socket)) {
        $buffer = fgets($socket, 1024);
        if ($buffer === false) {
            break;
        }
        $response .= $buffer;

        $info = stream_get_meta_data($socket);
        if ($info['timed_out']) {
            break;
        }
    }

    fclose($socket);

    return $response ?: null;
}

/**
 * Extract WHOIS server from IANA WHOIS response
 */
function extractWhoisServer(string $response): ?string
{
    // Look for "whois:" line in the response
    // Use [ \t]* instead of \s* to avoid matching newlines
    if (preg_match('/^whois:[ \t]*(\S+)/mi', $response, $matches)) {
        $server = trim($matches[1]);
        // Return null if empty or placeholder
        if (empty($server) || $server === '-' || $server === 'NULL') {
            return null;
        }
        return strtolower($server);
    }

    return null;
}

/**
 * Check if a WHOIS server is reachable
 */
function isWhoisServerReachable(string $server): bool
{
    $socket = @fsockopen($server, 43, $errno, $errstr, 3);
    if ($socket) {
        fclose($socket);
        return true;
    }
    return false;
}

/**
 * Convert punycode TLD to display form for output
 */
function formatTldForDisplay(string $tld): string
{
    if (strpos($tld, 'xn--') === 0 && function_exists('idn_to_utf8')) {
        $unicode = idn_to_utf8($tld, IDNA_DEFAULT, INTL_IDNA_VARIANT_UTS46);
        if ($unicode !== false && $unicode !== $tld) {
            return "$tld ($unicode)";
        }
    }
    return $tld;
}

// Main execution
try {
    echo "=== WHOIS Servers Update Script ===\n\n";

    if ($dryRun) {
        echo "Running in DRY-RUN mode - no changes will be written\n\n";
    }

    // Load existing WHOIS servers
    if (!file_exists(WHOIS_SERVERS_FILE)) {
        throw new RuntimeException("WHOIS servers file not found: " . WHOIS_SERVERS_FILE);
    }

    $existingServers = include WHOIS_SERVERS_FILE;
    if (!is_array($existingServers)) {
        throw new RuntimeException("Failed to parse existing WHOIS servers file");
    }

    echo "Loaded " . count($existingServers) . " existing WHOIS server entries\n\n";

    // Fetch TLD list from IANA
    $tlds = fetchTldList();

    // Track changes
    $added = [];
    $updated = [];
    $removed = [];
    $unchanged = 0;
    $noWhois = [];
    $errors = [];

    // Process each TLD
    $total = count($tlds);
    $current = 0;

    echo "\nQuerying IANA WHOIS for each TLD...\n";

    foreach ($tlds as $tld) {
        $current++;
        $progress = sprintf("[%d/%d] ", $current, $total);

        if ($verbose) {
            echo $progress . "Processing: " . formatTldForDisplay($tld) . "... ";
        } elseif ($current % 50 === 0) {
            echo $progress . "Processed $current TLDs\n";
        }

        // Query IANA WHOIS
        $response = queryIanaWhois($tld);

        if ($response === null) {
            $errors[] = $tld;
            if ($verbose) {
                echo "ERROR (connection failed)\n";
            }
            continue;
        }

        $ianaServer = extractWhoisServer($response);
        $existingServer = $existingServers[$tld] ?? null;

        if ($ianaServer === null) {
            $noWhois[] = $tld;
            // Only remove if existing server doesn't work anymore
            if ($existingServer !== null) {
                if (!isWhoisServerReachable($existingServer)) {
                    $removed[$tld] = $existingServer;
                    unset($existingServers[$tld]);
                    if ($verbose) {
                        echo "REMOVED (IANA empty + server unreachable)\n";
                    }
                } else {
                    $unchanged++;
                    if ($verbose) {
                        echo "kept (IANA empty but server works)\n";
                    }
                }
            } else {
                if ($verbose) {
                    echo "no WHOIS server defined\n";
                }
            }
            continue;
        }

        if ($existingServer === null) {
            // New TLD - verify the server works before adding
            if (isWhoisServerReachable($ianaServer)) {
                $added[$tld] = $ianaServer;
                $existingServers[$tld] = $ianaServer;
                if ($verbose) {
                    echo "ADDED: $ianaServer\n";
                }
            } else {
                if ($verbose) {
                    echo "skipped (IANA server unreachable: $ianaServer)\n";
                }
            }
        } elseif (strtolower($existingServer) !== $ianaServer) {
            // Updated WHOIS server - only update if new server works
            if (isWhoisServerReachable($ianaServer)) {
                $updated[$tld] = ['old' => $existingServer, 'new' => $ianaServer];
                $existingServers[$tld] = $ianaServer;
                if ($verbose) {
                    echo "UPDATED: $existingServer -> $ianaServer\n";
                }
            } else {
                $unchanged++;
                if ($verbose) {
                    echo "kept (new IANA server unreachable)\n";
                }
            }
        } else {
            $unchanged++;
            if ($verbose) {
                echo "unchanged\n";
            }
        }

        // Small delay to avoid rate limiting
        usleep(REQUEST_DELAY_MS * 1000);
    }

    // Sort the servers alphabetically
    ksort($existingServers);

    // Print summary
    echo "\n\n=== Summary ===\n";
    echo "Total TLDs processed: $total\n";
    echo "Unchanged: $unchanged\n";
    echo "Added: " . count($added) . "\n";
    echo "Updated: " . count($updated) . "\n";
    echo "Removed (no WHOIS): " . count($removed) . "\n";
    echo "No WHOIS server: " . count($noWhois) . "\n";
    echo "Errors: " . count($errors) . "\n";

    if (count($added) > 0) {
        echo "\n--- Added TLDs ---\n";
        foreach ($added as $tld => $server) {
            echo "  " . formatTldForDisplay($tld) . ": $server\n";
        }
    }

    if (count($updated) > 0) {
        echo "\n--- Updated TLDs ---\n";
        foreach ($updated as $tld => $change) {
            echo "  " . formatTldForDisplay($tld) . ": {$change['old']} -> {$change['new']}\n";
        }
    }

    if (count($removed) > 0) {
        echo "\n--- Removed TLDs (IANA says no WHOIS) ---\n";
        foreach ($removed as $tld => $oldServer) {
            echo "  " . formatTldForDisplay($tld) . ": was $oldServer\n";
        }
    }

    if (count($errors) > 0 && $verbose) {
        echo "\n--- Errors ---\n";
        foreach ($errors as $tld) {
            echo "  " . formatTldForDisplay($tld) . "\n";
        }
    }

    // Write updated file
    if (!$dryRun && (count($added) > 0 || count($updated) > 0 || count($removed) > 0)) {
        echo "\nWriting updated WHOIS servers file...\n";

        $date = date('Y-m-d');
        $count = count($existingServers);
        $phpContent = "<?php\n\n/**\n * WHOIS servers list\n *\n * Updated on $date - $count entries\n * Source: IANA WHOIS database\n *\n * Do not edit manually - use scripts/update_whois_servers.php to regenerate\n */\n\nreturn " . var_export($existingServers, true) . ";\n";

        if (file_put_contents(WHOIS_SERVERS_FILE, $phpContent) === false) {
            throw new RuntimeException("Failed to write WHOIS servers file");
        }

        echo "Done! Updated " . WHOIS_SERVERS_FILE . "\n";
    } elseif ($dryRun) {
        echo "\nDry-run complete. No changes written.\n";
    } else {
        echo "\nNo changes needed.\n";
    }

} catch (Exception $e) {
    echo "Error: " . $e->getMessage() . "\n";
    exit(1);
}
