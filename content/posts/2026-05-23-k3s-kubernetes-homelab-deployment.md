---
title: "K3s Kubernetes Cluster — Lightweight Deployment for Your Homelab"
description: "Deploy a lightweight K3s Kubernetes cluster on Proxmox VMs for your homelab. Covers multi-node setup, Longhorn storage, Traefik ingress, MetalLB load balancer, and practical workloads."
date: 2026-05-23T11:00:00-04:00
tags:
  - docker
  - kubernetes
  - linux
  - homelab
  - devops
keywords:
  - K3s Kubernetes homelab deployment Proxmox
  - K3s multi-node cluster installation guide
  - Longhorn distributed storage K3s homelab
  - MetalLB load balancer bare metal Kubernetes
  - K3s Traefik ingress controller configuration
  - lightweight Kubernetes single board computer cluster
  - Kubernetes homelab workload migration Docker Compose
summary: "Deploy a production-grade K3s Kubernetes cluster in your homelab on Proxmox VMs — multi-node setup, Longhorn persistent storage, MetalLB load balancing, Traefik ingress, and migrating existing Docker Compose workloads."
canonical: "https://gntech.dev/posts/k3s-kubernetes-homelab-deployment/"
---

You have mastered Docker Compose. Your homelab runs a dozen stacks
behind Traefik, your backups are automated, and monitoring covers
every container. But managing twenty individual Compose files across
multiple hosts is starting to hurt. Rolling out an update means SSH
into the right VM, pulling the right stack, and praying nothing
conflicts.

**K3s** — Rancher's CNCF-certified lightweight Kubernetes
distribution — solves this. It strips Kubernetes down to a single
binary under 100 MB, replaces etcd with SQLite (or embedded
etcd for HA), and runs comfortably on 1 GB RAM VMs. It is
Kubernetes, not a toy: every standard kubectl command, Helm chart,
and Kubernetes resource works as expected.

This guide walks through deploying a production-grade K3s cluster
on Proxmox VMs, adding longhorn for persistent storage, MetalLB
for bare-metal load balancing, Traefik for ingress, and migrating
your Docker Compose workloads into Kubernetes.

---

## Why K3s Over Full Kubernetes or Docker Swarm

Full Kubernetes (kubeadm, kube-spawn) assumes three control plane
nodes with etcd, which wastes resources in a homelab. Docker Swarm
is simpler but lacks the ecosystem — no Helm, no CRDs, limited
CNI choices.

K3s hits the sweet spot: it speaks real Kubernetes API, supports
every standard workload, and runs on a single VM if that's all you
have. Rancher reports over 200,000 production K3s deployments in
edge and IoT environments. If it runs factory robots and oil rig
sensors, it handles your homelab.

**Resource comparison for a three-node cluster:**

| Platform | RAM per node | Disk | Binary size |
|---|---|---|---|
| kubeadm (etcd) | 2–4 GB | 20 GB+ | 500+ MB |
| K3s (SQLite) | 512 MB–1 GB | 10 GB | ~90 MB |
| K3s (embedded etcd, HA) | 1–2 GB | 15 GB | ~90 MB |

For a homelab, a three-node cluster with embedded etcd (HA) or a
single server with SQLite plus two agents (agents only) is the
sweet spot.

---

## Prerequisites and VM Provisioning on Proxmox

Start with three Proxmox VMs running Ubuntu Server 24.04 LTS
(minimal install, no Docker — K3s bundles containerd):

| Node | Role | vCPU | RAM | Disk |
|---|---|---|---|---|
| k3s-srv1 | Server (control plane) | 2 | 2 GB | 20 GB |
| k3s-agent1 | Agent (worker) | 2 | 4 GB | 40 GB |
| k3s-agent2 | Agent (worker) | 2 | 4 GB | 40 GB |

Create them with cloud-init or manually. The minimum viable setup
is a single server and one agent, but three nodes give you
tolerance for Longhorn replication.

### Network Setup

Assign static IPs on your management VLAN. These examples use the
`10.0.30.x/24` subnet:

```
k3s-srv1:  10.0.30.10
k3s-agent1: 10.0.30.11
k3s-agent2: 10.0.30.12
```

Enable promiscuous mode on the Proxmox vNIC if you plan to use
MetalLB in L2 mode — K3s nodes will respond to ARP for service
IPs on that interface.

