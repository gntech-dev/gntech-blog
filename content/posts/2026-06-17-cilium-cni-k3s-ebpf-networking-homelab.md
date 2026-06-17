---
title: "Cilium CNI for K3s — eBPF Networking in the Homelab"
description: "Replace K3s default Flannel with Cilium CNI for eBPF-powered networking, kube-proxy replacement, Hubble observability, and identity-based network policies in your homelab."
date: 2026-06-17T11:00:00-04:00
tags:
  - kubernetes
  - docker
  - networking
  - homelab
  - linux
keywords:
  - Cilium CNI K3s homelab installation replacement
  - Cilium eBPF kube-proxy replacement K3s configuration
  - Hubble observability Cilium network monitoring homelab
  - CiliumNetworkPolicy identity-based Kubernetes network security
  - Cilium Helm chart install K3s single-node cluster
  - Cilium replace Flannel K3s default CNI eBPF
  - Cilium k3s L7 network policy HTTP API filtering
summary: "Replace K3s default Flannel with Cilium CNI for accelerated eBPF networking, remove kube-proxy, gain Hubble observability, and enforce identity-based network policies in a lightweight homelab cluster."
canonical: "https://blog.gntech.me/posts/cilium-cni-k3s-ebpf-networking-homelab/"
---

K3s ships with Flannel as its default CNI and a bundled kube-proxy for service routing. It works out of the box, but for a homelab where you want deep visibility, granular security policies, and modern eBPF performance, both Flannel and kube-proxy leave room for improvement.

Cilium changes that. Built on eBPF (extended Berkeley Packet Filter), Cilium replaces the entire Kubernetes networking stack — CNI, kube-proxy, and network policies — with a unified, kernel-native data path. It delivers lower latency for service traffic, identity-aware security policies down to the pod level, and built-in observability through Hubble.

This guide walks through replacing K3s's default networking with Cilium on a running cluster, enabling kube-proxy-free operation, setting up Hubble for flow monitoring, and writing real CiliumNetworkPolicy rules for defense-in-depth.

## Prerequisites

Before starting, confirm your environment meets these requirements:

- **K3s cluster** — single-node or multi-node, already installed and running
- **Root or sudo access** on all nodes
- **Helm CLI** installed (`helm version`)
- **Linux kernel >= 5.10** with eBPF support — check with:

```bash
ls /sys/kernel/btf/vmlinux && echo "eBPF supported"
```

If the file exists, your kernel has BTF (BPF Type Format) and Cilium can use its full eBPF data path. All modern distributions — Ubuntu 22.04+, Debian 12, Fedora — ship compatible kernels.

On each cluster node, confirm the conntrack tools are available (Cilium uses them for connection tracking migration during startup):

```bash
apt install -y conntrack     # Debian/Ubuntu
# or
dnf install -y conntrack-tools  # Fedora/RHEL
```

## Disable K3s Default CNI

Cilium needs to own the entire data path. That means disabling Flannel and kube-proxy before installing Cilium.

### Option A — Fresh K3s Install

If you're starting from scratch, install K3s with both disabled:

```bash
curl -sfL https://get.k3s.io | sh -s - \
  --flannel-backend=none \
  --disable-kube-proxy \
  --disable-network-policy
```

The `--disable-network-policy` flag prevents K3s from deploying its own network policy controller, which would conflict with Cilium's.

### Option B — Existing K3s Cluster

For an already-running cluster, edit the K3s systemd service file:

```bash
sudo sed -i 's|ExecStart=/usr/local/bin/k3s server|& --flannel-backend=none --disable-kube-proxy --disable-network-policy|' /etc/systemd/system/k3s.service
sudo systemctl daemon-reload
sudo systemctl restart k3s
```

After the restart, verify that no kube-proxy pods or Flannel interfaces remain:

```bash
kubectl get pods -n kube-system | grep -E '(kube-proxy|flannel)'
ip link show | grep flannel
```

If you see any leftover Flannel CNI configs, remove them:

```bash
sudo rm -f /var/lib/rancher/k3s/agent/etc/cni/net.d/*
sudo systemctl restart k3s
```

## Install Cilium via Helm

With K3s ready for a new CNI, install Cilium using Helm. Create a values file for the configuration tailored to K3s:

```bash
cat > cilium-values.yaml << 'EOF'
cluster:
  name: k3s-homelab
  id: 1

ipam:
  mode: kubernetes

kubeProxyReplacement: true
k8sServiceHost: 127.0.0.1
k8sServicePort: 6443

l2announcements:
  enabled: false

routingMode: native
autoDirectNodeRoutes: true

hubble:
  enabled: true
  relay:
    enabled: true
  ui:
    enabled: false   # enable later when needed

securityContext:
  capabilities:
    ciliumAgent:
      - CHOWN
      - NET_ADMIN
      - NET_RAW
      - IPC_LOCK
      - SYS_MODULE
      - SYS_ADMIN
      - SYS_RESOURCE
    cleanCiliumState:
      - NET_ADMIN
      - SYS_MODULE
      - SYS_ADMIN
      - SYS_RESOURCE
EOF
```

