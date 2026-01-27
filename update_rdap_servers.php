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
 * Script to update RDAP servers from IANA bootstrap file
 *
 * This script fetches the official RDAP bootstrap data from IANA
 * and updates the rdap_servers.json file.
 *
 * IANA RDAP Bootstrap: https://data.iana.org/rdap/dns.json
 *
 * Usage:
 *   php scripts/update_rdap_servers.php [options]
 *
 * Options:
 *   --dry-run     Show changes without writing to file
 *   --verbose     Show detailed progress
 *   --help        Show this help message
 */

define('IANA_RDAP_BOOTSTRAP_URL', 'https://data.iana.org/rdap/dns.json');
define('RDAP_SERVERS_FILE', __DIR__ . '/../data/rdap_servers.php');

// Parse command line options
$options = getopt('', ['dry-run', 'verbose', 'help']);
$dryRun = isset($options['dry-run']);
$verbose = isset($options['verbose']);
$showHelp = isset($options['help']);

if ($showHelp) {
    echo <<<HELP
Update RDAP servers from IANA bootstrap file

Usage:
  php scripts/update_rdap_servers.php [options]

Options:
  --dry-run     Show changes without writing to file
  --verbose     Show detailed progress
  --help        Show this help message

Examples:
  php scripts/update_rdap_servers.php --dry-run --verbose
  php scripts/update_rdap_servers.php

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
        CURLOPT_USERAGENT => 'Mozilla/5.0 (compatible; Poweradmin RDAP Updater/1.0)',
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
 * Normalize RDAP URL (ensure consistent format)
 */
function normalizeRdapUrl(string $url): string
{
    $url = trim($url);
    // Ensure HTTPS
    if (strpos($url, 'http://') === 0) {
        $url = 'https://' . substr($url, 7);
    }
    return $url;
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
    echo "=== RDAP Servers Update Script ===\n\n";

    if ($dryRun) {
        echo "Running in DRY-RUN mode - no changes will be written\n\n";
    }

    // Load existing RDAP servers
    if (!file_exists(RDAP_SERVERS_FILE)) {
        throw new RuntimeException("RDAP servers file not found: " . RDAP_SERVERS_FILE);
    }

    $existingServers = include RDAP_SERVERS_FILE;
    if (!is_array($existingServers)) {
        throw new RuntimeException("Failed to parse existing RDAP servers file");
    }

    echo "Loaded " . count($existingServers) . " existing RDAP server entries\n\n";

    // Fetch IANA RDAP bootstrap data
    echo "Fetching RDAP bootstrap data from IANA...\n";
    $bootstrapJson = fetchUrl(IANA_RDAP_BOOTSTRAP_URL);

    $bootstrapData = json_decode($bootstrapJson, true);
    if (json_last_error() !== JSON_ERROR_NONE) {
        throw new RuntimeException("Failed to parse IANA RDAP bootstrap data");
    }

    if (!isset($bootstrapData['services']) || !is_array($bootstrapData['services'])) {
        throw new RuntimeException("Invalid IANA RDAP bootstrap data format");
    }

    // Display bootstrap metadata
    if (isset($bootstrapData['version'])) {
        echo "Bootstrap version: " . $bootstrapData['version'] . "\n";
    }
    if (isset($bootstrapData['publication'])) {
        echo "Publication date: " . $bootstrapData['publication'] . "\n";
    }

    // Parse bootstrap data into TLD -> URL mapping
    // IANA format: services is array of [TLDs array, URLs array]
    $ianaServers = [];
    foreach ($bootstrapData['services'] as $service) {
        if (!is_array($service) || count($service) < 2) {
            continue;
        }

        $tlds = $service[0];
        $urls = $service[1];

        if (!is_array($tlds) || !is_array($urls) || empty($urls)) {
            continue;
        }

        // Use the first URL as the primary RDAP server
        $primaryUrl = normalizeRdapUrl($urls[0]);

        foreach ($tlds as $tld) {
            $tld = strtolower(trim($tld));
            if (!empty($tld)) {
                $ianaServers[$tld] = $primaryUrl;
            }
        }
    }

    echo "Found " . count($ianaServers) . " TLDs in IANA bootstrap data\n\n";

    // Track changes
    $added = [];
    $updated = [];
    $removed = [];
    $unchanged = 0;

    // Process IANA servers - add/update
    foreach ($ianaServers as $tld => $ianaUrl) {
        $existingUrl = $existingServers[$tld] ?? null;

        if ($existingUrl === null) {
            // New TLD
            $added[$tld] = $ianaUrl;
            $existingServers[$tld] = $ianaUrl;
            if ($verbose) {
                echo "ADDED: " . formatTldForDisplay($tld) . " -> $ianaUrl\n";
            }
        } elseif (normalizeRdapUrl($existingUrl) !== $ianaUrl) {
            // Updated URL
            $updated[$tld] = ['old' => $existingUrl, 'new' => $ianaUrl];
            $existingServers[$tld] = $ianaUrl;
            if ($verbose) {
                echo "UPDATED: " . formatTldForDisplay($tld) . ": $existingUrl -> $ianaUrl\n";
            }
        } else {
            $unchanged++;
            if ($verbose) {
                echo "unchanged: " . formatTldForDisplay($tld) . "\n";
            }
        }
    }

    // Find removed TLDs (in existing but not in IANA)
    foreach ($existingServers as $tld => $url) {
        if (!isset($ianaServers[$tld])) {
            $removed[$tld] = $url;
            unset($existingServers[$tld]);
            if ($verbose) {
                echo "REMOVED: " . formatTldForDisplay($tld) . " (was $url)\n";
            }
        }
    }

    // Sort the servers alphabetically
    ksort($existingServers);

    // Print summary
    echo "\n=== Summary ===\n";
    echo "Total TLDs in IANA bootstrap: " . count($ianaServers) . "\n";
    echo "Unchanged: $unchanged\n";
    echo "Added: " . count($added) . "\n";
    echo "Updated: " . count($updated) . "\n";
    echo "Removed: " . count($removed) . "\n";

    if (count($added) > 0) {
        echo "\n--- Added TLDs ---\n";
        foreach ($added as $tld => $url) {
            echo "  " . formatTldForDisplay($tld) . ": $url\n";
        }
    }

    if (count($updated) > 0) {
        echo "\n--- Updated TLDs ---\n";
        foreach ($updated as $tld => $change) {
            echo "  " . formatTldForDisplay($tld) . ": {$change['old']} -> {$change['new']}\n";
        }
    }

    if (count($removed) > 0) {
        echo "\n--- Removed TLDs ---\n";
        foreach ($removed as $tld => $oldUrl) {
            echo "  " . formatTldForDisplay($tld) . ": was $oldUrl\n";
        }
    }

    // Write updated file
    if (!$dryRun && (count($added) > 0 || count($updated) > 0 || count($removed) > 0)) {
        echo "\nWriting updated RDAP servers file...\n";

        $date = date('Y-m-d');
        $count = count($existingServers);
        $phpContent = "<?php\n\n/**\n * RDAP servers list\n *\n * Updated on $date - $count entries\n * Source: IANA RDAP Bootstrap (https://data.iana.org/rdap/dns.json)\n *\n * Do not edit manually - use scripts/update_rdap_servers.php to regenerate\n */\n\nreturn " . var_export($existingServers, true) . ";\n";

        if (file_put_contents(RDAP_SERVERS_FILE, $phpContent) === false) {
            throw new RuntimeException("Failed to write RDAP servers file");
        }

        echo "Done! Updated " . RDAP_SERVERS_FILE . "\n";
    } elseif ($dryRun) {
        echo "\nDry-run complete. No changes written.\n";
    } else {
        echo "\nNo changes needed.\n";
    }

} catch (Exception $e) {
    echo "Error: " . $e->getMessage() . "\n";
    exit(1);
}
