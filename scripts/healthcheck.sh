#!/usr/bin/env bash

# SPDX-License-Identifier: BSD-2-Clause
#
# Copyright (c) 2026, Daniel Lima
#
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions are met:
#
# 1. Redistributions of source code must retain the above copyright notice,
#    this list of conditions and the following disclaimer.
#
# 2. Redistributions in binary form must reproduce the above copyright notice,
#    this list of conditions and the following disclaimer in the documentation
#    and/or other materials provided with the distribution.
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
# AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
# IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE
# DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE LIABLE
# FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL
# DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR
# SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER
# CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY,
# OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE
# OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.

set -e

#region OSPF and Routing

IP_ADDRESS="172.31.0.15/32"
IPV6_ADDRESS="2001:DB8::FF/128"

conf_ospf()
{
    vtysh -c 'conf t' -c "$1" -c 'end' -c 'wr'
}

remove_from_ospf()
{
    conf_ospf "no ip prefix-list ANYCAST-DNS-V4 seq 10"
    conf_ospf "no ipv6 prefix-list ANYCAST-DNS-V6 seq 10"
}

add_to_ospf()
{
    conf_ospf "ip prefix-list ANYCAST-DNS-V4 seq 10 $IP_ADDRESS"
    conf_ospf "ipv6 prefix-list ANYCAST-DNS-V6 seq 10 $IPV6_ADDRESS"
}

is_announced() {
    config=$(vtysh -c 'show running-config') || return 1

    if grep -Fq "ip prefix-list ANYCAST-DNS-V4 seq 10 permit $IP_ADDRESS" <<< "$config" ||
       grep -Fq "ipv6 prefix-list ANYCAST-DNS-V6 seq 10 permit $IPV6_ADDRESS" <<< "$config"
    then
        return 0
    fi

    return 1
}

#endregion

#region Alerts

ZABBIX_IP=$1
HOSTNAME=$2
ITEM_KEY="unbound.status"

send_error()
{
    zabbix_sender -z "$ZABBIX_IP" -s "$HOSTNAME" -k "$ITEM_KEY" -o "Failure" >/dev/null 2>&1
}

send_success()
{
    zabbix_sender -z "$ZABBIX_IP" -s "$HOSTNAME" -k "$ITEM_KEY" -o "Operational" >/dev/null 2>&1
}

#endregion

# Percent
FAILURE_THRESHOLD=100
SUCCESS_THRESHOLD=100

DNS_SERVER="192.168.0.5"

DOMAINS=(
    "www.google.com"
    "www.youtube.com"
    "www.cloudflare.com"
    "www.wikipedia.org"
    "www.microsoft.com"
    "www.apple.com"
    "www.amazon.com"
    "www.facebook.com"
    "www.instagram.com"
    "www.netflix.com"
    "www.github.com"
    "www.debian.org"
    "www.gov.br"
    "www.uol.com.br"
    "www.globo.com"
)

run()
{
    # TODO: Implement the DNS Anycast health-check and failover logic.
    #
    # This function should:
    # 1. Prevent concurrent executions using a lock file.
    # 2. Check whether the Unbound service is active and attempt to
    #    restart it if necessary.
    # 3. Run test_dns() to verify DNS resolution against the local
    #    resolver using the configured list of domains.
    # 4. Track consecutive failures and successful checks using
    #    FAILURE_THRESHOLD and SUCCESS_THRESHOLD.
    # 5. Withdraw the Anycast prefixes from OSPF when DNS resolution
    #    remains unavailable after the failure threshold is reached.
    # 6. Restore the Anycast announcements after DNS resolution
    #    recovers and the success threshold is reached.
    # 7. Check the current announcement state to avoid unnecessary
    #    FRR configuration changes.
    # 8. Implement logging and notifications using the project's
    #    preferred alerting mechanism (e.g., Telegram, email, or logs).
    # 9. Handle command failures, timeouts, state persistence, and
    #    unexpected FRR or systemd errors safely.
    #
    # Ensure that IPv4 and IPv6 announcements are handled consistently.
    # Validate the actual DNS service health before advertising the
    # Anycast prefixes, and avoid route flapping during transient failures.
    #
    # TODO: Implement the logic according to the deployment environment
    # and the chosen monitoring and notification strategy.

    exec 150>/home/daniel/dns.lock
    flock -n 150 || return 0

    if ! systemctl is-active --quiet unbound
    then
        
        systemctl restart unbound || true
        sleep 2
    
        systemctl is-active --quiet unbound || remove_from_ospf
    
    fi

    failure=0
    success=0
    total_domains="${#DOMAINS[@]}"

    for domain in "${DOMAINS[@]}"
    do
        # unbound-control flush "$domain"
        if dig @"$DNS_SERVER" "$domain" A +time=2 +tries=1 +short |
            grep -qE '^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$'
        then
            printf '[%-4s]  %s\n' "OK" "$domain"
            (( success += 1 ))
        else
            printf '[%-4s]  %s\n' "FAIL" "$domain"
            (( failure += 1 ))
        fi
    done

    failure_rate=$(( failure * 100 / total_domains ))
    success_rate=$(( success * 100 / total_domains))
    printf 'Failure rate: %d/%d (%.2f%%)\n' "$failure" "$total_domains" "$failure_rate"

    if [[ $failure -ge $FAILURE_THRESHOLD ]] && is_announced
    then
        remove_from_ospf
        send_error
        exit
    elif [[ $success_rate -ge $SUCCESS_THRESHOLD ]] && ! is_announced
    then
        add_to_ospf
        send_success
        exit
    fi
}

run "$@"