Key values explained:

- `kubeProxyReplacement: true` — Cilium replaces kube-proxy entirely via eBPF. No kube-proxy pod needed.
- `k8sServiceHost: 127.0.0.1` — K3s exposes the API server on localhost. Cilium talks to it over the local socket.
- `routingMode: native` — uses the node's routing table instead of overlays. More performant in a flat L2 homelab network.
- `autoDirectNodeRoutes: true` — creates direct routes between nodes when they share a L2 segment.

Add the Cilium Helm repository and install:

```bash
helm repo add cilium https://helm.cilium.io/
helm repo update
helm install cilium cilium/cilium \
  --namespace kube-system \
  --values cilium-values.yaml
```

Wait for Cilium to become ready:

```bash
kubectl -n kube-system wait --for=condition=ready pod -l k8s-app=cilium --timeout=300s
```

## Verify eBPF Data Path and kube-proxy Replacement

Once the Cilium agent pods are running, confirm the installation:

```bash
kubectl -n kube-system exec -it ds/cilium -- cilium status --verbose
```

Look for these lines in the output:

```
KVStore:                 Ok   Disabled
Kubernetes:              Ok   1.32 (v1.32.2+k3s1) [default=172.16.0.0/16]
KubeProxyReplacement:    Strict   [enp0sX 10.0.20.X]
Host firewall:           Disabled
```

`KubeProxyReplacement: Strict` means Cilium fully replaced kube-proxy. No kube-proxy pods should exist:

```bash
kubectl get pods -A | grep kube-proxy
# Expected: no output
```

Check that Cilium is managing service forwarding through eBPF:

```bash
kubectl -n kube-system exec -it ds/cilium -- cilium service list
```

You'll see the cluster's Service IPs mapped to eBPF BPF_MAPS_TYPE_HASH entries — no iptables involved.

## Hubble Observability — Network Flow Monitoring

Hubble is Cilium's observability layer. It captures every network flow at the eBPF level and provides a CLI, a gRPC relay API, and a web UI.

### Enable the Hubble UI

Upgrade the Cilium Helm release to add the Hubble UI:

```bash
helm upgrade cilium cilium/cilium \
  --namespace kube-system \
  --reuse-values \
  --set hubble.ui.enabled=true
```

Wait for the UI pod:

```bash
kubectl -n kube-system wait --for=condition=ready pod -l k8s-app=hubble-ui --timeout=120s
```

### Access Hubble via Port-Forward

```bash
kubectl -n kube-system port-forward svc/hubble-ui 12000:80
```

Open `http://localhost:12000` in your browser. The UI shows a live service graph with traffic flows between pods, namespaces, and external endpoints.

### Hubble CLI

Install the Hubble client on your management machine:

```bash
curl -L https://raw.githubusercontent.com/cilium/hubble/main/hubble/install.sh | bash
```

Set up the connection to the Hubble relay:

```bash
export HUBBLE_SERVER=$(kubectl -n kube-system get svc hubble-relay -o jsonpath='{.spec.clusterIP}'):80
hubble observe --server $HUBBLE_SERVER --last 20
```

You'll see flows like:

```
TIMESTAMP    SRC_POD -> DST_POD     FORWARDED  PROTO  ACTION
12:34:56     coredns-1234 -> 10.0.0.1:53   YES   UDP   FORWARDED
12:34:57     nginx-pod -> 10.0.0.2:80      YES   TCP   FORWARDED
```

Use Hubble's filtering to narrow down traffic:

```bash
# DNS queries only
hubble observe --protocol dns --last 50

# Traffic between specific namespaces
hubble observe --from-namespace default --to-namespace kube-system

# Dropped packets
hubble observe --verdict DROPPED
```

This level of visibility is invaluable when debugging network policies or application connectivity.

## CiliumNetworkPolicy — Identity-Based Security

CiliumNetworkPolicy (CNP) extends Kubernetes NetworkPolicy with identity-based selectors, L7 filtering, and cluster-wide scoping. Unlike standard NetworkPolicy, CNP can filter by pod labels across any namespace without requiring matching namespace selectors.

### Default Deny Ingress on a Namespace

Create a policy that drops all inbound traffic to the `default` namespace unless explicitly allowed:

```yaml
cat << 'EOF' | kubectl apply -f -
apiVersion: cilium.io/v2
kind: CiliumNetworkPolicy
metadata:
  name: default-deny-ingress
  namespace: default
spec:
  endpointSelector:
    matchLabels: {}
  ingress:
    - fromEndpoints:
        - matchLabels:
            k8s:app: ingress-controller
EOF
```

This allows ingress only from pods with the label `k8s:app: ingress-controller`. Every other pod attempting to reach services in `default` namespace will be dropped.

### L3/L4 Policy — Allow DNS Egress

Allow pods in the `default` namespace to reach DNS (UDP 53) both internally and externally:

