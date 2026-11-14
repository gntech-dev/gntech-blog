---
title: "Measure Proxmox Recovery Time Until the Application Works"
description: "Time a full off-site VM restore through the first successful HTTP response with the expected data."
date: 2026-11-14T00:00:00-04:00
draft: false
ShowToc: true
tags: [proxmox, backup, disaster-recovery, monitoring]
keywords: [Proxmox recovery time, RTO drill, isolated VM restore, application validation]
summary: "Measure restore, boot and application readiness separately using an isolated recovery network."
cover:
  image: "/images/posts/proxmox-application-recovery-time/featured.webp"
  alt: "A stopwatch and a laptop on a warmly lit workbench in front of a server rack."
  caption: "AI-generated editorial artwork."
  relative: false
---

The Proxmox restore task can finish while users are still waiting for the service. Boot, configuration changes and application startup add time. Measure through the first valid application response so you can see where the recovery window actually went.

[Part 10](/posts/2026-11-04-gntech-infrastructure-part-10-backup-disaster-recovery/) shows how to recover a guest using only off-site storage. This companion times the next step from a separate client. It uses Proxmox VE 9, a disposable Linux VM, an off-site PBS snapshot, and a second Linux VM to test the service. The timings are for your drill to measure.

## 1. Prepare a fixture with a recognizable response

In the disposable source VM, use Python 3 and systemd. Save a copy of the marker on the probe VM through your lab's provisioning workflow before the drill. Copy only that file and record which backup should contain it.

```bash
sudo install -d -m 0755 /srv/recovery-fixture
printf 'recovery-fixture %s\n' "$(date -u +%FT%TZ)" |
  sudo tee /srv/recovery-fixture/marker.txt >/dev/null

sudo tee /etc/systemd/system/recovery-fixture.service >/dev/null <<'UNIT'
[Unit]
Description=Disposable recovery fixture
After=network.target

[Service]
User=nobody
ExecStart=/usr/bin/python3 -m http.server 8080 --directory /srv/recovery-fixture

[Install]
WantedBy=multi-user.target
UNIT
sudo systemctl daemon-reload
sudo systemctl enable --now recovery-fixture.service
curl --noproxy '*' --fail --max-time 3 http://127.0.0.1:8080/marker.txt
```

Use this simple server only in a disposable VM on an isolated network. Confirm that the response matches the saved marker, then back up the guest and sync the exact snapshot to off-site PBS using Part 10. Prepare a recovery bridge with no physical uplink, no host address, and no routing to other networks. Connect only the probe VM and the recovered guest. In the example, the probe uses `192.0.2.20/24` and the guest uses `192.0.2.10/24`, with no default gateway on either VM. Use static addresses and make sure the probe has no second NIC that could reach a production copy.

## 2. Start the clock before retrieving recovery access

Keep this stopwatch running in a separate terminal on the operator's workstation. Run other steps from the PVE interface, guest console and probe terminal. Start the clock at the simulated incident declaration if you want to include access and key retrieval in the result.

```python
from time import monotonic

stages = ("off-site snapshot accessible", "restore complete", "guest boot started",
          "first valid application response")
input("Press Enter to declare the simulated incident: ")
start = previous = monotonic()
for stage in stages:
    input(f"Press Enter when {stage}: ")
    now = monotonic()
    print(f"{stage}: +{now - start:.1f}s total, {now - previous:.1f}s stage", flush=True)
    previous = now
```

Confirm the recorded off-site snapshot using the recovery credential and matching key if encrypted. Restore to an unused VM ID and recovery storage. Leave **Start after restore** and **Live restore** unchecked. Record task completion, then inspect the restored configuration before starting it. Disable automatic startup, move its NIC to the isolated bridge, and check for extra NICs and passthrough devices. Keep the guest stopped until those checks pass. Confirm the guest's address from its console and include any changes you make after boot in the elapsed time.

## 3. Test the first usable response

Start the restored VM manually and mark that milestone. On the probe VM, run the loop below with the trusted `expected-marker.txt` in the current directory. You can start the probe as soon as the guest starts booting.

```bash
set -e
test -s expected-marker.txt
body="$(mktemp)"
trap 'rm -f -- "$body"' EXIT

for attempt in $(seq 1 60); do
  if status="$(curl --noproxy '*' --silent --max-time 2 \
      --output "$body" --write-out '%{http_code}' \
      http://192.0.2.10:8080/marker.txt)" &&
      [[ "$status" = 200 ]] && cmp -s expected-marker.txt "$body"; then
    printf 'Valid application response on probe %s\n' "$attempt"
    exit 0
  fi
  sleep 2
done

printf 'Application readiness timed out\n' >&2
exit 1
```

Mark the last stopwatch milestone only after the probe succeeds. A timeout means the drill did not reach application readiness within the probe window. Save the elapsed time and failure stage. Review the guest console, IP and bridge settings, then check `systemctl status recovery-fixture` and its journal. Repeat with an intentionally different expected marker in a separate run to confirm that an HTTP 200 with the wrong data fails.

## 4. Compare the result with your recovery objective

| Evidence | What to record |
| --- | --- |
| Recovery point | Exact off-site PBS snapshot and its age at incident declaration. |
| Restore | Destination storage, disk size and restore task ID. |
| Guest startup | Time of manual start and any network or service configuration delays. |
| Application readiness | First HTTP 200 with the expected body, plus total elapsed time. |

Keep the snapshot age separate from elapsed recovery time. Manual marks include operator reaction time and the application probe has a polling delay. Record those limits when comparing repeated runs. For a real service, use a small read-only transaction through its intended access path, such as reading a known record over HTTPS. Include dependency startup and the actual access path in any result you compare against the production recovery time objective.

After recording evidence, shut down the recovered VM. Confirm its lab VM ID before removing it, and remove the isolated bridge only if it was dedicated to this exercise and has no other guests attached.

## References

- [Proxmox VE backup and restore](https://pve.proxmox.com/pve-docs/chapter-vzdump.html)
- [Proxmox VE network configuration](https://pve.proxmox.com/pve-docs/pve-network-plain.html)
- [Python monotonic clock](https://docs.python.org/3/library/time.html#time.monotonic)
- [Python HTTP server](https://docs.python.org/3/library/http.server.html)
- [curl command reference](https://curl.se/docs/manpage.html)