```bash
# On each Proxmox host, for each K3s VM network interface:
# Hardware → select NIC → enable "VLAN aware" and "Promiscuous"
# Or via CLI:
qm set <VMID> --net0 virtio,bridge=vmbr0,firewall=0
```

---

## Installing the K3s Server Node

SSH into `k3s-srv1` and run the one-line install:

```bash
curl -sfL https://get.k3s.io | sh -s - server \
  --cluster-init \
  --disable=traefik \
  --disable=servicelb \
  --node-ip=10.0.30.10 \
  --flannel-iface=eth0
```

**Flags explained:**

- `--cluster-init` — Start the cluster with embedded etcd (HA
  mode). Omit for single-node SQLite mode.
- `--disable=traefik` — We install Traefik ourselves via Helm for
  full control. K3s bundles a minimal Traefik by default.
- `--disable=servicelb` — Disable K3s's built-in LoadBalancer. We
  use MetalLB instead.
- `--node-ip` — Pin the node IP so cluster traffic uses the
  correct interface.
- `--flannel-iface` — Tell Flannel (the CNI) which interface to
  use for pod networking.

After the install completes, copy the node token — you need it for
agent nodes:

```bash
sudo cat /var/lib/rancher/k3s/server/node-token
```

Save this token. Also copy the kubeconfig for local access:

```bash
mkdir -p ~/.kube
sudo cp /etc/rancher/k3s/k3s.yaml ~/.kube/config
sudo chown $USER:$USER ~/.kube/config
sed -i 's/127.0.0.1/10.0.30.10/' ~/.kube/config
kubectl get nodes
```

You should see `k3s-srv1` in `Ready` status.

---

## Joining Agent Nodes

On `k3s-agent1` and `k3s-agent2`, run the agent install with the
server's IP and token:

```bash
curl -sfL https://get.k3s.io | K3S_URL=https://10.0.30.10:6443 \
  K3S_TOKEN=<YOUR_TOKEN> sh -s - agent \
  --node-ip=10.0.30.11 \
  --flannel-iface=eth0
```

Repeat for agent2 with `--node-ip=10.0.30.12`.

Back on the server, verify all nodes joined:

```bash
kubectl get nodes -o wide
```

Expect output like:

```
NAME         STATUS   ROLES                  AGE   VERSION
k3s-srv1     Ready    control-plane,master   5m    v1.32.3+k3s1
k3s-agent1   Ready    <none>                 2m    v1.32.3+k3s1
k3s-agent2   Ready    <none>                 2m    v1.32.3+k3s1
```

---

## Installing Helm

Helm is the Kubernetes package manager. Everything from Longhorn to
Traefik installs via a single Helm command:

```bash
curl https://raw.githubusercontent.com/helm/helm/main/scripts/get-helm-3 | bash
helm repo add longhorn https://charts.longhorn.io
helm repo add traefik https://traefik.github.io/charts
helm repo add metallb https://metallb.github.io/metallb
helm repo update
```

---

## MetalLB — Bare-Metal Load Balancer

Kubernetes `LoadBalancer` services only work on cloud providers
(AWS, GCP) where a cloud controller provisions real load
balancers. In a homelab, MetalLB assigns IPs from your local
subnet and announces them via ARP (L2 mode) or BGP.

### Install MetalLB

```bash
helm upgrade --install metallb metallb/metallb \
  --namespace metallb-system \
  --create-namespace \
  --set speaker.frr.enabled=false
```

Wait for the pods to start:

```bash
kubectl -n metallb-system wait --for=condition=ready pod \
  --selector=app.kubernetes.io/instance=metallb --timeout=60s
```

### Configure an IP Address Pool

Create `metallb-pool.yaml`:

```yaml
apiVersion: metallb.io/v1beta1
kind: IPAddressPool
metadata:
  name: homelab-pool
  namespace: metallb-system
spec:
  addresses:
  - 10.0.30.200-10.0.30.220
---
apiVersion: metallb.io/v1beta1
kind: L2Advertisement
metadata:
  name: l2-advert
  namespace: metallb-system
spec:
  ipAddressPools:
  - homelab-pool
```

Apply it:

```bash
kubectl apply -f metallb-pool.yaml
```

Any service with `type: LoadBalancer` now gets an IP from the
`10.0.30.200-10.0.30.220` range without needing a real load
balancer.

---