```yaml
cat << 'EOF' | kubectl apply -f -
apiVersion: cilium.io/v2
kind: CiliumNetworkPolicy
metadata:
  name: allow-dns-egress
  namespace: default
spec:
  endpointSelector:
    matchLabels: {}
  egress:
    - toPorts:
        - ports:
            - port: "53"
              protocol: UDP
          rules:
            dns:
              - matchPattern: "*"
EOF
```

### L7 Policy — HTTP Method Filtering

Cilium can inspect HTTP requests at the eBPF level and filter by method, path, and headers. This deploys an HTTP-aware policy that allows `GET` to `/api` but blocks `POST`:

```yaml
cat << 'EOF' | kubectl apply -f -
apiVersion: cilium.io/v2
kind: CiliumNetworkPolicy
metadata:
  name: api-http-allow
  namespace: default
spec:
  endpointSelector:
    matchLabels:
      app: api
  ingress:
    - fromEndpoints:
        - matchLabels:
            app: frontend
      toPorts:
        - ports:
            - port: "8080"
              protocol: TCP
          rules:
            http:
              - method: "GET"
                path: "/api"
EOF
```

Without an explicit `POST` rule, all `POST /api` requests from the frontend will be dropped at the eBPF level — no iptables rules, no userspace proxy, just a kernel BPF program denying the packet.

### Test the Policy

Deploy a test pod and verify:

```bash
kubectl run test-pod --image=nginx:alpine -it --rm --restart=Never -- /bin/sh
```

Inside the pod:

```bash
# This should succeed (DNS is explicitly allowed)
curl -s http://service-in-default:8080/api

# This should fail or hang (no matching L7 rule for POST)
curl -s -X POST http://service-in-default:8080/api
```

Check Hubble for the dropped flows:

```bash
hubble observe --verdict DROPPED --from-pod default/test-pod
```

## Troubleshooting Common Issues

### Cilium Agent Not Starting

If the Cilium pod remains in `CrashLoopBackOff`, check the agent logs:

```bash
kubectl -n kube-system logs -l k8s-app=cilium --tail=50
```

Common causes:

- **Missing BTF file:** run `ls /sys/kernel/btf/vmlinux`. If absent, Cilium falls back to legacy mode but some eBPF features won't work.
- **Conntrack tools missing:** install `conntrack` and restart the node.
- **Flannel CNI leftovers:** remove stale CNI configs from `/var/lib/rancher/k3s/agent/etc/cni/net.d/` and restart K3s.

```bash
sudo rm -rf /var/lib/rancher/k3s/agent/etc/cni/net.d/*
sudo systemctl restart k3s
```

### Hubble Relay Connection Refused

If `hubble observe` returns connection errors:

```bash
kubectl -n kube-system get pods -l k8s-app=hubble-relay
kubectl -n kube-system logs -l k8s-app=hubble-relay
```

The relay needs the Cilium agent's Hubble socket. Ensure `hubble.relay.enabled=true` in your Helm values and restart both relay and agent pods:

```bash
kubectl -n kube-system rollout restart ds/cilium
kubectl -n kube-system rollout restart deploy/hubble-relay
```

### Flannel Network Interface Persisting

Old Flannel routes or interfaces can interfere with Cilium's routing. Clean them:

```bash
sudo ip link delete cni0
sudo ip link delete flannel.1
sudo ip link delete docker0   # only if not used by Docker explicitly
```

Then restart Cilium:

```bash
kubectl -n kube-system rollout restart ds/cilium
```

### Kernel Parameters for eBPF

Cilium's eBPF mode requires specific sysctl values. Validate them:

```bash
sysctl net.ipv4.conf.all.rp_filter
sysctl net.ipv4.conf.default.rp_filter
```

Both should return `1` (strict reverse path filtering). If they show `2`, set them:

```bash
cat >> /etc/sysctl.d/90-cilium.conf << 'EOF'
net.ipv4.conf.all.rp_filter = 1
net.ipv4.conf.default.rp_filter = 1
EOF
sysctl --system
```

## Conclusion

Replacing K3s's default Flannel and kube-proxy with Cilium transforms a basic Kubernetes cluster into an eBPF-powered platform with baked-in observability, identity-based security, and lower-latency service routing. The key gains for a homelab:

- **Full kube-proxy replacement** — service traffic goes through eBPF maps, not iptables
- **Hubble observability** — every flow visible, filterable, and searchable
- **L7 network policies** — filter HTTP methods and paths without sidecar proxies
- **Identity-aware security** — policies based on Kubernetes labels, not IP CIDRs

Start with the Helm install and `cilium status`, enable Hubble, then gradually replace your Kubernetes NetworkPolicy resources with CiliumNetworkPolicy for richer L7 controls. The eBPF data path makes your cluster faster and more observable with zero additional infrastructure.

### Further Reading

- [Cilium Documentation](https://docs.cilium.io/)
- [Cilium Network Policy Language](https://docs.cilium.io/en/stable/security/policy/)
- [Hubble Documentation](https://docs.cilium.io/en/stable/observability/hubble/)
- [Cilium GitHub](https://github.com/cilium/cilium)
