#!/usr/bin/env python3

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

# To use this script you should setup unbound-control and enable it in unbound.conf.
#
# server:
#   extended-statistics: yes
#   statistics-cumulative: no
#   statistics-interval: 0
# remote-control:
#   control-enable: yes
#
# If extended-statistics is not enabled you will get output with limited meaning.

import json
import re
import subprocess
import sys
from pathlib import Path


def get_unbound_statistics() -> str:
    result = subprocess.run(
        ["unbound-control", "stats_noreset"], capture_output=True, text=True, check=True
    )
    return result.stdout


def send_to_zabbix(
    zabbix_ip: str, hostname: str, items: dict[str, str | int | float]
) -> None:
    payload = "".join(f"{hostname} {key} {value}\n" for key, value in items.items())

    subprocess.run(
        ["zabbix_sender", "-z", zabbix_ip, "-i", "-"],
        input=payload,
        text=True,
        check=True,
    )


def parse_values(raw: str) -> dict[str, str]:
    data = {}
    for line in raw.splitlines():
        if "=" not in line:
            continue

        key, val = line.split("=", 1)
        data[key] = val.strip()
    return data


def parse_metrics(
    stats: dict[str, str],
) -> dict[str, str | int | float | dict]:
    integer_metrics = {
        # Queries & cache
        "total.num.queries": "unbound.queries",
        "total.num.cachehits": "unbound.cache.hits",
        "total.num.cachemiss": "unbound.cache.misses",
        "total.num.prefetch": "unbound.cache.prefetch",
        "total.num.expired": "unbound.cache.expired",
        "total.num.recursivereplies": "unbound.recursion.replies",
        # Limits & discards
        "total.num.queries_ip_ratelimited": "unbound.queries.ratelimited_ip",
        "total.num.queries_discard_timeout": "unbound.queries.discard_timeout",
        "total.num.queries_replyaddr_limit": "unbound.queries.replyaddr_limit",
        "total.num.queries_wait_limit": "unbound.queries.wait_limit",
        "total.num.queries_timed_out": "unbound.queries.timed_out",
        "total.num.dns_error_reports": "unbound.dns.error_reports",
        # Request list
        "total.requestlist.overwritten": "unbound.requestlist.overwritten",
        "total.requestlist.exceeded": "unbound.requestlist.exceeded",
        "total.requestlist.current.all": "unbound.requestlist.current",
        "total.requestlist.current.user": "unbound.requestlist.current_user",
        "total.requestlist.current.replies": "unbound.requestlist.current_replies",
        "total.requestlist.max": "unbound.requestlist.max",
        # Transport method
        "total.tcpusage": "unbound.tcp.usage",
        "num.query.tcp": "unbound.queries.tcp",
        "num.query.tcpout": "unbound.queries.tcp_out",
        "num.query.udpout": "unbound.queries.udp_out",
        "num.query.tls": "unbound.queries.tls",
        "num.query.ipv6": "unbound.queries.ipv6",
        # DNS answer codes
        "num.answer.rcode.NOERROR": "unbound.rcode.noerror",
        "num.answer.rcode.NXDOMAIN": "unbound.rcode.nxdomain",
        "num.answer.rcode.SERVFAIL": "unbound.rcode.servfail",
        "num.answer.rcode.REFUSED": "unbound.rcode.refused",
        "num.answer.rcode.FORMERR": "unbound.rcode.formerr",
        "num.answer.rcode.NOTIMPL": "unbound.rcode.notimpl",
        "num.answer.rcode.nodata": "unbound.rcode.nodata",
        # DNSSEC
        "num.answer.secure": "unbound.dnssec.secure",
        "num.answer.bogus": "unbound.dnssec.bogus",
        "num.rrset.bogus": "unbound.dnssec.rrset_bogus",
        "num.valops": "unbound.dnssec.validation_ops",
        # Others
        "unwanted.queries": "unbound.unwanted.queries",
        "unwanted.replies": "unbound.unwanted.replies",
        "num.query.edns.present": "unbound.edns.present",
        "num.query.edns.DO": "unbound.edns.do",
        "num.query.flags.AD": "unbound.query.flags.ad",
        "num.query.flags.CD": "unbound.query.flags.cd",
        # Internal cache
        "msg.cache.count": "unbound.msg_cache.count",
        "rrset.cache.count": "unbound.rrset_cache.count",
        "infra.cache.count": "unbound.infra_cache.count",
        "key.cache.count": "unbound.key_cache.count",
        "msg.cache.max_collisions": "unbound.msg_cache.max_collisions",
        "rrset.cache.max_collisions": "unbound.rrset_cache.max_collisions",
        # Memory
        "mem.cache.rrset": "unbound.memory.rrset_cache",
        "mem.cache.message": "unbound.memory.message_cache",
        "mem.mod.iterator": "unbound.memory.iterator",
        "mem.mod.validator": "unbound.memory.validator",
        "mem.mod.respip": "unbound.memory.respip",
        "mem.mod.subnet": "unbound.memory.subnet",
        "mem.streamwait": "unbound.memory.streamwait",
    }

    float_metrics = {
        # Time in seconds
        "total.requestlist.avg": "unbound.requestlist.avg",
        "total.recursion.time.avg": "unbound.recursion.time.avg",
        "total.recursion.time.median": "unbound.recursion.time.median",
        # Activity time
        "time.up": "unbound.uptime",
        "time.elapsed": "unbound.stats.elapsed",
    }

    metrics: dict[str, str | int | float | dict] = {}

    for source, target in integer_metrics.items():
        value = stats.get(source)
        if value is not None:
            try:
                metrics[target] = int(value)
            except ValueError:
                continue

    for source, target in float_metrics.items():
        value = stats.get(source)
        if value is not None:
            try:
                metrics[target] = float(value)
            except ValueError:
                continue

    query_types = (
        "A",
        "AAAA",
        "PTR",
        "SRV",
        "SVCB",
        "HTTPS",
        "MX",
        "TXT",
        "NS",
        "SOA",
        "CNAME",
        "DS",
        "DNSKEY",
        "TLSA",
        "NAPTR",
        "ANY",
    )

    for query_type in query_types:
        source = f"num.query.type.{query_type}"
        value = stats.get(source)

        if value is not None:
            try:
                metrics[f"unbound.queries.type.{query_type.lower()}"] = int(value)
            except ValueError:
                continue
        else:
            metrics[f"unbound.queries.type.{query_type.lower()}"] = 0

    thread_pattern = re.compile(r"^thread(\d+)\.(.+)$")

    thread_integer_metrics = {
        "num.queries": "queries",
        "num.cachehits": "cache_hits",
        "num.cachemiss": "cache_misses",
        "num.prefetch": "prefetch",
        "num.expired": "expired",
        "num.recursivereplies": "recursion_replies",
        "num.queries_ip_ratelimited": "queries_ratelimited_ip",
        "num.queries_discard_timeout": "queries_discard_timeout",
        "num.queries_replyaddr_limit": "queries_replyaddr_limit",
        "num.queries_wait_limit": "queries_wait_limit",
        "num.queries_timed_out": "queries_timed_out",
        "num.dns_error_reports": "dns_error_reports",
        "requestlist.overwritten": "requestlist_overwritten",
        "requestlist.exceeded": "requestlist_exceeded",
        "requestlist.current.all": "requestlist_current",
        "requestlist.current.user": "requestlist_current_user",
        "requestlist.current.replies": "requestlist_current_replies",
        "requestlist.max": "requestlist_max",
        "tcpusage": "tcp_usage",
    }

    thread_float_metrics = {
        "requestlist.avg": "requestlist_avg",
        "recursion.time.avg": "recursion_time_avg",
        "recursion.time.median": "recursion_time_median",
        "query.queue_time_us.max": "query_queue_time_us_max",
    }

    threads: dict[str, dict[str, int | float]] = {}

    for source, value in stats.items():
        match = thread_pattern.match(source)
        if match is None:
            continue

        thread_id, metric_name = match.groups()

        if metric_name in thread_integer_metrics:
            try:
                parsed_value: int | float = int(value)
            except ValueError:
                continue
            target = thread_integer_metrics[metric_name]

        elif metric_name in thread_float_metrics:
            try:
                parsed_value = float(value)
            except ValueError:
                continue
            target = thread_float_metrics[metric_name]

        else:
            continue

        threads.setdefault(thread_id, {})[target] = parsed_value

    metrics["threads"] = threads

    return metrics


def run(argv: list) -> None:
    if (
        len(argv) == 3
        and argv[1] == "-f"
        and Path(argv[2]).resolve().expanduser().exists()
    ):
        raw = Path("unbound-stats").read_text()
    else:
        raw = get_unbound_statistics()

    stats = parse_values(raw)
    metrics = parse_metrics(stats)

    print(json.dumps(metrics))


if __name__ == "__main__":
    run(sys.argv)