## Longhorn — Distributed Persistent Storage

Docker Compose volumes map to host directories. Kubernetes
requires CSI (Container Storage Interface) drivers for persistent
storage. Longhorn creates replicated block storage across your
K3s nodes using the available disk space on each node's
`/var/lib/longhorn/` directory.

### Install Longhorn

```bash
helm upgrade --install longhorn longhorn/longhorn \
  --namespace longhorn-system \
  --create-namespace \
  --set defaultSettings.defaultReplicaCount=2 \
  --set persistence.defaultFsType=ext4
```

With `defaultReplicaCount=2`, Longhorn stores two copies of every
volume — enough redundancy for a three-node homelab without
wasting the disk space of three replicas.

Wait for all pods:

```bash
kubectl -n longhorn-system get pods -w
```

Access the Longhorn UI at `http://10.0.30.10:30000` (it spawns as
a NodePort service by default). Every node's available disk is
automatically detected and added as storage.

### Create a StorageClass for Workloads

Longhorn creates a default `longhorn` StorageClass. Verify it:

```bash
kubectl get sc
```

Output:

```
NAME                   PROVISIONER             RECLAIMPOLICY
longhorn (default)     driver.longhorn.io      Delete
longhorn-static        driver.longhorn.io      Delete
```

Your PVCs (PersistentVolumeClaims) now automatically provision
replicated block storage across the cluster.

---

## Traefik Ingress Controller

Traefik is the standard ingress for K3s homelabs. It receives
external HTTP/HTTPS traffic, routes it to the correct service
based on hostname, and handles TLS termination.

Install Traefik with Helm:

```bash
cat <<'EOF' > traefik-values.yaml
deployment:
  replicas: 2
  kind: Deployment
ingressClass:
  enabled: true
  isDefaultClass: true
service:
  type: LoadBalancer
  annotations: {}
ports:
  web:
    port: 80
    expose: true
    exposedPort: 80
  websecure:
    port: 443
    expose: true
    exposedPort: 443
providers:
  kubernetesCRD:
    enabled: true
  kubernetesIngress:
    enabled: true
    publishedService:
      enabled: true
EOF

helm upgrade --install traefik traefik/traefik \
  --namespace traefik \
  --create-namespace \
  --values traefik-values.yaml
```

Check that Traefik received a MetalLB IP:

```bash
kubectl -n traefik get svc traefik
```

Example output:

```
NAME      TYPE           CLUSTER-IP     EXTERNAL-IP   PORT(S)
traefik   LoadBalancer   10.43.231.45   10.0.30.200   80:31234,443:32567
```

Point `*.apps.yourdomain.com` DNS to `10.0.30.200` and Traefik
routes all subdomain traffic to the matching Ingress resources.

---

## Deploying Your First Workload

Let's deploy Whoami — a simple HTTP echo service — to verify
everything works end-to-end.

### Create a Deployment and Service

```yaml
# whoami.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: whoami
spec:
  replicas: 2
  selector:
    matchLabels:
      app: whoami
  template:
    metadata:
      labels:
        app: whoami
    spec:
      containers:
      - name: whoami
        image: traefik/whoami:v1.10
        ports:
        - containerPort: 80
        resources:
          requests:
            cpu: 50m
            memory: 64Mi
          limits:
            cpu: 200m
            memory: 128Mi
---
apiVersion: v1
kind: Service
metadata:
  name: whoami
spec:
  selector:
    app: whoami
  ports:
  - port: 80
---
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: whoami
spec:
  ingressClassName: traefik
  rules:
  - host: whoami.apps.yourdomain.com
    http:
      paths:
      - path: /
        pathType: Prefix
        backend:
          service:
            name: whoami
            port:
              number: 80
```

Apply it:

```bash
kubectl apply -f whoami.yaml
```

Wait a moment, then curl the ingress:

```bash
curl -H "Host: whoami.apps.yourdomain.com" http://10.0.30.200
```

You should see the container's hostname, IP, and request headers.

---

## Adding TLS with Let's Encrypt

Create a ClusterIssuer for automatic certificates:

```yaml
# cluster-issuer.yaml
apiVersion: cert-manager.io/v1
kind: ClusterIssuer
metadata:
  name: letsencrypt-prod
spec:
  acme:
    email: admin@yourdomain.com
    server: https://acme-v02.api.letsencrypt.org/directory
    privateKeySecretRef:
      name: letsencrypt-prod-key
    solvers:
    - http01:
        ingress:
          class: traefik
```

Install cert-manager first:

```bash
helm repo add jetstack https://charts.jetstack.io
helm upgrade --install cert-manager jetstack/cert-manager \
  --namespace cert-manager \
  --create-namespace \
  --set crds.enabled=true

kubectl apply -f cluster-issuer.yaml
```

Then annotate any Ingress to get automatic TLS:

```yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: whoami
  annotations:
    cert-manager.io/cluster-issuer: "letsencrypt-prod"
spec:
  ingressClassName: traefik
  tls:
  - hosts:
    - whoami.apps.yourdomain.com
    secretName: whoami-tls
  rules:
  - host: whoami.apps.yourdomain.com
    http:
      paths:
      - path: /
        pathType: Prefix
        backend:
          service:
            name: whoami
            port:
              number: 80
```

cert-manager handles the HTTP-01 challenge automatically, stores
the certificate in `whoami-tls`, and Traefik serves it.

---

## Migrating from Docker Compose to Kubernetes

Moving existing Compose workloads to K3s follows a pattern:

1. **Images** — Your existing Docker images work as-is. No rebuild
   needed.
2. **Volumes** — Replace bind mounts with PVCs.
3. **Networks** — Kubernetes Services replace Compose network
   names. DNS resolves as `<service>.<namespace>.svc.cluster.local`.
4. **Environment** — Use ConfigMaps (non-secret) and Secrets.
5. **Reverse proxy** — Replace Traefik Compose labels with
   Ingress resources + annotations.

### Example: PostgreSQL from Compose to K3s

Docker Compose volume:

```yaml
volumes:
  pgdata:
    driver: local
```

Kubernetes equivalent:

```yaml
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: postgres-data
spec:
  accessModes:
  - ReadWriteOnce
  resources:
    requests:
      storage: 10Gi
  storageClassName: longhorn
---
apiVersion: apps/v1
kind: StatefulSet
metadata:
  name: postgres
spec:
  serviceName: postgres
  replicas: 1
  selector:
    matchLabels:
      app: postgres
  template:
    metadata:
      labels:
        app: postgres
    spec:
      containers:
      - name: postgres
        image: postgres:17
        env:
        - name: POSTGRES_PASSWORD
          valueFrom:
            secretKeyRef:
              name: postgres-secret
              key: password
        ports:
        - containerPort: 5432
        volumeMounts:
        - name: data
          mountPath: /var/lib/postgresql/data
      volumes:
      - name: data
        persistentVolumeClaim:
          claimName: postgres-data
```

A tool like `kompose` (`https://kompose.io/`) can auto-translate
Compose files into Kubernetes manifests as a starting point, but
reviewing and hand-tuning the output is recommended for
production workloads.

---

## Monitoring the Cluster

Install the kube-prometheus-stack for real-time cluster
visibility:

```bash
helm repo add prometheus-community https://prometheus-community.github.io/helm-charts
helm upgrade --install kube-prometheus prometheus-community/kube-prometheus-stack \
  --namespace monitoring \
  --create-namespace
```

Access Grafana:

```bash
kubectl -n monitoring port-forward svc/kube-prometheus-grafana 3000:80
```

Open `http://localhost:3000` — default credentials are
`admin`/`prom-operator`. The "Kubernetes / Views / Global" and
"Nodes" dashboards give immediate insight into pod resource usage,
node health, and cluster events.

Longhorn also exposes Prometheus metrics at
`http://<any-node-ip>:9500/metrics` if you want to scrape storage
metrics into the same Prometheus instance.

---

## What's Next

With a working K3s cluster, your homelab gains real Kubernetes
capabilities:

- **Namespace isolation** — Separate environments
  (`staging`, `prod`, `monitoring`) with resource quotas.
- **GitOps** — Connect a GitHub/Gitea repo with ArgoCD or Flux
  for declarative deployments.
- **Horizontal pod autoscaling** — Let Kubernetes scale web
  services based on CPU or custom metrics.
- **Cluster upgrades** — K3s supports one-line upgrades:
  `curl -sfL https://get.k3s.io | sh -s - --update-server`.

K3s is Kubernetes without the baggage — small enough for a
Raspberry Pi, capable enough for production edge workloads. Your
homelab deserves the upgrade.
